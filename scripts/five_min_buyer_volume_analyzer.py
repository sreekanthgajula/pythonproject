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


def evaluate_daily_breakout_ripeness(symbol: str, current_price: float, token: int = None, kite=None) -> dict:
    """
    Evaluates whether the Daily chart structure is 'RIPE' for a breakout,
    ensuring a 5-minute breakout trigger is NOT just intraday noise or mean-reverting churn.

    NOTE: Per project rules, this Daily Ripeness Gatekeeper applies EXCLUSIVELY to individual
    equity stocks. Derivatives (NIFTY/BANKNIFTY/Options/Futures) bypass this gate as their trades
    are governed strictly by intraday 5m 3-confirmation OI + Straddle dynamics.

    Criteria for a 'RIPE' Daily Stock Breakout:
      1. Proximity to 20-Day Resistance Pivot:
         Current 5m price must be within -2.0% to +2.5% of the 20-day high (testing or piercing the daily ceiling).
         If > 2.5% above: overextended. If < -2.0% below: stuck in mid-range noise.
      2. Daily Macro Trend:
         Price must be trading above the 20-Day Daily EMA (and ideally 50 SMA).
         Prevents buying 5m counter-trend dead-cat bounces in Stage 4 downtrends.
      3. Daily ATR Headroom (Not Exhausted):
         Today's high-low range must not exceed 1.6x 14-day Daily ATR.
    """
    clean_sym = symbol.strip().upper().replace(".NS", "")

    # Check if derivative (NIFTY, BANKNIFTY, FINNIFTY, Futures, Options)
    try:
        from scripts.chart_generator import is_derivative_symbol
        if is_derivative_symbol(clean_sym):
            return {
                "is_ripe": True,
                "ripeness_score": 10,
                "reason": "Derivative instrument bypasses stock Daily pivot/Darvas gate (governed by 3-Confirmation OI+Straddle engine).",
                "is_derivative": True,
                "summary": "Derivative (Bypassed)",
                "metrics": {}
            }
    except Exception:
        pass

    kite = kite or get_kite_client()
    if not kite or current_price <= 0:
        return {
            "is_ripe": False,
            "ripeness_score": 1,
            "reason": "Kite client unavailable or invalid price for Daily Ripe evaluation.",
            "metrics": {}
        }

    try:
        from tradingagents.dataflows.zerodha import get_instrument_token
        token = token or get_instrument_token(clean_sym)
        if not token:
            return {"is_ripe": False, "ripeness_score": 1, "reason": "No instrument token.", "metrics": {}}

        today = datetime.now()
        from_date = today - timedelta(days=120)
        daily_candles = kite.historical_data(
            instrument_token=token,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=today.strftime("%Y-%m-%d"),
            interval="day"
        )
        if not daily_candles or len(daily_candles) < 25:
            return {
                "is_ripe": False,
                "ripeness_score": 1,
                "reason": f"Insufficient daily candles ({len(daily_candles) if daily_candles else 0}).",
                "metrics": {}
            }

        import pandas as pd
        import numpy as np

        df_d = pd.DataFrame(daily_candles)
        # Use prior 20 completed days (excluding the last active day) for pivot high
        history_20 = df_d.iloc[-21:-1] if len(df_d) >= 21 else df_d.iloc[:-1]
        pivot_20d_high = float(history_20["high"].max())
        pivot_50d_high = float(df_d["high"].iloc[-51:-1].max()) if len(df_d) >= 51 else pivot_20d_high

        # 20-period EMA on daily close
        df_d["ema20"] = df_d["close"].ewm(span=20, adjust=False).mean()
        daily_ema20 = float(df_d["ema20"].iloc[-1])

        # 50-period SMA on daily close
        df_d["sma50"] = df_d["close"].rolling(50).mean()
        daily_sma50 = float(df_d["sma50"].iloc[-1]) if pd.notna(df_d["sma50"].iloc[-1]) else daily_ema20

        # Distance to 20-day high pivot
        dist_to_pivot_pct = round(((current_price - pivot_20d_high) / pivot_20d_high) * 100.0, 2) if pivot_20d_high > 0 else 0.0

        # ATR 14 Calculation
        tr1 = df_d["high"] - df_d["low"]
        tr2 = (df_d["high"] - df_d["close"].shift(1)).abs()
        tr3 = (df_d["low"] - df_d["close"].shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        daily_atr = float(tr.rolling(14).mean().iloc[-1]) if len(tr) >= 14 else float(tr.mean())

        today_candle = df_d.iloc[-1]
        today_range = float(today_candle["high"] - today_candle["low"])
        atr_ratio = round(today_range / daily_atr, 2) if daily_atr > 0 else 1.0
        is_atr_exhausted = atr_ratio > 1.6

        # 1. Proximity condition: at or piercing daily ceiling (-2.0% to +2.5%)
        at_daily_pivot = (-2.0 <= dist_to_pivot_pct <= 2.5)
        # 2. Daily trend condition: above 20 EMA
        above_20_ema = current_price >= (daily_ema20 * 0.99)
        above_50_sma = current_price >= daily_sma50

        # Daily Ripeness Score (1 to 10)
        score = 1
        reasons = []

        if at_daily_pivot:
            score += 4
            reasons.append(f"At Daily Resistance Pivot ({dist_to_pivot_pct:+.1f}% of 20d High ₹{pivot_20d_high:.2f})")
        elif -3.5 <= dist_to_pivot_pct < -2.0:
            score += 2
            reasons.append(f"Approaching Daily Pivot ({dist_to_pivot_pct:+.1f}% of 20d High)")
        elif dist_to_pivot_pct > 2.5:
            reasons.append(f"Overextended above Daily Pivot (+{dist_to_pivot_pct:.1f}% > 20d High)")
        else:
            reasons.append(f"Stuck in Mid-Range Noise ({dist_to_pivot_pct:.1f}% below 20d High)")

        if above_20_ema:
            score += 2
            reasons.append(f"Above Daily 20 EMA (₹{daily_ema20:.2f})")
        else:
            reasons.append(f"Below Daily 20 EMA (₹{daily_ema20:.2f}) — Downtrend Risk")

        if above_50_sma:
            score += 1
            reasons.append(f"Above Daily 50 SMA (₹{daily_sma50:.2f})")

        if not is_atr_exhausted:
            score += 2
            reasons.append(f"Healthy ATR Headroom ({atr_ratio}x ATR, not exhausted)")
        else:
            reasons.append(f"Intraday Move Exhausted ({atr_ratio}x Daily ATR)")

        score = max(1, min(10, score))

        # RIPE verdict: requires being at/piercing daily pivot, above 20 EMA, and not exhausted
        is_ripe = bool(at_daily_pivot and above_20_ema and (not is_atr_exhausted))

        summary_reason = "RIPE BREAKOUT: Testing/piercing Daily 20-day high in strong uptrend with ample ATR runway." if is_ripe else f"NOT RIPE: 5m breakout is noise — Daily chart is not at a ripe breakout pivot ({dist_to_pivot_pct:+.1f}% from 20d high)."

        return {
            "is_ripe": is_ripe,
            "ripeness_score": score,
            "at_daily_pivot": at_daily_pivot,
            "above_20_ema": above_20_ema,
            "above_50_sma": above_50_sma,
            "is_atr_exhausted": is_atr_exhausted,
            "dist_to_pivot_pct": dist_to_pivot_pct,
            "pivot_20d_high": pivot_20d_high,
            "pivot_50d_high": pivot_50d_high,
            "daily_ema20": round(daily_ema20, 2),
            "daily_sma50": round(daily_sma50, 2),
            "daily_atr": round(daily_atr, 2),
            "atr_ratio": atr_ratio,
            "reasons": reasons,
            "summary": summary_reason
        }
    except Exception as e:
        logger.error(f"Error in evaluate_daily_breakout_ripeness for {symbol}: {e}")
        return {
            "is_ripe": False,
            "ripeness_score": 1,
            "reason": f"Evaluation error: {e}",
            "metrics": {}
        }


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

    # If insufficient candles available from Zerodha
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

    # 5. Evaluate Daily Breakout Ripeness (Hierarchical Multi-Timeframe Confirmation)
    daily_ripeness = evaluate_daily_breakout_ripeness(clean_sym, curr_close, token=token, kite=kite)
    is_daily_ripe = daily_ripeness.get("is_ripe", False)
    is_deriv = daily_ripeness.get("is_derivative", False)

    # Master BUY decision:
    # 5-minute good buyer volume triggers the spark.
    # For individual equity stocks: the Daily chart MUST be RIPE to filter out mean-reverting 5m noise!
    # For derivatives: strictly governed by intraday 5m 3-confirmation OI + Straddle dynamics.
    passed_count = sum([is_bullish_candle, is_volume_spike, is_order_book_buyers, is_price_breakout])
    five_min_signal = (score >= 7) or (passed_count >= 3 and is_volume_spike and is_bullish_candle)

    # Combined Multi-Timeframe Signal: Spark (5m) + Dry Powder (Daily for Stocks)
    if is_deriv:
        is_buy_signal = bool(five_min_signal)
    else:
        is_buy_signal = bool(five_min_signal and is_daily_ripe)

    return {
        "symbol": clean_sym,
        "buy_signal": is_buy_signal,
        "five_min_signal": five_min_signal,
        "is_daily_ripe": is_daily_ripe,
        "daily_ripeness": daily_ripeness,
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
            "price_breakout": is_price_breakout,
            "daily_ripe": is_daily_ripe
        },
        "data_source": data_source
    }

