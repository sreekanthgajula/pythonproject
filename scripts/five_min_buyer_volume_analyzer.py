"""
===============================================================================
5-MINUTE GOOD BUYER VOLUME ANALYZER & RATING ENGINE
===============================================================================
Description:
    1. Fetches current trading day's 5-minute historical candle data using
       Zerodha KiteConnect `kite.historical_data(..., interval='5minute')`
       (with market data fallback).
    2. Checks live Order Book Market Depth (`total_buy_quantity` vs `total_sell_quantity`).
    3. Evaluates 4 Good Buyer Volume conditions:
       - Bullish Candle: close > open & close near high of candle
       - Volume Spike: 5m volume >= 2.5x to 3x 20-period SMA of 5m volume
       - Order Book Buyers: total_buy_quantity > total_sell_quantity
       - Price Action Confirmation: close > prev_5m_high
    4. Computes a Buy Signal Rating out of 1 to 10.
    5. Returns boolean decision (True/False), rating out of 10, metrics, and
       formatted Telegram message block.
===============================================================================
"""

import os
import sys
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

load_dotenv(dotenv_path=project_root / ".env")
logger = logging.getLogger("FiveMinBuyerVolumeAnalyzer")

# Try importing KiteConnect & yfinance
try:
    from kiteconnect import KiteConnect
    KITE_AVAILABLE = True
except ImportError:
    KITE_AVAILABLE = False

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

def get_kite_client():
    """Retrieves authenticated Zerodha KiteConnect instance."""
    api_key = os.getenv("ZERODHA_API_KEY")
    access_token = os.getenv("ZERODHA_ACCESS_TOKEN")
    if KITE_AVAILABLE and api_key and access_token:
        try:
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            return kite
        except Exception as e:
            logger.warning(f"Zerodha KiteConnect init error in 5m analyzer: {e}")
            return None
    return None

