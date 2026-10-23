"""
===============================================================================
EVENING PROFESSIONAL BUYING & BTST ACCUMULATION SCANNER (2:30 PM - 3:30 PM)
===============================================================================
Scans watchlist stocks for high-probability Evening Professional Buying
and BTST Accumulation opportunities based on:
1. Day-End Close Power (Close Position >= 75% of day's range, minimal upper wick)
2. Late-Day Volume Expansion (Volume >= 1.2x 20d SMA with strong green close)
3. Positive Intraday Momentum (+1.0% to +5.0% gain with Close > Open)
4. Trend Alignment (Trading above 20d/50d moving averages)
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


def analyze_evening_pro_candidate(symbol: str, df: pd.DataFrame = None) -> dict:
    """
    Analyzes stock for Professional Evening Accumulation & BTST Buying Score (0 - 100).
    """
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("-EQ", "")
    
    if df is None or df.empty or len(df) < 30:
        df = fetch_historical_daily_data(clean_sym, period="1y")

    if df is None or df.empty or len(df) < 30:
        return {
            "symbol": clean_sym,
            "pro_buying_score": 0.0,
            "is_pro_buying": False,
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

    # 1. Day-End Close Position Power (% from low to high)
    day_range = curr_high - curr_low
    if day_range > 0:
        close_position_pct = round(((curr_close - curr_low) / day_range) * 100.0, 1)
        lower_wick_pct = round(((min(curr_open, curr_close) - curr_low) / day_range) * 100.0, 1)
    else:
        close_position_pct = 50.0
        lower_wick_pct = 0.0

    # 2. Intraday Momentum & Candle Type
    is_green_candle = (curr_close >= curr_open)
    price_change_pct = round(((curr_close - prev_close) / prev_close) * 100.0, 2)

    # 3. Moving Averages & Trend Alignment
    sma20 = float(pd.Series(closes).rolling(20).mean().iloc[-1]) if n >= 20 else float(np.mean(closes))
    sma50 = float(pd.Series(closes).rolling(50).mean().iloc[-1]) if n >= 50 else sma20
    above_sma20 = (curr_close >= sma20)
    above_sma50 = (curr_close >= sma50)

    # 4. Volume Surge & Liquidity Guardrail
    vol_sma20 = float(pd.Series(volumes).rolling(20).mean().iloc[-1]) if n >= 20 else float(np.mean(volumes))
    vol_ratio = round(curr_vol / vol_sma20, 2) if vol_sma20 > 0 else 1.0

    # =========================================================================
    # ACCUMULATION SCORE CALCULATION (0 - 100 Points)
    # =========================================================================
    score = 0.0

    # Factor 1: Day-End Closing Power (Max 40 pts)
    if close_position_pct >= 90.0:
        score += 40.0
    elif close_position_pct >= 75.0:
        score += 30.0
    elif close_position_pct >= 60.0:
        score += 15.0

    # Factor 2: Late-Day Volume Expansion (Max 30 pts)
    if is_green_candle and vol_ratio >= 2.0:
        score += 30.0
    elif is_green_candle and vol_ratio >= 1.5:
        score += 20.0
    elif is_green_candle and vol_ratio >= 1.2:
        score += 10.0

    # Factor 3: Intraday Momentum Gain (Max 20 pts)
    if price_change_pct >= 3.0:
        score += 20.0
    elif price_change_pct >= 1.5:
        score += 15.0
    elif price_change_pct > 0.0:
        score += 10.0

    # Factor 4: Trend Alignment (Max 10 pts)
    if above_sma20 and above_sma50:
        score += 10.0
    elif above_sma20:
        score += 5.0

    score = min(100.0, round(score, 1))
    is_pro_buying = (score >= 50.0)

    # Risk Management Levels for Swing / BTST Buy
    suggested_entry = round(curr_close, 2)
    stop_loss = round(curr_low * 0.995, 2)  # Stop loss 0.5% below Intraday Low
    target_price = round(curr_close * 1.03, 2)  # 3% BTST Target

    reason_str = f"Heavy Professional Buying (Closed at {close_position_pct}% of day's range)"

    return {
        "symbol": clean_sym,
        "pro_buying_score": score,
        "is_pro_buying": is_pro_buying,
        "close_price": curr_close,
        "open_price": curr_open,
        "high_price": curr_high,
        "low_price": curr_low,
        "price_change_pct": price_change_pct,
        "close_position_pct": close_position_pct,
        "volume_surge_ratio": vol_ratio,
        "suggested_entry": suggested_entry,
        "stop_loss": stop_loss,
        "target_price": target_price,
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2),
        "reason": reason_str
    }


def get_all_watchlist_symbols() -> list:
    """Retrieves all tracked stocks from MongoDB user tables (monthly, weekly, daily, manual, darvas)."""
    symbols = set()
    try:
        dm = DataManager()
        for tf in ["monthly", "weekly", "daily", "manual", "darvas"]:
            records = dm.get_stock_ratings(tf)
            for r in records:
                s = r.get("symbol") or r.get("ticker")
                if s:
                    symbols.add(normalize_symbol(s))
    except Exception as e:
        logger.warning(f"Could not load watchlist symbols from DB: {e}")

    return sorted(list(symbols))


def scan_and_rank_evening_pro_candidates() -> list:
    """Scans all watchlist stocks and ranks them by Professional Buying Accumulation Score."""
    symbols = get_all_watchlist_symbols()
    logger.info(f"🔍 Scanning {len(symbols)} stocks for Evening Professional Buying & BTST Accumulation...")

    results = []
    for s in symbols:
        try:
            res = analyze_evening_pro_candidate(s)
            results.append(res)
        except Exception as e:
            logger.error(f"Error scanning {s} for evening pro buying candidate: {e}")

    # Sort descending by pro_buying_score
    sorted_results = sorted(results, key=lambda x: x.get("pro_buying_score", 0.0), reverse=True)

    # Save to MongoDB 'evening_pro_candidates' collection
    try:
        dm = DataManager()
        col = dm.db["evening_pro_candidates"]
        col.delete_many({})  # Refresh collection
        if sorted_results:
            docs_to_save = []
            for r in sorted_results:
                if r.get("is_pro_buying") or r.get("pro_buying_score") >= 40.0:
                    doc = dict(r)
                    doc["updated_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
                    docs_to_save.append(doc)
            if docs_to_save:
                col.insert_many(docs_to_save)
                logger.info(f"✅ Saved {len(docs_to_save)} evening pro buying candidates to MongoDB 'evening_pro_candidates'.")
    except Exception as e:
        logger.warning(f"Could not save evening pro candidates to MongoDB: {e}")

    return sorted_results


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ranked_candidates = scan_and_rank_evening_pro_candidates()
    
    print("\n" + "=" * 90)
    print(" 🚀 EVENING PROFESSIONAL BUYING & BTST ACCUMULATION CANDIDATES (RANKED DESCENDING)")
    print("=" * 90)
    print(f"{'RANK':<5} {'SYMBOL':<12} {'PRO SCORE':<12} {'CLOSE':<10} {'STOP LOSS':<10} {'TARGET':<10} {'REASON / ACCUMULATION':<30}")
    print("-" * 90)

    for i, c in enumerate(ranked_candidates[:15], 1):
        sym = c.get("symbol")
        score = f"{c.get('pro_buying_score'):.1f}/100"
        close_p = f"₹{c.get('close_price'):.2f}"
        sl = f"₹{c.get('stop_loss'):.2f}"
        tgt = f"₹{c.get('target_price'):.2f}"
        reason = c.get("reason")[:40]

        print(f"{i:<5} {sym:<12} {score:<12} {close_p:<10} {sl:<10} {tgt:<10} {reason:<30}")

    print("=" * 90 + "\n")
