"""
===============================================================================
NIFTY DERIVATIVES 3-CONFIRMATION AUTOMATED BREAKOUT & ALERT ENGINE
===============================================================================
Implements the strict 3-Confirmation Nifty Derivatives Alert System with
fully automated, regime-adaptive parameter calculation and MongoDB continuous
refinement:

1. Confirmation 1 – Futures OI Buildup (Nifty Current-Month Futures via Zerodha)
   - Long Buildup  = Current Close > Previous Close AND Current OI > Previous OI
                     AND OI increase >= Auto-Calculated Dynamic OI Threshold
   - Short Buildup = Current Close < Previous Close AND Current OI > Previous OI
                     AND OI increase >= Auto-Calculated Dynamic OI Threshold
   - OI Threshold is dynamically computed from rolling statistics of recent OI
     changes (mean + 1.0–1.5 std dev & high percentile of last 20–50 bars),
     adapted to the current volatility regime and refined via MongoDB history.

2. Confirmation 2 – ATM Straddle Premium Expansion
   - Auto-selects nearest ATM strike (50-pt step) from current underlying/futures price.
   - Fetches 5m candles for ATM Call (CE) + ATM Put (PE) from Zerodha NFO.
   - Combined Premium = ATM CE Close + ATM PE Close.
   - Confirms expansion when Current Combined Premium > Previous Combined Premium
     AND expansion % >= Auto-Calculated Minimum Expansion % Threshold (derived
     from recent straddle volatility / underlying ATR and refined via MongoDB).

3. Confirmation 3 – Price Action
   - Auto Swing Lookback (N): Dynamically chosen (3–6 bars) using ATR & ADX-style
     regime detection (shorter in high-volatility / strong trend, longer in
     low-volatility / range-bound conditions).
   - Auto Body Strength %: Dynamically set from the distribution of recent candle
     body-to-range ratios (requiring top 30–40% of recent body strength, i.e.,
     60th–70th percentile).
   - Bullish Price Action: Candle closes above highest high of previous N candles
     AND body-to-range ratio >= Auto Body Strength %.
   - Bearish Price Action: Candle closes below lowest low of previous N candles
     AND body-to-range ratio >= Auto Body Strength %.

Alert Rules (Strict):
   - Bullish Alert ONLY when ALL THREE are true:
     Long Buildup + ATM Straddle Expansion + Bullish Price Action
   - Bearish Alert ONLY when ALL THREE are true:
     Short Buildup + ATM Straddle Expansion + Bearish Price Action
   - Never triggers if even one confirmation is missing.

Telegram Alerts:
   - Clear Bullish / Bearish signal with Rating out of 10.
   - Snapshot of the 5m chart including Candlestick + Volume + OBV + TSI indicators.
===============================================================================
"""

import os
import sys
import time
import logging
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd
import numpy as np
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

load_dotenv(dotenv_path=project_root / ".env")

logger = logging.getLogger("NiftyDerivatives3Confirmation")

# In-memory deduplication state across bars
_ALERT_DEDUP_STATE: Dict[str, Any] = {
    "last_alert_bar_time": None,
    "last_alert_direction": None,
    "last_alert_ts": 0.0,
}


# =============================================================================
# 1. ZERODHA CLIENT & INSTRUMENT RESOLUTION (STRICTLY ZERODHA API)
# =============================================================================

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


_NFO_INSTRUMENTS_CACHE: Dict[str, Any] = {
    "date": None,
    "df": None
}


def get_nfo_instruments_df(kite=None) -> pd.DataFrame:
    """Fetches and caches the NFO instruments DataFrame for the current day."""
    today = date.today()
    if _NFO_INSTRUMENTS_CACHE["date"] == today and _NFO_INSTRUMENTS_CACHE["df"] is not None:
        return _NFO_INSTRUMENTS_CACHE["df"]

    try:
        from tradingagents.dataflows.zerodha import _get_instruments_df
        inst_df = _get_instruments_df()
        if inst_df is not None and not inst_df.empty:
            nfo_df = inst_df[inst_df["exchange"] == "NFO"].copy() if "exchange" in inst_df.columns else inst_df.copy()
            if not nfo_df.empty:
                nfo_df["expiry_date"] = pd.to_datetime(nfo_df["expiry"]).dt.date
                _NFO_INSTRUMENTS_CACHE["date"] = today
                _NFO_INSTRUMENTS_CACHE["df"] = nfo_df
                return nfo_df
    except Exception:
        pass

    kite = kite or get_kite_client()
    if not kite:
        return pd.DataFrame()

    try:
        instruments = kite.instruments("NFO")
        if instruments:
            df = pd.DataFrame(instruments)
            df["expiry_date"] = pd.to_datetime(df["expiry"]).dt.date
            _NFO_INSTRUMENTS_CACHE["date"] = today
            _NFO_INSTRUMENTS_CACHE["df"] = df
            return df
    except Exception as e:
        logger.warning(f"Failed to fetch NFO instruments from Zerodha: {e}")

    return pd.DataFrame()


def resolve_nifty_near_month_future(kite=None) -> Optional[Dict[str, Any]]:
    """
    Resolves the current/near-month Nifty Futures contract (NIFTY1!) from Zerodha NFO.
    """
    nfo_df = get_nfo_instruments_df(kite)
    if nfo_df.empty:
        return None

    today = date.today()
    futs = nfo_df[
        (nfo_df["name"] == "NIFTY") &
        (nfo_df["instrument_type"] == "FUT") &
        (nfo_df["expiry_date"] >= today)
    ].sort_values("expiry_date")

    if futs.empty:
        return None

    near_fut = futs.iloc[0]
    return {
        "tradingsymbol": str(near_fut["tradingsymbol"]),
        "instrument_token": int(near_fut["instrument_token"]),
        "expiry": str(near_fut["expiry_date"]),
    }


def auto_select_atm_strike(underlying_price: float, step: int = 50) -> int:
    """
    Automatically selects the nearest Nifty strike to the current futures/underlying price.
    No manual input exposed.
    """
    if underlying_price <= 0:
        return 24850
    return int(round(underlying_price / float(step)) * step)


def resolve_atm_straddle_contracts(
    underlying_price: float,
    kite=None
) -> Optional[Dict[str, Any]]:
    """
    Auto-calculates the approximate ATM strike from underlying/futures close and resolves
    both the nearest-expiry ATM Call (CE) and ATM Put (PE) contracts from Zerodha NFO.
    """
    atm_strike = auto_select_atm_strike(underlying_price, step=50)
    nfo_df = get_nfo_instruments_df(kite)
    if nfo_df.empty:
        return None

    today = date.today()
    opts = nfo_df[
        (nfo_df["name"] == "NIFTY") &
        (nfo_df["instrument_type"].isin(["CE", "PE"])) &
        (nfo_df["expiry_date"] >= today)
    ]
    if opts.empty:
        return None

    nearest_expiry = sorted(opts["expiry_date"].unique())[0]
    atm_opts = opts[
        (opts["expiry_date"] == nearest_expiry) &
        (opts["strike"].astype(float).round(0) == float(atm_strike))
    ]

    ce_rows = atm_opts[atm_opts["instrument_type"] == "CE"]
    pe_rows = atm_opts[atm_opts["instrument_type"] == "PE"]
    if ce_rows.empty or pe_rows.empty:
        return None

    ce_row = ce_rows.iloc[0]
    pe_row = pe_rows.iloc[0]

    return {
        "atm_strike": atm_strike,
        "expiry": str(nearest_expiry),
        "ce_symbol": str(ce_row["tradingsymbol"]),
        "ce_token": int(ce_row["instrument_token"]),
        "pe_symbol": str(pe_row["tradingsymbol"]),
        "pe_token": int(pe_row["instrument_token"]),
    }