def analyze_5min_good_buyer_volume(symbol: str, kite=None) -> dict:
    """
    Analyzes the latest 5-minute candle data for a given stock symbol based on 4 Good Buyer Volume conditions:
      1. Bullish Candle: close > open & close near high of candle
      2. Volume Spike: 5m volume >= 2.5x 20-period SMA of volume
      3. Order Book Buyers (Market Depth): total_buy_quantity > total_sell_quantity
      4. Price Action Confirmation: close > prev_candle_high
      
    Returns a dict containing boolean decisions, individual condition details, score out of 10, and summary string.
    """
    clean_sym = symbol.strip().upper().replace(".NS", "")
    kite = kite or get_kite_client()
    
    candles = []
    total_buy_qty = 0
    total_sell_qty = 0
    data_source = "UNKNOWN"

    # 1. Fetch 5-minute candles & quote from Zerodha Kite Connect
    if kite:
        try:
            from tradingagents.dataflows.zerodha import get_instrument_token
            try:
                token = get_instrument_token(clean_sym)
            except Exception:
                token = None

            if token:
                today = datetime.now()
                from_date = today - timedelta(days=5)
                candles_raw = kite.historical_data(
                    instrument_token=token,
                    from_date=from_date.strftime("%Y-%m-%d"),
                    to_date=today.strftime("%Y-%m-%d"),
                    interval="5minute"
                )
                if candles_raw:
                    candles = candles_raw
                    data_source = "ZERODHA_KITE_API"

            # Fetch live Market Depth / Quote for Buy vs Sell Quantity
            try:
                quote_resp = kite.quote(f"NSE:{clean_sym}")
                q_data = quote_resp.get(f"NSE:{clean_sym}", {})
                total_buy_qty = int(q_data.get("total_buy_quantity") or 0)
                total_sell_qty = int(q_data.get("total_sell_quantity") or 0)
            except Exception as q_err:
                logger.warning(f"Zerodha quote market depth fetch notice for {clean_sym}: {q_err}")

        except Exception as k_err:
            logger.warning(f"Zerodha historical 5m fetch notice for {clean_sym}: {k_err}")

    # 2. Fallback to yfinance if Zerodha historical fetch failed
    if len(candles) < 21 and YFINANCE_AVAILABLE:
        try:
            yf_sym = f"{clean_sym}.NS" if not clean_sym.endswith(".NS") else clean_sym
            t = yf.Ticker(yf_sym)
            df = t.history(period="5d", interval="5m")
            if not df.empty and len(df) >= 21:
                candles = []
                for idx, row in df.iterrows():
                    candles.append({
                        "date": idx,
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": int(row["Volume"])
                    })
                data_source = "YFINANCE_FALLBACK"
        except Exception as yf_err:
            logger.warning(f"yfinance 5m fallback fetch failed for {clean_sym}: {yf_err}")

    # If insufficient candles available
    if len(candles) < 21:
        return {
            "symbol": clean_sym,
            "buy_signal": False,
            "score_out_of_10": 1,
            "reason": f"Insufficient 5-minute candle data ({len(candles)} candles found).",
            "conditions": {
                "bullish_candle": False,
                "volume_spike": False,
                "order_book_buyers": False,
                "price_breakout": False
            },
            "metrics": {
                "close": 0.0, "open": 0.0, "high": 0.0, "low": 0.0,
                "volume": 0, "prev_high": 0.0, "sma_20_vol": 0.0,
                "vol_ratio": 0.0, "total_buy_qty": total_buy_qty, "total_sell_qty": total_sell_qty
            },
            "data_source": data_source
        }

    # Extract current (latest completed/active) and previous candles
    curr = candles[-1]
    prev = candles[-2]
    history_20 = candles[-21:-1] # 20 candles prior to current

    curr_open = float(curr["open"])
    curr_high = float(curr["high"])
    curr_low = float(curr["low"])
    curr_close = float(curr["close"])
    curr_vol = int(curr["volume"])
    prev_high = float(prev["high"])

    # 20-period SMA of 5-minute volume
    sma_20_vol = sum(int(c["volume"]) for c in history_20) / 20.0
    vol_ratio = (curr_vol / sma_20_vol) if sma_20_vol > 0 else 1.0

    # -------------------------------------------------------------------------
    # EVALUATE 4 GOOD BUYER VOLUME CONDITIONS
    # -------------------------------------------------------------------------
    
    # Condition 1: Bullish Candle (close > open & close near high of candle)
    candle_range = max(curr_high - curr_low, 0.01)
    close_near_high_ratio = (curr_close - curr_low) / candle_range
    is_bullish_candle = (curr_close > curr_open) and (close_near_high_ratio >= 0.60)

    # Condition 2: Volume Spike (latest 5m volume >= 2.5x 20-period SMA)
    is_volume_spike = vol_ratio >= 2.5

    # Condition 3: Order Book Buyers (total_buy_quantity > total_sell_quantity)
    if total_buy_qty > 0 or total_sell_qty > 0:
        is_order_book_buyers = total_buy_qty > total_sell_qty
    else:
        is_order_book_buyers = (curr_close > curr_open) and (vol_ratio >= 2.0)

    # Condition 4: Price Action Confirmation (close > previous 5m candle high)
    is_price_breakout = curr_close > prev_high

    # -------------------------------------------------------------------------
    # CALCULATE RATING / CONVICTION SCORE (1 to 10)
    # -------------------------------------------------------------------------
    score = 1  # Base starting score

    # Condition 1 points
    if is_bullish_candle:
        score += 2
    elif curr_close > curr_open:
        score += 1

    # Condition 2 points (Volume ratio weighting)
    if vol_ratio >= 3.5:
        score += 3
    elif vol_ratio >= 2.5:
        score += 2
    elif vol_ratio >= 1.8:
        score += 1

    # Condition 3 points (Market Depth / Order Book weighting)
    if total_buy_qty > 0 and total_sell_qty > 0:
        buy_sell_ratio = total_buy_qty / max(total_sell_qty, 1)
        if buy_sell_ratio >= 1.5:
            score += 2
        elif buy_sell_ratio > 1.0:
            score += 1
    elif is_order_book_buyers:
        score += 1

    # Condition 4 points
    if is_price_breakout:
        score += 2

    # Final score bounds [1, 10]
    score = max(1, min(10, score))

    # Master BUY decision: True if score >= 7 or (at least 3 conditions pass including vol_spike & bullish_candle)
    passed_count = sum([is_bullish_candle, is_volume_spike, is_order_book_buyers, is_price_breakout])
    is_buy_signal = (score >= 7) or (passed_count >= 3 and is_volume_spike and is_bullish_candle)

    return {
        "symbol": clean_sym,
        "buy_signal": is_buy_signal,
        "score_out_of_10": score,
        "metrics": {
            "close": curr_close,
            "open": curr_open,
            "high": curr_high,
            "low": curr_low,
            "volume": curr_vol,
            "prev_high": prev_high,
            "sma_20_vol": round(sma_20_vol, 1),
            "vol_ratio": round(vol_ratio, 2),
            "total_buy_qty": total_buy_qty,
            "total_sell_qty": total_sell_qty
        },
        "conditions": {
            "bullish_candle": is_bullish_candle,
            "volume_spike": is_volume_spike,
            "order_book_buyers": is_order_book_buyers,
            "price_breakout": is_price_breakout
        },
        "data_source": data_source
    }

import html

def is_telegram_alert_allowed(buyer_score: int) -> bool:
    """
    Filtering Rule for Telegram Alert Messages:
    - ALLOW sending Telegram alert ONLY IF BUY CONVICTION RATING is:
      8/10, 9/10, 10/10 (High Conviction Buy) OR 1/10, 2/10, 3/10 (High Conviction Caution/Neutral).
    - IGNORE / BLOCK Telegram alert IF BUY CONVICTION RATING is:
      4/10, 5/10, 6/10, 7/10 (Mid-tier/Rest of messages).
    """
    try:
        score = int(buyer_score)
        return score in (1, 2, 3, 8, 9, 10)
    except (ValueError, TypeError):
        return False