import html

def is_telegram_alert_allowed(buyer_score: int, daily_ripeness: dict = None) -> bool:
    """
    Dual-Tier Filtering Rule for Telegram Alert Messages:
    - ALLOW sending Telegram alert ONLY IF BUY CONVICTION RATING is:
      8/10, 9/10, 10/10 (High Conviction Buy) OR 1/10, 2/10, 3/10 (High Conviction Caution/Neutral).
    - IGNORE / BLOCK Telegram alert IF BUY CONVICTION RATING is:
      4/10, 5/10, 6/10, 7/10 (Mid-tier/Rest of messages).
    - CRITICAL MULTI-TIMEFRAME GATE: If rating is 8, 9, 10 (Buy signal), the Daily Breakout MUST BE RIPE!
      If 5m looks good but Daily is NOT ripe (noise / mean-reverting churn), the alert is BLOCKED/SUPPRESSED.
    """
    try:
        score = int(buyer_score)
        if score not in (1, 2, 3, 8, 9, 10):
            return False

        # If it's a Buy alert, enforce Daily Ripeness Gate!
        if score in (8, 9, 10):
            if daily_ripeness and not daily_ripeness.get("is_ripe", False):
                logger.info(f"🚫 [TELEGRAM ALERT SUPPRESSED] 5m Buy signal blocked: Daily chart is NOT ripe ({daily_ripeness.get('summary')}).")
                return False
        return True
    except (ValueError, TypeError):
        return False