def fetch_zerodha_5m_candles_with_oi(
    instrument_token: int,
    days: int = 5,
    kite=None,
    tradingsymbol: Optional[str] = None
) -> pd.DataFrame:
    """
    Fetches 5-minute OHLCV + Open Interest (OI) candles from Zerodha Kite Connect API.
    Also enriches the latest bar with live quote OI if available.
    """
    kite = kite or get_kite_client()
    if not kite or not instrument_token:
        return pd.DataFrame()

    try:
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)
        raw_candles = kite.historical_data(
            instrument_token=instrument_token,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
            interval="5minute",
            oi=True
        )
        if not raw_candles:
            return pd.DataFrame()

        df = pd.DataFrame(raw_candles)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.set_index("date")
        df = df.rename(columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
            "oi": "OI"
        })
        for col in ["Open", "High", "Low", "Close"]:
            df[col] = df[col].astype(float)
        df["Volume"] = df["Volume"].fillna(0).astype(float)
        if "OI" not in df.columns:
            df["OI"] = 0.0
        else:
            df["OI"] = df["OI"].fillna(0).astype(float)

        # Enrich latest candle with live quote OI & LTP if available
        if tradingsymbol:
            try:
                q_key = f"NFO:{tradingsymbol}"
                q = kite.quote([q_key])
                if q_key in q:
                    live_oi = float(q[q_key].get("oi") or 0.0)
                    if live_oi > 0 and df["OI"].iloc[-1] == 0:
                        df.iloc[-1, df.columns.get_loc("OI")] = live_oi
            except Exception:
                pass

        return df
    except Exception as e:
        logger.warning(f"Failed to fetch 5m candles with OI for token {instrument_token}: {e}")
        return pd.DataFrame()


# =============================================================================
# 2. MONGODB CONTINUOUS PARAMETER LEARNING & PERFORMANCE PERSISTENCE
# =============================================================================

def _get_mongo_db():
    """Returns the MongoDB database instance via DataManager if reachable."""
    try:
        from data_manager import DataManager
        dm = DataManager()
        return dm.db
    except Exception as e:
        logger.debug(f"MongoDB unavailable for parameter refinement: {e}")
        return None


def update_and_fetch_historical_refinement(current_fut_price: float) -> Dict[str, float]:
    """
    1. Evaluates previously triggered signals stored in MongoDB (`nifty_derivatives_signals`)
       against `current_fut_price` to record forward performance (win/loss & return %).
    2. Computes adaptive calibration multipliers from historical parameter performance
       so the auto-thresholds continuously refine over time.
    """
    default_calibration = {
        "oi_std_multiplier": 1.20,
        "straddle_exp_multiplier": 1.15,
        "body_percentile_target": 65.0,
        "historical_win_rate": 0.60,
        "sample_size": 0
    }

    db = _get_mongo_db()
    if db is None:
        return default_calibration

    try:
        signals_col = db["nifty_derivatives_signals"]

        # 1. Update open/unsettled signals that are at least 15 minutes old
        if current_fut_price > 0:
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=15)
            open_signals = list(signals_col.find({
                "outcome_evaluated": False,
                "created_at_utc": {"$lte": cutoff_time}
            }).limit(50))

            for sig in open_signals:
                entry_p = float(sig.get("futures_close") or 0.0)
                direction = str(sig.get("direction") or "BULLISH").upper()
                if entry_p > 0:
                    raw_ret_pct = ((current_fut_price - entry_p) / entry_p) * 100.0
                    signed_ret_pct = raw_ret_pct if direction == "BULLISH" else -raw_ret_pct
                    is_win = signed_ret_pct > 0.05  # Profitable directional move
                    signals_col.update_one(
                        {"_id": sig["_id"]},
                        {"$set": {
                            "outcome_evaluated": True,
                            "eval_price": current_fut_price,
                            "signed_return_pct": round(signed_ret_pct, 4),
                            "is_win": is_win,
                            "evaluated_at_utc": datetime.now(timezone.utc)
                        }}
                    )

        # 2. Compute adaptive calibration from evaluated signals
        evaluated_sigs = list(
            signals_col.find({"outcome_evaluated": True})
            .sort("created_at_utc", -1)
            .limit(40)
        )
        if not evaluated_sigs:
            return default_calibration

        wins = [s for s in evaluated_sigs if s.get("is_win")]
        win_rate = len(wins) / float(len(evaluated_sigs))

        # If win rate is lower than 55%, tighten auto-thresholds; if > 70%, slightly relax toward winning mean
        if win_rate < 0.50:
            oi_mult = 1.40
            strad_mult = 1.30
            body_pct = 70.0
        elif win_rate < 0.65:
            oi_mult = 1.25
            strad_mult = 1.15
            body_pct = 66.0
        else:
            oi_mult = 1.10
            strad_mult = 1.05
            body_pct = 62.0

        return {
            "oi_std_multiplier": round(oi_mult, 3),
            "straddle_exp_multiplier": round(strad_mult, 3),
            "body_percentile_target": round(body_pct, 1),
            "historical_win_rate": round(win_rate, 3),
            "sample_size": len(evaluated_sigs)
        }
    except Exception as e:
        logger.debug(f"Error updating/fetching MongoDB parameter refinement: {e}")
        return default_calibration