def format_telegram_buyer_analysis_text(symbol: str, db_doc: dict, analysis: dict) -> str:
    """
    Formats the complete Telegram alert message incorporating MongoDB DB details
    (Symbol, Grok Rating, Grok Reason) + the 5-Minute Good Buyer Volume Signal & 1-10 Rating.
    Uses Green theme banners & blocks for POSITIVE BUY signals and Red theme banners & blocks for NEUTRAL/NO BUY signals.
    """
    rating_val = db_doc.get("rating", "N/A")
    reason_val = html.escape(str(db_doc.get("reason", "Evaluated via Grok AI screener.")))
    recent_high = db_doc.get("recent_high", 0.0)
    trigger_price = db_doc.get("alert_trigger_price", 0.0)
    timeframe = str(db_doc.get("timeframe", "monthly")).upper()
    gtt_status = html.escape(str(db_doc.get("gtt_status", "REJECTED (Qty: 5000)")))
    clean_symbol = html.escape(symbol.upper())

    buyer_score = analysis.get("score_out_of_10", 1)
    is_positive = bool(analysis.get("buy_signal")) or (buyer_score >= 7)

    c = analysis.get("conditions", {})
    m = analysis.get("metrics", {})

    c1 = "✅ <b>YES</b>" if c.get("bullish_candle") else "❌ <b>NO</b>"
    c2 = f"✅ <b>YES ({m.get('vol_ratio', 0)}x SMA)</b>" if c.get("volume_spike") else f"❌ <b>NO ({m.get('vol_ratio', 0)}x SMA)</b>"
    
    buy_qty = m.get("total_buy_qty", 0)
    sell_qty = m.get("total_sell_qty", 0)
    if buy_qty > 0 or sell_qty > 0:
        c3 = f"✅ <b>YES (Buy: {buy_qty:,} > Sell: {sell_qty:,})</b>" if c.get("order_book_buyers") else f"❌ <b>NO (Buy: {buy_qty:,} &lt;= Sell: {sell_qty:,})</b>"
    else:
        c3 = "✅ <b>YES (Bullish Vol Flow)</b>" if c.get("order_book_buyers") else "⚠️ <b>NO (Depth Unavailable)</b>"
        
    c4 = f"✅ <b>YES (Close ₹{m.get('close', 0):.2f} > Prev High ₹{m.get('prev_high', 0):.2f})</b>" if c.get("price_breakout") else f"❌ <b>NO (Close ₹{m.get('close', 0):.2f} &lt;= Prev High ₹{m.get('prev_high', 0):.2f})</b>"

    if is_positive:
        banner = "🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢"
        header_title = "🟢 <b>POSITIVE BUY SIGNAL CONFIRMED</b> 🟢"
        callout_status = "🟢 <b>[BUY SIGNAL CONFIRMED — HIGH BUYER CONVICTION]</b>"
        buy_decision = "🚀 <b>BUY (TRIGGERED - POSITIVE SIGNAL)</b>"
        score_badge = f"🟢 <b>{buyer_score} / 10 (POSITIVE BUY RATING)</b>"
    else:
        banner = "🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴"
        header_title = "🔴 <b>NEUTRAL / NO BUY SIGNAL — CAUTION</b> 🔴"
        callout_status = "🔴 <b>[NEUTRAL / NO BUY SIGNAL — WEAK VOLUME]</b>"
        buy_decision = "⚠️ <b>HOLD / NO BUY (NEUTRAL / WEAK SIGNAL)</b>"
        score_badge = f"🔴 <b>{buyer_score} / 10 (NEUTRAL / LOW RATING)</b>"

    msg = (
        f"{banner}\n"
        f"{header_title}\n"
        f"{banner}\n\n"
        f"{callout_status}\n\n"
        f"📌 <b>Symbol</b>: <code>{clean_symbol}</code> ({timeframe})\n"
        f"⭐ <b>Grok Conviction Rating</b>: <b>{rating_val} / 5.0</b>\n"
        f"📝 <b>Grok Rationale</b>: <i>{reason_val}</i>\n\n"
        f"💰 <b>Recent Peak High</b>: <code>₹{recent_high:.2f}</code>\n"
        f"🎯 <b>DB Trigger Price</b>: <code>₹{trigger_price:.2f}</code> (+1% Breakout)\n"
        f"📦 <b>Zerodha Order Status</b>: <code>{gtt_status}</code>\n\n"
        f"📊 <b>5-MINUTE GOOD BUYER VOLUME ANALYSIS</b>:\n"
        f"• <b>Bullish Candle</b>: {c1}\n"
        f"• <b>Volume Spike (>= 2.5x SMA)</b>: {c2}\n"
        f"• <b>Order Book Buyers</b>: {c3}\n"
        f"• <b>Price Action Breakout</b>: {c4}\n\n"
        f"🎯 <b>BUY SIGNAL DECISION</b>: {buy_decision}\n"
        f"🏆 <b>BUY CONVICTION RATING</b>: {score_badge}\n\n"
        f"{banner}"
    )
    return msg

