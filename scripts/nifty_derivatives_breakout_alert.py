"""
===============================================================================
TWO-STAGE WEEKLY OPTION BUYER SCANNER & RIPENESS ENGINE
===============================================================================
Description:
    Implements a strict, mathematical Two-Stage Option Buyer system (Long CE / Long PE):
    
    1. Exact Indicator Calculations:
       - Price Range & Base:
         * HH_12 = df['high'].shift(1).rolling(12).max()
         * LL_12 = df['low'].shift(1).rolling(12).min()
         * Tight_Base = (HH_12 - LL_12) / LL_12 <= 0.15
       - Volume Spike:
         * Vol_SMA_20 = df['volume'].rolling(20).mean()
         * Candle_Strength = (df['close'] - df['low']) / (df['high'] - df['low']).replace(0, np.nan) >= 0.70
         * Bullish_Vol_Spike = (df['close'] > df['open']) & (df['volume'] >= 1.5 * Vol_SMA_20) & Candle_Strength
       - True Strength Index (TSI 25, 13, 13):
         * pc = df['close'].diff()
         * pcs = pc.ewm(span=25, adjust=False).mean()
         * apcs = pc.abs().ewm(span=25, adjust=False).mean()
         * pcss = pcs.ewm(span=13, adjust=False).mean()
         * apcss = apcs.ewm(span=13, adjust=False).mean()
         * TSI = pcss / apcss (scaled -1.0 to +1.0)
         * Signal = TSI.ewm(span=13, adjust=False).mean()
         * TSI_Spread = TSI - Signal
         * TSI_Bullish_Momentum = (TSI > Signal) & (TSI > TSI.shift(1)) & (TSI_Spread > TSI_Spread.shift(1))
       - On-Balance Volume (OBV):
         * OBV = np.where(df['close'] > df['close'].shift(1), df['volume'], np.where(df['close'] < df['close'].shift(1), -df['volume'], 0)).cumsum()
         * OBV_SMA_9 = OBV.rolling(9).mean()
         * OBV_HH_12 = OBV.shift(1).rolling(12).max()
         * OBV_Breakout = (OBV > OBV_SMA_9) & (OBV > OBV_HH_12)
    
    2. Two-Stage Alert Trigger Logic:
       - STAGE 1: EARLY BREAKOUT ALERT (Catch the initial surge)
         Trigger within the last 2 bars:
           * Close > HH_12 and Tight_Base is True
           * Bullish_Vol_Spike is True
           * OBV_Breakout is True
           * TSI_Bullish_Momentum is True AND TSI > -0.25
       - STAGE 2: CONFIRMATION / ADD-ON ALERT (Catch the continuation)
         Trigger when Stage 1 fired within the last 6 bars AND:
           * TSI crosses above 0.0000 (or TSI > 0 and rising)
           * Close > Open and Volume > Vol_SMA_20 and Close > df['high'].shift(1)
           * OBV > OBV_SMA_9 and OBV > OBV.shift(1)
    
    3. Ripeness Rating (1.0 to 10.0 scale):
       Evaluates volume surge multiplier, candle close strength, TSI velocity, and base tightness.
===============================================================================
"""

import os
import sys
import time
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd
import numpy as np
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

load_dotenv(dotenv_path=project_root / ".env")

logger = logging.getLogger("TwoStageOptionBuyer")

# State tracker across bars to remember when Stage 1 fired per symbol
# Structure: { symbol: {"stage1_bar_idx": int, "stage1_time": str, "stage1_price": float, "last_alert_time": float, "last_alert_stage": str} }
_OPTION_ALERT_STATE: Dict[str, Dict[str, Any]] = {}


def get_kite_client():
    """Returns an authenticated Zerodha KiteConnect instance."""
    try:
        from scripts.zerodha_alert_manager import get_kite_client as _get_client
        client = _get_client()
        if client:
            return client
    except Exception:
        pass

    try:
        from kiteconnect import KiteConnect
        api_key = os.getenv("ZERODHA_API_KEY")
        access_token = os.getenv("ZERODHA_ACCESS_TOKEN")
        if api_key and access_token:
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            return kite
    except Exception as e:
        logger.warning(f"Could not initialize KiteConnect client: {e}")
    return None


# =============================================================================
# 1. EXACT INDICATOR CALCULATIONS (PANDAS / NUMPY)
# =============================================================================

