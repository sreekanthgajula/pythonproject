"""
===============================================================================
ZERODHA 1% ABOVE RECENT HIGH ALERT ENGINE
===============================================================================
Description:
    1. Takes stock symbols evaluated by Grok API.
    2. Queries Zerodha Kite Connect API (or fallback historical data) for each
       stock to determine its recent price high (e.g., 20-period or 30-day high).
    3. Calculates the breakout alert trigger price:
           alert_trigger_price = recent_high * 1.01  (1% above recent high)
    4. Sets up a Zerodha GTT (Good-Till-Triggered) single-trigger alert / order
       or registers an active monitoring alert.
    5. Updates the stock entry in the database ('monthly', 'weekly', 'daily') with
       recent_high and alert_trigger_price.
===============================================================================
"""

import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from data_manager import DataManager
from tradingagents.dataflows.symbol_utils import normalize_symbol

# Try importing KiteConnect
try:
    from kiteconnect import KiteConnect
    KITE_AVAILABLE = True
except ImportError:
    KITE_AVAILABLE = False

# Try importing yfinance for market data fallback
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

load_dotenv(dotenv_path=project_root / ".env")
logger = logging.getLogger(__name__)

def get_kite_client():
    """Returns an authenticated Zerodha KiteConnect instance if credentials are valid."""
    api_key = os.getenv("ZERODHA_API_KEY")
    access_token = os.getenv("ZERODHA_ACCESS_TOKEN")

    if KITE_AVAILABLE and api_key and access_token:
        try:
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            return kite
        except Exception as e:
            logger.warning(f"Zerodha KiteConnect initialization failed: {e}")
            return None
    return None

def fetch_recent_high(symbol: str, timeframe: str = "monthly", lookback_periods: int = 20) -> tuple[float, float]:
    """
    Fetches the recent price high for a stock symbol using Zerodha API (or yfinance fallback)
    and computes the 1% breakout trigger price (recent_high * 1.01).
    
    Returns:
        tuple[float, float]: (recent_high, alert_trigger_price)
    """
    clean_sym = symbol.strip().upper()
    kite = get_kite_client()
    recent_high = None

    # 1. Attempt Zerodha API quote / historical fetch
    if kite:
        try:
            # Format trading symbol for Zerodha (e.g. NSE:WELCORP)
            trading_symbol = f"NSE:{clean_sym}"
            quote = kite.quote(trading_symbol)
            if trading_symbol in quote:
                data = quote[trading_symbol]
                # Extract 52-week high or current day's high
                ohlc = data.get("ohlc", {})
                day_high = ohlc.get("high", 0.0)
                fifty_two_week_high = data.get("52week_setting", {}).get("high", 0.0)
                recent_high = max(day_high, fifty_two_week_high) if fifty_two_week_high > 0 else day_high
        except Exception as e:
            logger.warning(f"Zerodha quote fetch failed for {clean_sym}: {e}. Falling back to historical data.")

    # 2. Fallback to yfinance if Zerodha quote is unavailable or unauthenticated
    if (not recent_high or recent_high <= 0) and YFINANCE_AVAILABLE:
        try:
            yf_symbol = normalize_symbol(clean_sym)
            if not yf_symbol.endswith(".NS") and "=" not in yf_symbol and "-" not in yf_symbol:
                yf_symbol = f"{yf_symbol}.NS"
                
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="3mo")
            if not hist.empty and "High" in hist.columns:
                recent_high = float(hist["High"].tail(lookback_periods).max())
        except Exception as e:
            logger.warning(f"yfinance fallback fetch failed for {clean_sym}: {e}")

    # Fallback default if market data is unreachable
    if not recent_high or recent_high <= 0:
        recent_high = 100.0  # Placeholder fallback

    # Calculate 1% above recent high
    alert_trigger_price = round(recent_high * 1.01, 2)
    return round(recent_high, 2), alert_trigger_price

