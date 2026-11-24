"""
===============================================================================
WEEKLY COILING & PRE-BREAKOUT SCANNER (v1.0)
===============================================================================
Institutional-grade pre-breakout scanner inspired by SPECTRUM's July 2026 setup:
1. 100% Zerodha API Compliance (Zero yfinance dependencies).
2. Weekly True Strength Index (TSI 13,25,13) Absorption Gate.
3. Weekly On-Balance Volume (OBV) Stealth Accumulation Gate.
4. Multi-Week Tight Consolidation Shelf (VCP / Darvas Box Coiling).
5. Automatic GTT Entry (+1% Breakout Trigger) & Stop-Loss Calculation.
6. Persists qualified candidates to MongoDB collection 'weekly_coiling_candidates'.
===============================================================================
"""

import os
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

import pandas as pd
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from tradingagents.dataflows.symbol_utils import normalize_symbol
from tradingagents.dataflows.zerodha import get_instrument_token
from tradingagents.market_timing import (
    get_now_ist,
    get_today_ist,
    get_ist_date_str,
    format_dual_timezone_stamp,
)
from data_manager import DataManager
from scripts.zerodha_alert_manager import get_kite_client
from momentum_volume_monitor import calculate_tsi, calculate_obv

load_dotenv(dotenv_path=project_root / ".env")
logger = logging.getLogger("weekly_coiling_scanner")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def analyze_weekly_coiling_candidate(symbol: str, kite=None) -> Optional[Dict[str, Any]]:
    """
    Evaluates whether a stock is forming a high-probability Weekly Pre-Breakout Coiling setup.
    Returns metrics dict or None if insufficient history or not coiling.
    """
    clean_sym = normalize_symbol(symbol).replace(".NS", "").replace("-EQ", "")
    kite = kite or get_kite_client()
    if not kite:
        logger.warning("[COILING SCANNER] Zerodha Kite client not connected.")
        return None

    try:
        token = get_instrument_token(clean_sym)
    except Exception as e:
        logger.debug(f"[COILING SCANNER] No token for {clean_sym}: {e}")
        return None

    # Fetch daily historical candles for the last 400 days
    to_d = datetime.now()
    from_d = to_d - timedelta(days=400)
    try:
        candles = kite.historical_data(token, from_d, to_d, "day")
        if not candles or len(candles) < 60:
            return None
    except Exception as e:
        logger.debug(f"[COILING SCANNER] Historical fetch failed for {clean_sym}: {e}")
        return None

    df = pd.DataFrame(candles)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)

    # Resample to weekly (Friday close)
    weekly_agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }
    df_w = df.resample("W-FRI").agg(weekly_agg).dropna().copy()
    if len(df_w) < 25:
        return None

    # Indicator calculations on Weekly Frame
    tsi_res = calculate_tsi(df_w, fast=13, slow=25, signal=13)
    df_w["tsi"] = tsi_res["tsi"]
    df_w["tsi_signal"] = tsi_res["tsi_signal"]
    df_w["tsi_slope_2"] = df_w["tsi"].diff(2)

    df_w["obv"] = calculate_obv(df_w)
    df_w["obv_ema20"] = df_w["obv"].ewm(span=20, adjust=False).mean()
    df_w["ema20"] = df_w["close"].ewm(span=20, adjust=False).mean()
    df_w["sma50"] = df_w["close"].rolling(50).mean()
    df_w["vol_sma20"] = df_w["volume"].rolling(20).mean()

    latest = df_w.iloc[-1]
    curr_price = float(latest["close"])
    if curr_price <= 0:
        return None

    # =========================================================================
    # INSTITUTIONAL BALANCING GATES (VCP / RISK / LIQUIDITY)
    # =========================================================================
    # 1. Liquidity Floor: Filter out microcaps / penny stocks subject to circuit locks
    vol_val = float(latest["volume"]) if pd.notna(latest["volume"]) else 0.0
    vol_sma = float(latest["vol_sma20"]) if pd.notna(latest["vol_sma20"]) else vol_val
    if curr_price < 50.0 or vol_sma < 20000:
        return None

    # 2. Moving Average Structural Health Gate
    ema20_val = float(latest["ema20"]) if pd.notna(latest["ema20"]) else curr_price
    above_20_ema = bool(curr_price >= ema20_val)
    if curr_price < (ema20_val * 0.95):
        # Stock has broken down significantly below its 20-week EMA
        return None

    # 3. Multi-Week Base (4 Weeks) & Terminal Pivot Shelf (Last 2 Weeks)
    shelf_weeks = min(4, len(df_w))
    recent_shelf = df_w.iloc[-shelf_weeks:]
    shelf_high = float(recent_shelf["high"].max())
    shelf_low = float(recent_shelf["low"].min())
    if shelf_low <= 0:
        return None
    shelf_spread_pct = round(((shelf_high - shelf_low) / shelf_low) * 100.0, 2)

    # Reject loose, wide bases (> 20.0% spread across 4 weeks)
    if shelf_spread_pct > 20.0:
        return None

    # Terminal 2-Week Coiling Pivot (where the coil tightens before ignition)
    pivot_shelf = df_w.iloc[-2:]
    pivot_high = float(pivot_shelf["high"].max())
    pivot_low = float(pivot_shelf["low"].min())
    pivot_spread_pct = round(((pivot_high - pivot_low) / pivot_low) * 100.0, 2) if pivot_low > 0 else shelf_spread_pct

    # Hard Terminal Coil Gate: The final 2 weeks must contract tightly (<= 12.0%)
    if pivot_spread_pct > 12.0:
        return None

    # 4. GTT Trigger, Risk Geometry & R-Multiple Targets
    gtt_trigger = round(shelf_high * 1.01, 2)
    # Anchor stop-loss to the 2-week terminal pivot low or 20-week EMA
    anchored_stop = max(pivot_low * 0.99, ema20_val * 0.99) if ema20_val > pivot_low else pivot_low * 0.99
    gtt_stoploss = round(anchored_stop, 2)
    risk_pct = round(((gtt_trigger - gtt_stoploss) / gtt_trigger) * 100.0, 2) if gtt_trigger > 0 else 0.0

    # Hard Risk Ceiling Gate: Institutional swing trades must not exceed 11.0% stop distance
    if risk_pct > 11.0:
        return None

    # Automated R-Multiple Milestones
    r_distance = round(gtt_trigger - gtt_stoploss, 2)
    target_1r = round(gtt_trigger + r_distance, 2)
    target_2r = round(gtt_trigger + (2.0 * r_distance), 2)
    target_3r = round(gtt_trigger + (3.5 * r_distance), 2)

    # 5. Wyckoff Spring / Shakeout Detection on Terminal Candle
    rng = float(latest["high"] - latest["low"])
    lower_shadow = float(min(latest["open"], latest["close"]) - latest["low"])
    shadow_ratio = round(lower_shadow / rng, 2) if rng > 0 else 0.0
    close_pos = round((latest["close"] - latest["low"]) / rng, 2) if rng > 0 else 0.0
    has_spring = bool(shadow_ratio >= 0.35 and close_pos >= 0.55)

    # 6. Base Longevity Tier (Darvas Base Age)
    base_age_weeks = 4
    for w in [6, 8, 10, 12]:
        if len(df_w) >= w:
            b_slice = df_w.iloc[-w:]
            b_high = float(b_slice["high"].max())
            b_low = float(b_slice["low"].min())
            b_spread = ((b_high - b_low) / b_low) * 100.0 if b_low > 0 else 999.0
            if b_spread <= 22.0:
                base_age_weeks = w

    # 7. Prior 3-Month Trend Return
    lookback_3m = min(13, len(df_w) - 1)
    close_3m_ago = float(df_w.iloc[-lookback_3m]["close"])
    prior_3m_return = round(((curr_price - close_3m_ago) / close_3m_ago) * 100.0, 2) if close_3m_ago > 0 else 0.0

    # 8. Weekly TSI Metrics
    tsi_val = float(latest["tsi"]) if pd.notna(latest["tsi"]) else 0.0
    sig_val = float(latest["tsi_signal"]) if pd.notna(latest["tsi_signal"]) else 0.0
    slope_val = float(latest["tsi_slope_2"]) if pd.notna(latest["tsi_slope_2"]) else 0.0

    # 9. Weekly OBV Metrics
    obv_val = float(latest["obv"]) if pd.notna(latest["obv"]) else 0.0
    obv_ema = float(latest["obv_ema20"]) if pd.notna(latest["obv_ema20"]) else 0.0
    obv_20w_max = float(df_w["obv"].iloc[-20:].max()) if len(df_w) >= 20 else obv_val

    # 10. Volume Contraction Ratio
    vol_ratio = round(vol_val / vol_sma, 2) if vol_sma > 0 else 1.0

    # =========================================================================
    # BALANCED SCORING ALGORITHM (0 to 100 Max)
    # =========================================================================
    score = 0
    reasons = []

    # Pillar A: Prior Trend Momentum (max 20 pts)
    if prior_3m_return >= 30.0:
        score += 20
        reasons.append(f"Strong 3M Markup (+{prior_3m_return}%)")
    elif prior_3m_return >= 15.0:
        score += 14
        reasons.append(f"Healthy 3M Uptrend (+{prior_3m_return}%)")
    elif prior_3m_return >= 5.0:
        score += 8
        reasons.append(f"Moderate 3M Uptrend (+{prior_3m_return}%)")
    elif prior_3m_return < -5.0:
        score -= 15

    # Pillar B: Weekly True Strength Index Coiling (max 25 pts)
    if tsi_val > 0 and tsi_val >= sig_val and slope_val >= 0:
        score += 25
        reasons.append(f"TSI Bullish Coiling (TSI: {tsi_val:.1f} > Sig: {sig_val:.1f}, Slope: +{slope_val:.1f})")
    elif tsi_val >= sig_val:
        score += 18
        reasons.append(f"TSI Bullish Crossover ({tsi_val:.1f} > {sig_val:.1f})")
    elif tsi_val > 0:
        score += 8

    # Pillar C: Weekly OBV Stealth Accumulation (max 25 pts)
    if obv_val >= obv_ema and obv_val >= (obv_20w_max * 0.95):
        score += 25
        reasons.append("OBV Stealth Accumulation (Near 20W Highs above EMA)")
    elif obv_val >= obv_ema:
        score += 18
        reasons.append("OBV Trending Above 20-Period EMA")
    elif obv_val > 0:
        score += 8

    # Pillar D: Volatility Contraction Shelf Tightness (max 20 pts)
    if pivot_spread_pct <= 6.5:
        score += 20
        reasons.append(f"Vise-Grip 2W Coil ({pivot_spread_pct}% terminal spread, 4W base {shelf_spread_pct}%)")
    elif pivot_spread_pct <= 9.0:
        score += 15
        reasons.append(f"Tight 2W Pivot ({pivot_spread_pct}% terminal spread)")
    elif pivot_spread_pct <= 12.0:
        score += 10
        reasons.append(f"Controlled 2W Pivot ({pivot_spread_pct}% terminal spread)")

    # Pillar E: Volume Dry-Up Exhaustion (max 10 pts)
    if vol_ratio <= 0.50:
        score += 10
        reasons.append(f"Heavy Supply Dry-Up ({vol_ratio}x of 20W avg)")
    elif vol_ratio <= 0.70:
        score += 7
        reasons.append(f"Volume Dry-Up ({vol_ratio}x of 20W avg)")
    elif vol_ratio <= 0.85:
        score += 4
        reasons.append(f"Mild Volume Contraction ({vol_ratio}x of 20W avg)")
    elif vol_ratio > 1.25:
        score -= 5
        reasons.append(f"Volume Churn Warning ({vol_ratio}x avg)")

    # Wyckoff Spring Shakeout Bonus (+5 pts)
    if has_spring:
        score += 5
        reasons.append(f"Wyckoff Spring Shakeout (Lower Shadow {int(shadow_ratio*100)}% Rejection)")

    # Apex Monster Base Bonus (+5 pts)
    if base_age_weeks >= 8:
        score += 5
        reasons.append(f"Apex Monster Base ({base_age_weeks} Weeks Coiling)")
    elif base_age_weeks >= 6:
        score += 3
        reasons.append(f"Extended Base ({base_age_weeks} Weeks Coiling)")

    score = max(0, min(100, score))

    # Minimum threshold to qualify for tracking
    if score < 55:
        return None

    # Elite Actionable Readiness: High score, low risk, and dry volume
    if score >= 75 and risk_pct <= 9.5 and vol_ratio <= 0.85:
        status = "COILING_READY"
        reasons.append("Elite VCP Balance: Tight Terminal Pivot + Dry Volume + Low Risk")
    else:
        status = "COILING_FORMING"

    return {
        "symbol": str(clean_sym),
        "token": int(token),
        "ltp": float(curr_price),
        "coiling_score": int(score),
        "status": str(status),
        "shelf_high": float(shelf_high),
        "shelf_low": float(shelf_low),
        "shelf_spread_pct": float(shelf_spread_pct),
        "pivot_spread_pct": float(pivot_spread_pct),
        "shelf_weeks": int(shelf_weeks),
        "base_age_weeks": int(base_age_weeks),
        "has_spring": bool(has_spring),
        "spring_shadow_pct": int(shadow_ratio * 100),
        "prior_3m_return": float(prior_3m_return),
        "weekly_tsi": float(round(tsi_val, 2)),
        "weekly_tsi_signal": float(round(sig_val, 2)),
        "weekly_tsi_slope": float(round(slope_val, 2)),
        "weekly_obv": float(round(obv_val, 2)),
        "weekly_obv_ema": float(round(obv_ema, 2)),
        "vol_ratio": float(vol_ratio),
        "above_20_ema": bool(above_20_ema),
        "gtt_trigger_price": float(gtt_trigger),
        "gtt_stoploss_price": float(gtt_stoploss),
        "risk_pct": float(risk_pct),
        "r_distance": float(r_distance),
        "target_1r": float(target_1r),
        "target_2r": float(target_2r),
        "target_3r": float(target_3r),
        "reasons": list(reasons),
        "timestamp_ist": get_now_ist().strftime("%Y-%m-%d %H:%M:%S IST"),
        "date": get_ist_date_str()
    }


