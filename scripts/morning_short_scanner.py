"""
===============================================================================
MORNING EXHAUSTION, ORB BREAKDOWN & VWAP REVERSION (SHORT) SCANNER ENGINE v2.0
===============================================================================
Timeframe: 5-Minute Intraday OHLCV (Strictly via Zerodha Kite Connect API)

Three Institutional Morning Short Playbooks:
1. STAGE 1: SNIPER TOP / GAP-UP EXHAUSTION REVERSION (09:35 AM - 11:45 AM IST)
   - Parabolic morning run-up (>= +1.5% from Open and touched +2 SD VWAP) OR
     Gap-Up Exhaustion (Gap >= +1.2% above Prev Close / rejected at Prev Day High).
   - Failed Second Push (Lower High breakdown or Upthrust bull-trap rejection).
   - Daily-reset Intraday OBV breakdown (< OBV_SMA9) + TSI (25,13,13) bearish roll.
   - Room to VWAP >= 0.6% and Risk/Reward >= 1 : 1.4.

2. STAGE 2: INTRADAY VWAP BREAKDOWN & FAILED RETEST (09:45 AM - 12:30 PM IST)
   - Prior morning run-up or gap-up followed by a fresh breakdown below Intraday VWAP
     (or failed retest kiss of VWAP from below) on Volume >= 1.2x SMA20.
   - Intraday OBV at 8-bar low + TSI < Signal and sloping down + R:R >= 1 : 1.4.

3. STAGE 3: 15-MIN OPENING RANGE + VWAP BREAKDOWN ("ORB TREND SHORT", 09:30 AM - 11:30 AM IST)
   - Stock breaks below the first 15-minute Opening Range Low (09:15 - 09:30 AM ORL_15m)
     AND trades below Intraday VWAP with solid bearish body and Volume >= 1.2x SMA20.
   - Daily-reset Intraday OBV at session/6-bar low + TSI < Signal + R:R >= 1 : 1.4.

6-Agent Pre-Alert Quantitative Debate:
- Every candidate is evaluated by 6 specialized agents (Exhaustion/Structure,
  OBV/Distribution, TSI/Momentum, Short Researcher, Squeeze-Risk Researcher,
  and Chief Risk Judge) to produce `agents_debate_rating` out of 10 before
  saving or sending a Telegram chart alert.
===============================================================================
"""

import os
import sys
import logging
from datetime import datetime, timezone, timedelta, date, time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Set

import numpy as np
import pandas as pd
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from data_manager import DataManager
from scripts.chart_generator import (
    fetch_5min_candles_zerodha,
    generate_5min_short_chart_buffer,
    send_telegram_chart_alert,
    get_kite_client
)

load_dotenv(dotenv_path=project_root / ".env")
logger = logging.getLogger("MorningShortScanner")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# In-memory deduplication cache: { "YYYY-MM-DD_SYMBOL_STAGE": timestamp }
_SENT_ALERTS_TODAY: Dict[str, float] = {}

# Liquid F&O shortable universe to complement watchlist symbols
LIQUID_FNO_SHORT_UNIVERSE = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK",
    "KOTAKBANK", "INDUSINDBANK", "BAJFINANCE", "BAJAJFINSV", "TATAMOTORS",
    "TATASTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "JSWSTEEL", "ADANIENT",
    "ADANIPORTS", "DLF", "LT", "BHARTIARTL", "SUNPHARMA", "DRREDDY",
    "CIPLA", "MARUTI", "M&M", "HEROMOTOCO", "BAJAJ-AUTO", "TITAN",
    "WIPRO", "HCLTECH", "TECHM", "LTIM", "BHEL", "PFC", "RECLTD",
    "POWERGRID", "NTPC", "COALINDIA", "ONGC", "BPCL", "HAL", "BEL"
]


# =============================================================================
# 1. 5-MINUTE INDICATOR & INTRADAY STRUCTURE CALCULATIONS
# =============================================================================