def persist_parameters_and_signal_to_mongodb(
    auto_params: Dict[str, Any],
    confirmations: Dict[str, Any],
    signal_triggered: bool,
    signal_payload: Optional[Dict[str, Any]] = None
) -> None:
    """
    Stores historical auto-threshold parameter values and triggered signals in MongoDB
    so the system can continuously refine the auto-thresholds over time.
    """
    db = _get_mongo_db()
    if db is None:
        return

    now_utc = datetime.now(timezone.utc)
    try:
        params_col = db["nifty_derivatives_auto_params"]
        params_doc = {
            "created_at_utc": now_utc,
            "timestamp_ist": (now_utc + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S IST"),
            "auto_parameters": auto_params,
            "confirmations_summary": {
                "c1_long_buildup": confirmations.get("c1_long_buildup", False),
                "c1_short_buildup": confirmations.get("c1_short_buildup", False),
                "c2_straddle_expansion": confirmations.get("c2_straddle_expansion", False),
                "c3_bullish_price_action": confirmations.get("c3_bullish_price_action", False),
                "c3_bearish_price_action": confirmations.get("c3_bearish_price_action", False),
            },
            "signal_triggered": signal_triggered,
        }
        params_col.insert_one(params_doc)

        if signal_triggered and signal_payload:
            signals_col = db["nifty_derivatives_signals"]
            sig_doc = {
                "created_at_utc": now_utc,
                "timestamp_ist": (now_utc + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S IST"),
                "direction": signal_payload.get("direction"),
                "signal_title": signal_payload.get("signal_title"),
                "rating_out_of_10": signal_payload.get("rating"),
                "futures_symbol": signal_payload.get("futures_symbol"),
                "futures_close": signal_payload.get("futures_close"),
                "atm_strike": signal_payload.get("atm_strike"),
                "straddle_premium": signal_payload.get("straddle_current"),
                "auto_parameters": auto_params,
                "outcome_evaluated": False
            }
            signals_col.insert_one(sig_doc)
    except Exception as e:
        logger.debug(f"Could not persist Nifty derivatives parameters to MongoDB: {e}")


# =============================================================================
# 3. TECHNICAL INDICATORS & AUTOMATED PARAMETER CALCULATION ENGINE
# =============================================================================

def compute_futures_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes ATR(14), ADX-style directional regime strength, OBV, TSI(25, 13, 13),
    candle body-to-range ratios, and OI changes on the Nifty Futures 5m DataFrame.
    """
    out = df.copy()
    for c in ["Open", "High", "Low", "Close"]:
        out[c] = out[c].astype(float)
    out["Volume"] = out.get("Volume", pd.Series(0.0, index=out.index)).astype(float)
    out["OI"] = out.get("OI", pd.Series(0.0, index=out.index)).astype(float)

    # True Range & ATR(14)
    prev_close = out["Close"].shift(1)
    tr1 = out["High"] - out["Low"]
    tr2 = (out["High"] - prev_close).abs()
    tr3 = (out["Low"] - prev_close).abs()
    out["TR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    out["ATR_14"] = out["TR"].rolling(14, min_periods=3).mean()
    out["ATR_50"] = out["TR"].rolling(40, min_periods=5).mean()

    # ADX-style Directional Movement for regime detection
    up_move = out["High"].diff()
    down_move = -out["Low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr_safe = out["ATR_14"].replace(0, np.nan)
    plus_di = 100.0 * (pd.Series(plus_dm, index=out.index).ewm(span=14, adjust=False).mean() / atr_safe)
    minus_di = 100.0 * (pd.Series(minus_dm, index=out.index).ewm(span=14, adjust=False).mean() / atr_safe)
    dx = 100.0 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    out["ADX_14"] = dx.ewm(span=14, adjust=False).mean().fillna(20.0)

    # Candle Body & Full Range
    full_range = (out["High"] - out["Low"]).replace(0, np.nan)
    out["Body_Size"] = (out["Close"] - out["Open"]).abs()
    out["Body_Ratio"] = (out["Body_Size"] / full_range).fillna(0.0).clip(0.0, 1.0)

    # OI Change & OI Change %
    out["OI_Change"] = out["OI"].diff().fillna(0.0)
    prev_oi_safe = out["OI"].shift(1).replace(0, np.nan)
    out["OI_Change_Pct"] = ((out["OI_Change"] / prev_oi_safe) * 100.0).fillna(0.0)

    # On-Balance Volume (OBV)
    direction = np.where(out["Close"] > out["Close"].shift(1), 1.0,
                         np.where(out["Close"] < out["Close"].shift(1), -1.0, 0.0))
    out["OBV"] = (direction * out["Volume"]).cumsum()
    out["OBV_EMA20"] = out["OBV"].ewm(span=20, adjust=False).mean()

    # True Strength Index (TSI 25, 13, 13)
    pc = out["Close"].diff()
    pcs = pc.ewm(span=25, adjust=False).mean().ewm(span=13, adjust=False).mean()
    apcs = pc.abs().ewm(span=25, adjust=False).mean().ewm(span=13, adjust=False).mean()
    out["TSI"] = (100.0 * (pcs / apcs.replace(0, np.nan))).fillna(0.0)
    out["TSI_Signal"] = out["TSI"].ewm(span=13, adjust=False).mean().fillna(0.0)

    return out


def auto_determine_parameters(
    fut_df: pd.DataFrame,
    straddle_series: pd.Series,
    calibration: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    Automatically determines all 5 critical parameters without any fixed user input:
      1. OI Threshold (rolling mean + 1.0–1.5 std dev / percentile of recent OI increases,
         adapted to current volatility regime)
      2. Straddle Expansion % (derived from recent ATM straddle volatility & underlying ATR)
      3. Swing Lookback N (3–5+ based on ATR / ADX market regime detection)
      4. Body Strength % (top 30–40% of recent candle body-to-range ratios)
      5. ATM Strike (nearest 50-pt strike to current futures close)
    """
    calibration = calibration or {
        "oi_std_multiplier": 1.20,
        "straddle_exp_multiplier": 1.15,
        "body_percentile_target": 65.0,
        "historical_win_rate": 0.60,
        "sample_size": 0
    }

    lookback_window = min(40, max(20, len(fut_df) - 2))
    recent = fut_df.iloc[-lookback_window - 1:-1] if len(fut_df) > lookback_window + 1 else fut_df.iloc[:-1]

    curr_close = float(fut_df["Close"].iloc[-1])
    curr_atr = float(fut_df["ATR_14"].iloc[-1]) if not np.isnan(fut_df["ATR_14"].iloc[-1]) else curr_close * 0.0015
    base_atr = float(fut_df["ATR_50"].iloc[-1]) if not np.isnan(fut_df["ATR_50"].iloc[-1]) else curr_atr
    curr_adx = float(fut_df["ADX_14"].iloc[-1]) if not np.isnan(fut_df["ADX_14"].iloc[-1]) else 20.0

    vol_ratio_regime = curr_atr / max(1e-6, base_atr)

    # Determine Volatility & Trend Regime
    if vol_ratio_regime >= 1.18 or curr_adx >= 28.0:
        regime = "HIGH_VOL_STRONG_TREND"
        swing_lookback_n = 3
        regime_oi_factor = 1.25  # Require stronger OI surge in high volatility
    elif vol_ratio_regime <= 0.85 and curr_adx <= 18.0:
        regime = "LOW_VOL_RANGE_BOUND"
        swing_lookback_n = 5
        regime_oi_factor = 1.00
    else:
        regime = "NORMAL_REGIME"
        swing_lookback_n = 4
        regime_oi_factor = 1.10

    # 1. Dynamic OI Threshold (from rolling positive OI changes over last 20-50 bars)
    pos_oi_changes = recent["OI_Change"][recent["OI_Change"] > 0]
    pos_oi_pct = recent["OI_Change_Pct"][recent["OI_Change_Pct"] > 0]

    std_mult = float(calibration.get("oi_std_multiplier", 1.20)) * regime_oi_factor

    if len(pos_oi_changes) >= 3:
        oi_mean = float(pos_oi_changes.mean())
        oi_std = float(pos_oi_changes.std(ddof=0))
        oi_p75 = float(np.percentile(pos_oi_changes, 72))
        auto_oi_abs_threshold = max(1.0, min(oi_mean + std_mult * oi_std, oi_p75 * 1.15))

        pct_mean = float(pos_oi_pct.mean())
        pct_std = float(pos_oi_pct.std(ddof=0))
        pct_p75 = float(np.percentile(pos_oi_pct, 72))
        auto_oi_pct_threshold = max(0.01, min(pct_mean + std_mult * pct_std, pct_p75 * 1.15))
    else:
        # Fallback if historical OI series is flat/minimal
        curr_oi = float(fut_df["OI"].iloc[-1])
        auto_oi_pct_threshold = 0.15
        auto_oi_abs_threshold = max(50.0, curr_oi * 0.0015)

    # 2. Dynamic ATM Straddle Expansion % Threshold
    straddle_clean = straddle_series.dropna()
    if len(straddle_clean) >= 5:
        straddle_pct_changes = straddle_clean.pct_change() * 100.0
        recent_strad_changes = straddle_pct_changes.iloc[-lookback_window - 1:-1].dropna()
        pos_expansions = recent_strad_changes[recent_strad_changes > 0]
        if len(pos_expansions) >= 2:
            avg_exp = float(pos_expansions.mean())
            p70_exp = float(np.percentile(pos_expansions, 68))
            strad_mult = float(calibration.get("straddle_exp_multiplier", 1.15))
            auto_straddle_exp_pct = max(0.05, round(((avg_exp * strad_mult) + p70_exp) / 2.0, 4))
        else:
            # Scale from underlying ATR %
            atr_pct = (curr_atr / max(1.0, curr_close)) * 100.0
            auto_straddle_exp_pct = max(0.10, round(atr_pct * 3.5, 4))
    else:
        atr_pct = (curr_atr / max(1.0, curr_close)) * 100.0
        auto_straddle_exp_pct = max(0.10, round(atr_pct * 3.5, 4))

    # 3. Dynamic Body Strength % Threshold (top 30-40% of recent candle body-to-range ratios)
    recent_bodies = recent["Body_Ratio"].dropna()
    target_pctile = float(calibration.get("body_percentile_target", 65.0))
    if len(recent_bodies) >= 5:
        auto_body_strength_ratio = float(np.percentile(recent_bodies, target_pctile))
        auto_body_strength_ratio = float(np.clip(auto_body_strength_ratio, 0.45, 0.82))
    else:
        auto_body_strength_ratio = 0.62

    # 4. Auto ATM Strike
    atm_strike = auto_select_atm_strike(curr_close, step=50)

    return {
        "atm_strike": atm_strike,
        "volatility_regime": regime,
        "vol_ratio_regime": round(vol_ratio_regime, 3),
        "adx_14": round(curr_adx, 2),
        "atr_14": round(curr_atr, 2),
        "swing_lookback_n": int(swing_lookback_n),
        "oi_threshold_abs": round(auto_oi_abs_threshold, 2),
        "oi_threshold_pct": round(auto_oi_pct_threshold, 4),
        "straddle_expansion_threshold_pct": round(auto_straddle_exp_pct, 4),
        "body_strength_threshold_pct": round(auto_body_strength_ratio * 100.0, 2),
        "body_strength_threshold_ratio": round(auto_body_strength_ratio, 4),
        "mongodb_calibration": calibration
    }


# =============================================================================
# 4. THREE-CONFIRMATION EVALUATION & RATING ENGINE (OUT OF 10)
# =============================================================================

def calculate_signal_rating_out_of_10(
    oi_change_pct: float,
    oi_threshold_pct: float,
    straddle_exp_pct: float,
    straddle_threshold_pct: float,
    body_ratio: float,
    body_threshold_ratio: float,
    breakout_distance_atr: float,
    obv_aligned: bool,
    tsi_aligned: bool
) -> Dict[str, Any]:
    """
    Computes a clear 1.0 to 10.0 signal rating when all 3 confirmations trigger:
      - Confirmation 1 (OI Buildup excess over auto-threshold): up to 3.0 pts
      - Confirmation 2 (ATM Straddle Expansion excess over auto-threshold): up to 3.0 pts
      - Confirmation 3 (Price Action breakout & body strength): up to 2.5 pts
      - Chart Indicator Alignment (OBV + TSI momentum confirmation): up to 1.5 pts
    """
    # 1. OI Buildup score (up to 3.0 pts)
    oi_ratio = oi_change_pct / max(0.01, oi_threshold_pct)
    oi_pts = min(3.0, max(1.8, 1.8 + (oi_ratio - 1.0) * 0.8))

    # 2. Straddle Expansion score (up to 3.0 pts)
    strad_ratio = straddle_exp_pct / max(0.01, straddle_threshold_pct)
    strad_pts = min(3.0, max(1.8, 1.8 + (strad_ratio - 1.0) * 0.8))

    # 3. Price Action score (up to 2.5 pts)
    body_excess = body_ratio / max(0.1, body_threshold_ratio)
    pa_pts = min(2.5, max(1.5, 1.5 + (body_excess - 1.0) * 0.6 + min(0.5, breakout_distance_atr * 0.4)))

    # 4. Volume / OBV / TSI indicator alignment (up to 1.5 pts)
    ind_pts = (0.75 if obv_aligned else 0.25) + (0.75 if tsi_aligned else 0.25)

    total = round(min(10.0, max(1.0, oi_pts + strad_pts + pa_pts + ind_pts)), 1)
    if total >= 8.5:
        conviction = "HIGH CONVICTION 🔥"
    elif total >= 7.0:
        conviction = "STRONG SIGNAL 🚀"
    else:
        conviction = "CONFIRMED ✅"

    filled = int(round(total))
    bar = "█" * filled + "░" * (10 - filled)

    return {
        "rating": total,
        "conviction": conviction,
        "bar": bar,
        "oi_pts": round(oi_pts, 2),
        "straddle_pts": round(strad_pts, 2),
        "price_action_pts": round(pa_pts, 2),
        "indicator_pts": round(ind_pts, 2)
    }


def run_derivatives_agents_debate(
    direction: str,
    oi_change_pct: float,
    oi_threshold_pct: float,
    straddle_exp_pct: float,
    straddle_threshold_pct: float,
    body_ratio: float,
    body_threshold_ratio: float,
    breakout_distance_atr: float,
    obv_aligned: bool,
    tsi_aligned: bool,
    adx_val: float = 25.0,
    vol_surge_ratio: float = 1.5,
    volatility_regime: str = "NORMAL_REGIME",
) -> Dict[str, Any]:
    """
    Runs a 6-Agent Quantitative Multi-Agent Debate (100% Zerodha Data, $0 AI Cost)
    BEFORE dispatching a Nifty Derivatives Telegram alert to judge how good the
    alert is out of 10:
      1. Institutional Flow & OI Analyst (evaluates Futures OI buildup & 5m volume surge)
      2. Options Volatility & Straddle Analyst (evaluates ATM CE+PE expansion & regime)
      3. Price Action & Momentum Analyst (evaluates Swing Breakout ATR, Body %, OBV & TSI)
      4. Bull Researcher (argues upside/directional breakout conviction)
      5. Bear / Trap Researcher (stress-tests whipsaw, ADX chop, or momentum divergence)
      6. Chief Risk & Portfolio Judge (arbitrates Bull vs Bear debate -> final X.X / 10 rating)
    """
    is_bull = direction.upper().startswith("BULL")

    # Agent 1: Institutional Flow & OI Analyst (0-10)
    oi_multiple = abs(oi_change_pct) / max(0.01, oi_threshold_pct)
    oi_agent_score = min(10.0, max(5.0, 6.2 + (oi_multiple - 1.0) * 2.2 + min(1.5, max(0.0, vol_surge_ratio - 1.0) * 1.1)))
    oi_agent_score = round(oi_agent_score, 1)

    # Agent 2: Options Volatility & Straddle Analyst (0-10)
    strad_multiple = straddle_exp_pct / max(0.01, straddle_threshold_pct)
    strad_agent_score = min(10.0, max(5.0, 6.2 + (strad_multiple - 1.0) * 2.4))
    if volatility_regime == "LOW_VOL_SQUEEZE":
        strad_agent_score = min(10.0, strad_agent_score + 0.5)  # Squeeze breakout bonus
    strad_agent_score = round(strad_agent_score, 1)

    # Agent 3: Price Action & Momentum Analyst (0-10)
    body_multiple = body_ratio / max(0.1, body_threshold_ratio)
    pa_base = 6.0 + (body_multiple - 1.0) * 3.0 + min(1.6, max(0.0, breakout_distance_atr) * 1.2)
    if obv_aligned:
        pa_base += 0.7
    if tsi_aligned:
        pa_base += 0.7
    pa_agent_score = round(min(10.0, max(4.5, pa_base)), 1)

    # Agent 4: Directional Pro-Breakout Researcher (Bull/Bear Lead)
    pro_score = round((oi_agent_score * 0.38) + (strad_agent_score * 0.32) + (pa_agent_score * 0.30), 1)

    # Agent 5: Counter-Thesis / Trap Researcher (evaluates whipsaw risk penalty 0.0 - 2.5)
    trap_penalty = 0.0
    trap_reasons = []
    if adx_val < 18.0:
        trap_penalty += 0.6
        trap_reasons.append(f"Low ADX ({adx_val:.1f})")
    if not obv_aligned:
        trap_penalty += 0.5
        trap_reasons.append("OBV divergence")
    if not tsi_aligned:
        trap_penalty += 0.5
        trap_reasons.append("TSI lag")
    if vol_surge_ratio < 1.05:
        trap_penalty += 0.4
        trap_reasons.append(f"Modest Vol ({vol_surge_ratio:.2f}x)")
    if breakout_distance_atr > 2.2:
        trap_penalty += 0.4
        trap_reasons.append("Extended ATR")
    trap_penalty = round(min(2.5, trap_penalty), 1)

    # Agent 6: Chief Risk & Portfolio Judge (final synthesis out of 10)
    adx_bonus = 0.4 if adx_val >= 25.0 else (0.2 if adx_val >= 20.0 else 0.0)
    final_debate_rating = round(min(10.0, max(1.0, pro_score + adx_bonus - trap_penalty)), 1)

    if final_debate_rating >= 8.5:
        verdict = "STRONG CONSENSUS 🔥"
    elif final_debate_rating >= 7.5:
        verdict = "DEBATE APPROVED ✅"
    elif final_debate_rating >= 6.5:
        verdict = "MODERATE CONVICTION ⚡"
    else:
        verdict = "CAUTIOUS / SPLIT ⚠️"

    filled = int(round(final_debate_rating))
    debate_bar = "█" * filled + "░" * (10 - filled)

    risk_note = "Clean Momentum" if not trap_reasons else ", ".join(trap_reasons[:2])
    summary = (
        f"OI {oi_agent_score}/10 • Straddle {strad_agent_score}/10 • "
        f"PA/Mom {pa_agent_score}/10 | Risk: {risk_note}"
    )

    return {
        "agents_debate_rating": final_debate_rating,
        "agents_debate_verdict": verdict,
        "agents_debate_bar": debate_bar,
        "agents_debate_summary": summary,
        "oi_agent_score": oi_agent_score,
        "straddle_agent_score": strad_agent_score,
        "momentum_agent_score": pa_agent_score,
        "pro_researcher_score": pro_score,
        "trap_penalty": trap_penalty,
        "trap_reasons": trap_reasons,
        "direction": direction,
    }


def evaluate_three_confirmations(
    fut_df: pd.DataFrame,
    ce_df: pd.DataFrame,
    pe_df: pd.DataFrame,
    futures_symbol: str = "NIFTY1!",
    atm_strike: Optional[int] = None,
    expiry_str: str = ""
) -> Dict[str, Any]:
    """
    Evaluates the 3 mandatory confirmations on the latest 5-minute candle:
      1. Confirmation 1 – Futures OI Buildup (Long Buildup or Short Buildup)
      2. Confirmation 2 – ATM Straddle Premium Expansion (CE + PE Combined Premium)
      3. Confirmation 3 – Price Action (N-bar Swing High/Low breakout + Strong Body)

    Alert Rules:
      - Bullish Alert ONLY when ALL three are true:
        Long Buildup + ATM Straddle Expansion + Bullish Price Action
      - Bearish Alert ONLY when ALL three are true:
        Short Buildup + ATM Straddle Expansion + Bearish Price Action
      - Never triggers if even one confirmation is missing.
    """
    if fut_df.empty or len(fut_df) < 15:
        return {"alert_triggered": False, "reason": "Insufficient Nifty Futures candle history"}

    df_ind = compute_futures_indicators(fut_df)

    # Align ATM CE + PE combined premium series
    if not ce_df.empty and not pe_df.empty:
        ce_close = ce_df["Close"].astype(float)
        pe_close = pe_df["Close"].astype(float)
        combined_df = pd.DataFrame({"ce": ce_close, "pe": pe_close}).ffill().dropna()
        straddle_series = combined_df["ce"] + combined_df["pe"]
    else:
        straddle_series = pd.Series(dtype=float)

    if len(straddle_series) < 2:
        return {"alert_triggered": False, "reason": "Insufficient ATM Straddle (CE+PE) candle history"}

    curr_fut = df_ind.iloc[-1]
    prev_fut = df_ind.iloc[-2]

    curr_close = float(curr_fut["Close"])
    prev_close = float(prev_fut["Close"])
    curr_open = float(curr_fut["Open"])
    curr_high = float(curr_fut["High"])
    curr_low = float(curr_fut["Low"])
    curr_oi = float(curr_fut["OI"])
    prev_oi = float(prev_fut["OI"])

    # Fetch MongoDB continuous calibration & update past outcomes
    calibration = update_and_fetch_historical_refinement(curr_close)

    # Auto-determine all dynamic thresholds
    auto_params = auto_determine_parameters(df_ind, straddle_series, calibration=calibration)
    if atm_strike is not None:
        auto_params["atm_strike"] = int(atm_strike)

    # -------------------------------------------------------------------------
    # CONFIRMATION 1: FUTURES OI BUILDUP
    # -------------------------------------------------------------------------
    oi_diff = curr_oi - prev_oi
    oi_diff_pct = ((curr_oi - prev_oi) / prev_oi * 100.0) if prev_oi > 0 else 0.0
    oi_thresh_abs = auto_params["oi_threshold_abs"]
    oi_thresh_pct = auto_params["oi_threshold_pct"]

    oi_exceeds_threshold = (oi_diff >= oi_thresh_abs) or (oi_diff_pct >= oi_thresh_pct)
    c1_long_buildup = (curr_close > prev_close) and (curr_oi > prev_oi) and oi_exceeds_threshold
    c1_short_buildup = (curr_close < prev_close) and (curr_oi > prev_oi) and oi_exceeds_threshold

    # -------------------------------------------------------------------------
    # CONFIRMATION 2: ATM STRADDLE PREMIUM EXPANSION
    # -------------------------------------------------------------------------
    straddle_curr = float(straddle_series.iloc[-1])
    straddle_prev = float(straddle_series.iloc[-2])
    ce_curr = float(ce_df["Close"].iloc[-1]) if not ce_df.empty else straddle_curr * 0.5
    pe_curr = float(pe_df["Close"].iloc[-1]) if not pe_df.empty else straddle_curr * 0.5

    straddle_diff = straddle_curr - straddle_prev
    straddle_exp_pct = ((straddle_curr - straddle_prev) / straddle_prev * 100.0) if straddle_prev > 0 else 0.0
    straddle_thresh_pct = auto_params["straddle_expansion_threshold_pct"]

    c2_straddle_expansion = (straddle_curr > straddle_prev) and (straddle_exp_pct >= straddle_thresh_pct)

    # -------------------------------------------------------------------------
    # CONFIRMATION 3: PRICE ACTION (SWING LOOKBACK N + BODY STRENGTH)
    # -------------------------------------------------------------------------
    n_lookback = int(auto_params["swing_lookback_n"])
    prev_n_slice = df_ind.iloc[-(n_lookback + 1):-1]
    swing_hh_n = float(prev_n_slice["High"].max())
    swing_ll_n = float(prev_n_slice["Low"].min())

    curr_body_ratio = float(curr_fut["Body_Ratio"])
    body_thresh_ratio = float(auto_params["body_strength_threshold_ratio"])
    is_strong_body = curr_body_ratio >= body_thresh_ratio

    c3_bullish_pa = (curr_close > swing_hh_n) and (curr_close > curr_open) and is_strong_body
    c3_bearish_pa = (curr_close < swing_ll_n) and (curr_close < curr_open) and is_strong_body

    # -------------------------------------------------------------------------
    # STRICT ALERT TRIGGER CHECK (ALL THREE MUST BE TRUE)
    # -------------------------------------------------------------------------
    bullish_alert = bool(c1_long_buildup and c2_straddle_expansion and c3_bullish_pa)
    bearish_alert = bool(c1_short_buildup and c2_straddle_expansion and c3_bearish_pa)
    alert_triggered = bullish_alert or bearish_alert

    confirmations_detail = {
        "c1_long_buildup": bool(c1_long_buildup),
        "c1_short_buildup": bool(c1_short_buildup),
        "c1_oi_current": int(curr_oi),
        "c1_oi_previous": int(prev_oi),
        "c1_oi_change": int(oi_diff),
        "c1_oi_change_pct": round(oi_diff_pct, 3),
        "c2_straddle_expansion": bool(c2_straddle_expansion),
        "c2_straddle_current": round(straddle_curr, 2),
        "c2_straddle_previous": round(straddle_prev, 2),
        "c2_straddle_change_pct": round(straddle_exp_pct, 3),
        "c2_ce_ltp": round(ce_curr, 2),
        "c2_pe_ltp": round(pe_curr, 2),
        "c3_bullish_price_action": bool(c3_bullish_pa),
        "c3_bearish_price_action": bool(c3_bearish_pa),
        "c3_swing_lookback_n": n_lookback,
        "c3_swing_high_n": round(swing_hh_n, 2),
        "c3_swing_low_n": round(swing_ll_n, 2),
        "c3_body_strength_pct": round(curr_body_ratio * 100.0, 1),
    }

    signal_payload = None
    if alert_triggered:
        direction = "BULLISH" if bullish_alert else "BEARISH"
        atr_val = max(1.0, float(auto_params["atr_14"]))
        breakout_dist = (curr_close - swing_hh_n) / atr_val if bullish_alert else (swing_ll_n - curr_close) / atr_val

        obv_aligned = (
            float(curr_fut["OBV"]) > float(curr_fut["OBV_EMA20"])
            if bullish_alert else
            float(curr_fut["OBV"]) < float(curr_fut["OBV_EMA20"])
        )
        tsi_aligned = (
            float(curr_fut["TSI"]) > float(curr_fut["TSI_Signal"])
            if bullish_alert else
            float(curr_fut["TSI"]) < float(curr_fut["TSI_Signal"])
        )

        rating_info = calculate_signal_rating_out_of_10(
            oi_change_pct=abs(oi_diff_pct),
            oi_threshold_pct=oi_thresh_pct,
            straddle_exp_pct=straddle_exp_pct,
            straddle_threshold_pct=straddle_thresh_pct,
            body_ratio=curr_body_ratio,
            body_threshold_ratio=body_thresh_ratio,
            breakout_distance_atr=max(0.0, breakout_dist),
            obv_aligned=obv_aligned,
            tsi_aligned=tsi_aligned
        )

        avg_vol_20 = float(df_ind["Volume"].iloc[-21:-1].mean()) if len(df_ind) >= 21 else float(df_ind["Volume"].mean())
        curr_vol = float(curr_fut.get("Volume", avg_vol_20))
        vol_surge_ratio = curr_vol / max(1.0, avg_vol_20)

        debate_info = run_derivatives_agents_debate(
            direction=direction,
            oi_change_pct=abs(oi_diff_pct),
            oi_threshold_pct=oi_thresh_pct,
            straddle_exp_pct=straddle_exp_pct,
            straddle_threshold_pct=straddle_thresh_pct,
            body_ratio=curr_body_ratio,
            body_threshold_ratio=body_thresh_ratio,
            breakout_distance_atr=max(0.0, breakout_dist),
            obv_aligned=obv_aligned,
            tsi_aligned=tsi_aligned,
            adx_val=float(auto_params.get("adx_14", 25.0)),
            vol_surge_ratio=vol_surge_ratio,
            volatility_regime=str(auto_params.get("volatility_regime", "NORMAL_REGIME")),
        )

        signal_payload = {
            "alert_triggered": True,
            "direction": direction,
            "signal_title": f"NIFTY DERIVATIVES {direction} BREAKOUT ALERT",
            "futures_symbol": futures_symbol,
            "expiry_str": expiry_str,
            "timeframe": "5m",
            "futures_close": round(curr_close, 2),
            "futures_prev_close": round(prev_close, 2),
            "atm_strike": auto_params["atm_strike"],
            "straddle_current": round(straddle_curr, 2),
            "straddle_prev": round(straddle_prev, 2),
            "straddle_exp_pct": round(straddle_exp_pct, 2),
            "ce_ltp": round(ce_curr, 2),
            "pe_ltp": round(pe_curr, 2),
            "swing_trigger_level": round(swing_hh_n if bullish_alert else swing_ll_n, 2),
            "stop_level": round(curr_low if bullish_alert else curr_high, 2),
            "rating": rating_info["rating"],
            "conviction": rating_info["conviction"],
            "rating_bar": rating_info["bar"],
            "rating_breakdown": rating_info,
            "agents_debate_rating": debate_info["agents_debate_rating"],
            "agents_debate_verdict": debate_info["agents_debate_verdict"],
            "agents_debate_bar": debate_info["agents_debate_bar"],
            "agents_debate_summary": debate_info["agents_debate_summary"],
            "agents_debate": debate_info,
            "auto_parameters": auto_params,
            "confirmations": confirmations_detail,
            "bar_time": str(df_ind.index[-1]),
            "df": df_ind
        }

    # Persist auto-parameters and signal to MongoDB for continuous refinement
    persist_parameters_and_signal_to_mongodb(
        auto_params=auto_params,
        confirmations=confirmations_detail,
        signal_triggered=alert_triggered,
        signal_payload=signal_payload
    )

    if signal_payload:
        return signal_payload

    return {
        "alert_triggered": False,
        "reason": "Not all 3 confirmations met simultaneously",
        "futures_symbol": futures_symbol,
        "futures_close": round(curr_close, 2),
        "auto_parameters": auto_params,
        "confirmations": confirmations_detail,
        "df": df_ind
    }


# =============================================================================
# 5. TELEGRAM ALERT FORMATTER & CHART DISPATCHER
# =============================================================================

def format_three_confirmation_telegram_alert(signal_data: Dict[str, Any]) -> str:
    """
    Formats the Telegram alert message when all 3 confirmations trigger:
      - Clear Bullish / Bearish signal with rating out of 10
      - Breakdown of Confirmation 1 (Futures OI Buildup), Confirmation 2 (ATM Straddle
        Premium Expansion), and Confirmation 3 (Price Action Swing Breakout & Body Strength)
      - Accompanied by the 5m Candlestick + Volume + OBV + TSI chart snapshot.
    """
    direction = signal_data.get("direction", "BULLISH").upper()
    is_bull = direction == "BULLISH"
    header_emoji = "🟢" if is_bull else "🔴"
    dir_emoji = "🐂" if is_bull else "🐻"
    buildup_label = "Long Buildup (Close ↑ & OI ↑)" if is_bull else "Short Buildup (Close ↓ & OI ↑)"

    rating = signal_data.get("rating", 8.5)
    conviction = signal_data.get("conviction", "HIGH CONVICTION 🔥")
    r_bar = signal_data.get("rating_bar", "████████░░")

    fut_sym = signal_data.get("futures_symbol", "NIFTY1!")
    fut_close = signal_data.get("futures_close", 0.0)
    atm_strike = signal_data.get("atm_strike", 24850)
    exp_str = signal_data.get("expiry_str", "")
    exp_Part = f" ({exp_str})" if exp_str else ""

    conf = signal_data.get("confirmations", {})
    params = signal_data.get("auto_parameters", {})

    oi_chg = conf.get("c1_oi_change", 0)
    oi_chg_pct = conf.get("c1_oi_change_pct", 0.0)
    oi_thresh_pct = params.get("oi_threshold_pct", 0.15)

    strad_curr = conf.get("c2_straddle_current", 0.0)
    strad_prev = conf.get("c2_straddle_previous", 0.0)
    strad_pct = conf.get("c2_straddle_change_pct", 0.0)
    strad_thresh = params.get("straddle_expansion_threshold_pct", 0.20)
    ce_ltp = conf.get("c2_ce_ltp", 0.0)
    pe_ltp = conf.get("c2_pe_ltp", 0.0)

    n_bars = conf.get("c3_swing_lookback_n", 4)
    swing_lvl = signal_data.get("swing_trigger_level", 0.0)
    body_pct = conf.get("c3_body_strength_pct", 70.0)
    body_thresh = params.get("body_strength_threshold_pct", 65.0)
    regime = params.get("volatility_regime", "NORMAL_REGIME")

    if "agents_debate_rating" not in signal_data:
        fallback_debate = run_derivatives_agents_debate(
            direction=direction,
            oi_change_pct=abs(float(oi_chg_pct)),
            oi_threshold_pct=float(oi_thresh_pct or 0.15),
            straddle_exp_pct=float(strad_pct),
            straddle_threshold_pct=float(strad_thresh or 0.20),
            body_ratio=float(body_pct) / 100.0,
            body_threshold_ratio=float(body_thresh or 65.0) / 100.0,
            breakout_distance_atr=0.8,
            obv_aligned=True,
            tsi_aligned=True,
            adx_val=float(params.get("adx_14", 25.0)),
            vol_surge_ratio=1.5,
            volatility_regime=regime,
        )
        signal_data["agents_debate_rating"] = fallback_debate["agents_debate_rating"]
        signal_data["agents_debate_verdict"] = fallback_debate["agents_debate_verdict"]
        signal_data["agents_debate_summary"] = fallback_debate["agents_debate_summary"]
        signal_data["agents_debate"] = fallback_debate

    debate_rating = signal_data.get("agents_debate_rating", rating)
    debate_verdict = signal_data.get("agents_debate_verdict", "STRONG CONSENSUS 🔥")
    debate_summary = signal_data.get("agents_debate_summary", "")

    now_time = datetime.now().strftime("%I:%M %p")

    msg = (
        f"{header_emoji} <b>NIFTY DERIVATIVES: {direction} SIGNAL ({rating}/10) {dir_emoji}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Signal Rating:</b> <b>{rating} / 10</b> ({conviction})\n"
        f"🤖 <b>Agents Debate Rating:</b> <b>{debate_rating} / 10</b> ({debate_verdict})\n"
        f"🗣️ <i>{debate_summary}</i>\n"
        f"📊 <code>[{r_bar}]</code>\n"
        f"📈 <b>Nifty Futures ({fut_sym})</b>: <b>₹{fut_close:,.2f}</b>\n"
        f"🎯 <b>Auto ATM Strike</b>: <b>{atm_strike}{exp_Part}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>1. Futures OI Buildup ({buildup_label})</b>\n"
        f"• OI Change: <b>+{oi_chg:,} ({oi_chg_pct:+.2f}%)</b> | Auto Min: +{oi_thresh_pct:.2f}%\n\n"
        f"✅ <b>2. ATM Straddle Premium Expansion ({atm_strike} CE+PE)</b>\n"
        f"• Combined Premium: <b>₹{strad_prev:,.2f} → ₹{strad_curr:,.2f} ({strad_pct:+.2f}%)</b>\n"
        f"• Legs: CE ₹{ce_ltp:,.2f} + PE ₹{pe_ltp:,.2f} | Auto Min: +{strad_thresh:.2f}%\n\n"
        f"✅ <b>3. {direction.title()} Price Action Breakout</b>\n"
        f"• {n_bars}-Bar Swing {'High' if is_bull else 'Low'} Broken: <b>₹{swing_lvl:,.2f}</b>\n"
        f"• Candle Body Strength: <b>{body_pct:.1f}%</b> (Auto Min: {body_thresh:.1f}% | {regime})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📸 <i>5m Chart Attached: Candlestick + Volume + OBV + TSI</i>\n"
        f"⏰ {now_time} | ⚡ <i>Zerodha 3-Confirmation Engine</i>"
    )
    return msg


def dispatch_three_confirmation_telegram_alert(
    signal_data: Dict[str, Any],
    kite=None,
    force_send: bool = False
) -> Dict[str, Any]:
    """
    Renders the 5m Candlestick + Volume + OBV + TSI chart snapshot and sends the
    Telegram photo alert when all 3 confirmations are met.
    """
    if not signal_data.get("alert_triggered") and not force_send:
        return {
            "status": "skipped",
            "sent": False,
            "reason": signal_data.get("reason", "Confirmations missing")
        }

    tg_text = format_three_confirmation_telegram_alert(signal_data)
    fut_sym = signal_data.get("futures_symbol", "NIFTY 50")
    df_chart = signal_data.get("df")
    direction = signal_data.get("direction", "BULLISH")
    rating = signal_data.get("rating", 8.5)
    debate_rating = signal_data.get("agents_debate_rating", rating)

    chart_buffer = None
    try:
        from scripts.chart_generator import generate_5min_chart_buffer
        chart_buffer = generate_5min_chart_buffer(
            symbol=fut_sym,
            df=df_chart,
            trigger_price=signal_data.get("swing_trigger_level"),
            kite=kite,
            title_suffix=f" • {direction} {rating}/10 • Agents Debate {debate_rating}/10"
        )
    except Exception as chart_err:
        logger.warning(f"Could not render 5m chart for {fut_sym}: {chart_err}")

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return {
            "status": "mock_generated",
            "sent": False,
            "message": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in .env. Alert formatted successfully.",
            "sample_telegram_text": tg_text,
            "signal_data": {k: v for k, v in signal_data.items() if k != "df"},
            "has_chart": chart_buffer is not None
        }

    try:
        from scripts.chart_generator import send_telegram_chart_alert
        dispatch_res = send_telegram_chart_alert(
            symbol=fut_sym,
            message_text=tg_text,
            chart_buffer=chart_buffer,
            trigger_price=signal_data.get("swing_trigger_level"),
            parse_mode="HTML",
            kite=kite
        )
        dispatch_res["sample_telegram_text"] = tg_text
        dispatch_res["signal_data"] = {k: v for k, v in signal_data.items() if k != "df"}
        return dispatch_res
    except Exception as e:
        logger.error(f"[TELEGRAM] Failed to dispatch 3-confirmation alert: {e}")
        return {
            "status": "error",
            "sent": False,
            "error": str(e),
            "sample_telegram_text": tg_text,
            "signal_data": {k: v for k, v in signal_data.items() if k != "df"}
        }


# =============================================================================
# 6. LIVE ZERODHA SCANNER & MOCK BUILDER FOR TESTING
# =============================================================================

def build_mock_three_confirmation_data(direction: str = "BULLISH") -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Constructs realistic 5-minute Nifty Futures (with OI) and ATM CE/PE DataFrames
    that satisfy all 3 confirmations for testing or previewing alerts.
    """
    is_bull = direction.upper().startswith("BULL")
    dates = pd.date_range(end=datetime.now(), periods=45, freq="5min")
    np.random.seed(42 if is_bull else 99)

    base_price = 24850.0
    noise = np.random.randn(45) * 8.0
    close = base_price + np.cumsum(noise)
    # Keep recent 10 bars before trigger in a controlled range
    close[-10:-1] = 24850.0 + np.sin(np.linspace(0, np.pi, 9)) * 18.0

    high = close + np.random.uniform(4.0, 12.0, 45)
    low = close - np.random.uniform(4.0, 12.0, 45)
    open_p = close - np.random.uniform(-6.0, 6.0, 45)
    vol = np.random.randint(80000, 160000, 45).astype(float)
    oi = (12500000 + np.cumsum(np.random.randint(-15000, 25000, 45))).astype(float)

    # Trigger bar (-1) satisfies Confirmation 1 (OI buildup) & Confirmation 3 (Price Action)
    prev_hh = float(np.max(high[-8:-1]))
    prev_ll = float(np.min(low[-8:-1]))

    if is_bull:
        open_p[-1] = prev_hh - 4.0
        close[-1] = prev_hh + 28.0
        high[-1] = close[-1] + 2.5
        low[-1] = open_p[-1] - 2.0
    else:
        open_p[-1] = prev_ll + 4.0
        close[-1] = prev_ll - 28.0
        high[-1] = open_p[-1] + 2.0
        low[-1] = close[-1] - 2.5

    vol[-1] = float(np.mean(vol[-20:-1]) * 2.3)
    oi[-1] = oi[-2] + 145000.0  # Strong OI buildup on current bar

    fut_df = pd.DataFrame({
        "Open": open_p,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": vol,
        "OI": oi
    }, index=dates)

    # ATM CE & PE premiums expanding on the trigger bar (Confirmation 2)
    ce_close = 135.0 + np.cumsum(np.random.randn(45) * 1.2)
    pe_close = 130.0 + np.cumsum(np.random.randn(45) * 1.2)
    if is_bull:
        ce_close[-1] = ce_close[-2] + 18.5
        pe_close[-1] = pe_close[-2] - 6.0
    else:
        pe_close[-1] = pe_close[-2] + 19.0
        ce_close[-1] = ce_close[-2] - 6.5

    ce_df = pd.DataFrame({"Close": ce_close}, index=dates)
    pe_df = pd.DataFrame({"Close": pe_close}, index=dates)
    return fut_df, ce_df, pe_df


def check_and_trigger_spot_index_breakout(kite=None) -> Dict[str, Any]:
    """
    Live 5-minute scanner executed by the server background loop:
      1. Resolves active near-month Nifty Futures from Zerodha NFO.
      2. Fetches 5m Futures candles with Open Interest (OI).
      3. Auto-selects the nearest ATM strike and fetches 5m candles for ATM CE + ATM PE.
      4. Evaluates Confirmation 1 (Futures OI Buildup), Confirmation 2 (ATM Straddle
         Premium Expansion), and Confirmation 3 (Price Action Swing Breakout + Body Strength)
         using fully automated, MongoDB-refined thresholds.
      5. Dispatches a Telegram alert with 1-10 rating + Candlestick/Volume/OBV/TSI chart
         ONLY when ALL three confirmations are simultaneously true.
    """
    global _ALERT_DEDUP_STATE
    kite = kite or get_kite_client()
    if not kite:
        return {"alert_sent": False, "count": 0, "reason": "Zerodha Kite client not connected"}

    fut_info = resolve_nifty_near_month_future(kite)
    if not fut_info:
        return {"alert_sent": False, "count": 0, "reason": "Could not resolve near-month Nifty Futures contract"}

    fut_df = fetch_zerodha_5m_candles_with_oi(
        instrument_token=fut_info["instrument_token"],
        days=5,
        kite=kite,
        tradingsymbol=fut_info["tradingsymbol"]
    )
    if fut_df.empty or len(fut_df) < 15:
        return {"alert_sent": False, "count": 0, "reason": "Insufficient Nifty Futures 5m candles from Zerodha"}

    underlying_close = float(fut_df["Close"].iloc[-1])
    straddle_info = resolve_atm_straddle_contracts(underlying_close, kite=kite)
    if not straddle_info:
        return {"alert_sent": False, "count": 0, "reason": "Could not resolve ATM CE/PE straddle contracts"}

    ce_df = fetch_zerodha_5m_candles_with_oi(
        instrument_token=straddle_info["ce_token"],
        days=5,
        kite=kite,
        tradingsymbol=straddle_info["ce_symbol"]
    )
    pe_df = fetch_zerodha_5m_candles_with_oi(
        instrument_token=straddle_info["pe_token"],
        days=5,
        kite=kite,
        tradingsymbol=straddle_info["pe_symbol"]
    )

    eval_res = evaluate_three_confirmations(
        fut_df=fut_df,
        ce_df=ce_df,
        pe_df=pe_df,
        futures_symbol=fut_info["tradingsymbol"],
        atm_strike=straddle_info["atm_strike"],
        expiry_str=straddle_info["expiry"]
    )

    if not eval_res.get("alert_triggered"):
        return {
            "alert_sent": False,
            "count": 0,
            "reason": eval_res.get("reason", "Confirmations not met"),
            "evaluation": {k: v for k, v in eval_res.items() if k != "df"}
        }

    bar_time = eval_res.get("bar_time")
    direction = eval_res.get("direction")
    if (
        _ALERT_DEDUP_STATE.get("last_alert_bar_time") == bar_time
        and _ALERT_DEDUP_STATE.get("last_alert_direction") == direction
    ):
        return {
            "alert_sent": False,
            "count": 0,
            "reason": f"Alert already sent for bar {bar_time} ({direction})"
        }

    dispatch_res = dispatch_three_confirmation_telegram_alert(eval_res, kite=kite, force_send=True)
    if dispatch_res.get("sent") or dispatch_res.get("status") == "mock_generated":
        _ALERT_DEDUP_STATE["last_alert_bar_time"] = bar_time
        _ALERT_DEDUP_STATE["last_alert_direction"] = direction
        _ALERT_DEDUP_STATE["last_alert_ts"] = time.time()

    return {
        "alert_sent": bool(dispatch_res.get("sent")),
        "count": 1 if dispatch_res.get("sent") else 0,
        "alerts": [dispatch_res],
        "evaluation": {k: v for k, v in eval_res.items() if k != "df"}
    }


def send_nifty_breakout_telegram_alert(
    breakout_type: str = "BULLISH",
    spot_price: Optional[float] = None,
    force_send: bool = False,
    use_mock: bool = False,
    kite=None,
    **kwargs
) -> Dict[str, Any]:
    """
    Evaluates live Zerodha Nifty Futures + ATM Straddle data if connected (or constructs
    a 3-confirmation test dataset when `use_mock=True` or `force_send=True` is requested for testing)
    and dispatches the 3-confirmation Telegram alert with 5m Candlestick + Volume + OBV + TSI chart.
    """
    kite = kite or get_kite_client()
    if kite and not force_send and not use_mock:
        live_res = check_and_trigger_spot_index_breakout(kite=kite)
        if live_res.get("alerts"):
            return live_res["alerts"][0]
        if live_res.get("evaluation"):
            return live_res

    direction = "BULLISH" if breakout_type.upper().startswith("BULL") else "BEARISH"
    fut_df, ce_df, pe_df = build_mock_three_confirmation_data(direction=direction)
    atm = auto_select_atm_strike(spot_price or float(fut_df["Close"].iloc[-1]), step=50)
    eval_res = evaluate_three_confirmations(
        fut_df=fut_df,
        ce_df=ce_df,
        pe_df=pe_df,
        futures_symbol="NIFTY1!",
        atm_strike=atm,
        expiry_str=date.today().strftime("%d-%b-%Y")
    )
    if force_send:
        return dispatch_three_confirmation_telegram_alert(eval_res, kite=kite, force_send=True)
    else:
        tg_text = format_three_confirmation_telegram_alert(eval_res) if eval_res.get("alert_triggered") else None
        return {
            "status": "preview_generated" if eval_res.get("alert_triggered") else "not_triggered",
            "sent": False,
            "sample_telegram_text": tg_text,
            "signal_data": {k: v for k, v in eval_res.items() if k != "df"}
        }


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Nifty Derivatives 3-Confirmation Automated Alert Engine")
    parser.add_argument("--direction", type=str, default="BULLISH", choices=["BULLISH", "BEARISH"], help="Signal direction to test")
    parser.add_argument("--live", action="store_true", help="Run live scan against Zerodha API")
    parser.add_argument("--force-send", action="store_true", help="Dispatch alert to Telegram")
    args = parser.parse_args()

    if args.live:
        print("[*] Running live Zerodha 3-Confirmation Nifty Derivatives scan...")
        out = check_and_trigger_spot_index_breakout()
        print(out)
    else:
        print(f"[*] Testing 3-Confirmation Nifty Derivatives Alert ({args.direction})...")
        res = send_nifty_breakout_telegram_alert(
            breakout_type=args.direction,
            force_send=args.force_send,
            use_mock=True
        )
        print("\n" + "=" * 65)
        print("TELEGRAM ALERT MESSAGE PREVIEW:")
        print("=" * 65)
        print(res.get("sample_telegram_text"))
        print("=" * 65)
        print(f"Sent Status: {res.get('sent')} | Status: {res.get('status')}")