def format_telegram_buyer_analysis_text(symbol: str, db_doc: dict, analysis: dict) -> str:
    """
    Formats the complete Telegram alert message incorporating MongoDB DB details
    (Symbol, Grok Rating, Grok Reason) + the 5-Minute Good Buyer Volume Signal & 1-10 Rating
    + Multi-Timeframe Daily Ripeness Confirmation.
    """
    rating_val = db_doc.get("rating", "N/A")
    reason_val = html.escape(str(db_doc.get("reason", "Evaluated via Grok AI screener.")))
    recent_high = db_doc.get("recent_high", 0.0)
    trigger_price = db_doc.get("alert_trigger_price", 0.0)
    timeframe = str(db_doc.get("timeframe", "monthly")).upper()
    gtt_status = html.escape(str(db_doc.get("gtt_status", "REJECTED (Qty: 5000)")))
    clean_symbol = html.escape(symbol.upper())

    buyer_score = analysis.get("score_out_of_10", 1)
    is_daily_ripe = analysis.get("is_daily_ripe", False)
    is_positive = bool(analysis.get("buy_signal"))

    c = analysis.get("conditions", {})
    m = analysis.get("metrics", {})
    d_rip = analysis.get("daily_ripeness", {})

    c1 = "✅ <b>YES</b>" if c.get("bullish_candle") else "❌ <b>NO</b>"
    c2 = f"✅ <b>YES ({m.get('vol_ratio', 0)}x SMA)</b>" if c.get("volume_spike") else f"❌ <b>NO ({m.get('vol_ratio', 0)}x SMA)</b>"

    buy_qty = m.get("total_buy_qty", 0)
    sell_qty = m.get("total_sell_qty", 0)
    if buy_qty > 0 or sell_qty > 0:
        c3 = f"✅ <b>YES (Buy: {buy_qty:,} > Sell: {sell_qty:,})</b>" if c.get("order_book_buyers") else f"❌ <b>NO (Buy: {buy_qty:,} &lt;= Sell: {sell_qty:,})</b>"
    else:
        c3 = "✅ <b>YES (Bullish Vol Flow)</b>" if c.get("order_book_buyers") else "⚠️ <b>NO (Depth Unavailable)</b>"

    c4 = f"✅ <b>YES (Close ₹{m.get('close', 0):.2f} > Prev High ₹{m.get('prev_high', 0):.2f})</b>" if c.get("price_breakout") else f"❌ <b>NO (Close ₹{m.get('close', 0):.2f} &lt;= Prev High ₹{m.get('prev_high', 0):.2f})</b>"

    # Daily Timeframe block formatting
    p20 = d_rip.get("pivot_20d_high", 0)
    dist = d_rip.get("dist_to_pivot_pct", 0)
    ema = d_rip.get("daily_ema20", 0)
    atr_r = d_rip.get("atr_ratio", 1.0)
    d_score = d_rip.get("ripeness_score", 1)

    if is_daily_ripe:
        d_status = "🟢 <b>RIPE DAILY BREAKOUT (Not Noise!)</b>"
    else:
        d_status = "🔴 <b>DAILY NOT RIPE (Intraday Noise / Mid-Range)</b>"

    daily_block = (
        f"🏛️ <b>DAILY TIMEFRAME CONFIRMATION (IS IT RIPE?)</b>:\n"
        f"• <b>Status</b>: {d_status}\n"
        f"• <b>20-Day Resistance Pivot</b>: <code>₹{p20:.2f}</code> ({dist:+.1f}% from 5m price)\n"
        f"• <b>Daily Trend</b>: {'✅ Above 20 EMA (₹' + str(ema) + ')' if d_rip.get('above_20_ema') else '❌ Below 20 EMA'}\n"
        f"• <b>ATR Headroom</b>: {'✅ Healthy (' + str(atr_r) + 'x ATR)' if not d_rip.get('is_atr_exhausted') else '⚠️ Exhausted'}\n"
        f"• <b>Daily Ripeness Rating</b>: <b>{d_score} / 10</b>"
    )

    if is_positive:
        banner = "🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢"
        header_title = "🟢 <b>RIPE BUY BREAKOUT CONFIRMED</b> 🟢"
        callout_status = "🟢 <b>[5M SPARK + RIPE DAILY BREAKOUT CONFIRMED]</b>"
        buy_decision = "🚀 <b>BUY (5M TRIGGER + DAILY PIVOT RIPE)</b>"
        score_badge = f"🟢 <b>{buyer_score} / 10 (RIPE BREAKOUT CONFIRMED)</b>"
    elif analysis.get("five_min_signal") and not is_daily_ripe:
        banner = "🟡🟡🟡🟡🟡🟡🟡🟡🟡🟡🟡🟡🟡🟡🟡"
        header_title = "🟡 <b>INTRADAY NOISE DETECTED — DAILY NOT RIPE</b> 🟡"
        callout_status = "🟡 <b>[5M BREAKOUT IS NOISE — DAILY STRUCTURE NOT RIPE]</b>"
        buy_decision = "⚠️ <b>DISCARD (5M GREEN BUT DAILY MID-RANGE/DOWNTREND)</b>"
        score_badge = f"🟡 <b>{buyer_score} / 10 (5M TRIGGER BUT DAILY COLD)</b>"
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
        f"📊 <b>5-MINUTE GOOD BUYER VOLUME ANALYSIS (TACTICAL SPARK)</b>:\n"
        f"• <b>Bullish Candle</b>: {c1}\n"
        f"• <b>Volume Spike (>= 2.5x SMA)</b>: {c2}\n"
        f"• <b>Order Book Buyers</b>: {c3}\n"
        f"• <b>Price Action Breakout</b>: {c4}\n\n"
        f"{daily_block}\n\n"
        f"🎯 <b>BUY SIGNAL DECISION</b>: {buy_decision}\n"
        f"🏆 <b>BUY CONVICTION RATING</b>: {score_badge}\n\n"
        f"{banner}"
    )
    return msg