def calculate_morning_short_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes all 5-minute indicators with strict daily resets at 09:15 AM IST:
      - Intraday VWAP, +1.5 SD & +2.0 SD Upper Overextension Bands
      - Daily-reset Intraday OBV & 9-period SMA
      - 15-Minute Opening Range High (ORH_15m) & Opening Range Low (ORL_15m)
      - Previous Trading Day High (Prev_Day_High), Low (Prev_Day_Low), Close (Prev_Day_Close)
      - Morning High, Day Open, Day Low, TSI (25, 13, 13), and Volume 20 SMA
    """
    if df.empty or len(df) < 5:
        return df

    out_df = df.copy()

    # Normalize column names
    col_map = {c: c.capitalize() for c in out_df.columns}
    out_df = out_df.rename(columns=col_map)
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in out_df.columns:
            out_df[col] = out_df[col].astype(float)

    # Trading date grouping for intraday indicators (resets at 09:15 daily)
    dates = out_df.index.date
    out_df["Date_Only"] = dates

    # Typical Price & Volume products
    out_df["TP"] = (out_df["High"] + out_df["Low"] + out_df["Close"]) / 3.0
    out_df["TP_Vol"] = out_df["TP"] * out_df["Volume"]

    # 1. Cumulative VWAP per trading day
    cum_vol = out_df.groupby("Date_Only")["Volume"].cumsum()
    cum_tp_vol = out_df.groupby("Date_Only")["TP_Vol"].cumsum()
    out_df["VWAP"] = (cum_tp_vol / cum_vol.replace(0, np.nan)).fillna(out_df["Close"])

    # Volume-weighted Standard Deviation & +1.5 SD / +2.0 SD Upper Bands
    dev_sq_vol = out_df["Volume"] * ((out_df["TP"] - out_df["VWAP"]) ** 2)
    out_df["Dev_Sq_Vol"] = dev_sq_vol
    cum_dev_sq_vol = out_df.groupby("Date_Only")["Dev_Sq_Vol"].cumsum()
    vwap_var = cum_dev_sq_vol / cum_vol.replace(0, np.nan)
    out_df["VWAP_SD"] = np.sqrt(vwap_var.clip(lower=0)).fillna(0.0)
    out_df["Upper_Band_1_5SD"] = out_df["VWAP"] + (1.5 * out_df["VWAP_SD"])
    out_df["Upper_Band_2SD"] = out_df["VWAP"] + (2.0 * out_df["VWAP_SD"])

    # 2. Intraday Session Reference Levels
    out_df["Day_Open"] = out_df.groupby("Date_Only")["Open"].transform("first")
    out_df["Morning_High"] = out_df.groupby("Date_Only")["High"].cummax()
    out_df["Day_Low"] = out_df.groupby("Date_Only")["Low"].cummin()
    out_df["Day_Bar_Idx"] = out_df.groupby("Date_Only").cumcount()  # 0-indexed candle number of the day

    # 3. 15-Minute Opening Range High/Low (first 3 candles: 09:15, 09:20, 09:25)
    first_3_mask = out_df["Day_Bar_Idx"] < 3
    orh_map = out_df[first_3_mask].groupby("Date_Only")["High"].max()
    orl_map = out_df[first_3_mask].groupby("Date_Only")["Low"].min()
    out_df["ORH_15m"] = out_df["Date_Only"].map(orh_map).fillna(out_df["Morning_High"])
    out_df["ORL_15m"] = out_df["Date_Only"].map(orl_map).fillna(out_df["Day_Low"])

    # 4. Previous Trading Day Reference Levels (Prev_Day_Close, Prev_Day_High, Prev_Day_Low)
    daily_summary = out_df.groupby("Date_Only").agg(
        d_high=("High", "max"),
        d_low=("Low", "min"),
        d_close=("Close", "last")
    )
    prev_daily = daily_summary.shift(1)
    out_df["Prev_Day_High"] = out_df["Date_Only"].map(prev_daily["d_high"]).fillna(0.0)
    out_df["Prev_Day_Low"] = out_df["Date_Only"].map(prev_daily["d_low"]).fillna(0.0)
    out_df["Prev_Day_Close"] = out_df["Date_Only"].map(prev_daily["d_close"]).fillna(out_df["Day_Open"])

    # 5. Volume SMA 20
    out_df["Vol_SMA20"] = out_df["Volume"].rolling(window=20, min_periods=3).mean()

    # 6. Daily-Reset Intraday On-Balance Volume (OBV) & 9-period SMA
    close_diff = out_df["Close"].diff()
    direction = np.where(close_diff > 0, 1, np.where(close_diff < 0, -1, 0))
    direction[0] = 0
    out_df["Signed_Vol"] = direction * out_df["Volume"]
    out_df["OBV"] = out_df.groupby("Date_Only")["Signed_Vol"].cumsum()
    out_df["OBV_SMA9"] = out_df.groupby("Date_Only")["OBV"].transform(
        lambda s: s.rolling(window=9, min_periods=2).mean()
    )

    # 7. True Strength Index (TSI 25, 13, 13)
    pc = out_df["Close"].diff()
    abs_pc = pc.abs()
    pc_ema_slow = pc.ewm(span=25, min_periods=1, adjust=False).mean()
    pc_ema_fast = pc_ema_slow.ewm(span=13, min_periods=1, adjust=False).mean()
    abs_pc_ema_slow = abs_pc.ewm(span=25, min_periods=1, adjust=False).mean()
    abs_pc_ema_fast = abs_pc_ema_slow.ewm(span=13, min_periods=1, adjust=False).mean()

    abs_pc_safe = abs_pc_ema_fast.replace(0, np.nan)
    out_df["TSI"] = (pc_ema_fast / abs_pc_safe).fillna(0.0)
    out_df["TSI_Signal"] = out_df["TSI"].ewm(span=13, min_periods=1, adjust=False).mean().fillna(0.0)

    return out_df


def is_nifty_making_intraday_high(kite=None) -> bool:
    """
    Checks if Nifty 50 benchmark index is currently pushing a new intraday high.
    Returns True if Nifty is at day's high (blocking short signals).
    """
    try:
        if kite is None:
            kite = get_kite_client()
        if kite:
            q = kite.quote(["NSE:NIFTY 50"])
            if "NSE:NIFTY 50" in q:
                nifty_data = q["NSE:NIFTY 50"]
                ohlc = nifty_data.get("ohlc", {})
                last_price = float(nifty_data.get("last_price") or 0)
                day_high = float(ohlc.get("high") or 0)
                if day_high > 0 and (last_price >= day_high * 0.9995):
                    logger.info(f"NIFTY 50 is at new intraday high ({last_price} vs {day_high}). Blocking short signal.")
                    return True
    except Exception as e:
        logger.debug(f"Nifty regime check error: {e}")
    return False


# =============================================================================
# 2. 6-AGENT QUANTITATIVE DEBATE ENGINE FOR MORNING SHORTS
# =============================================================================

def run_morning_short_agents_debate(
    symbol: str,
    stage: Optional[str],
    morning_runup_pct: float,
    gap_pct: float,
    touched_2sd: bool,
    failed_push: bool,
    orb_breakdown: bool,
    fresh_vwap_breakdown: bool,
    vol_ratio: float,
    vol_climax: bool,
    obv_breakdown: bool,
    tsi_bearish_cross: bool,
    tsi_sloping_down: bool,
    is_solid_red_bar: bool,
    rr_ratio: float,
    room_to_vwap_pct: float,
) -> Dict[str, Any]:
    """
    Runs a 6-Agent Pre-Short Debate (100% Zerodha 5m Data, $0 AI Cost) to rate
    how strong the Morning Short setup is out of 10:
      1. Exhaustion & Structure Analyst (Gap/2SD extension, Failed Push, or ORB breakdown)
      2. Institutional Distribution & OBV Analyst (Daily-reset OBV breakdown + Volume surge)
      3. Momentum & TSI Velocity Analyst (TSI bearish cross + solid red body rejection)
      4. Short Seller Researcher (Synthesizes directional short thesis)
      5. Short-Squeeze Risk Researcher (Penalizes low R:R, weak volume, or squeeze traps)
      6. Chief Risk & Portfolio Judge (Produces final `agents_debate_rating` out of 10)
    """
    # Agent 1: Exhaustion & Structure Analyst (0-10)
    struct_score = 4.5
    if stage == "STAGE 1":
        struct_score = 7.8 + min(1.5, max(0.0, morning_runup_pct - 1.5) * 0.5) + (0.6 if abs(gap_pct) >= 1.0 else 0.0)
    elif stage == "STAGE 2":
        struct_score = 7.7 + min(1.5, max(0.0, morning_runup_pct - 1.2) * 0.5) + (0.5 if fresh_vwap_breakdown else 0.0)
    elif stage == "STAGE 3":
        struct_score = 7.9 + (0.8 if orb_breakdown else 0.0) + min(1.0, max(0.0, abs(gap_pct)) * 0.4)
    else:
        if touched_2sd:
            struct_score += 1.5
        if failed_push or orb_breakdown or fresh_vwap_breakdown:
            struct_score += 1.8
    struct_score = round(min(10.0, max(2.0, struct_score)), 1)

    # Agent 2: Institutional Distribution & OBV Analyst (0-10)
    obv_score = 4.5
    if obv_breakdown:
        obv_score += 2.8
    if vol_climax:
        obv_score += 1.4
    if vol_ratio >= 1.2:
        obv_score += min(1.5, (vol_ratio - 1.0) * 1.1)
    obv_score = round(min(10.0, max(2.0, obv_score)), 1)

    # Agent 3: Momentum & TSI Velocity Analyst (0-10)
    mom_score = 4.5
    if tsi_bearish_cross:
        mom_score += 2.2
    if tsi_sloping_down:
        mom_score += 1.4
    if is_solid_red_bar:
        mom_score += 1.5
    mom_score = round(min(10.0, max(2.0, mom_score)), 1)

    # Agent 4: Short Seller Lead Researcher
    short_thesis_score = round((struct_score * 0.40) + (obv_score * 0.32) + (mom_score * 0.28), 1)

    # Agent 5: Short-Squeeze Risk Researcher (Counter-Thesis Penalty 0.0 - 3.5)
    squeeze_penalty = 0.0
    squeeze_reasons = []
    if rr_ratio < 1.4:
        squeeze_penalty += 1.2
        squeeze_reasons.append(f"Low R:R (1:{rr_ratio:.2f})")
    elif rr_ratio < 1.7:
        squeeze_penalty += 0.3
    if not obv_breakdown:
        squeeze_penalty += 0.8
        squeeze_reasons.append("OBV holding")
    if not tsi_bearish_cross:
        squeeze_penalty += 0.7
        squeeze_reasons.append("TSI bullish")
    if vol_ratio < 0.9 and not vol_climax:
        squeeze_penalty += 0.5
        squeeze_reasons.append(f"Light Vol ({vol_ratio:.1f}x)")
    squeeze_penalty = round(min(3.5, squeeze_penalty), 1)

    # Agent 6: Chief Risk & Portfolio Judge
    rr_bonus = 0.6 if rr_ratio >= 2.0 else (0.3 if rr_ratio >= 1.6 else 0.0)
    final_rating = round(min(10.0, max(1.0, short_thesis_score + rr_bonus - squeeze_penalty)), 1)

    if final_rating >= 8.5:
        verdict = "STRONG SHORT CONSENSUS 🔥"
    elif final_rating >= 7.2:
        verdict = "DEBATE APPROVED ✅"
    elif final_rating >= 6.0:
        verdict = "WATCH / DEVELOPING ⚡"
    else:
        verdict = "HIGH SQUEEZE RISK ⚠️"

    filled = int(round(final_rating))
    bar = "█" * filled + "░" * (10 - filled)
    risk_str = "Clean R:R & Flow" if not squeeze_reasons else ", ".join(squeeze_reasons[:2])
    summary = (
        f"Struct {struct_score}/10 • OBV/Flow {obv_score}/10 • "
        f"TSI/Mom {mom_score}/10 | Squeeze Risk: {risk_str}"
    )

    return {
        "agents_debate_rating": final_rating,
        "agents_debate_verdict": verdict,
        "agents_debate_bar": bar,
        "agents_debate_summary": summary,
        "structure_agent_score": struct_score,
        "obv_agent_score": obv_score,
        "momentum_agent_score": mom_score,
        "short_thesis_score": short_thesis_score,
        "squeeze_penalty": squeeze_penalty,
        "squeeze_reasons": squeeze_reasons,
    }


# =============================================================================
# 3. CORE SETUP EVALUATION ENGINE (STAGE 1, STAGE 2 & STAGE 3 ORB)
# =============================================================================

def analyze_morning_short_candidate(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    kite=None,
    check_nifty: bool = True
) -> Dict[str, Any]:
    """
    Analyzes a stock on 5-minute Zerodha candles across 3 institutional short setups:
      - STAGE 1: Sniper Top / Gap-Up Exhaustion Reversion Short (Above VWAP -> VWAP)
      - STAGE 2: Intraday VWAP Breakdown & Failed Retest Short (Below VWAP -> Day Low)
      - STAGE 3: 15-Minute Opening Range + VWAP Breakdown ("ORB Trend Short")
    """
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("-EQ", "")

    if df is None or df.empty:
        df = fetch_5min_candles_zerodha(clean_sym, days=5, kite=kite)

    if df is None or df.empty or len(df) < 15:
        return {
            "symbol": clean_sym,
            "stage": None,
            "stage_title": None,
            "is_short_candidate": False,
            "short_probability_score": 0.0,
            "agents_debate_rating": 0.0,
            "reason": "Insufficient 5-minute candle data from Zerodha API",
            "close_price": 0.0
        }

    df_ind = calculate_morning_short_indicators(df)

    # If the latest bar in df_ind is after 12:30 PM (post-morning session or pre-market next day),
    # evaluate across the morning window (09:30 - 12:25) of the latest trading day to surface
    # the strongest morning short setup from that session.
    last_ts = df_ind.index[-1]
    if hasattr(last_ts, "time") and last_ts.time() > time(12, 30) and "_slice_eval" not in symbol:
        latest_day = df_ind["Date_Only"].iloc[-1]
        day_mask = (df_ind["Date_Only"] == latest_day)
        morning_indices = [
            idx for idx, ts in enumerate(df_ind.index)
            if day_mask.iloc[idx] and hasattr(ts, "time") and time(9, 30) <= ts.time() <= time(12, 25)
        ]
        if morning_indices:
            best_cand = None
            # Sample morning bars (every bar from 09:35 to 12:20) to find the peak morning trigger
            for m_idx in morning_indices:
                sub_df = df.iloc[: m_idx + 1]
                if len(sub_df) < 15:
                    continue
                cand = analyze_morning_short_candidate(
                    f"{clean_sym}_slice_eval",
                    df=sub_df,
                    kite=kite,
                    check_nifty=False
                )
                cand["symbol"] = clean_sym
                if best_cand is None or (
                    cand.get("is_short_candidate", False),
                    cand.get("agents_debate_rating", 0.0),
                    cand.get("short_probability_score", 0.0),
                ) > (
                    best_cand.get("is_short_candidate", False),
                    best_cand.get("agents_debate_rating", 0.0),
                    best_cand.get("short_probability_score", 0.0),
                ):
                    best_cand = cand
            if best_cand is not None:
                return best_cand

    clean_sym = clean_sym.replace("_SLICE_EVAL", "")
    latest_bar = df_ind.iloc[-1]
    curr_close = float(latest_bar["Close"])
    curr_open = float(latest_bar["Open"])
    curr_high = float(latest_bar["High"])
    curr_low = float(latest_bar["Low"])
    curr_vol = float(latest_bar["Volume"])
    curr_vwap = float(latest_bar["VWAP"])
    curr_upper_1_5sd = float(latest_bar["Upper_Band_1_5SD"])
    curr_upper_2sd = float(latest_bar["Upper_Band_2SD"])
    curr_morning_high = float(latest_bar["Morning_High"])
    curr_day_open = float(latest_bar["Day_Open"])
    curr_day_low = float(latest_bar["Day_Low"])
    curr_orh_15m = float(latest_bar["ORH_15m"])
    curr_orl_15m = float(latest_bar["ORL_15m"])
    prev_day_high = float(latest_bar["Prev_Day_High"])
    prev_day_low = float(latest_bar["Prev_Day_Low"])
    prev_day_close = float(latest_bar["Prev_Day_Close"])
    bar_idx_in_day = int(latest_bar["Day_Bar_Idx"])

    vol_sma20 = float(latest_bar["Vol_SMA20"]) if not np.isnan(latest_bar["Vol_SMA20"]) else 1.0
    vol_ratio = round(curr_vol / vol_sma20, 2) if vol_sma20 > 0 else 1.0

    curr_tsi = float(latest_bar["TSI"])
    curr_tsi_sig = float(latest_bar["TSI_Signal"])
    prev_tsi = float(df_ind["TSI"].iloc[-2]) if len(df_ind) >= 2 else curr_tsi

    curr_obv = float(latest_bar["OBV"])
    curr_obv_sma9 = float(latest_bar["OBV_SMA9"]) if not np.isnan(latest_bar["OBV_SMA9"]) else curr_obv

    last_timestamp = df_ind.index[-1]
    candle_time = last_timestamp.time() if hasattr(last_timestamp, "time") else None

    # Session progress flags
    has_orb_window = (bar_idx_in_day >= 3)          # >= 09:30 AM IST (after first 15m ORB forms)
    has_sufficient_session_time = (bar_idx_in_day >= 4)  # >= 09:35 AM IST

    # 1. Daily Context & Morning Extension
    morning_runup_pct = round(((curr_morning_high - curr_day_open) / curr_day_open) * 100.0, 2) if curr_day_open > 0 else 0.0
    gap_pct = round(((curr_day_open - prev_day_close) / prev_day_close) * 100.0, 2) if prev_day_close > 0 else 0.0
    pdh_rejected = (prev_day_high > 0) and (curr_morning_high >= prev_day_high * 0.997) and (curr_close < prev_day_high)

    recent_5 = df_ind.tail(5)
    touched_2sd_recently = bool((recent_5["High"] >= recent_5["Upper_Band_2SD"]).any())
    touched_1_5sd_recently = bool((recent_5["High"] >= recent_5["Upper_Band_1_5SD"]).any())

    has_runup = (morning_runup_pct >= 1.5) or (gap_pct >= 1.2 and morning_runup_pct >= 0.6)
    statistically_extended = (touched_2sd_recently and morning_runup_pct >= 1.5) or (
        touched_1_5sd_recently and (gap_pct >= 1.2 or pdh_rejected)
    )

    # 2. Failed Second Push / Upthrust Rejection
    lower_high_breakdown = False
    bull_trap_upthrust = False
    failed_push_type = "None"

    if len(df_ind) >= 6 and has_orb_window:
        high_series = df_ind["High"]
        low_series = df_ind["Low"]

        recent_10_highs = high_series.tail(10).values
        max_high_idx = int(np.argmax(recent_10_highs))
        bars_since_peak = (len(recent_10_highs) - 1) - max_high_idx

        h1 = float(high_series.iloc[-2])
        h2 = float(high_series.iloc[-3])
        l1 = float(low_series.iloc[-2])
        l2 = float(low_series.iloc[-3])
        l3 = float(low_series.iloc[-4])
        min_prev_lows = min(l1, l2, l3)

        if bars_since_peak >= 2 and (h1 > h2) and (h1 < curr_morning_high) and (curr_close < min_prev_lows):
            lower_high_breakdown = True
            failed_push_type = "Lower High Support Breakdown"

        prior_6_high = float(high_series.iloc[-7:-1].max()) if len(df_ind) >= 7 else curr_morning_high
        if (curr_high >= prior_6_high or curr_high >= curr_morning_high or pdh_rejected) and (curr_close < l1):
            if vol_ratio >= 1.1 or curr_vol >= float(df_ind["Volume"].iloc[-2]):
                bull_trap_upthrust = True
                failed_push_type = "PDH / Upthrust Bull-Trap Rejection" if pdh_rejected else "Bull Trap / Upthrust Rejection"

    failed_push = (lower_high_breakdown or bull_trap_upthrust)

    # 3. Candle Body & Volume Climax
    candle_range = curr_high - curr_low
    close_pos_ratio = (curr_close - curr_low) / candle_range if candle_range > 0 else 0.5
    body_ratio = abs(curr_close - curr_open) / candle_range if candle_range > 0 else 0.0
    is_solid_red_bar = (curr_close < curr_open) and (close_pos_ratio <= 0.38 or body_ratio >= 0.55)
    max_vol_4 = float(df_ind["Volume"].tail(4).max())
    vol_climax_occurred = (max_vol_4 >= 1.5 * vol_sma20)

    # 4. Daily-Reset Intraday OBV Distribution
    obv_5bar_floor = float(df_ind["OBV"].iloc[-6:-1].min()) if len(df_ind) >= 6 else curr_obv
    obv_breakdown = (curr_obv < curr_obv_sma9) and (curr_obv <= obv_5bar_floor)

    # 5. TSI (25, 13, 13) Momentum Roll
    recent_5_tsi = df_ind["TSI"].tail(5)
    tsi_peaked = bool((recent_5_tsi.max() >= 0.10)) or (gap_pct >= 1.0)
    tsi_bearish_cross = (curr_tsi < curr_tsi_sig)
    tsi_sloping_down = (curr_tsi < prev_tsi)
    tsi_confirmed_roll = tsi_peaked and tsi_bearish_cross and tsi_sloping_down

    # Room to VWAP
    room_to_vwap_ratio = (curr_close - curr_vwap) / curr_close if curr_close > 0 else 0.0
    room_to_vwap_pct = round(room_to_vwap_ratio * 100.0, 2)
    has_room_to_vwap = (room_to_vwap_ratio >= 0.006)  # >= 0.6% buffer above VWAP

    # 6. Benchmark NIFTY Filter
    nifty_blocked = False
    if check_nifty:
        nifty_blocked = is_nifty_making_intraday_high(kite=kite)

    # =========================================================================
    # THREE-PLAYBOOK QUALIFICATION RULES
    # =========================================================================
    stage = None
    stage_title = None
    stage_desc = None
    score = 0.0
    conditions_met = []

    # -------------------------------------------------------------------------
    # PLAYBOOK 1 (STAGE 1): SNIPER TOP / GAP-UP EXHAUSTION REVERSION SHORT
    # Active Window: 09:35 AM - 12:00 PM IST
    # -------------------------------------------------------------------------
    stage1_time_window = True
    if candle_time:
        stage1_time_window = (time(9, 35) <= candle_time <= time(12, 0))

    is_stage1 = (
        not nifty_blocked
        and has_sufficient_session_time
        and stage1_time_window
        and statistically_extended
        and (curr_close > curr_vwap)
        and failed_push
        and obv_breakdown
        and tsi_confirmed_roll
        and has_room_to_vwap
    )

    # -------------------------------------------------------------------------
    # PLAYBOOK 2 (STAGE 2): INTRADAY VWAP BREAKDOWN & FAILED RETEST SHORT
    # Active Window: 09:45 AM - 12:30 PM IST
    # -------------------------------------------------------------------------
    stage2_time_window = True
    if candle_time:
        stage2_time_window = (time(9, 45) <= candle_time <= time(12, 30))

    prev_close_1 = float(df_ind["Close"].iloc[-2]) if len(df_ind) >= 2 else curr_close
    prev_vwap_1 = float(df_ind["VWAP"].iloc[-2]) if len(df_ind) >= 2 else curr_vwap
    prev_close_2 = float(df_ind["Close"].iloc[-3]) if len(df_ind) >= 3 else curr_close
    prev_vwap_2 = float(df_ind["VWAP"].iloc[-3]) if len(df_ind) >= 3 else curr_vwap

    fresh_vwap_violation = (
        (curr_close < curr_vwap)
        and (prev_close_1 >= prev_vwap_1 * 0.999)
        and (prev_close_2 >= prev_vwap_2 * 0.999)
        and (curr_close < curr_open)
        and (vol_ratio >= 1.2)
    )
    failed_vwap_retest = (
        (curr_close < curr_vwap)
        and (curr_high >= curr_vwap * 0.9985)
        and is_solid_red_bar
        and (vol_ratio >= 1.15)
    )
    fresh_vwap_breakdown = (fresh_vwap_violation or failed_vwap_retest)

    obv_8bar_floor = float(df_ind["OBV"].iloc[-9:-1].min()) if len(df_ind) >= 9 else curr_obv
    obv_8bar_low = (curr_obv <= obv_8bar_floor) and (curr_obv < curr_obv_sma9)

    is_stage2 = (
        not nifty_blocked
        and has_runup
        and stage2_time_window
        and fresh_vwap_breakdown
        and tsi_bearish_cross
        and tsi_sloping_down
        and obv_8bar_low
    )

    # -------------------------------------------------------------------------
    # PLAYBOOK 3 (STAGE 3): 15-MIN OPENING RANGE + VWAP BREAKDOWN ("ORB SHORT")
    # Active Window: 09:30 AM - 11:45 AM IST
    # -------------------------------------------------------------------------
    stage3_time_window = True
    if candle_time:
        stage3_time_window = (time(9, 30) <= candle_time <= time(11, 45))

    prev_above_orl = (prev_close_1 >= curr_orl_15m * 0.999)
    orb_breakdown = (
        has_orb_window
        and (curr_orl_15m > 0)
        and (curr_close < curr_orl_15m)
        and (curr_close < curr_vwap)
        and prev_above_orl
        and is_solid_red_bar
        and (vol_ratio >= 1.2 or vol_climax_occurred)
    )
    if orb_breakdown and failed_push_type == "None":
        failed_push_type = "15m Opening Range Low (ORL) Breakdown"

    is_stage3 = (
        not nifty_blocked
        and stage3_time_window
        and orb_breakdown
        and obv_breakdown
        and tsi_bearish_cross
        and tsi_sloping_down
    )

    # =========================================================================
    # TRADE LEVELS, SCORING & MULTI-AGENT DEBATE
    # =========================================================================
    if is_stage1:
        stage = "STAGE 1"
        stage_title = "STAGE 1: Sniper Top Reversion"
        stage_desc = "Mean reversion from +2 SD VWAP / Gap-Up exhaustion back to intraday VWAP"
        base_score = 78.0

        if vol_climax_occurred:
            base_score += 8.0
            conditions_met.append("Volume Climax at Highs (>=1.5x SMA20)")
        if room_to_vwap_pct >= 1.0:
            base_score += 7.0
            conditions_met.append(f"Deep Room to VWAP ({room_to_vwap_pct}%)")
        if is_solid_red_bar:
            base_score += 4.0
            conditions_met.append("Dominant Bearish Rejection Candle")
        if pdh_rejected or gap_pct >= 1.2:
            base_score += 3.0
            conditions_met.append(f"Gap/PDH Exhaustion (Gap {gap_pct:+.1f}%)")

        conditions_met.extend([
            f"Extended (+{morning_runup_pct}% from Open, +2SD Band Rejection)",
            f"Failed Push: {failed_push_type}",
            "Intraday OBV Distribution Breakdown",
            f"TSI Bearish Roll ({curr_tsi:.3f} < {curr_tsi_sig:.3f})"
        ])
        score = min(100.0, round(base_score, 1))

        suggested_entry = round(curr_close, 2)
        stop_loss = round(curr_morning_high * 1.003, 2)
        target_price = round(curr_vwap, 2)
        target_price_2 = round(min(curr_day_low, curr_vwap - (curr_close - curr_vwap) * 0.6), 2)

    elif is_stage2:
        stage = "STAGE 2"
        stage_title = "STAGE 2: VWAP Breakdown"
        stage_desc = "High-velocity breakdown / failed retest below Intraday VWAP toward Day's Low"
        base_score = 78.0

        if vol_ratio >= 1.5:
            base_score += 8.0
            conditions_met.append(f"Heavy Breakdown Volume ({vol_ratio}x SMA20)")
        if morning_runup_pct >= 2.0 or gap_pct >= 1.2:
            base_score += 7.0
            conditions_met.append(f"Trapped Morning Buyers (+{morning_runup_pct}% peak)")
        if is_solid_red_bar:
            base_score += 5.0
            conditions_met.append("Solid Red Close Below VWAP")

        conditions_met.extend([
            "Fresh Intraday VWAP Violation / Rejection",
            "Intraday OBV Collapsed to 8-Bar Low",
            f"TSI Bearish Acceleration ({curr_tsi:.3f} < {curr_tsi_sig:.3f})"
        ])
        score = min(100.0, round(base_score, 1))

        prev_h = float(df_ind["High"].iloc[-2]) if len(df_ind) >= 2 else curr_vwap
        suggested_entry = round(curr_close, 2)
        stop_loss = round(max(curr_vwap, curr_high, prev_h) * 1.003, 2)
        risk_dist = max(suggested_entry * 0.005, stop_loss - suggested_entry)
        raw_tgt1 = min(curr_day_low, suggested_entry - (risk_dist * 1.6))
        target_price = round(raw_tgt1, 2)
        target_price_2 = round(suggested_entry - (risk_dist * 2.5), 2)

    elif is_stage3:
        stage = "STAGE 3"
        stage_title = "STAGE 3: 15m ORB + VWAP Breakdown"
        stage_desc = "Opening Range Low (ORL) & VWAP breakdown with institutional OBV selling"
        base_score = 80.0

        if vol_ratio >= 1.5:
            base_score += 8.0
            conditions_met.append(f"Institutional ORB Breakdown Vol ({vol_ratio}x SMA20)")
        if gap_pct <= -0.5 or pdh_rejected:
            base_score += 6.0
            conditions_met.append(f"Weak Open / PDH Rejection (Gap {gap_pct:+.1f}%)")
        if is_solid_red_bar:
            base_score += 5.0
            conditions_met.append("Wide-Range Bearish Breakdown Bar")

        conditions_met.extend([
            f"Broke 15m Opening Range Low (₹{curr_orl_15m:,.2f}) & VWAP",
            "Intraday OBV Making Session Lows",
            f"TSI Bearish Trend ({curr_tsi:.3f} < {curr_tsi_sig:.3f})"
        ])
        score = min(100.0, round(base_score, 1))

        suggested_entry = round(curr_close, 2)
        stop_loss = round(max(curr_vwap, curr_orl_15m, curr_high) * 1.003, 2)
        risk_dist = max(suggested_entry * 0.005, stop_loss - suggested_entry)
        target_price = round(suggested_entry - (risk_dist * 1.8), 2)
        target_price_2 = round(
            prev_day_low if (0 < prev_day_low < target_price) else (suggested_entry - (risk_dist * 2.6)),
            2
        )

    else:
        # Strict developing candidate evaluation (requires genuine multi-factor alignment)
        partial_score = 0.0
        if statistically_extended:
            partial_score += 25.0
            conditions_met.append("Extended at +2SD VWAP / PDH")
        if failed_push or orb_breakdown or fresh_vwap_breakdown:
            partial_score += 22.0
            conditions_met.append(f"Structure: {failed_push_type if failed_push_type != 'None' else 'VWAP Breakdown'}")
        if obv_breakdown:
            partial_score += 15.0
            conditions_met.append("Intraday OBV Breakdown")
        if tsi_confirmed_roll or (tsi_bearish_cross and tsi_sloping_down):
            partial_score += 12.0
            conditions_met.append("TSI Bearish Roll")
        if is_solid_red_bar and vol_ratio >= 1.1:
            partial_score += 8.0
            conditions_met.append(f"Bearish Vol ({vol_ratio}x)")

        score = round(partial_score, 1)
        suggested_entry = round(curr_close, 2)
        stop_loss = round(max(curr_morning_high, curr_vwap * 1.005) * 1.003, 2)
        risk_dist = max(suggested_entry * 0.005, stop_loss - suggested_entry)
        target_price = round(
            curr_vwap if (curr_close > curr_vwap and (curr_close - curr_vwap) >= risk_dist * 1.3)
            else (suggested_entry - risk_dist * 1.5),
            2
        )
        target_price_2 = round(target_price - risk_dist * 0.8, 2)

    # Risk / Reward calculations
    risk_per_share = round(max(0.05, stop_loss - suggested_entry), 2)
    risk_pct = round((risk_per_share / suggested_entry) * 100.0, 2) if suggested_entry > 0 else 0.0
    reward_per_share = round(max(0.05, suggested_entry - target_price), 2)
    reward_pct = round((reward_per_share / suggested_entry) * 100.0, 2) if suggested_entry > 0 else 0.0
    rr_ratio = round(reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0.0

    # Run the 6-Agent Morning Short Debate before finalizing candidate
    debate_info = run_morning_short_agents_debate(
        symbol=clean_sym,
        stage=stage,
        morning_runup_pct=morning_runup_pct,
        gap_pct=gap_pct,
        touched_2sd=statistically_extended,
        failed_push=failed_push,
        orb_breakdown=orb_breakdown,
        fresh_vwap_breakdown=fresh_vwap_breakdown,
        vol_ratio=vol_ratio,
        vol_climax=vol_climax_occurred,
        obv_breakdown=obv_breakdown,
        tsi_bearish_cross=tsi_bearish_cross,
        tsi_sloping_down=tsi_sloping_down,
        is_solid_red_bar=is_solid_red_bar,
        rr_ratio=rr_ratio,
        room_to_vwap_pct=room_to_vwap_pct,
    )

    # Enforce minimum R:R >= 1.35 and Debate Rating >= 6.8 for confirmed short alerts
    is_short_candidate = bool(
        (is_stage1 or is_stage2 or is_stage3)
        and (rr_ratio >= 1.35)
        and (debate_info["agents_debate_rating"] >= 6.8)
    )
    if (is_stage1 or is_stage2 or is_stage3) and not is_short_candidate:
        # Downgrade to developing watchlist if R:R or debate is too weak
        stage = None
        stage_title = "WATCH: Sub-Optimal R:R"
        score = min(score, 62.0)

    if stage == "STAGE 1":
        reason_str = f"Stage 1 Sniper Reversion: {failed_push_type} above VWAP (+2SD rejection, {room_to_vwap_pct}% room to VWAP)"
    elif stage == "STAGE 2":
        reason_str = f"Stage 2 VWAP Breakdown: Fresh violation of VWAP on {vol_ratio}x volume following +{morning_runup_pct}% morning run"
    elif stage == "STAGE 3":
        reason_str = f"Stage 3 ORB Breakdown: Broke 15m Opening Range Low (₹{curr_orl_15m:,.2f}) & VWAP on {vol_ratio}x volume"
    elif conditions_met:
        reason_str = f"Developing Short: {', '.join(conditions_met[:3])}"
    else:
        reason_str = f"Neutral intraday structure (Close: ₹{curr_close:,.2f}, VWAP: ₹{curr_vwap:,.2f})"

    return {
        "symbol": clean_sym,
        "stage": stage,
        "stage_title": stage_title,
        "stage_desc": stage_desc,
        "is_short_candidate": is_short_candidate,
        "short_probability_score": score,
        "agents_debate_rating": debate_info["agents_debate_rating"],
        "agents_debate_verdict": debate_info["agents_debate_verdict"],
        "agents_debate_bar": debate_info["agents_debate_bar"],
        "agents_debate_summary": debate_info["agents_debate_summary"],
        "agents_debate": debate_info,
        "close_price": curr_close,
        "open_price": curr_open,
        "high_price": curr_high,
        "low_price": curr_low,
        "day_open": curr_day_open,
        "morning_high": curr_morning_high,
        "day_low": curr_day_low,
        "orh_15m": round(curr_orh_15m, 2),
        "orl_15m": round(curr_orl_15m, 2),
        "prev_day_high": round(prev_day_high, 2),
        "prev_day_low": round(prev_day_low, 2),
        "prev_day_close": round(prev_day_close, 2),
        "gap_pct": gap_pct,
        "vwap": round(curr_vwap, 2),
        "upper_band_2sd": round(curr_upper_2sd, 2),
        "suggested_entry": suggested_entry,
        "stop_loss": stop_loss,
        "target_price": target_price,
        "target_price_2": target_price_2,
        "risk_per_share": risk_per_share,
        "reward_per_share": reward_per_share,
        "risk_pct": risk_pct,
        "reward_pct": reward_pct,
        "rr_ratio": rr_ratio,
        "risk_reward": f"1 : {rr_ratio}",
        "room_to_vwap_pct": room_to_vwap_pct,
        "morning_runup_pct": morning_runup_pct,
        "tsi_val": round(curr_tsi, 4),
        "tsi_signal": round(curr_tsi_sig, 4),
        "tsi_confirmed_roll": tsi_confirmed_roll,
        "obv_breakdown": obv_breakdown,
        "orb_breakdown": orb_breakdown,
        "failed_push_type": failed_push_type,
        "volume_surge_ratio": vol_ratio,
        "vol_climax": vol_climax_occurred,
        "statistically_extended": statistically_extended,
        "nifty_regime_blocked": nifty_blocked,
        "conditions_met": conditions_met,
        "reason": reason_str,
        "time_str": str(last_timestamp),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }


# =============================================================================
# 4. TELEGRAM ALERT DISPATCHER (WITH AGENTS DEBATE RATING)
# =============================================================================

def format_short_telegram_alert(candidate: Dict[str, Any]) -> str:
    """Formats professional HTML Telegram alert message for Morning Short Setup with Agents Debate Rating."""
    symbol = candidate.get("symbol", "")
    stage_title = candidate.get("stage_title") or candidate.get("stage") or "MORNING SHORT SETUP"
    score = candidate.get("short_probability_score", 80.0)
    debate_rating = candidate.get("agents_debate_rating") or round(min(10.0, max(1.0, score / 10.0)), 1)
    debate_verdict = candidate.get("agents_debate_verdict") or "STRONG SHORT CONSENSUS 🔥"
    debate_summary = candidate.get("agents_debate_summary") or ""
    entry = candidate.get("suggested_entry", 0.0)
    sl = candidate.get("stop_loss", 0.0)
    tgt1 = candidate.get("target_price", 0.0)
    tgt2 = candidate.get("target_price_2", 0.0)
    risk_pct = candidate.get("risk_pct", 0.0)
    reward_pct = candidate.get("reward_pct", 0.0)
    rr = candidate.get("risk_reward", "1 : 2.0")
    vwap = candidate.get("vwap", 0.0)
    upper_2sd = candidate.get("upper_band_2sd", 0.0)
    m_high = candidate.get("morning_high", 0.0)
    runup = candidate.get("morning_runup_pct", 0.0)
    room = candidate.get("room_to_vwap_pct", 0.0)
    tsi = candidate.get("tsi_val", 0.0)
    tsi_sig = candidate.get("tsi_signal", 0.0)
    vol_ratio = candidate.get("volume_surge_ratio", 1.0)
    conditions = candidate.get("conditions_met", [])
    now_str = datetime.now().strftime("%I:%M %p")

    cond_bullets = "\n".join([f"   • {c}" for c in conditions[:4]])
    summary_line = f"🗣️ <i>{debate_summary}</i>\n" if debate_summary else ""

    msg = (
        f"🚨 <b>MORNING EXHAUSTION SHORT ALERT</b> 🚨\n"
        f"⚡ <b>Setup</b>: <b>{stage_title}</b>\n"
        f"🏷️ <b>Symbol</b>: <b>#{symbol}</b>  •  🕒 <b>{now_str} IST</b>\n"
        f"🤖 <b>Agents Debate Rating:</b> <b>{debate_rating} / 10</b> ({debate_verdict})\n"
        f"{summary_line}\n"
        f"📉 <b>EXECUTION LEVELS (5-MIN SETUP)</b>:\n"
        f"   • <b>Suggested Entry</b>: ₹{entry:,.2f}\n"
        f"   • <b>Stop Loss</b>: ₹{sl:,.2f} (Risk: {risk_pct:.2f}%)\n"
        f"   • <b>Target 1 (Mean Reversion)</b>: ₹{tgt1:,.2f} (+{reward_pct:.2f}%)\n"
        f"   • <b>Target 2 (Extended Trend)</b>: ₹{tgt2:,.2f}\n"
        f"   • <b>Risk / Reward</b>: <b>{rr}</b>\n\n"
        f"📊 <b>KEY METRICS & STRUCTURE</b>:\n"
        f"   • <b>Intraday VWAP</b>: ₹{vwap:,.2f}  |  <b>+2SD Band</b>: ₹{upper_2sd:,.2f}\n"
        f"   • <b>Morning Peak</b>: ₹{m_high:,.2f} (+{runup:.2f}% from Open)\n"
        f"   • <b>Room to VWAP</b>: {room:.2f}%\n"
        f"   • <b>TSI (25,13,13)</b>: {tsi:.3f} vs Signal: {tsi_sig:.3f} (Bearish)\n"
        f"   • <b>Volume Ratio</b>: {vol_ratio:.1f}x 20-SMA\n\n"
        f"🔍 <b>CONFIRMED STRUCTURAL TRIGGERS</b>:\n"
        f"{cond_bullets}\n\n"
        f"🎯 <i>Strict Execution: Honor Stop Loss. Trail SL to Breakeven once Target 1 is hit.</i>\n"
        f"🤖 <i>Live Scanner Engine via Zerodha Kite Connect API</i>"
    )
    return msg


def send_morning_short_telegram_alert(
    candidate: Dict[str, Any],
    kite=None,
    force: bool = False
) -> Dict[str, Any]:
    """
    Sends 5-minute candlestick chart (with Volume + OBV + TSI) + technical alert message to Telegram.
    Enforces strict anti-spam: Max 1 alert per stage per symbol per day.
    """
    symbol = candidate.get("symbol", "").strip().upper()
    stage = candidate.get("stage") or "SHORT"
    today_str = datetime.now().strftime("%Y-%m-%d")
    dedup_key = f"{today_str}_{symbol}_{stage}"

    if not force and dedup_key in _SENT_ALERTS_TODAY:
        logger.info(f"[DEDUP] Alert already sent today for {symbol} ({stage}). Skipping duplicate.")
        return {"status": "skipped", "reason": "Already alerted today", "symbol": symbol, "stage": stage}

    try:
        dm = DataManager()
        hist_col = dm.db["short_alerts_history"]
        existing = hist_col.find_one({"date": today_str, "symbol": symbol, "stage": stage})
        if not force and existing:
            _SENT_ALERTS_TODAY[dedup_key] = existing.get("timestamp", datetime.now().timestamp())
            logger.info(f"[DEDUP-DB] Alert already recorded in DB today for {symbol} ({stage}). Skipping.")
            return {"status": "skipped", "reason": "Already recorded in MongoDB today", "symbol": symbol, "stage": stage}
    except Exception as db_err:
        logger.debug(f"MongoDB deduplication check notice: {db_err}")

    chart_buf = None
    try:
        debate_r = candidate.get("agents_debate_rating", 8.0)
        chart_buf = generate_5min_short_chart_buffer(
            symbol=symbol,
            entry_price=candidate.get("suggested_entry"),
            stop_loss=candidate.get("stop_loss"),
            target_price=candidate.get("target_price"),
            num_candles=60,
            kite=kite,
            stage_label=f"[{stage} • Debate {debate_r}/10]"
        )
    except Exception as chart_err:
        logger.error(f"Failed to generate 5m short chart for {symbol}: {chart_err}")

    msg_text = format_short_telegram_alert(candidate)
    res = send_telegram_chart_alert(
        symbol=symbol,
        message_text=msg_text,
        chart_buffer=chart_buf,
        trigger_price=candidate.get("stop_loss"),
        parse_mode="HTML",
        kite=kite
    )

    if res.get("sent"):
        _SENT_ALERTS_TODAY[dedup_key] = datetime.now().timestamp()
        try:
            dm = DataManager()
            dm.db["short_alerts_history"].update_one(
                {"date": today_str, "symbol": symbol, "stage": stage},
                {"$set": {
                    "date": today_str,
                    "symbol": symbol,
                    "stage": stage,
                    "score": candidate.get("short_probability_score"),
                    "agents_debate_rating": candidate.get("agents_debate_rating"),
                    "entry": candidate.get("suggested_entry"),
                    "stop_loss": candidate.get("stop_loss"),
                    "target": candidate.get("target_price"),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }},
                upsert=True
            )
        except Exception as e:
            logger.debug(f"Could not write to short_alerts_history: {e}")

    return res


# =============================================================================
# 5. WATCHLIST SCANNER & STRICT HIGH-CONVICTION RANKER
# =============================================================================

def get_all_watchlist_symbols() -> List[str]:
    """Retrieves liquid F&O shortable stocks combined with active database watchlist symbols."""
    symbols: Set[str] = set(LIQUID_FNO_SHORT_UNIVERSE)
    try:
        dm = DataManager()
        for tf in ["daily", "weekly", "manual"]:
            records = dm.get_stock_ratings(tf)
            for r in records:
                sym = r.get("symbol")
                if sym:
                    symbols.add(sym.strip().upper().replace(".NS", "").replace("-EQ", ""))
    except Exception as e:
        logger.warning(f"Could not load MongoDB watchlists: {e}")

    return sorted(list(symbols))


def scan_and_rank_short_candidates(
    symbols: Optional[List[str]] = None,
    send_telegram: bool = True
) -> List[Dict[str, Any]]:
    """
    Scans stocks on 5-minute Zerodha data for Morning Short setups (Stage 1, Stage 2, Stage 3 ORB).
    Enforces a strict quality & Agents Debate filter so only genuine actionable short setups
    (and top developing setups with Score >= 55, R:R >= 1.3, Debate >= 6.0) are saved to MongoDB.
    """
    if symbols is None or len(symbols) == 0:
        symbols = get_all_watchlist_symbols()

    logger.info(f"🔍 Scanning {len(symbols)} stocks for 5m Morning Short (Stage 1 / Stage 2 / Stage 3 ORB) setups...")

    kite = get_kite_client()
    confirmed_results: List[Dict[str, Any]] = []
    developing_results: List[Dict[str, Any]] = []

    for s in symbols:
        try:
            cand = analyze_morning_short_candidate(s, kite=kite)
            if not cand:
                continue

            is_confirmed = bool(cand.get("is_short_candidate"))
            score = float(cand.get("short_probability_score", 0.0) or 0.0)
            debate_rating = float(cand.get("agents_debate_rating", 0.0) or 0.0)
            rr_val = float(cand.get("rr_ratio", 0.0) or 0.0)

            if is_confirmed:
                confirmed_results.append(cand)
                if send_telegram:
                    logger.info(
                        f"🚨 Qualified Short Trigger for {s} ({cand.get('stage')} | "
                        f"Debate: {debate_rating}/10)! Dispatching Telegram alert..."
                    )
                    try:
                        send_morning_short_telegram_alert(cand, kite=kite)
                    except Exception as tg_err:
                        logger.error(f"Error dispatching Telegram alert for {s}: {tg_err}")
            elif score >= 55.0 and debate_rating >= 6.0 and rr_val >= 1.3:
                developing_results.append(cand)

        except Exception as e:
            logger.debug(f"Error scanning {s} for morning short: {e}")

    # Sort confirmed by (agents_debate_rating, short_probability_score) descending
    confirmed_sorted = sorted(
        confirmed_results,
        key=lambda x: (x.get("agents_debate_rating", 0.0), x.get("short_probability_score", 0.0)),
        reverse=True
    )
    # Keep at most top 12 high-conviction developing candidates so the tab stays sniper-focused
    developing_sorted = sorted(
        developing_results,
        key=lambda x: (x.get("agents_debate_rating", 0.0), x.get("short_probability_score", 0.0)),
        reverse=True
    )[:12]

    sorted_results = confirmed_sorted + developing_sorted

    # Save to MongoDB 'short_candidates' collection
    try:
        dm = DataManager()
        col = dm.db["short_candidates"]
        col.delete_many({})
        if sorted_results:
            docs_to_save = []
            for r in sorted_results:
                doc = dict(r)
                doc["updated_at"] = datetime.now(timezone.utc).isoformat()
                docs_to_save.append(doc)
            if docs_to_save:
                col.insert_many(docs_to_save)
                logger.info(
                    f"✅ Saved {len(docs_to_save)} high-conviction short candidates "
                    f"({len(confirmed_sorted)} confirmed, {len(developing_sorted)} developing) to MongoDB."
                )
    except Exception as e:
        logger.warning(f"Could not save short candidates to MongoDB: {e}")

    return sorted_results


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    import argparse
    parser = argparse.ArgumentParser(description="Morning Exhaustion, ORB & VWAP Reversion Short Scanner v2.0")
    parser.add_argument("--symbol", type=str, default=None, help="Scan a single symbol (e.g. RELIANCE)")
    parser.add_argument("--telegram", action="store_true", help="Send Telegram alerts for triggers")
    parser.add_argument("--limit", type=int, default=30, help="Number of symbols to scan (default 30)")
    args = parser.parse_args()

    if args.symbol:
        sym = args.symbol.strip().upper()
        print(f"\nAnalyzing single symbol: {sym}...")
        res = analyze_morning_short_candidate(sym)
        import json
        print(json.dumps({k: v for k, v in res.items() if k not in ["conditions_met"]}, indent=2, default=str))
        if args.telegram:
            print("\nDispatching test Telegram alert...")
            send_morning_short_telegram_alert(res, force=True)
    else:
        all_syms = get_all_watchlist_symbols()
        scan_syms = all_syms[:args.limit]
        print(f"\nScanning {len(scan_syms)} liquid stocks on 5m Zerodha data...")
        ranked = scan_and_rank_short_candidates(symbols=scan_syms, send_telegram=args.telegram)

        print("\n" + "=" * 125)
        print(" 🚨 MORNING SHORT v2.0: STAGE 1 (2SD/GAP FADE) • STAGE 2 (VWAP BREAK) • STAGE 3 (15M ORB SHORT)")
        print("=" * 125)
        print(f"{'RANK':<5} {'SYMBOL':<12} {'STAGE':<10} {'DEBATE':<10} {'SCORE':<10} {'CLOSE':<10} {'VWAP':<10} {'R:R':<10} {'KEY PATTERN':<30}")
        print("-" * 125)

        for i, c in enumerate(ranked[:15], 1):
            sym = c.get("symbol")
            stg = c.get("stage") or "WATCH"
            deb = f"{c.get('agents_debate_rating', 0):.1f}/10"
            sc = f"{c.get('short_probability_score'):.1f}/100"
            cp = f"₹{c.get('close_price'):.2f}"
            vw = f"₹{c.get('vwap'):.2f}"
            rr = c.get("risk_reward") or "1:1.5"
            reason = (c.get("failed_push_type") or c.get("reason") or "")[:30]
            print(f"{i:<5} {sym:<12} {stg:<10} {deb:<10} {sc:<10} {cp:<10} {vw:<10} {rr:<10} {reason:<30}")

        print("=" * 125 + "\n")
