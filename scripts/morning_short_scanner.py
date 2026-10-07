"""
===============================================================================
MORNING SHORT & FADE SCANNER ENGINE (9:15 AM - 10:15 AM HIGH VOLATILITY)
===============================================================================
Scans watchlist stocks for high-probability morning short/fade opportunities
based on:
1. Upper Wick Rejection & Low Range Close (< 35% of day's range)
2. Morning Gap-Up Exhaustion & Red Candle Reversal (Close < Open)
3. Overhead Resistance Rejection (Trading below 50d/200d SMA or 52w High lag)
4. Heavy Volume Distribution (Volume >= 1.2x 20d SMA on red/rejection bar)
5. Risk/Reward & Stop Loss (Stop Loss placed 0.5% above Intraday High)
===============================================================================
"""

import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from tradingagents.dataflows.symbol_utils import normalize_symbol
from data_manager import DataManager

load_dotenv(dotenv_path=project_root / ".env")
logger = logging.getLogger(__name__)


def fetch_historical_daily_data(symbol: str, period: str = "1y") -> pd.DataFrame:
    """Fetches daily OHLCV historical data for a given ticker exclusively via Zerodha API."""
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("-EQ", "")

    try:
        from tradingagents.dataflows.zerodha import get_zerodha_stock_df
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=365)
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")

        df_z = get_zerodha_stock_df(clean_sym, start_str, end_str, interval="day")
        if df_z is not None and not df_z.empty:
            df_z = df_z.rename(columns={
                "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"
            })
            if {"open", "high", "low", "close", "volume"}.issubset(df_z.columns):
                res_df = df_z[["open", "high", "low", "close", "volume"]].dropna()
                if len(res_df) >= 30:
                    return res_df
    except Exception as e:
        logger.error(f"Zerodha data fetch for {clean_sym} failed: {e}")

    return pd.DataFrame()


def analyze_morning_short_candidate(symbol: str, df: pd.DataFrame = None) -> dict:
    """
    Analyzes stock for Morning Short & Reversal Probability (0 - 100 Score).
    """
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("-EQ", "")
    
    if df is None or df.empty or len(df) < 30:
        df = fetch_historical_daily_data(clean_sym, period="1y")

    if df is None or df.empty or len(df) < 30:
        return {
            "symbol": clean_sym,
            "short_probability_score": 0.0,
            "is_short_candidate": False,
            "reason": "Insufficient OHLCV data"
        }

    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    opens = df["open"].values
    volumes = df["volume"].values
    n = len(df)

    curr_close = float(closes[-1])
    curr_open = float(opens[-1])
    curr_high = float(highs[-1])
    curr_low = float(lows[-1])
    curr_vol = float(volumes[-1])
    prev_close = float(closes[-2]) if n >= 2 else curr_close

    # 1. Upper Wick Rejection & Close Power Calculation
    day_range = curr_high - curr_low
    if day_range > 0:
        close_position_pct = round(((curr_close - curr_low) / day_range) * 100.0, 1)
        upper_wick_pct = round(((curr_high - max(curr_open, curr_close)) / day_range) * 100.0, 1)
    else:
        close_position_pct = 50.0
        upper_wick_pct = 0.0

    # 2. Gap-Up Exhaustion & Reversal Detection
    gap_pct = round(((curr_open - prev_close) / prev_close) * 100.0, 2)
    is_red_candle = (curr_close < curr_open)
    price_change_pct = round(((curr_close - prev_close) / prev_close) * 100.0, 2)

    # 3. Moving Average Overhead Resistance Filters
    sma50 = float(pd.Series(closes).rolling(50).mean().iloc[-1]) if n >= 50 else float(np.mean(closes))
    sma200 = float(pd.Series(closes).rolling(200).mean().iloc[-1]) if n >= 200 else sma50
    below_sma50 = (curr_close < sma50)
    below_sma200 = (curr_close < sma200)

    # 52-week High Distance
    lookback_52w = min(252, n)
    high_52w = float(np.max(highs[-lookback_52w:]))
    pct_from_52w_high = round((curr_close / high_52w) * 100.0, 1) if high_52w > 0 else 100.0

    # 4. Volume Distribution & Liquidity Guardrail
    vol_sma20 = float(pd.Series(volumes).rolling(20).mean().iloc[-1]) if n >= 20 else float(np.mean(volumes))
    vol_ratio = round(curr_vol / vol_sma20, 2) if vol_sma20 > 0 else 1.0
    avg_turnover_cr = round((vol_sma20 * curr_close) / 10000000.0, 2)
    has_liquidity = (avg_turnover_cr >= 1.0) or (curr_close >= 50.0)

    # =========================================================================
    # SHORT PROBABILITY SCORE CALCULATION (0 - 100 Points)
    # =========================================================================
    score = 0.0

    # Factor 1: Upper Wick Rejection / Lower Range Close (Max 35 pts)
    if close_position_pct <= 20.0:
        score += 35.0
    elif close_position_pct <= 35.0:
        score += 25.0
    elif close_position_pct <= 50.0:
        score += 15.0

    # Extra points for severe upper wick rejection (intraday high rejection)
    if upper_wick_pct >= 40.0:
        score += 10.0

    # Factor 2: Gap-Up Exhaustion & Red Reversal (Max 25 pts)
    if gap_pct > 0.5 and is_red_candle:
        score += 25.0  # Classic "Gap & Crap" Short Pattern
    elif is_red_candle:
        score += 15.0

    # Factor 3: Overhead Trend Resistance (Max 20 pts)
    if below_sma50 and below_sma200:
        score += 20.0
    elif below_sma50 or below_sma200:
        score += 10.0

    # Factor 4: Volume Distribution Surge (Max 10 pts)
    if is_red_candle and vol_ratio >= 1.5:
        score += 10.0
    elif is_red_candle and vol_ratio >= 1.2:
        score += 5.0

    # Factor 5: Counter-trend Lag (Max 10 pts)
    if pct_from_52w_high < 80.0:
        score += 10.0
    elif pct_from_52w_high < 90.0:
        score += 5.0

    score = min(100.0, round(score, 1))
    is_short_candidate = (score >= 50.0) and has_liquidity

    # Risk Management Levels for Short Trade
    suggested_entry = round(curr_close, 2)
    stop_loss = round(curr_high * 1.005, 2)  # Stop loss 0.5% above Intraday High
    risk_per_share = round(stop_loss - suggested_entry, 2)
    risk_pct = round((risk_per_share / suggested_entry) * 100.0, 2) if suggested_entry > 0 else 0.0
    target_price = round(curr_close - (risk_per_share * 2.0), 2)  # 2:1 Reward to Risk

    # Formulate clear analytical reasoning - ONLY keep Heavy Upper Wick Rejection
    reason_str = f"Heavy Upper Wick Rejection (Closed at {close_position_pct}% of day's range)"

    return {
        "symbol": clean_sym,
        "short_probability_score": score,
        "is_short_candidate": is_short_candidate,
        "close_price": curr_close,
        "open_price": curr_open,
        "high_price": curr_high,
        "low_price": curr_low,
        "gap_pct": gap_pct,
        "price_change_pct": price_change_pct,
        "upper_wick_pct": upper_wick_pct,
        "close_position_pct": close_position_pct,
        "volume_surge_ratio": vol_ratio,
        "avg_turnover_cr": avg_turnover_cr,
        "suggested_entry": suggested_entry,
        "stop_loss": stop_loss,
        "target_price": target_price,
        "risk_pct": risk_pct,
        "sma50": round(sma50, 2),
        "sma200": round(sma200, 2),
        "pct_from_52w_high": pct_from_52w_high,
        "reason": reason_str
    }


