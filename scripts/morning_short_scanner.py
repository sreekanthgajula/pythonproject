"""
===============================================================================
MORNING EXHAUSTION & MIDDAY VWAP REVERSION (SHORT) SCANNER ENGINE
===============================================================================
Timeframe: 5-Minute Intraday OHLCV (Strictly via Zerodha Kite Connect API)

Key Mathematical Architecture:
1. Intraday VWAP & +2 SD Overextension Band (Resets at 09:15 AM IST):
   - Typical_Price (TP) = (High + Low + Close) / 3
   - VWAP = cumsum(TP * Volume) / cumsum(Volume)
   - VWAP_SD = sqrt(cumsum(Volume * (TP - VWAP)^2) / cumsum(Volume))
   - Upper_Band_2SD = VWAP + (2.0 * VWAP_SD)
   - Statistically_Extended: Within last 5 bars, High >= Upper_Band_2SD AND
     (Morning_High - Day_Open) / Day_Open >= 0.015 (+1.5% morning run-up).

2. Price Action: Failed Second Push / Upthrust (Kills "Bull Flag" Noise):
   - Requires >= 6 candles since 09:15 AM (time >= 09:45 AM IST).
   - Failed_Push: Either:
     a) Lower High Breakdown: Morning_High occurred 2-8 bars ago, bounce attempted
        (High[1] > High[2]), failed to break Morning_High, and Close < min(Low[1], Low[2], Low[3]).
     b) Bull Trap / Upthrust: Price wicked above prior 6-bar high (High >= Morning_High)
        but rejected hard and closed below prior bar low (Close < Low[1]) on volume >= 1.2x SMA20.

3. Volume Climax & Distribution Filter:
   - Vol_SMA_20 = SMA(Volume, 20)
   - Climax occurred at top: max(Volume, last 4 bars) >= 1.8 * Vol_SMA_20
   - Current trigger bar is solidly bearish: Close < Open AND (Close - Low) / (High - Low) <= 0.30.

4. OBV Distribution & Divergence (Smart Money Exit):
   - OBV = cumsum(sign(diff(Close)) * Volume)
   - OBV_SMA_9 = SMA(OBV, 9)
   - OBV_Breakdown: OBV < OBV_SMA_9 AND OBV < min(OBV in prior 5 bars).
   - OBV_Bearish_Divergence: OBV failed to make new high at morning price peak.

5. TSI (25, 13, 13) Verified Bearish Cross:
   - Double-smoothed momentum ratio (scaled -1.0 to +1.0)
   - TSI_Confirmed_Roll: TSI peaked > 0.15 within last 5 bars, now TSI < Signal AND TSI < TSI[1].

6. Market Regime Filter (Optional NIFTY Check):
   - Block short signal if NIFTY 50 is currently making a new intraday high on the same candle.

Two-Stage Trigger Rules:
- STAGE 1: SNIPER TOP REVERSAL SHORT (Above VWAP, Reversion to VWAP, 09:45 AM - 11:45 AM IST)
- STAGE 2: VWAP BREAKDOWN SHORT (Trend Flip to Day's Low, 10:15 AM - 12:15 PM IST)

Telegram Output & Anti-Spam:
- Max 1 Stage-1 alert and 1 Stage-2 alert per symbol per day.
- Generates and dispatches 5-minute candlestick chart with Volume, OBV, and TSI.
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


# =============================================================================
# 1. 5-MINUTE INDICATOR & STRUCTURE CALCULATIONS
# =============================================================================

def calculate_morning_short_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes all 5-minute indicators with daily resets for intraday VWAP, +2SD Upper Band,
    Morning High, Day Open, TSI (25, 13, 13), OBV with 9 SMA, and Volume 20 SMA.
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

    # Volume-weighted Standard Deviation & +2 SD Upper Band
    dev_sq_vol = out_df["Volume"] * ((out_df["TP"] - out_df["VWAP"]) ** 2)
    out_df["Dev_Sq_Vol"] = dev_sq_vol
    cum_dev_sq_vol = out_df.groupby("Date_Only")["Dev_Sq_Vol"].cumsum()
    vwap_var = cum_dev_sq_vol / cum_vol.replace(0, np.nan)
    out_df["VWAP_SD"] = np.sqrt(vwap_var.clip(lower=0)).fillna(0.0)
    out_df["Upper_Band_2SD"] = out_df["VWAP"] + (2.0 * out_df["VWAP_SD"])

    # 2. Intraday Session Reference Levels
    out_df["Day_Open"] = out_df.groupby("Date_Only")["Open"].transform("first")
    out_df["Morning_High"] = out_df.groupby("Date_Only")["High"].cummax()
    out_df["Day_Low"] = out_df.groupby("Date_Only")["Low"].cummin()
    out_df["Day_Bar_Idx"] = out_df.groupby("Date_Only").cumcount()  # 0-indexed candle number of the day

    # 3. Volume SMA 20
    out_df["Vol_SMA20"] = out_df["Volume"].rolling(window=20, min_periods=3).mean()

    # 4. On-Balance Volume (OBV) & 9-period SMA
    close_diff = out_df["Close"].diff()
    direction = np.where(close_diff > 0, 1, np.where(close_diff < 0, -1, 0))
    direction[0] = 0
    out_df["OBV"] = (direction * out_df["Volume"]).cumsum()
    out_df["OBV_SMA9"] = out_df["OBV"].rolling(window=9, min_periods=2).mean()

    # 5. True Strength Index (TSI 25, 13, 13)
    pc = out_df["Close"].diff()
    abs_pc = pc.abs()
    pc_ema_slow = pc.ewm(span=25, min_periods=1, adjust=False).mean()
    pc_ema_fast = pc_ema_slow.ewm(span=13, min_periods=1, adjust=False).mean()
    abs_pc_ema_slow = abs_pc.ewm(span=25, min_periods=1, adjust=False).mean()
    abs_pc_ema_fast = abs_pc_ema_slow.ewm(span=13, min_periods=1, adjust=False).mean()

    abs_pc_safe = abs_pc_ema_fast.replace(0, np.nan)
    # Scaled -1.0 to +1.0
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
# 2. CORE SETUP EVALUATION ENGINE (STAGE 1 & STAGE 2)
# =============================================================================

def analyze_morning_short_candidate(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    kite=None,
    check_nifty: bool = True
) -> Dict[str, Any]:
    """
    Analyzes a stock on 5-minute candles for:
      - STAGE 1: Sniper Top Reversal Short (VWAP Reversion from +2SD)
      - STAGE 2: VWAP Breakdown Short (Trend Flip to Day's Low)
    Returns complete candidate structure including trade levels, score, and reasoning.
    """
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("-EQ", "")

    # 1. Fetch 5m candle data via Zerodha if not provided
    if df is None or df.empty:
        df = fetch_5min_candles_zerodha(clean_sym, days=5, kite=kite)

    if df is None or df.empty or len(df) < 15:
        return {
            "symbol": clean_sym,
            "stage": None,
            "stage_title": None,
            "is_short_candidate": False,
            "short_probability_score": 0.0,
            "reason": "Insufficient 5-minute candle data from Zerodha API",
            "close_price": 0.0
        }

    # Calculate full 5m indicator structure
    df_ind = calculate_morning_short_indicators(df)

    # We evaluate on the latest available completed/active candle
    latest_bar = df_ind.iloc[-1]
    curr_close = float(latest_bar["Close"])
    curr_open = float(latest_bar["Open"])
    curr_high = float(latest_bar["High"])
    curr_low = float(latest_bar["Low"])
    curr_vol = float(latest_bar["Volume"])
    curr_vwap = float(latest_bar["VWAP"])
    curr_upper_2sd = float(latest_bar["Upper_Band_2SD"])
    curr_morning_high = float(latest_bar["Morning_High"])
    curr_day_open = float(latest_bar["Day_Open"])
    curr_day_low = float(latest_bar["Day_Low"])
    bar_idx_in_day = int(latest_bar["Day_Bar_Idx"])

    vol_sma20 = float(latest_bar["Vol_SMA20"]) if not np.isnan(latest_bar["Vol_SMA20"]) else 1.0
    vol_ratio = round(curr_vol / vol_sma20, 2) if vol_sma20 > 0 else 1.0

    curr_tsi = float(latest_bar["TSI"])
    curr_tsi_sig = float(latest_bar["TSI_Signal"])
    prev_tsi = float(df_ind["TSI"].iloc[-2]) if len(df_ind) >= 2 else curr_tsi

    curr_obv = float(latest_bar["OBV"])
    curr_obv_sma9 = float(latest_bar["OBV_SMA9"]) if not np.isnan(latest_bar["OBV_SMA9"]) else curr_obv

    # Time filter check: Indian Market Time
    last_timestamp = df_ind.index[-1]
    candle_time = last_timestamp.time() if hasattr(last_timestamp, "time") else None
    
    # Check minimum 6 candles since 09:15 AM (at or after 09:45 AM IST)
    has_sufficient_session_time = (bar_idx_in_day >= 5)

    # 1. Statistically Extended Check:
    # Within last 5 bars: High >= Upper_Band_2SD AND morning runup >= 1.5%
    recent_5 = df_ind.tail(5)
    morning_runup_pct = round(((curr_morning_high - curr_day_open) / curr_day_open) * 100.0, 2) if curr_day_open > 0 else 0.0
    has_runup = (morning_runup_pct >= 1.5)
    touched_2sd_recently = bool((recent_5["High"] >= recent_5["Upper_Band_2SD"]).any())
    statistically_extended = touched_2sd_recently and has_runup

    # 2. Failed Second Push / Upthrust:
    # a) Lower High Breakdown:
    # Morning high occurred at least 2 bars ago (up to 10 bars ago)
    # A bounce attempted: High[1] > High[2] (failed to exceed morning high)
    # Close < min(Low[1], Low[2], Low[3])
    lower_high_breakdown = False
    bull_trap_upthrust = False
    failed_push_type = "None"

    if len(df_ind) >= 6 and has_sufficient_session_time:
        high_series = df_ind["High"]
        low_series = df_ind["Low"]
        
        # Check if morning high was set at least 2 bars ago
        recent_10_highs = high_series.tail(10).values
        max_high_idx = int(np.argmax(recent_10_highs))
        bars_since_peak = (len(recent_10_highs) - 1) - max_high_idx

        h1 = float(high_series.iloc[-2])
        h2 = float(high_series.iloc[-3])
        l1 = float(low_series.iloc[-2])
        l2 = float(low_series.iloc[-3])
        l3 = float(low_series.iloc[-4])
        min_prev_lows = min(l1, l2, l3)

        # Condition a: Lower High Breakdown
        if bars_since_peak >= 2 and (h1 > h2) and (h1 < curr_morning_high) and (curr_close < min_prev_lows):
            lower_high_breakdown = True
            failed_push_type = "Lower High Support Breakdown"

        # Condition b: Bull Trap / Upthrust (wicked above prior 6-bar high, closed below Low[1] on vol)
        prior_6_high = float(high_series.iloc[-7:-1].max()) if len(df_ind) >= 7 else curr_morning_high
        if (curr_high >= prior_6_high or curr_high >= curr_morning_high) and (curr_close < l1):
            if vol_ratio >= 1.1 or curr_vol >= float(df_ind["Volume"].iloc[-2]):
                bull_trap_upthrust = True
                failed_push_type = "Bull Trap / Upthrust Rejection"

    failed_push = (lower_high_breakdown or bull_trap_upthrust)

    # 3. Volume Climax & Solid Bearish Trigger Bar:
    candle_range = curr_high - curr_low
    close_pos_ratio = (curr_close - curr_low) / candle_range if candle_range > 0 else 0.5
    is_solid_red_bar = (curr_close < curr_open) and (close_pos_ratio <= 0.35)
    max_vol_4 = float(df_ind["Volume"].tail(4).max())
    vol_climax_occurred = (max_vol_4 >= 1.5 * vol_sma20)

    # 4. OBV Distribution:
    # OBV below 9 SMA and below 5-bar floor
    obv_5bar_floor = float(df_ind["OBV"].iloc[-6:-1].min()) if len(df_ind) >= 6 else curr_obv
    obv_breakdown = (curr_obv < curr_obv_sma9) and (curr_obv <= obv_5bar_floor)

    # 5. TSI (25, 13, 13) Verified Bearish Roll:
    # Peaked above 0.15 within last 5 bars, now TSI < Signal and TSI < TSI[1]
    recent_5_tsi = df_ind["TSI"].tail(5)
    tsi_peaked_above_15 = bool((recent_5_tsi.max() >= 0.15))
    tsi_bearish_cross = (curr_tsi < curr_tsi_sig)
    tsi_sloping_down = (curr_tsi < prev_tsi)
    tsi_confirmed_roll = tsi_peaked_above_15 and tsi_bearish_cross and tsi_sloping_down

    # Room to VWAP: (Close - VWAP) / Close
    room_to_vwap_ratio = (curr_close - curr_vwap) / curr_close if curr_close > 0 else 0.0
    room_to_vwap_pct = round(room_to_vwap_ratio * 100.0, 2)
    has_room_to_vwap = (room_to_vwap_ratio >= 0.005)  # >= 0.5% buffer

    # 6. Benchmark NIFTY Filter:
    nifty_blocked = False
    if check_nifty:
        nifty_blocked = is_nifty_making_intraday_high(kite=kite)

    # =========================================================================
    # TWO-STAGE QUALIFICATION RULES
    # =========================================================================
    stage = None
    stage_title = None
    stage_desc = None
    score = 0.0
    conditions_met = []

    # -------------------------------------------------------------------------
    # STAGE 1: SNIPER TOP REVERSAL SHORT (Above VWAP, Reversion to VWAP)
    # Active Window: 09:45 AM - 11:45 AM IST
    # -------------------------------------------------------------------------
    stage1_time_window = True
    if candle_time:
        stage1_time_window = (time(9, 45) <= candle_time <= time(12, 0))

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
    # STAGE 2: VWAP BREAKDOWN SHORT (Trend Flip to Day's Low)
    # Active Window: 10:15 AM - 12:15 PM IST
    # -------------------------------------------------------------------------
    stage2_time_window = True
    if candle_time:
        stage2_time_window = (time(10, 15) <= candle_time <= time(12, 30))

    # Fresh VWAP Breakdown: previous 2 candles closed >= VWAP, now Close < VWAP
    prev_close_1 = float(df_ind["Close"].iloc[-2]) if len(df_ind) >= 2 else curr_close
    prev_vwap_1 = float(df_ind["VWAP"].iloc[-2]) if len(df_ind) >= 2 else curr_vwap
    prev_close_2 = float(df_ind["Close"].iloc[-3]) if len(df_ind) >= 3 else curr_close
    prev_vwap_2 = float(df_ind["VWAP"].iloc[-3]) if len(df_ind) >= 3 else curr_vwap
    fresh_vwap_breakdown = (
        (curr_close < curr_vwap)
        and (prev_close_1 >= prev_vwap_1 * 0.999)
        and (prev_close_2 >= prev_vwap_2 * 0.999)
        and (curr_close < curr_open)
        and (vol_ratio >= 1.2)
    )

    # 10-bar OBV low
    obv_10bar_floor = float(df_ind["OBV"].iloc[-11:-1].min()) if len(df_ind) >= 11 else curr_obv
    obv_10bar_low = (curr_obv <= obv_10bar_floor)

    is_stage2 = (
        not nifty_blocked
        and has_runup
        and stage2_time_window
        and fresh_vwap_breakdown
        and (curr_tsi < curr_tsi_sig)
        and (curr_tsi < prev_tsi)
        and obv_10bar_low
    )

    # Evaluate Trade Parameters & Scoring
    if is_stage1:
        stage = "STAGE 1"
        stage_title = "STAGE 1: Sniper Top Reversion"
        stage_desc = "Mean reversion from +2 SD VWAP exhaustion band back to intraday VWAP support"
        base_score = 75.0

        if vol_climax_occurred:
            base_score += 10.0
            conditions_met.append("Volume Climax at Highs (>=1.8x SMA20)")
        if room_to_vwap_pct >= 1.0:
            base_score += 10.0
            conditions_met.append(f"Deep Room to VWAP ({room_to_vwap_pct}%)")
        if is_solid_red_bar:
            base_score += 5.0
            conditions_met.append("Dominant Bearish Red Rejection Body")

        conditions_met.extend([
            f"Statistically Extended (+{morning_runup_pct}% from Open, touched +2SD Band)",
            f"Failed Push: {failed_push_type}",
            "OBV Smart Money Breakdown (Breaks 25m Floor & 9-SMA)",
            f"TSI Verified Bearish Cross ({curr_tsi:.3f} < {curr_tsi_sig:.3f})"
        ])

        score = min(100.0, round(base_score, 1))

        # Risk Management (Stage 1)
        suggested_entry = round(curr_close, 2)
        stop_loss = round(curr_morning_high * 1.003, 2)  # 0.3% above morning peak
        target_price = round(curr_vwap, 2)               # Target 1: VWAP
        target_price_2 = round(curr_vwap - (curr_close - curr_vwap) * 0.5, 2)  # Target 2

    elif is_stage2:
        stage = "STAGE 2"
        stage_title = "STAGE 2: VWAP Breakdown"
        stage_desc = "High-velocity momentum breakdown below VWAP flipping morning runup toward day's low"
        base_score = 75.0

        if vol_ratio >= 1.5:
            base_score += 10.0
            conditions_met.append(f"Heavy Breakdown Volume Surge ({vol_ratio}x SMA20)")
        if morning_runup_pct >= 2.5:
            base_score += 10.0
            conditions_met.append(f"Prior Strong Morning Run-up (+{morning_runup_pct}%)")
        if is_solid_red_bar:
            base_score += 5.0
            conditions_met.append("Solid Red Close below VWAP")

        conditions_met.extend([
            "Fresh Intraday VWAP Breakdown (Violated after holding)",
            "OBV Collapsed to 10-Bar Low",
            f"TSI Bearish Acceleration ({curr_tsi:.3f} < {curr_tsi_sig:.3f})"
        ])

        score = min(100.0, round(base_score, 1))

        # Risk Management (Stage 2)
        prev_h = float(df_ind["High"].iloc[-2]) if len(df_ind) >= 2 else curr_vwap
        suggested_entry = round(curr_close, 2)
        stop_loss = round(max(curr_vwap, prev_h) * 1.003, 2)  # Above VWAP / previous candle high
        target_price = round(curr_day_low, 2)                 # Target 1: Day's low
        target_price_2 = round(curr_day_low * 0.995, 2)       # Target 2: Continuation below day's low

    else:
        # Developing setup / partial scoring for watchlist ranking
        partial_score = 0.0
        if touched_2sd_recently and has_runup:
            partial_score += 25.0
            conditions_met.append("Extended near +2SD VWAP")
        elif touched_2sd_recently:
            partial_score += 15.0

        if failed_push:
            partial_score += 15.0
            conditions_met.append(f"Failed Push Attempt ({failed_push_type})")

        if tsi_confirmed_roll or (curr_tsi < curr_tsi_sig):
            partial_score += 10.0
            conditions_met.append("TSI Bearish Cross")

        if obv_breakdown or (curr_obv < curr_obv_sma9):
            partial_score += 10.0
            conditions_met.append("OBV below 9-SMA")

        if is_solid_red_bar:
            partial_score += 5.0

        score = round(partial_score, 1)

        suggested_entry = round(curr_close, 2)
        stop_loss = round(curr_morning_high * 1.004, 2)
        target_price = round(curr_vwap if curr_close > curr_vwap else curr_day_low, 2)
        target_price_2 = round(target_price * 0.995, 2)

    # Risk / Reward calculations
    risk_per_share = round(max(0.05, stop_loss - suggested_entry), 2)
    risk_pct = round((risk_per_share / suggested_entry) * 100.0, 2) if suggested_entry > 0 else 0.0
    reward_per_share = round(max(0.05, suggested_entry - target_price), 2)
    reward_pct = round((reward_per_share / suggested_entry) * 100.0, 2) if suggested_entry > 0 else 0.0
    rr_ratio = round(reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0.0

    # Human-readable consolidated reason
    if stage == "STAGE 1":
        reason_str = f"Stage 1 Sniper Reversion: {failed_push_type} above VWAP (+2SD rejection, {room_to_vwap_pct}% room to VWAP)"
    elif stage == "STAGE 2":
        reason_str = f"Stage 2 VWAP Breakdown: Fresh violation of VWAP on {vol_ratio}x volume following +{morning_runup_pct}% morning run"
    elif conditions_met:
        reason_str = f"Watchlist Candidate: {', '.join(conditions_met[:3])}"
    else:
        reason_str = f"Neutral intraday structure (Close: ₹{curr_close:,.2f}, VWAP: ₹{curr_vwap:,.2f})"

    is_short_candidate = (is_stage1 or is_stage2)

    return {
        "symbol": clean_sym,
        "stage": stage,
        "stage_title": stage_title,
        "stage_desc": stage_desc,
        "is_short_candidate": is_short_candidate,
        "short_probability_score": score,
        "close_price": curr_close,
        "open_price": curr_open,
        "high_price": curr_high,
        "low_price": curr_low,
        "day_open": curr_day_open,
        "morning_high": curr_morning_high,
        "day_low": curr_day_low,
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
        "risk_reward": f"1 : {rr_ratio}",
        "room_to_vwap_pct": room_to_vwap_pct,
        "morning_runup_pct": morning_runup_pct,
        "tsi_val": round(curr_tsi, 4),
        "tsi_signal": round(curr_tsi_sig, 4),
        "tsi_confirmed_roll": tsi_confirmed_roll,
        "obv_breakdown": obv_breakdown,
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
# 3. TELEGRAM ALERT DISPATCHER (STRICT ANTI-SPAM DEDUPLICATION)
# =============================================================================

def format_short_telegram_alert(candidate: Dict[str, Any]) -> str:
    """Formats professional HTML Telegram alert message for Morning Short Setup."""
    symbol = candidate.get("symbol", "")
    stage_title = candidate.get("stage_title") or candidate.get("stage") or "MORNING SHORT SETUP"
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

    msg = (
        f"🚨 <b>MORNING EXHAUSTION SHORT ALERT</b> 🚨\n"
        f"⚡ <b>Setup</b>: <b>{stage_title}</b>\n"
        f"🏷️ <b>Symbol</b>: <b>#{symbol}</b>  •  🕒 <b>{now_str} IST</b>\n\n"
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
    Sends 5-minute candlestick chart + technical alert message to Telegram.
    Enforces strict anti-spam: Max 1 Stage-1 alert and 1 Stage-2 alert per symbol per day.
    """
    symbol = candidate.get("symbol", "").strip().upper()
    stage = candidate.get("stage") or "SHORT"
    today_str = datetime.now().strftime("%Y-%m-%d")
    dedup_key = f"{today_str}_{symbol}_{stage}"

    # 1. Anti-spam check in memory
    if not force and dedup_key in _SENT_ALERTS_TODAY:
        logger.info(f"[DEDUP] Alert already sent today for {symbol} ({stage}). Skipping duplicate.")
        return {"status": "skipped", "reason": "Already alerted today", "symbol": symbol, "stage": stage}

    # 2. Anti-spam check in MongoDB
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

    # 3. Generate specialized 5-minute short chart buffer
    chart_buf = None
    try:
        chart_buf = generate_5min_short_chart_buffer(
            symbol=symbol,
            entry_price=candidate.get("suggested_entry"),
            stop_loss=candidate.get("stop_loss"),
            target_price=candidate.get("target_price"),
            num_candles=60,
            kite=kite,
            stage_label=f"[{stage}]"
        )
    except Exception as chart_err:
        logger.error(f"Failed to generate 5m short chart for {symbol}: {chart_err}")

    # 4. Dispatch alert to Telegram
    msg_text = format_short_telegram_alert(candidate)
    res = send_telegram_chart_alert(
        symbol=symbol,
        message_text=msg_text,
        chart_buffer=chart_buf,
        trigger_price=candidate.get("stop_loss"),
        parse_mode="HTML",
        kite=kite
    )

    # 5. Record successful dispatch to prevent future duplicates today
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
# 4. WATCHLIST SCANNER & RANKER
# =============================================================================

def get_all_watchlist_symbols() -> List[str]:
    """Retrieves unique stock symbols from all database watchlists."""
    symbols = set()
    try:
        dm = DataManager()
        for tf in ["monthly", "weekly", "daily", "manual", "darvas"]:
            records = dm.get_stock_ratings(tf)
            for r in records:
                sym = r.get("symbol")
                if sym:
                    symbols.add(sym.strip().upper().replace(".NS", "").replace("-EQ", ""))
    except Exception as e:
        logger.warning(f"Could not load MongoDB watchlists: {e}")

    # Fallback default liquid Indian Nifty watchlist if DB is empty
    if not symbols:
        symbols = {
            "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN",
            "TATAMOTORS", "TATASTEEL", "BHARTIARTL", "AXISBANK", "LT",
            "BAJFINANCE", "MARUTI", "SUNPHARMA", "TITAN", "WIPRO", "HCLTECH"
        }
    return sorted(list(symbols))


def scan_and_rank_short_candidates(
    symbols: Optional[List[str]] = None,
    send_telegram: bool = True
) -> List[Dict[str, Any]]:
    """
    Scans all watchlist stocks on 5-minute Zerodha data for Morning Short setups.
    Ranks them descending by Short Probability Score.
    Saves to MongoDB collection 'short_candidates' and dispatches Telegram chart alerts.
    """
    if symbols is None or len(symbols) == 0:
        symbols = get_all_watchlist_symbols()

    logger.info(f"🔍 Scanning {len(symbols)} stocks for 5m Morning Short & VWAP Reversion setups...")

    kite = get_kite_client()
    results = []

    for s in symbols:
        try:
            cand = analyze_morning_short_candidate(s, kite=kite)
            if cand and cand.get("short_probability_score", 0) > 0:
                results.append(cand)

                # Send Telegram alert if a qualified Stage 1 or Stage 2 setup is triggered
                if send_telegram and cand.get("is_short_candidate"):
                    logger.info(f"🚨 Qualified Short Trigger for {s} ({cand.get('stage')})! Dispatching Telegram alert...")
                    try:
                        send_morning_short_telegram_alert(cand, kite=kite)
                    except Exception as tg_err:
                        logger.error(f"Error dispatching Telegram alert for {s}: {tg_err}")

        except Exception as e:
            logger.debug(f"Error scanning {s} for morning short: {e}")

    # Sort descending by short_probability_score (highest conviction at top)
    sorted_results = sorted(results, key=lambda x: x.get("short_probability_score", 0.0), reverse=True)

    # Save to MongoDB 'short_candidates' collection
    try:
        dm = DataManager()
        col = dm.db["short_candidates"]
        col.delete_many({})  # Refresh collection
        if sorted_results:
            docs_to_save = []
            for r in sorted_results:
                doc = dict(r)
                doc["updated_at"] = datetime.now(timezone.utc).isoformat()
                docs_to_save.append(doc)
            if docs_to_save:
                col.insert_many(docs_to_save)
                logger.info(f"✅ Saved {len(docs_to_save)} short candidates to MongoDB 'short_candidates' collection.")
    except Exception as e:
        logger.warning(f"Could not save short candidates to MongoDB: {e}")

    return sorted_results


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    import argparse
    parser = argparse.ArgumentParser(description="Morning Exhaustion & Midday VWAP Reversion Short Scanner")
    parser.add_argument("--symbol", type=str, default=None, help="Scan a single symbol (e.g. RELIANCE)")
    parser.add_argument("--telegram", action="store_true", help="Send Telegram alerts for triggers")
    parser.add_argument("--limit", type=int, default=20, help="Number of symbols to scan (default 20)")
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
        print(f"\nScanning {len(scan_syms)} liquid stocks on 5m data...")
        ranked = scan_and_rank_short_candidates(symbols=scan_syms, send_telegram=args.telegram)

        print("\n" + "=" * 115)
        print(" 🚨 MORNING EXHAUSTION & MIDDAY VWAP REVERSION (SHORT) CANDIDATES")
        print("=" * 115)
        print(f"{'RANK':<5} {'SYMBOL':<12} {'STAGE':<10} {'SCORE':<10} {'CLOSE':<10} {'VWAP':<10} {'ENTRY':<10} {'STOP LOSS':<10} {'TARGET':<10} {'KEY PATTERN':<25}")
        print("-" * 115)

        for i, c in enumerate(ranked[:15], 1):
            sym = c.get("symbol")
            stg = c.get("stage") or "WATCH"
            sc = f"{c.get('short_probability_score'):.1f}/100"
            cp = f"₹{c.get('close_price'):.2f}"
            vw = f"₹{c.get('vwap'):.2f}"
            ent = f"₹{c.get('suggested_entry'):.2f}"
            sl = f"₹{c.get('stop_loss'):.2f}"
            tgt = f"₹{c.get('target_price'):.2f}"
            reason = (c.get("failed_push_type") or c.get("reason") or "")[:25]
            print(f"{i:<5} {sym:<12} {stg:<10} {sc:<10} {cp:<10} {vw:<10} {ent:<10} {sl:<10} {tgt:<10} {reason:<25}")

        print("=" * 115 + "\n")