def scan_and_rank_weekly_coiling_candidates(send_telegram: bool = False, limit: int = 50) -> Dict[str, Any]:
    """
    Scans all tracked symbols across database tables for Weekly Pre-Breakout Coiling Setups.
    Upserts qualified candidates into MongoDB collection 'weekly_coiling_candidates'.
    """
    dm = DataManager()
    if dm.db is None:
        logger.error("[COILING SCANNER] MongoDB not connected.")
        return {"status": "error", "message": "MongoDB not connected"}

    kite = get_kite_client()
    if not kite:
        logger.error("[COILING SCANNER] Zerodha Kite client not connected.")
        return {"status": "error", "message": "Zerodha Kite client not connected"}

    # 1. Collect unique tracked symbols across MongoDB collections
    tracked_symbols = set()
    for col_name in ["monthly", "weekly", "daily", "manual", "darvas"]:
        try:
            for doc in dm.db[col_name].find({}, {"symbol": 1}):
                sym = (doc.get("symbol") or "").strip().upper().replace(".NS", "").replace("-EQ", "")
                if sym:
                    tracked_symbols.add(sym)
        except Exception as e:
            logger.warning(f"[COILING SCANNER] Error reading collection {col_name}: {e}")

    # Ensure landmark benchmark like SPECTRUM is included if tracked
    tracked_symbols.add("SPECTRUM")

    clean_symbols = sorted(list(tracked_symbols))
    logger.info(f"[COILING SCANNER] Scanning {len(clean_symbols)} tracked stocks for Weekly Coiling setups...")

    t0 = time.time()
    candidates = []

    for idx, sym in enumerate(clean_symbols, 1):
        try:
            cand = analyze_weekly_coiling_candidate(sym, kite=kite)
            if cand:
                candidates.append(cand)
        except Exception as e:
            logger.debug(f"[COILING SCANNER] Error analyzing {sym}: {e}")

        if idx % 50 == 0 or idx == len(clean_symbols):
            logger.info(f"[COILING SCANNER] Progress: {idx}/{len(clean_symbols)} scanned ({round(time.time() - t0, 1)}s)")

    # Sort by coiling score descending
    candidates.sort(key=lambda x: x["coiling_score"], reverse=True)
    top_candidates = candidates[:limit]

    # Upsert into MongoDB collection 'weekly_coiling_candidates'
    col = dm.db["weekly_coiling_candidates"]
    col.delete_many({}) # Refresh current standings
    if top_candidates:
        col.insert_many(top_candidates)

    logger.info(f"[COILING SCANNER] Scan complete: Found {len(top_candidates)} coiling candidates ({round(time.time() - t0, 1)}s).")

    # Optional Telegram dispatch for top COILING_READY candidates
    if send_telegram and top_candidates:
        for cand in top_candidates:
            if cand.get("status") == "COILING_READY" and cand.get("coiling_score", 0) >= 80:
                send_weekly_coiling_telegram_alert(cand)

    return {
        "status": "success",
        "count": len(top_candidates),
        "candidates": top_candidates,
        "date": get_ist_date_str(),
        "elapsed_seconds": round(time.time() - t0, 1)
    }