def get_all_watchlist_symbols() -> list:
    """Retrieves unique stock symbols from all database watchlists."""
    symbols = set()
    try:
        dm = DataManager()
        for tf in ["monthly", "weekly", "daily", "manual", "darvas"]:
            records = dm.get_stock_ratings(tf)
            for r in records:
                sym = r.get("symbol")
                if sym:
                    symbols.add(sym.strip().upper())
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


def scan_and_rank_short_candidates() -> list:
    """
    Scans all watchlist stocks, scores their short probability,
    and returns them ordered in DESCENDING order (highest short probability at top).
    """
    symbols = get_all_watchlist_symbols()
    logger.info(f"🔍 Scanning {len(symbols)} stocks for Morning Short & Reversal Probability...")

    results = []
    for s in symbols:
        try:
            res = analyze_morning_short_candidate(s)
            results.append(res)
        except Exception as e:
            logger.error(f"Error scanning {s} for short candidate: {e}")

    # Sort descending by short_probability_score
    sorted_results = sorted(results, key=lambda x: x.get("short_probability_score", 0.0), reverse=True)

    # Save to MongoDB 'short_candidates' collection
    try:
        dm = DataManager()
        col = dm.db["short_candidates"]
        col.delete_many({})  # Refresh collection
        if sorted_results:
            docs_to_save = []
            for r in sorted_results:
                if r.get("is_short_candidate") or r.get("short_probability_score") >= 40.0:
                    doc = dict(r)
                    doc["updated_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
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

    ranked_candidates = scan_and_rank_short_candidates()
    
    print("\n" + "=" * 90)
    print(" 🚨 HIGH-PROBABILITY MORNING SHORT & REVERSAL CANDIDATES (RANKED DESCENDING)")
    print("=" * 90)
    print(f"{'RANK':<5} {'SYMBOL':<12} {'SHORT SCORE':<12} {'CLOSE':<10} {'STOP LOSS':<10} {'TARGET':<10} {'REASON / PATTERN':<30}")
    print("-" * 90)

    for i, c in enumerate(ranked_candidates[:15], 1):
        sym = c.get("symbol")
        score = f"{c.get('short_probability_score'):.1f}/100"
        close_p = f"₹{c.get('close_price'):.2f}"
        sl = f"₹{c.get('stop_loss'):.2f}"
        tgt = f"₹{c.get('target_price'):.2f}"
        reason = c.get("reason")[:40]

        print(f"{i:<5} {sym:<12} {score:<12} {close_p:<10} {sl:<10} {tgt:<10} {reason:<30}")

    print("=" * 90 + "\n")
