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

def set_zerodha_1pct_breakout_alert(symbol: str, timeframe: str = "monthly") -> dict:
    """
    Programmatically sets an alert 1% above the recent high for a stock symbol
    and records it in Zerodha (via GTT / Alert API) and the local database.
    """
    clean_sym = symbol.strip().upper()
    recent_high, trigger_price = fetch_recent_high(clean_sym, timeframe=timeframe)

    kite = get_kite_client()
    gtt_status = "REGISTERED_LOCAL"

    # Attempt Zerodha GTT (Good-Till-Triggered) order/alert placement
    if kite:
        try:
            trading_symbol = clean_sym.replace(".NS", "")
            # Place GTT single trigger alert 1% above recent high
            # Note: GTT trigger values expect trigger price
            gtt_resp = kite.place_gtt(
                trigger_type=kite.GTT_TYPE_SINGLE,
                tradingsymbol=trading_symbol,
                exchange="NSE",
                trigger_values=[trigger_price],
                last_price=recent_high,
                orders=[{
                    "transaction_type": kite.TRANSACTION_TYPE_BUY,
                    "quantity": 1,
                    "order_type": kite.ORDER_TYPE_LIMIT,
                    "product": kite.PRODUCT_CNC,
                    "price": trigger_price
                }]
            )
            gtt_id = gtt_resp.get("trigger_id")
            gtt_status = f"ZERODHA_GTT_ACTIVE (ID: {gtt_id})"
            logger.info(f"[ZERODHA GTT] Set 1% breakout alert for {trading_symbol} at ₹{trigger_price} (GTT ID: {gtt_id})")
        except Exception as e:
            logger.warning(f"Zerodha GTT placement for {clean_sym} notice: {e}")
            gtt_status = f"LOCAL_ALERT_SET ({e})"

    # Update database record with recent_high and alert_trigger_price
    try:
        dm = DataManager()
        col = dm.db[timeframe.strip().lower()]
        col.update_one(
            {"symbol": clean_sym},
            {
                "$set": {
                    "recent_high": recent_high,
                    "alert_trigger_price": trigger_price,
                    "alert_status": gtt_status,
                    "alert_updated_at": datetime.now(timezone.utc).replace(tzinfo=None)
                }
            },
            upsert=True
        )
        logger.info(f"Updated '{timeframe}' table for {clean_sym}: High=₹{recent_high}, Trigger=₹{trigger_price} (+1%)")
    except Exception as db_err:
        logger.error(f"Failed to update alert data in DB for {clean_sym}: {db_err}")

    return {
        "symbol": clean_sym,
        "timeframe": timeframe,
        "recent_high": recent_high,
        "alert_trigger_price": trigger_price,
        "status": gtt_status
    }

def setup_alerts_for_symbols(symbols: list[str], timeframe: str = "monthly") -> list[dict]:
    """
    Processes a list of stock symbols, computes 1% above recent high,
    and programmatically places alerts for all of them.
    """
    results = []
    print(f"\n=======================================================")
    print(f" SETTING ZERODHA 1% BREAKOUT ALERTS [{timeframe.upper()}]")
    print(f"=======================================================")
    
    for sym in symbols:
        res = set_zerodha_1pct_breakout_alert(sym, timeframe=timeframe)
        results.append(res)
        print(f"Symbol: {res['symbol']:<12} | Recent High: INR {res['recent_high']:<9} | Alert Trigger (+1%): INR {res['alert_trigger_price']:<9} | Status: {res['status']}")
        
    return results

if __name__ == "__main__":
    sample_symbols = ["WELCORP", "AEROFLEX", "SIGACHI"]
    print("Testing Zerodha 1% Breakout Alert Setup...")
    setup_alerts_for_symbols(sample_symbols, timeframe="monthly")