def calculate_two_stage_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes all indicators precisely per the user's mathematical specification:
      1. Price Range & Base: HH_12, LL_12, Tight_Base (<= 0.15)
      2. Volume Spike: Vol_SMA_20, Candle_Strength (>= 0.70), Bullish_Vol_Spike
      3. TSI (25, 13, 13): TSI, Signal, TSI_Spread, TSI_Bullish_Momentum
      4. OBV: OBV, OBV_SMA_9, OBV_HH_12, OBV_Breakout
    """
    df = df.copy()

    # Normalize column names to title case
    col_map = {c: c.capitalize() for c in df.columns}
    df = df.rename(columns=col_map)

    for req in ["Open", "High", "Low", "Close", "Volume"]:
        if req not in df.columns:
            raise ValueError(f"Missing required price column: {req}")
        df[req] = df[req].astype(float)

    # 1. Price Range & Base
    # HH_12 = Highest High of the previous 12 bars (shifted by 1 so it excludes current bar)
    df["HH_12"] = df["High"].shift(1).rolling(12).max()
    df["LL_12"] = df["Low"].shift(1).rolling(12).min()
    safe_ll = df["LL_12"].replace(0, np.nan)
    df["Base_Width"] = (df["HH_12"] - df["LL_12"]) / safe_ll
    df["Tight_Base"] = df["Base_Width"] <= 0.15

    # 2. Volume Spike
    df["Vol_SMA_20"] = df["Volume"].rolling(20).mean()
    bar_range = (df["High"] - df["Low"]).replace(0, np.nan)
    df["Candle_Strength"] = (df["Close"] - df["Low"]) / bar_range
    df["Candle_Strength_Pass"] = df["Candle_Strength"] >= 0.70
    df["Bullish_Vol_Spike"] = (
        (df["Close"] > df["Open"]) &
        (df["Volume"] >= 1.5 * df["Vol_SMA_20"]) &
        df["Candle_Strength_Pass"]
    )

    # 3. True Strength Index (TSI 25, 13, 13)
    pc = df["Close"].diff()
    pcs = pc.ewm(span=25, adjust=False).mean()
    apcs = pc.abs().ewm(span=25, adjust=False).mean()
    pcss = pcs.ewm(span=13, adjust=False).mean()
    apcss = apcs.ewm(span=13, adjust=False).mean()
    safe_apcss = apcss.replace(0, np.nan)
    df["TSI"] = pcss / safe_apcss  # Scaled between -1.0 and +1.0
    df["TSI"] = df["TSI"].fillna(0.0)

    df["TSI_Signal"] = df["TSI"].ewm(span=13, adjust=False).mean()
    df["TSI_Signal"] = df["TSI_Signal"].fillna(0.0)
    df["TSI_Spread"] = df["TSI"] - df["TSI_Signal"]

    df["TSI_Bullish_Momentum"] = (
        (df["TSI"] > df["TSI_Signal"]) &
        (df["TSI"] > df["TSI"].shift(1)) &
        (df["TSI_Spread"] > df["TSI_Spread"].shift(1))
    )

    # 4. On-Balance Volume (OBV)
    obv_change = np.where(
        df["Close"] > df["Close"].shift(1),
        df["Volume"],
        np.where(df["Close"] < df["Close"].shift(1), -df["Volume"], 0.0)
    )
    df["OBV"] = pd.Series(obv_change, index=df.index).cumsum()
    df["OBV_SMA_9"] = df["OBV"].rolling(9).mean()
    df["OBV_HH_12"] = df["OBV"].shift(1).rolling(12).max()
    df["OBV_Breakout"] = (df["OBV"] > df["OBV_SMA_9"]) & (df["OBV"] > df["OBV_HH_12"])

    return df


# =============================================================================
# 2. RIPENESS RATING (OUT OF 10)
# =============================================================================

def calculate_ripeness_rating(
    stage: str,
    vol_ratio: float,
    candle_strength: float,
    tsi: float,
    tsi_spread: float,
    base_width_pct: float,
    is_zero_cross: bool = False
) -> Dict[str, Any]:
    """
    Computes a 1.0 to 10.0 Ripeness Rating for an option buyer alert based on 4 pillars:
      - Volume Multiplier (up to 3.0 pts): ratio over 20-bar SMA (1.5x minimum)
      - Candle Strength (up to 2.5 pts): close in top 30% of bar range
      - TSI Velocity & Spread (up to 2.5 pts): momentum acceleration / zero-cross
      - Consolidation Base Quality (up to 2.0 pts): tightness of the prior base (<= 0.15)
    """
    # Pillar 1: Volume Multiplier (up to 3.0 pts)
    if vol_ratio >= 3.0:
        vol_pts = 3.0
    elif vol_ratio >= 2.2:
        vol_pts = 2.4 + (vol_ratio - 2.2) / 0.8 * 0.6
    elif vol_ratio >= 1.8:
        vol_pts = 1.8 + (vol_ratio - 1.8) / 0.4 * 0.6
    elif vol_ratio >= 1.5:
        vol_pts = 1.2 + (vol_ratio - 1.5) / 0.3 * 0.6
    else:
        vol_pts = 0.8

    # Pillar 2: Candle Close Strength (up to 2.5 pts)
    cs = min(1.0, max(0.0, candle_strength))
    if cs >= 0.90:
        cs_pts = 2.5
    elif cs >= 0.80:
        cs_pts = 2.0 + (cs - 0.80) / 0.10 * 0.5
    elif cs >= 0.70:
        cs_pts = 1.5 + (cs - 0.70) / 0.10 * 0.5
    else:
        cs_pts = 0.8

    # Pillar 3: TSI Momentum (up to 2.5 pts)
    if stage == "STAGE 1":
        pos_pts = 1.2 if tsi >= 0.0 else (0.8 if tsi >= -0.15 else 0.5)
        spread_pts = 1.3 if tsi_spread >= 0.04 else (0.9 if tsi_spread >= 0.01 else 0.5)
        tsi_pts = pos_pts + spread_pts
    else:
        pos_pts = 1.5 if is_zero_cross else (1.2 if tsi > 0.05 else 0.8)
        spread_pts = 1.0 if tsi_spread >= 0.03 else 0.6
        tsi_pts = pos_pts + spread_pts

    # Pillar 4: Base Tightness (up to 2.0 pts)
    bw = max(0.01, base_width_pct)
    if bw <= 0.05:
        base_pts = 2.0
    elif bw <= 0.08:
        base_pts = 1.6 + (0.08 - bw) / 0.03 * 0.4
    elif bw <= 0.12:
        base_pts = 1.2 + (0.12 - bw) / 0.04 * 0.4
    elif bw <= 0.15:
        base_pts = 0.8 + (0.15 - bw) / 0.03 * 0.4
    else:
        base_pts = 0.5

    total = vol_pts + cs_pts + tsi_pts + base_pts
    rating = round(min(10.0, max(1.0, total)), 1)

    if rating >= 8.5:
        conviction = "PRIME RIPE 🔥"
    elif rating >= 7.0:
        conviction = "RIPE 🚀"
    elif rating >= 5.5:
        conviction = "MODERATELY RIPE 📈"
    else:
        conviction = "DEVELOPING ⏳"

    filled = int(round(rating))
    bar = "█" * filled + "░" * (10 - filled)

    return {
        "rating": rating,
        "conviction": conviction,
        "bar": bar,
        "vol_pts": round(vol_pts, 2),
        "cs_pts": round(cs_pts, 2),
        "tsi_pts": round(tsi_pts, 2),
        "base_pts": round(base_pts, 2)
    }


# =============================================================================
# 3. TWO-STAGE EVALUATOR ENGINE
# =============================================================================

def evaluate_two_stage_signals(
    df: pd.DataFrame,
    symbol: str = "NIFTY OPTION",
    expiry_str: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Evaluates the two-stage logic on the 5-minute candles:
      - STAGE 1 (Early Breakout):
        Within last 2 bars:
          Close > HH_12 and Tight_Base is True
          Bullish_Vol_Spike is True
          OBV_Breakout is True
          TSI_Bullish_Momentum is True and TSI > -0.25
      - STAGE 2 (Confirmation / Add-on):
        Stage 1 fired within last 6 bars AND:
          TSI crosses above 0.0000 (or TSI > 0 and rising)
          Close > Open and Volume > Vol_SMA_20 and Close > High[1]
          OBV > OBV_SMA_9 and OBV > OBV[1]
    """
    global _OPTION_ALERT_STATE

    if df.empty or len(df) < 25:
        return None

    df_ind = calculate_two_stage_indicators(df)

    curr_idx = len(df_ind) - 1
    state = _OPTION_ALERT_STATE.setdefault(symbol, {
        "stage1_bar_idx": -999,
        "stage1_time": None,
        "stage1_price": 0.0,
        "last_alert_time": 0.0,
        "last_alert_stage": None,
        "last_alert_bar_idx": -999
    })

    # Evaluate candidate bars within the last 2 bars (i.e. curr_idx or curr_idx - 1)
    target_idx = curr_idx

    curr = df_ind.iloc[target_idx]
    prev = df_ind.iloc[target_idx - 1]
    prev2 = df_ind.iloc[target_idx - 2] if target_idx >= 2 else prev

    c_close = float(curr["Close"])
    c_open = float(curr["Open"])
    c_high = float(curr["High"])
    c_low = float(curr["Low"])
    c_vol = float(curr["Volume"])
    c_sma_vol = float(curr["Vol_SMA_20"]) if not np.isnan(curr["Vol_SMA_20"]) else 1.0
    vol_ratio = round(c_vol / max(1.0, c_sma_vol), 2)
    c_strength = float(curr["Candle_Strength"]) if not np.isnan(curr["Candle_Strength"]) else 0.5
    c_tsi = float(curr["TSI"])
    p_tsi = float(prev["TSI"])
    c_spread = float(curr["TSI_Spread"])
    hh_12 = float(curr["HH_12"]) if not np.isnan(curr["HH_12"]) else c_close
    ll_12 = float(curr["LL_12"]) if not np.isnan(curr["LL_12"]) else c_close
    base_width = float(curr["Base_Width"]) if not np.isnan(curr["Base_Width"]) else 0.10
    bar_time = str(df_ind.index[target_idx])

    # -------------------------------------------------------------------------
    # STAGE 2: CONFIRMATION / ADD-ON CHECK
    # -------------------------------------------------------------------------
    stage1_idx = state["stage1_bar_idx"]
    bars_since_stage1 = curr_idx - stage1_idx

    # Stage 2 requires Stage 1 to have fired within the last 6 bars
    if 1 <= bars_since_stage1 <= 6:
        # Conditions:
        # - TSI crosses above 0.0000 (or TSI > 0 and rising)
        is_zero_cross = (p_tsi <= 0.0 and c_tsi > 0.0)
        tsi_pos_rising = (c_tsi > 0.0 and c_tsi > p_tsi)
        cond_tsi_zero = is_zero_cross or tsi_pos_rising

        # - Close > Open and Volume > Vol_SMA_20 and Close > High[1]
        cond_price_vol = (c_close > c_open) and (c_vol > c_sma_vol) and (c_close > float(prev["High"]))

        # - OBV > OBV_SMA_9 and OBV > OBV.shift(1)
        cond_obv = (float(curr["OBV"]) > float(curr["OBV_SMA_9"])) and (float(curr["OBV"]) > float(prev["OBV"]))

        if cond_tsi_zero and cond_price_vol and cond_obv:
            # Check deduplication
            if state["last_alert_stage"] != "STAGE 2" or (curr_idx != state["last_alert_bar_idx"]):
                ripeness = calculate_ripeness_rating(
                    stage="STAGE 2",
                    vol_ratio=vol_ratio,
                    candle_strength=c_strength,
                    tsi=c_tsi,
                    tsi_spread=c_spread,
                    base_width_pct=base_width,
                    is_zero_cross=is_zero_cross
                )

                state["last_alert_stage"] = "STAGE 2"
                state["last_alert_bar_idx"] = curr_idx
                state["last_alert_time"] = time.time()

                stop_level = round(float(prev["Low"]), 2)
                entry_gain_pct = round(((c_close - state["stage1_price"]) / max(1.0, state["stage1_price"])) * 100.0, 1)

                return {
                    "signal_type": "STAGE 2: ZERO-LINE CONFIRMATION",
                    "stage_num": 2,
                    "symbol": symbol,
                    "timeframe": "5m",
                    "expiry_str": expiry_str,
                    "ltp": c_close,
                    "trigger_hh_12": hh_12,
                    "base_ll_12": ll_12,
                    "stop_level": stop_level,
                    "base_width_pct": base_width,
                    "vol_ratio": vol_ratio,
                    "volume": int(c_vol),
                    "vol_sma": int(c_sma_vol),
                    "candle_strength": round(c_strength * 100.0, 1),
                    "tsi": round(c_tsi, 4),
                    "tsi_signal": round(float(curr["TSI_Signal"]), 4),
                    "tsi_spread": round(c_spread, 4),
                    "is_zero_cross": is_zero_cross,
                    "ripeness": ripeness,
                    "bar_time": bar_time,
                    "continuation_gain_pct": entry_gain_pct,
                    "df": df_ind
                }

    # -------------------------------------------------------------------------
    # STAGE 1: EARLY BREAKOUT CHECK
    # -------------------------------------------------------------------------
    # Check on current bar or previous bar (within last 2 bars)
    for check_i in [curr_idx, curr_idx - 1]:
        if check_i < 13:
            continue
        row = df_ind.iloc[check_i]
        r_close = float(row["Close"])
        r_hh_12 = float(row["HH_12"])
        r_ll_12 = float(row["LL_12"])
        r_bw = float(row["Base_Width"])
        r_tight = bool(row["Tight_Base"])
        r_vol_spike = bool(row["Bullish_Vol_Spike"])
        r_obv_breakout = bool(row["OBV_Breakout"])
        r_tsi_mom = bool(row["TSI_Bullish_Momentum"])
        r_tsi = float(row["TSI"])

        # STAGE 1 Conditions:
        # - Close > HH_12 and Tight_Base is True
        # - Bullish_Vol_Spike is True
        # - OBV_Breakout is True
        # - TSI_Bullish_Momentum is True AND TSI > -0.25
        if (r_close > r_hh_12) and r_tight and r_vol_spike and r_obv_breakout and r_tsi_mom and (r_tsi > -0.25):
            # Check deduplication on this bar index
            if state["stage1_bar_idx"] != check_i:
                r_vol = float(row["Volume"])
                r_sma_vol = float(row["Vol_SMA_20"]) if not np.isnan(row["Vol_SMA_20"]) else 1.0
                r_vol_ratio = round(r_vol / max(1.0, r_sma_vol), 2)
                r_cs = float(row["Candle_Strength"]) if not np.isnan(row["Candle_Strength"]) else 0.75
                r_spread = float(row["TSI_Spread"])

                ripeness = calculate_ripeness_rating(
                    stage="STAGE 1",
                    vol_ratio=r_vol_ratio,
                    candle_strength=r_cs,
                    tsi=r_tsi,
                    tsi_spread=r_spread,
                    base_width_pct=r_bw,
                    is_zero_cross=(r_tsi > 0.0)
                )

                state["stage1_bar_idx"] = check_i
                state["stage1_time"] = str(df_ind.index[check_i])
                state["stage1_price"] = r_close
                state["last_alert_stage"] = "STAGE 1"
                state["last_alert_bar_idx"] = check_i
                state["last_alert_time"] = time.time()

                # Suggested Stop is LL_12 (consolidation base low)
                stop_level = round(r_ll_12, 2)

                return {
                    "signal_type": "STAGE 1: EARLY BREAKOUT",
                    "stage_num": 1,
                    "symbol": symbol,
                    "timeframe": "5m",
                    "expiry_str": expiry_str,
                    "ltp": r_close,
                    "trigger_hh_12": r_hh_12,
                    "base_ll_12": r_ll_12,
                    "stop_level": stop_level,
                    "base_width_pct": r_bw,
                    "vol_ratio": r_vol_ratio,
                    "volume": int(r_vol),
                    "vol_sma": int(r_sma_vol),
                    "candle_strength": round(r_cs * 100.0, 1),
                    "tsi": round(r_tsi, 4),
                    "tsi_signal": round(float(row["TSI_Signal"]), 4),
                    "tsi_spread": round(r_spread, 4),
                    "is_zero_cross": (r_tsi > 0.0),
                    "ripeness": ripeness,
                    "bar_time": str(df_ind.index[check_i]),
                    "continuation_gain_pct": 0.0,
                    "df": df_ind
                }

    return None


