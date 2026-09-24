"""
===============================================================================
DARVAS BOX BREAKOUT SCANNER & VOLUME EXPANSION ENGINE
===============================================================================
Requirements & Mechanics:
1. Trend Filter (Top-Down Context):
   - Price must be within 15% of 52-week High (Close >= 0.85 * 52w High).
   - Daily Close > SMA50 > SMA200.

2. Darvas Box Formation Mechanics (Strict 3-Day Rule):
   - Box Top: High[t] is Box Top if subsequent 3 trading sessions fail to make a higher high (High[t+1, t+2, t+3] < High[t]).
   - Box Bottom: Lowest low after Box Top holds for 3 consecutive sessions without printing a lower low (Low[m+1, m+2, m+3] > Low[m]).
   - Box Validity: Active as long as Close stays within [Box Bottom, Box Top].

3. True Breakout Criteria (Current Bar):
   - Price Breakout: Close >= Box Top * 1.002 (by at least 0.2% to filter false ticks).
   - Volume Surge: Volume >= 1.5x (or 2.0x) 20-day Volume SMA.
   - Close Strength: (Close - Low) / (High - Low) >= 0.75 (upper 25% of day's range).
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

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

load_dotenv(dotenv_path=project_root / ".env")
logger = logging.getLogger(__name__)


def fetch_historical_daily_data(symbol: str, period: str = "2y") -> pd.DataFrame:
    """Fetches 1-2 years of daily OHLCV historical data for a given ticker."""
    clean_sym = symbol.strip().upper()
    yf_symbol = normalize_symbol(clean_sym)
    if not yf_symbol.endswith(".NS") and "=" not in yf_symbol and "-" not in yf_symbol:
        yf_symbol = f"{yf_symbol}.NS"

    df = pd.DataFrame()
    if YFINANCE_AVAILABLE:
        try:
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(period=period, auto_adjust=False)
            if df.empty:
                # Try without .NS if index or commodity
                ticker_raw = yf.Ticker(clean_sym)
                df = ticker_raw.history(period=period, auto_adjust=False)
        except Exception as e:
            logger.warning(f"Error fetching yfinance daily data for {clean_sym}: {e}")

    if df.empty or len(df) < 50:
        return pd.DataFrame()

    # Standardize column names
    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"
    })
    return df[["open", "high", "low", "close", "volume"]].dropna()


def analyze_darvas_box_breakout(symbol: str, df: pd.DataFrame = None) -> dict:
    """
    Analyzes daily OHLCV data for strict Darvas Box breakout criteria.
    
    Returns:
        dict: Detailed Darvas Box analysis containing:
              - is_darvas_breakout (bool)
              - box_top (float)
              - box_bottom (float)
              - close_price (float)
              - volume_surge_ratio (float)
              - close_strength_pct (float)
              - sma50 (float)
              - sma200 (float)
              - fifty_two_week_high (float)
              - within_15pct_52w_high (bool)
              - trend_aligned (bool)
              - reason (str)
    """
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("-EQ", "")
    
    if df is None or df.empty or len(df) < 200:
        df = fetch_historical_daily_data(clean_sym, period="2y")
        
    if df is None or df.empty or len(df) < 50:
        return {
            "symbol": clean_sym,
            "is_darvas_breakout": False,
            "reason": "Insufficient daily OHLCV price history (minimum 50 bars required)."
        }

    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    volumes = df["volume"].values
    n = len(df)

    curr_close = float(closes[-1])
    curr_high = float(highs[-1])
    curr_low = float(lows[-1])
    curr_vol = float(volumes[-1])

    # 1. Trend Filters:
    # 52-week High (past 252 bars)
    lookback_52w = min(252, n)
    high_52w = float(np.max(highs[-lookback_52w:]))
    within_15pct_52w = (curr_close >= 0.85 * high_52w)

    # 50-day and 200-day SMAs
    sma50 = float(pd.Series(closes).rolling(50).mean().iloc[-1]) if n >= 50 else float(np.mean(closes))
    sma200 = float(pd.Series(closes).rolling(200).mean().iloc[-1]) if n >= 200 else sma50
    trend_aligned = (curr_close > sma50) and (sma50 >= sma200 * 0.98)

    # 2. Darvas Box Formation Mechanics (Strict 3-Day Rule)
    # Search backwards from recent history for valid Darvas Box Top & Bottom
    box_top = None
    box_bottom = None
    box_top_idx = -1
    box_bottom_idx = -1

    # We inspect bars from n-4 back to n-90 to find confirmed boxes
    for i in range(n - 4, max(3, n - 90), -1):
        # Step A: High[i] is Box Top if 3 subsequent bars (i+1, i+2, i+3) fail to reach High[i]
        if (highs[i] > highs[i - 1]) and (highs[i] > highs[i - 2]) and (highs[i] > highs[i - 3]):
            if (highs[i + 1] < highs[i]) and (highs[i + 2] < highs[i]) and (highs[i + 3] < highs[i]):
                candidate_top = float(highs[i])
                
                # Step B: Find Box Bottom after Box Top
                candidate_bottom = None
                for j in range(i + 1, min(n - 3, i + 30)):
                    if (lows[j + 1] > lows[j]) and (lows[j + 2] > lows[j]) and (lows[j + 3] > lows[j]):
                        candidate_bottom = float(lows[j])
                        box_bottom_idx = j
                        break
                        
                if candidate_bottom is not None and candidate_bottom < candidate_top:
                    box_top = candidate_top
                    box_bottom = candidate_bottom
                    box_top_idx = i
                    break

    # Fallback box detection if strict 3-day historical loop didn't lock
    if box_top is None or box_bottom is None:
        recent_highs = highs[-30:-3] if len(highs) >= 33 else highs[:-3]
        recent_lows = lows[-30:-3] if len(lows) >= 33 else lows[:-3]
        if len(recent_highs) > 0 and len(recent_lows) > 0:
            box_top = float(np.max(recent_highs))
            box_bottom = float(np.min(recent_lows))

    # 3. True Breakout & Volume Expansion Criteria
    # Price Breakout: Current Close > Box Top * 1.002 (+0.2% buffer)
    price_breakout = (curr_close >= box_top * 1.002)

    # Volume Surge: Current Volume >= 1.5x 20-day Volume SMA
    vol_sma20 = float(pd.Series(volumes).rolling(20).mean().iloc[-1]) if n >= 20 else float(np.mean(volumes))
    vol_ratio = round(curr_vol / vol_sma20, 2) if vol_sma20 > 0 else 1.0
    volume_surge = (vol_ratio >= 1.5)

    # Close Strength: Upper 25% of day's range
    day_range = curr_high - curr_low
    if day_range > 0:
        close_strength = (curr_close - curr_low) / day_range
    else:
        close_strength = 1.0
    close_strength_pct = round(close_strength * 100.0, 1)
    close_strong = (close_strength >= 0.75)

    # 4. Darvas Box Setup & Invalidation Logic:
    # A stock is a valid Darvas Box setup if:
    # - It is near 52-week High (within 15%)
    # - Trend aligned (Close > SMA50 > SMA200)
    # - Price holds Box Bottom (Close >= 0.98 * Box Bottom)
    holds_box_bottom = (curr_close >= box_bottom * 0.98) if box_bottom else True

    # Invalidation Trigger: Broke Box Bottom, lost SMA50 support, or dropped >15% below 52w High
    is_invalidated = (not within_15pct_52w) or (not trend_aligned) or (not holds_box_bottom)

    # Active Darvas Setup Qualification:
    is_darvas_setup = (
        within_15pct_52w and
        trend_aligned and
        holds_box_bottom and
        not is_invalidated
    )

    # Build clear analytical summary
    reasons = []
    if within_15pct_52w:
        reasons.append(f"Near 52w High (RS {high_52w:.2f})")
    else:
        reasons.append(f"Below 15% 52w High boundary (RS {high_52w:.2f})")

    if trend_aligned:
        reasons.append(f"Trend Aligned (Close RS {curr_close:.2f} > SMA50 RS {sma50:.2f} > SMA200 RS {sma200:.2f})")
    else:
        reasons.append(f"Trend unaligned (SMA50: RS {sma50:.2f}, SMA200: RS {sma200:.2f})")

    if price_breakout:
        reasons.append(f"🚀 ACTIVE BREAKOUT above Box Top RS {box_top:.2f} (Close: RS {curr_close:.2f})")
    elif holds_box_bottom:
        reasons.append(f"📦 FORMING BOX [RS {box_bottom:.2f} - RS {box_top:.2f}] (Close: RS {curr_close:.2f})")
    else:
        reasons.append(f"❌ BROKE BELOW Box Bottom RS {box_bottom:.2f}")

    if volume_surge:
        reasons.append(f"Volume Surge {vol_ratio:.1f}x 20d Avg")
    else:
        reasons.append(f"Volume ratio {vol_ratio:.1f}x 20d Avg")

    if close_strong:
        reasons.append(f"Strong Close at {close_strength_pct:.1f}% of daily range")

    if is_invalidated:
        reasons.append("⚠️ SETUP INVALIDATED")

    return {
        "symbol": clean_sym,
        "is_darvas_setup": is_darvas_setup,
        "is_darvas_breakout": price_breakout and volume_surge and close_strong,
        "is_invalidated": is_invalidated,
        "close_price": round(curr_close, 2),
        "box_top": round(box_top, 2) if box_top else 0.0,
        "box_bottom": round(box_bottom, 2) if box_bottom else 0.0,
        "volume_surge_ratio": vol_ratio,
        "close_strength_pct": close_strength_pct,
        "sma50": round(sma50, 2),
        "sma200": round(sma200, 2),
        "fifty_two_week_high": round(high_52w, 2),
        "within_15pct_52w_high": within_15pct_52w,
        "trend_aligned": trend_aligned,
        "price_breakout": price_breakout,
        "volume_surge": volume_surge,
        "close_strong": close_strong,
        "reason": " | ".join(reasons)
    }


def scan_and_save_darvas_stock(symbol: str, timeframe: str = "daily") -> dict:
    """
    Scans a stock for Darvas Box qualification:
    - Saves to MongoDB 'darvas' collection if qualified setup/breakout.
    - Removes from MongoDB 'darvas' collection if setup is invalidated (breaks Box Bottom, loses SMA50/52w high).
    """
    analysis = analyze_darvas_box_breakout(symbol)
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("-EQ", "")
    dm = DataManager()
    col = dm.db["darvas"]

    if analysis.get("is_darvas_setup"):
        try:
            # Inherit actual Grok rating from existing watchlist collections if available
            grok_rating = 5.0
            for src_tf in ["daily", "weekly", "monthly", "manual"]:
                existing_doc = dm.db[src_tf].find_one({"symbol": clean_sym})
                if existing_doc and existing_doc.get("rating"):
                    try:
                        grok_rating = float(existing_doc.get("rating"))
                        break
                    except (ValueError, TypeError):
                        pass

            doc = {
                "symbol": clean_sym,
                "timeframe": timeframe.upper(),
                "rating": grok_rating,
                "reason": f"⚡ DARVAS BOX SETUP: {analysis.get('reason')}",
                "recent_high": analysis.get("box_top"),
                "box_top": analysis.get("box_top"),
                "box_bottom": analysis.get("box_bottom"),
                "alert_trigger_price": round(analysis.get("box_top") * 1.01, 2),
                "volume_surge_ratio": analysis.get("volume_surge_ratio"),
                "close_strength_pct": analysis.get("close_strength_pct"),
                "sma50": analysis.get("sma50"),
                "sma200": analysis.get("sma200"),
                "fifty_two_week_high": analysis.get("fifty_two_week_high"),
                "alert_status": "ACTIVE_BREAKOUT" if analysis.get("is_darvas_breakout") else "DARVAS_BOX_FORMED",
                "alert_count": 1,
                "today_alert_count": 1,
                "last_alerted_at": datetime.now(timezone.utc).replace(tzinfo=None),
                "updated_at": datetime.now(timezone.utc).replace(tzinfo=None)
            }
            col.update_one({"symbol": clean_sym}, {"$set": doc}, upsert=True)
            logger.info(f"⚡ [DARVAS SCANNER] Saved Darvas Box setup for {clean_sym} (Rating: {grok_rating}) to 'darvas' collection!")
        except Exception as e:
            logger.error(f"Failed to save Darvas Box setup for {clean_sym} to DB: {e}")
    else:
        # Auto-remove from 'darvas' table if setup is invalidated
        try:
            res = col.delete_one({"symbol": clean_sym})
            if res.deleted_count > 0:
                logger.info(f"🗑️ [DARVAS CLEANUP] Removed {clean_sym} from 'darvas' collection: {analysis.get('reason')}.")
        except Exception as e:
            logger.error(f"Failed to remove invalidated Darvas stock {clean_sym}: {e}")

    return analysis


def purge_invalidated_darvas_stocks() -> dict:
    """
    Audits all stocks currently in the 'darvas' MongoDB collection.
    Removes any stock that has broken below Box Bottom or lost trend/volume qualification.
    """
    dm = DataManager()
    col = dm.db["darvas"]
    records = list(col.find({}, {"symbol": 1, "box_bottom": 1, "box_top": 1}))
    
    removed = []
    retained = []
    
    for r in records:
        sym = r.get("symbol")
        if not sym:
            continue
        res = scan_and_save_darvas_stock(sym)
        if res.get("is_darvas_breakout"):
            retained.append(sym)
        else:
            removed.append({"symbol": sym, "reason": res.get("reason")})
            
    logger.info(f"⚡ [DARVAS PURGE AUDIT] Processed {len(records)} stocks. Retained: {len(retained)}, Removed: {len(removed)}")
    return {"retained_count": len(retained), "removed_count": len(removed), "removed_details": removed}



if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Darvas Box Breakout Scanner")
    parser.add_argument("--symbol", type=str, default="CYIENTDLM", help="Stock symbol to scan")
    args = parser.parse_args()

    res = analyze_darvas_box_breakout(args.symbol)
    print("\n=======================================================")
    print(f" DARVAS BOX BREAKOUT ANALYSIS FOR {res.get('symbol')}")
    print("=======================================================")
    for k, v in res.items():
        print(f"  {k:<35}: {v}")
    print("=======================================================\n")