def set_zerodha_1pct_breakout_alert(symbol: str, timeframe: str = "monthly", override_recent_high: float = None, override_qty: int = None) -> dict:
    """
    Programmatically sets an alert 1% above the recent high for a stock symbol
    and records it in Zerodha (via GTT / Alert API) and the local database.
    If stock price >= ₹5000 RS (e.g. PTCIL), sets quantity to 500 (or override_qty).
    """
    clean_sym = symbol.strip().upper()
    if override_recent_high and override_recent_high > 0:
        recent_high = round(round(override_recent_high / 0.05) * 0.05, 2)
        raw_trigger = max(recent_high * 1.01, recent_high + 0.20)
        trigger_price = round(round(raw_trigger / 0.05) * 0.05, 2)
    else:
        recent_high, trigger_price = fetch_recent_high(clean_sym, timeframe=timeframe)
        recent_high = round(round(recent_high / 0.05) * 0.05, 2)
        raw_trigger = max(trigger_price, recent_high * 1.01, recent_high + 0.20)
        trigger_price = round(round(raw_trigger / 0.05) * 0.05, 2)

    stock_price = max(trigger_price, recent_high)
    kite = get_kite_client()
    gtt_status = "REGISTERED_LOCAL"
    requested_qty = int(os.getenv("ZERODHA_GTT_QUANTITY", "5000"))

    # Determine GTT quantity: override_qty if specified, else 500 if stock_price >= 5000 RS (e.g., PTCIL), else capped by max order value
    if override_qty and override_qty > 0:
        gtt_quantity = override_qty
        logger.info(f"[ZERODHA GTT] Using explicit override quantity QTY={gtt_quantity} for {clean_sym}.")
    elif stock_price >= 5000.0:
        gtt_quantity = 500
        logger.info(f"[ZERODHA GTT] High stock price detected for {clean_sym} (₹{stock_price:.2f} >= ₹5,000 RS). Setting GTT quantity to 500.")
    else:
        MAX_GTT_ORDER_VALUE = 50_000_000.0  # ₹5 Crore (50 Million INR)
        if trigger_price > 0:
            max_qty_allowed = max(1, int(MAX_GTT_ORDER_VALUE / trigger_price))
            gtt_quantity = min(requested_qty, max_qty_allowed)
        else:
            gtt_quantity = requested_qty

    gtt_id = None

    # Attempt Zerodha GTT order placement with primary quantity, with fallbacks (500, 100, 50) if placement fails
    if kite:
        trading_symbol = clean_sym.replace(".NS", "").replace("-EQ", "").strip()
        placed = False
        last_error = None

        # Build list of quantities to attempt
        qty_attempts = [gtt_quantity]
        if gtt_quantity > 500 or stock_price >= 5000.0:
            if 500 not in qty_attempts:
                qty_attempts.append(500)
        if 100 not in qty_attempts:
            qty_attempts.append(100)
        if 50 not in qty_attempts:
            qty_attempts.append(50)

        for try_qty in qty_attempts:
            for exch in ["NSE", "BSE"]:
                try:
                    gtt_resp = kite.place_gtt(
                        trigger_type=kite.GTT_TYPE_SINGLE,
                        tradingsymbol=trading_symbol,
                        exchange=exch,
                        trigger_values=[trigger_price],
                        last_price=recent_high,
                        orders=[{
                            "transaction_type": kite.TRANSACTION_TYPE_BUY,
                            "quantity": try_qty,
                            "order_type": kite.ORDER_TYPE_LIMIT,
                            "product": kite.PRODUCT_CNC,
                            "price": trigger_price
                        }]
                    )
                    gtt_id = gtt_resp.get("trigger_id")
                    gtt_quantity = try_qty
                    gtt_status = f"ZERODHA_GTT_ACTIVE (ID: {gtt_id}, Qty: {gtt_quantity}, Exch: {exch})"
                    logger.info(f"[ZERODHA GTT] Set 1% breakout alert for {trading_symbol} on {exch} at ₹{trigger_price} with QTY={gtt_quantity} (GTT ID: {gtt_id})")
                    placed = True
                    break
                except Exception as exch_err:
                    last_error = exch_err
                    logger.debug(f"GTT placement on {exch} for {trading_symbol} with QTY={try_qty} failed: {exch_err}. Trying next attempt...")
            if placed:
                break

        if not placed:
            logger.warning(f"Zerodha GTT placement for {clean_sym} notice: {last_error}")
            gtt_status = f"LOCAL_ALERT_SET ({last_error})"

    # Update database record with recent_high, alert_trigger_price, and gtt_quantity
    try:
        dm = DataManager()
        col = dm.db[timeframe.strip().lower()]
        set_dict = {
            "recent_high": recent_high,
            "alert_trigger_price": trigger_price,
            "alert_status": gtt_status,
            "gtt_quantity": gtt_quantity,
            "alert_updated_at": datetime.now(timezone.utc).replace(tzinfo=None)
        }
        if gtt_id:
            set_dict["gtt_id"] = gtt_id

        col.update_one(
            {"symbol": clean_sym},
            {"$set": set_dict},
            upsert=True
        )
        logger.info(f"Updated '{timeframe}' table for {clean_sym}: High=₹{recent_high}, Trigger=₹{trigger_price} (+1%), Qty={gtt_quantity}")
    except Exception as db_err:
        logger.error(f"Failed to update alert data in DB for {clean_sym}: {db_err}")

    return {
        "symbol": clean_sym,
        "timeframe": timeframe,
        "recent_high": recent_high,
        "alert_trigger_price": trigger_price,
        "gtt_quantity": gtt_quantity,
        "gtt_id": gtt_id,
        "status": gtt_status
    }