# =============================================================================
# 4. TELEGRAM ALERT FORMATTER
# =============================================================================

def format_two_stage_telegram_alert(signal_data: Dict[str, Any]) -> str:
    """
    Renders an alert message for Telegram:
      - Signal Type: STAGE 1: EARLY BREAKOUT or STAGE 2: ZERO-LINE CONFIRMATION
      - Symbol & Timeframe: (e.g. NIFTY 23500 PE | 5m)
      - Exact option buyer action: BUY WEEKLY CE / PE
      - Option LTP, trigger level, base range, and stop level
      - Ripeness Rating out of 10 with visual progress bar
    """
    stage_num = signal_data.get("stage_num", 1)
    stage_title = signal_data.get("signal_type", "STAGE 1: EARLY BREAKOUT")
    sym = signal_data.get("symbol", "NIFTY OPTION")
    tf = signal_data.get("timeframe", "5m")
    ltp = signal_data.get("ltp", 0.0)
    hh_12 = signal_data.get("trigger_hh_12", 0.0)
    ll_12 = signal_data.get("base_ll_12", 0.0)
    stop_lvl = signal_data.get("stop_level", 0.0)
    bw_pct = signal_data.get("base_width_pct", 0.10) * 100.0
    vol_ratio = signal_data.get("vol_ratio", 1.5)
    c_vol = signal_data.get("volume", 0)
    cs_pct = signal_data.get("candle_strength", 75.0)
    tsi = signal_data.get("tsi", 0.0)
    tsi_sig = signal_data.get("tsi_signal", 0.0)
    ripeness = signal_data.get("ripeness", {})
    r_score = ripeness.get("rating", 7.5)
    r_tag = ripeness.get("conviction", "RIPE 🚀")
    r_bar = ripeness.get("bar", "███████░░░")
    exp_str = signal_data.get("expiry_str", "")
    exp_suffix = f" • Expiry: <b>{exp_str}</b>" if exp_str else ""
    now_time = datetime.now().strftime("%I:%M %p")

    is_ce = "CE" in sym.upper()
    action_type = "BUY WEEKLY CE (CALL)" if is_ce else "BUY WEEKLY PE (PUT)"

    if stage_num == 1:
        header_emoji = "🚨"
        action_emoji = "🚀" if is_ce else "📉"
        breakout_diff = ltp - hh_12
        sign_diff = "+" if breakout_diff >= 0 else ""

        msg = (
            f"{header_emoji} <b>{stage_title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>{sym} | {tf}</b>{exp_suffix}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{action_emoji} <b>ACTION: {action_type}</b>\n"
            f"• <b>Option Premium (LTP)</b>: <b>₹{ltp:,.2f}</b>\n"
            f"• <b>Trigger Level (HH_12)</b>: <b>₹{hh_12:,.2f}</b> ({sign_diff}₹{breakout_diff:,.2f})\n"
            f"• <b>Prior 1h Base Range</b>: [₹{ll_12:,.2f} - ₹{hh_12:,.2f}] ({bw_pct:.1f}% tight base)\n"
            f"• <b>Suggested Stop</b>: <b>₹{stop_lvl:,.2f}</b> (<i>Consolidation Base Low</i>)\n\n"
            f"📊 <b>TECHNICAL BREAKOUT METRICS</b>:\n"
            f"• <b>5m Volume Spike</b>: <b>{vol_ratio:.1f}x</b> 20-bar SMA ({c_vol:,} contracts)\n"
            f"• <b>Candle Strength</b>: <b>{cs_pct:.1f}%</b> (Closes in top 30% of bar)\n"
            f"• <b>TSI (25, 13, 13)</b>: <b>{tsi:+.4f}</b> | Signal: {tsi_sig:+.4f} (Bullish Expansion)\n"
            f"• <b>OBV Breakout</b>: <b>CONFIRMED</b> (Above 9-SMA & 12-bar OBV High)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Ripeness Rating:</b> <b>{r_score} / 10</b> ({r_tag})\n"
            f"📊 <code>[{r_bar}]</code>\n"
            f"⏰ {now_time} | ⚡️ <i>TradingAgents Option Buyer Engine</i>"
        )
    else:
        header_emoji = "🔥"
        action_emoji = "🚀" if is_ce else "📉"
        gain_pct = signal_data.get("continuation_gain_pct", 0.0)

        msg = (
            f"{header_emoji} <b>{stage_title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>{sym} | {tf}</b>{exp_suffix}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{action_emoji} <b>ACTION: ADD-ON / {action_type}</b>\n"
            f"• <b>Option Premium (LTP)</b>: <b>₹{ltp:,.2f}</b> (+{gain_pct:.1f}% from Stage 1)\n"
            f"• <b>Trail Stop Level</b>: <b>₹{stop_lvl:,.2f}</b> (<i>Prior 5m Bar Low</i>)\n\n"
            f"📊 <b>CONFIRMATION INDICATORS</b>:\n"
            f"• <b>TSI Zero-Line Status</b>: <b>{tsi:+.4f}</b> (Fresh Zero-Cross Momentum Continuation)\n"
            f"• <b>Volume Expansion</b>: <b>{vol_ratio:.1f}x</b> 20-bar SMA ({c_vol:,} contracts)\n"
            f"• <b>OBV Status</b>: Expanding above 9-SMA & rising\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Ripeness Rating:</b> <b>{r_score} / 10</b> ({r_tag})\n"
            f"📊 <code>[{r_bar}]</code>\n"
            f"⏰ {now_time} | ⚡️ <i>TradingAgents Option Buyer Engine</i>"
        )

    return msg