def send_weekly_coiling_telegram_alert(cand: Dict[str, Any]) -> bool:
    """Dispatches a structured Weekly Pre-Breakout Coiling alert to Telegram."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return False

    sym = cand["symbol"]
    score = cand["coiling_score"]
    shelf_h = cand["shelf_high"]
    shelf_l = cand["shelf_low"]
    trigger = cand["gtt_trigger_price"]
    stoploss = cand["gtt_stoploss_price"]
    risk = cand["risk_pct"]
    time_str = format_dual_timezone_stamp(get_now_ist())

    reasons_text = "\n".join([f"• {r}" for r in cand.get("reasons", [])])

    msg = (
        f"⚡ <b>WEEKLY COILING PRE-BREAKOUT ALERT: {sym}</b> ⚡\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Coiling Score:</b> {score}/100 [COILING_READY]\n"
        f"📈 <b>LTP:</b> ₹{cand['ltp']:,.2f}\n"
        f"📦 <b>Weekly Consolidation Shelf:</b> ₹{shelf_l:,.2f} - ₹{shelf_h:,.2f} ({cand['shelf_spread_pct']}%)\n"
        f"🚀 <b>Suggested GTT Trigger (+1%):</b> ₹{trigger:,.2f}\n"
        f"🛑 <b>Suggested Stop-Loss (-1%):</b> ₹{stoploss:,.2f} (Risk: {risk}%)\n"
        f"🎯 <b>Target 1 (+1R):</b> ₹{cand.get('target_1r', 0):,.2f} (Move SL to BE)\n"
        f"🏆 <b>Target 2 (+2R):</b> ₹{cand.get('target_2r', 0):,.2f} (Partial Profit)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Pillars Qualified:</b>\n{reasons_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 {time_str}\n"
        f"<i>Pre-Breakout Alert: Setups coiling before expansion</i>"
    )

    try:
        import requests
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Failed to dispatch coiling Telegram alert for {sym}: {e}")
        return False


def send_ignition_telegram_alert(cand: Dict[str, Any], ignition: Dict[str, Any]) -> bool:
    """Dispatches a real-time Intraday Ignition alert to Telegram."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return False

    sym = cand["symbol"]
    ltp = ignition["ltp"]
    state = ignition["state"]
    trigger = ignition["gtt_trigger_price"]
    stoploss = ignition["stoploss"]
    t1r = ignition.get("target_1r", 0)
    t2r = ignition.get("target_2r", 0)
    time_str = format_dual_timezone_stamp(get_now_ist())

    msg = (
        f"🚨 <b>INTRADAY BREAKOUT IGNITION: {sym}</b> 🚨\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 <b>Live State:</b> {state}\n"
        f"📈 <b>Live LTP:</b> ₹{ltp:,.2f} (Shelf Ceiling: ₹{cand['shelf_high']:,.2f})\n"
        f"🚀 <b>GTT Trigger (+1%):</b> ₹{trigger:,.2f}\n"
        f"🛑 <b>Stop-Loss:</b> ₹{stoploss:,.2f} (Risk: {cand.get('risk_pct')} %)\n"
        f"🎯 <b>Target 1 (+1R):</b> ₹{t1r:,.2f} (Move SL to Breakeven)\n"
        f"🏆 <b>Target 2 (+2R):</b> ₹{t2r:,.2f} (Lock Partial Gains)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 {time_str}\n"
        f"<i>Intraday Ignition Sentinel via Zerodha Live Feeds</i>"
    )
    try:
        import requests
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Failed to dispatch ignition alert for {sym}: {e}")
        return False