def verify_and_retry_gtt_alerts(alerts_data: dict | list, timeframe: str = "monthly") -> dict | list:
    """
    After finishing setting up alerts, runs a verification loop to check if all alerts
    were placed successfully on Zerodha. For any symbol where GTT placement failed:
    1. Checks the stock price (recent_high / alert_trigger_price).
    2. If stock price >= ₹5000 (or if initial GTT placement failed), changes quantity to 500 (or 100/50).
    3. Retries placing the Zerodha GTT breakout alert order.
    """
    logger.info(f"[VERIFY LOOP] Checking if all Zerodha GTT alerts were set successfully for {timeframe.upper()}...")
    print(f"\n-------------------------------------------------------")
    print(f" VERIFYING GTT ALERTS SETUP & RETRYING FAILED [{timeframe.upper()}]")
    print(f"-------------------------------------------------------")

    is_dict = isinstance(alerts_data, dict)
    items_list = list(alerts_data.values()) if is_dict else list(alerts_data)

    for item in items_list:
        if not isinstance(item, dict):
            continue

        sym = item.get("symbol", "").upper()
        gtt_id = item.get("gtt_id")
        status = item.get("status", "")
        trigger_price = item.get("alert_trigger_price", 0.0)
        recent_high = item.get("recent_high", 0.0)
        price = max(trigger_price, recent_high)

        # Check if GTT alert was NOT set active on Zerodha
        if not gtt_id or "ZERODHA_GTT_ACTIVE" not in status:
            print(f"[VERIFY LOOP] ⚠️ Alert for {sym} is not active on Zerodha (Status: {status}). Stock Price: ₹{price:.2f}")

            # If stock price >= 5000 RS or alert placement failed, retry with reduced quantity (500, then 100, then 50)
            retry_quantities = [500, 100, 50] if price >= 5000.0 else [500, 100, 50]

            for retry_qty in retry_quantities:
                print(f"[VERIFY LOOP] Retrying GTT placement for {sym} with reduced quantity QTY={retry_qty} (Price: ₹{price:.2f})...")
                retry_res = set_zerodha_1pct_breakout_alert(sym, timeframe=timeframe, override_qty=retry_qty)

                if retry_res.get("gtt_id") and "ZERODHA_GTT_ACTIVE" in retry_res.get("status", ""):
                    print(f"[VERIFY LOOP] ✅ SUCCESS: GTT alert set for {sym} on Zerodha with QTY={retry_qty}! (GTT ID: {retry_res.get('gtt_id')})")
                    # Update item in-place
                    item.update(retry_res)
                    if is_dict:
                        alerts_data[sym] = item
                    break
                else:
                    print(f"[VERIFY LOOP] ❌ QTY={retry_qty} retry failed for {sym}: {retry_res.get('status')}")
        else:
            print(f"[VERIFY LOOP] ✅ Alert for {sym} is active on Zerodha (GTT ID: {gtt_id}, Qty: {item.get('gtt_quantity')})")

    return alerts_data

def setup_alerts_for_symbols(symbols: list[str], timeframe: str = "monthly") -> list[dict]:
    """
    Processes a list of stock symbols, computes 1% above recent high,
    programmatically places alerts for all of them, and verifies placement.
    """
    results = []
    print(f"\n=======================================================")
    print(f" SETTING ZERODHA 1% BREAKOUT ALERTS [{timeframe.upper()}]")
    print(f"=======================================================")

    for sym in symbols:
        res = set_zerodha_1pct_breakout_alert(sym, timeframe=timeframe)
        results.append(res)
        print(f"Symbol: {res['symbol']:<12} | Recent High: INR {res['recent_high']:<9} | Alert Trigger (+1%): INR {res['alert_trigger_price']:<9} | Qty: {res['gtt_quantity']} | Status: {res['status']}")

    # Post-setup verification & retry loop
    results = verify_and_retry_gtt_alerts(results, timeframe=timeframe)
    return results

if __name__ == "__main__":
    sample_symbols = ["WELCORP", "AEROFLEX", "SIGACHI"]
    print("Testing Zerodha 1% Breakout Alert Setup...")
    setup_alerts_for_symbols(sample_symbols, timeframe="monthly")