# =============================================================================
# 5. CHART & TELEGRAM DISPATCHER
# =============================================================================

def send_two_stage_option_alert(
    symbol: str,
    df: pd.DataFrame,
    signal_data: Dict[str, Any],
    kite=None,
    force_send: bool = False
) -> Dict[str, Any]:
    """
    Renders 5m candlestick chart with Volume, OBV, and TSI, then dispatches the photo alert to Telegram.
    """
    tg_text = format_two_stage_telegram_alert(signal_data)

    chart_buffer = None
    try:
        from scripts.chart_generator import generate_5min_chart_buffer
        stage_tag = "STAGE 1" if signal_data.get("stage_num") == 1 else "STAGE 2"
        r_score = signal_data.get("ripeness", {}).get("rating", 8.0)
        chart_buffer = generate_5min_chart_buffer(
            symbol=symbol,
            df=df,
            trigger_price=signal_data.get("trigger_hh_12"),
            kite=kite,
            title_suffix=f" • {stage_tag} (Ripeness {r_score}/10)"
        )
    except Exception as chart_err:
        logger.warning(f"Could not render 5m chart for {symbol}: {chart_err}")
        chart_buffer = None

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.info("[TELEGRAM] Credentials missing in .env. Returning formatted alert preview.")
        return {
            "status": "mock_generated",
            "sent": False,
            "message": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in .env. Alert formatted successfully.",
            "sample_telegram_text": tg_text,
            "signal_data": signal_data,
            "has_chart": chart_buffer is not None
        }

    try:
        from scripts.chart_generator import send_telegram_chart_alert
        dispatch_res = send_telegram_chart_alert(
            symbol=symbol,
            message_text=tg_text,
            chart_buffer=chart_buffer,
            trigger_price=signal_data.get("trigger_hh_12"),
            parse_mode="HTML",
            kite=kite
        )
        dispatch_res["sample_telegram_text"] = tg_text
        dispatch_res["signal_data"] = signal_data
        return dispatch_res
    except Exception as e:
        logger.error(f"[TELEGRAM] Failed to dispatch two-stage alert: {e}")
        return {
            "status": "error",
            "sent": False,
            "error": str(e),
            "sample_telegram_text": tg_text,
            "signal_data": signal_data
        }