def check_intraday_coiling_ignitions(kite=None, send_telegram: bool = True) -> Dict[str, Any]:
    """
    Checks all tracked coiling candidates for live intraday breakouts (testing shelf ceiling).
    Dispatches immediate alert if stock trades at or above shelf ceiling.
    """
    dm = DataManager()
    if dm.db is None:
        return {"status": "error", "message": "MongoDB not connected"}

    col = dm.db["weekly_coiling_candidates"]
    candidates = list(col.find())
    if not candidates:
        return {"status": "success", "message": "No candidates to check", "ignitions": []}

    kite = kite or get_kite_client()
    if not kite:
        return {"status": "error", "message": "Zerodha Kite not connected"}

    tokens = [int(c["token"]) for c in candidates if c.get("token")]
    if not tokens:
        return {"status": "success", "ignitions": []}

    try:
        quotes = kite.quote(tokens)
    except Exception as e:
        logger.error(f"[IGNITION SENTINEL] Kite quote failed: {e}")
        return {"status": "error", "message": str(e)}

    ignitions = []
    for cand in candidates:
        token_str = str(cand.get("token"))
        q = quotes.get(token_str)
        if not q:
            continue

        ltp = float(q.get("last_price", 0.0))
        volume = int(q.get("volume", 0))
        shelf_high = float(cand.get("shelf_high", 0.0))
        trigger = float(cand.get("gtt_trigger_price", 0.0))

        # Check if testing within 0.5% of shelf high or already breaking out
        is_testing = ltp >= (shelf_high * 0.995)
        is_breakout = ltp >= trigger

        if is_testing or is_breakout:
            state = "BREAKOUT_TRIGGERED" if is_breakout else "TESTING_CEILING"
            ignition_data = {
                "symbol": cand["symbol"],
                "ltp": ltp,
                "shelf_high": shelf_high,
                "gtt_trigger_price": trigger,
                "state": state,
                "today_volume": volume,
                "target_1r": cand.get("target_1r"),
                "target_2r": cand.get("target_2r"),
                "stoploss": cand.get("gtt_stoploss_price"),
                "timestamp_ist": get_now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
            }
            ignitions.append(ignition_data)
            col.update_one(
                {"_id": cand["_id"]},
                {"$set": {"ignition_state": state, "last_ignition_check": ignition_data["timestamp_ist"], "live_ltp": ltp}}
            )

            if send_telegram:
                send_ignition_telegram_alert(cand, ignition_data)

    return {
        "status": "success",
        "checked_count": len(candidates),
        "ignition_count": len(ignitions),
        "ignitions": ignitions,
        "timestamp_ist": get_now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
    }


if __name__ == "__main__":
    res = scan_and_rank_weekly_coiling_candidates(send_telegram=False)
    print("\n=======================================================")
    print(f" WEEKLY COILING SCAN RESULTS ({res.get('count', 0)} Candidates)")
    print("=======================================================")
    for c in res.get("candidates", [])[:10]:
        print(f"#{c['coiling_score']} {c['symbol']} | Status: {c['status']} | LTP: ₹{c['ltp']} | Box: ₹{c['shelf_low']} - ₹{c['shelf_high']} ({c['shelf_spread_pct']}%) | GTT Trigger: ₹{c['gtt_trigger_price']}")