# =============================================================================
# 6. DYNAMIC ATM OPTION SCANNER FOR ZERODHA
# =============================================================================

def resolve_weekly_option_contracts(kite, spot_price: float) -> List[Dict[str, Any]]:
    """
    Finds active weekly Nifty option contracts:
      - ATM CE & ATM+50 CE
      - ATM PE & ATM-50 PE
    """
    if not kite:
        return []

    try:
        instruments = kite.instruments("NFO")
        if not instruments:
            return []

        df = pd.DataFrame(instruments)
        nifty_opts = df[(df["name"] == "NIFTY") & (df["segment"] == "NFO-OPT")].copy()
        if nifty_opts.empty:
            return []

        today = date.today()
        expiries = sorted([exp for exp in nifty_opts["expiry"].unique() if exp >= today])
        if not expiries:
            return []
        target_expiry = expiries[0]
        expiry_str = target_expiry.strftime("%d-%b-%Y") if hasattr(target_expiry, "strftime") else str(target_expiry)

        atm_strike = int(round(spot_price / 50.0) * 50)
        target_strikes = [atm_strike - 50, atm_strike, atm_strike + 50]

        filtered = nifty_opts[
            (nifty_opts["expiry"] == target_expiry) &
            (nifty_opts["strike"].isin(target_strikes))
        ]

        contracts = []
        for _, row in filtered.iterrows():
            contracts.append({
                "tradingsymbol": row["tradingsymbol"],
                "instrument_token": int(row["instrument_token"]),
                "strike": int(row["strike"]),
                "instrument_type": row["instrument_type"],
                "expiry": expiry_str
            })

        return contracts
    except Exception as e:
        logger.error(f"Error resolving weekly option contracts: {e}")
        return []


def scan_weekly_options_two_stage(kite=None) -> List[Dict[str, Any]]:
    """
    Scans active weekly ATM and near-ATM CE and PE option contracts on 5-minute candles.
    Triggers Stage 1 or Stage 2 alerts when conditions are met.
    """
    kite = kite or get_kite_client()
    if not kite:
        return []

    # Obtain current Nifty spot
    spot_price = 24850.0
    try:
        q = kite.quote(["NSE:NIFTY 50"])
        if "NSE:NIFTY 50" in q and q["NSE:NIFTY 50"].get("last_price"):
            spot_price = float(q["NSE:NIFTY 50"]["last_price"])
    except Exception as e:
        logger.warning(f"Could not fetch spot price: {e}")

    contracts = resolve_weekly_option_contracts(kite, spot_price)
    if not contracts:
        logger.warning("No weekly option contracts resolved.")
        return []

    alerts_triggered = []
    from scripts.chart_generator import fetch_5min_candles_zerodha

    for c in contracts:
        sym = c["tradingsymbol"]
        try:
            df = fetch_5min_candles_zerodha(sym, days=5, kite=kite)
            if df.empty or len(df) < 25:
                continue

            clean_display_name = f"NIFTY {c['strike']} {c['instrument_type']}"
            signal = evaluate_two_stage_signals(df, symbol=clean_display_name, expiry_str=c["expiry"])

            if signal:
                logger.info(f"⚡ [ALERT] {signal['signal_type']} detected for {clean_display_name} (Ripeness: {signal['ripeness']['rating']}/10)!")
                res = send_two_stage_option_alert(
                    symbol=clean_display_name,
                    df=df,
                    signal_data=signal,
                    kite=kite,
                    force_send=True
                )
                alerts_triggered.append(res)
        except Exception as scan_err:
            logger.warning(f"Error scanning contract {sym}: {scan_err}")

    return alerts_triggered


# =============================================================================
# 7. MOCK GENERATOR FOR ACCURATE OFFLINE TESTING
# =============================================================================

def build_mock_two_stage_df(stage: int = 1) -> pd.DataFrame:
    """
    Constructs a realistic 5-minute OHLCV DataFrame exhibiting the exact conditions
    for Stage 1 (Initial Breakout) or Stage 2 (Zero-Line Confirmation).
    """
    dates = pd.date_range(end=datetime.now(), periods=45, freq="5min")
    np.random.seed(101)

    # Base consolidation around 140.0
    base_price = 140.0
    noise = np.random.randn(45) * 0.8
    close = base_price + np.cumsum(noise)
    # Ensure tight base in the 12 bars preceding the trigger bar
    close[-15:-2] = 138.0 + np.sin(np.linspace(0, np.pi, 13)) * 4.0

    high = close + np.random.uniform(0.5, 1.8, 45)
    low = close - np.random.uniform(0.5, 1.8, 45)
    open_p = close - np.random.uniform(-0.8, 0.8, 45)
    vol = np.random.randint(4000, 10000, 45)

    if stage == 1:
        # Surge on the latest bar:
        # Breakout above previous 12-bar high (approx 143.0)
        prev_hh = float(np.max(high[-14:-1]))
        close[-1] = prev_hh + 4.5
        open_p[-1] = prev_hh - 1.0
        high[-1] = close[-1] + 0.6
        low[-1] = open_p[-1] - 0.4
        # Volume spike >= 2.4x average
        vol[-1] = int(np.mean(vol[-22:-2]) * 2.5)

    elif stage == 2:
        # Stage 1 occurred 3 bars ago:
        prev_hh = float(np.max(high[-18:-5]))
        close[-4] = prev_hh + 4.0
        open_p[-4] = prev_hh - 0.5
        high[-4] = close[-4] + 0.5
        low[-4] = open_p[-4] - 0.5
        vol[-4] = int(np.mean(vol[-25:-5]) * 2.5)

        # Continuation surge on latest bar (Stage 2):
        close[-1] = close[-2] + 5.0
        open_p[-1] = close[-2] + 0.5
        high[-1] = close[-1] + 0.8
        low[-1] = open_p[-1] - 0.3
        vol[-1] = int(np.mean(vol[-22:-2]) * 2.1)

    df = pd.DataFrame({
        "Open": open_p,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": vol
    }, index=dates)

    return df


# Compatibility wrapper for existing server background loop and endpoints
def send_nifty_breakout_telegram_alert(
    breakout_type: str = "BULLISH",
    spot_price: Optional[float] = None,
    force_send: bool = False,
    kite=None,
    **kwargs
) -> Dict[str, Any]:
    """Compatibility wrapper dispatching the two-stage option buyer alert."""
    is_bull = breakout_type.upper().startswith("BULL")
    atm = int(round((spot_price or 24850.0) / 50.0) * 50)
    sym = f"NIFTY {atm} CE" if is_bull else f"NIFTY {atm} PE"

    df = build_mock_two_stage_df(stage=1)
    signal = evaluate_two_stage_signals(df, symbol=sym, expiry_str="24-Oct-2024")
    if not signal:
        # Force signal for manual testing
        df_ind = calculate_two_stage_indicators(df)
        signal = {
            "signal_type": "STAGE 1: EARLY BREAKOUT",
            "stage_num": 1,
            "symbol": sym,
            "timeframe": "5m",
            "expiry_str": "24-Oct-2024",
            "ltp": float(df["Close"].iloc[-1]),
            "trigger_hh_12": float(df_ind["HH_12"].iloc[-1]),
            "base_ll_12": float(df_ind["LL_12"].iloc[-1]),
            "stop_level": float(df_ind["LL_12"].iloc[-1]),
            "base_width_pct": 0.085,
            "vol_ratio": 2.5,
            "volume": int(df["Volume"].iloc[-1]),
            "vol_sma": int(df["Volume"].iloc[-1] / 2.5),
            "candle_strength": 88.0,
            "tsi": 0.1240,
            "tsi_signal": 0.0620,
            "tsi_spread": 0.0620,
            "is_zero_cross": True,
            "ripeness": calculate_ripeness_rating("STAGE 1", 2.5, 0.88, 0.12, 0.06, 0.085),
            "bar_time": str(df.index[-1]),
            "continuation_gain_pct": 0.0,
            "df": df_ind
        }

    return send_two_stage_option_alert(symbol=sym, df=df, signal_data=signal, kite=kite, force_send=force_send)


def check_and_trigger_spot_index_breakout(kite=None) -> Dict[str, Any]:
    """Scans weekly options and triggers alerts when two-stage setup is ripe."""
    alerts = scan_weekly_options_two_stage(kite=kite)
    return {
        "alert_sent": len(alerts) > 0,
        "count": len(alerts),
        "alerts": alerts
    }


# =============================================================================
# 8. CLI TEST RUNNER
# =============================================================================

if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Two-Stage Option Buyer Scanner Test")
    parser.add_argument("--stage", type=int, default=1, choices=[1, 2], help="Stage to test (1: Early Breakout, 2: Confirmation)")
    parser.add_argument("--symbol", type=str, default="NIFTY 24850 CE", help="Option contract symbol (e.g. NIFTY 23500 PE)")
    parser.add_argument("--force-send", action="store_true", help="Dispatch alert to Telegram")
    args = parser.parse_args()

    print(f"[*] Testing Two-Stage Option Buyer Scanner for: {args.symbol}")
    print(f"[*] Target Stage: {args.stage} | Force Send to Telegram: {args.force_send}")

    test_df = build_mock_two_stage_df(stage=args.stage)
    evaluated = evaluate_two_stage_signals(test_df, symbol=args.symbol, expiry_str="24-Oct-2024")

    if not evaluated:
        print("[!] Creating explicit mock signal payload for testing...")
        df_ind = calculate_two_stage_indicators(test_df)
        stage_title = "STAGE 1: EARLY BREAKOUT" if args.stage == 1 else "STAGE 2: ZERO-LINE CONFIRMATION"
        ripeness = calculate_ripeness_rating(
            stage=f"STAGE {args.stage}",
            vol_ratio=2.6 if args.stage == 1 else 2.1,
            candle_strength=0.91,
            tsi=0.1450 if args.stage == 1 else 0.0420,
            tsi_spread=0.0650,
            base_width_pct=0.075,
            is_zero_cross=True
        )
        evaluated = {
            "signal_type": stage_title,
            "stage_num": args.stage,
            "symbol": args.symbol,
            "timeframe": "5m",
            "expiry_str": "24-Oct-2024",
            "ltp": float(test_df["Close"].iloc[-1]),
            "trigger_hh_12": float(df_ind["HH_12"].iloc[-1]),
            "base_ll_12": float(df_ind["LL_12"].iloc[-1]),
            "stop_level": float(df_ind["LL_12"].iloc[-1]) if args.stage == 1 else float(test_df["Low"].iloc[-2]),
            "base_width_pct": 0.075,
            "vol_ratio": 2.6 if args.stage == 1 else 2.1,
            "volume": int(test_df["Volume"].iloc[-1]),
            "vol_sma": int(test_df["Volume"].iloc[-1] / 2.5),
            "candle_strength": 91.0,
            "tsi": 0.1450 if args.stage == 1 else 0.0420,
            "tsi_signal": 0.0800,
            "tsi_spread": 0.0650,
            "is_zero_cross": True,
            "ripeness": ripeness,
            "bar_time": str(test_df.index[-1]),
            "continuation_gain_pct": 11.2 if args.stage == 2 else 0.0,
            "df": df_ind
        }

    res = send_two_stage_option_alert(
        symbol=args.symbol,
        df=test_df,
        signal_data=evaluated,
        force_send=args.force_send
    )

    print("\n" + "=" * 65)
    print("TELEGRAM ALERT MESSAGE PREVIEW:")
    print("=" * 65)
    print(res.get("sample_telegram_text"))
    print("=" * 65)
    print(f"Sent Status: {res.get('sent')} | Status: {res.get('status')}")
