"""
Syncs and computes accurate baseline closing prices for all tracked stocks in MongoDB:
  - prev_close: Close of the most recently completed trading day
  - week_ago_close: Close of 5 trading days ago (~1 week)
  - month_ago_close: Close of 21 trading days ago (~1 month)

Uses 100% Zerodha Kite Connect API data.
Upserts into MongoDB collection `stock_returns_cache`.
"""
import sys
import os
import time
import logging
from datetime import datetime, timedelta, timezone

# Ensure project root is on PYTHONPATH
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sync_stock_returns")

def sync_stock_returns_cache(kite=None, force: bool = False) -> dict:
    from data_manager import DataManager
    from scripts.zerodha_alert_manager import get_kite_client
    from tradingagents.market_timing import get_now_ist, get_today_ist, get_ist_date_str

    dm = DataManager()
    if dm.db is None:
        logger.error("MongoDB not connected.")
        return {"status": "error", "message": "MongoDB not connected"}

    kite = kite or get_kite_client()
    if not kite:
        logger.error("Zerodha Kite client not connected.")
        return {"status": "error", "message": "Zerodha Kite client not connected"}

    # 1. Collect all unique tracked symbols across watchlists
    tracked_symbols = set()
    for col_name in ["monthly", "weekly", "daily", "manual", "darvas"]:
        try:
            for doc in dm.db[col_name].find({}, {"symbol": 1}):
                sym = (doc.get("symbol") or "").strip().upper().replace(".NS", "").replace("-EQ", "")
                if sym:
                    tracked_symbols.add(sym)
        except Exception as e:
            logger.warning(f"Error reading collection {col_name}: {e}")

    if not tracked_symbols:
        logger.info("No tracked symbols found in database.")
        return {"status": "success", "synced_count": 0, "message": "No tracked symbols found"}

    clean_symbols = sorted(list(tracked_symbols))
    logger.info(f"Syncing returns cache for {len(clean_symbols)} tracked symbols...")

    # 2. Fetch NSE instruments to map tradingsymbol -> instrument_token
    try:
        instruments = kite.instruments("NSE")
        token_map = {}
        for row in instruments:
            ts = row.get("tradingsymbol")
            tok = row.get("instrument_token")
            if ts and tok and ts in tracked_symbols:
                token_map[ts] = tok
    except Exception as e:
        logger.error(f"Failed to fetch NSE instruments from Zerodha: {e}")
        return {"status": "error", "message": f"Instrument lookup failed: {e}"}

    to_date = get_now_ist()
    # Fetch 45 days back to safely get >= 25 trading days
    from_date = to_date - timedelta(days=45)
    from_str = from_date.strftime("%Y-%m-%d")
    to_str = to_date.strftime("%Y-%m-%d")

    # 3. Batch fetch live quotes first (to get live LTP and today's close if active)
    quotes = {}
    try:
        for i in range(0, len(clean_symbols), 200):
            batch = clean_symbols[i:i + 200]
            q_chunk = kite.quote([f"NSE:{s}" for s in batch])
            for k, v in q_chunk.items():
                s = k.replace("NSE:", "").replace("BSE:", "")
                quotes[s] = v
    except Exception as qe:
        logger.warning(f"Failed to fetch batch quotes: {qe}")

    synced_records = []
    failed_symbols = []

    # Check which symbols need historical candle refresh
    # If a symbol was synced today and has valid week/month ago close, we can skip historical fetch unless force=True
    today_str = get_ist_date_str()
    existing_cache = {
        d["symbol"]: d for d in dm.db["stock_returns_cache"].find({"symbol": {"$in": clean_symbols}}, {"_id": 0})
    }

    t0 = time.time()
    for idx, sym in enumerate(clean_symbols, start=1):
        token = token_map.get(sym)
        q_data = quotes.get(sym) or {}
        ltp = float(q_data.get("last_price") or 0.0)
        q_prev = float((q_data.get("ohlc") or {}).get("close") or 0.0)

        existing = existing_cache.get(sym)
        needs_history_fetch = (
            force
            or not existing
            or existing.get("date") != today_str
            or float(existing.get("week_ago_close") or 0.0) <= 0
            or float(existing.get("month_ago_close") or 0.0) <= 0
        )

        prev_close = q_prev
        week_ago_close = float(existing.get("week_ago_close") or 0.0) if existing else 0.0
        month_ago_close = float(existing.get("month_ago_close") or 0.0) if existing else 0.0

        if needs_history_fetch and token:
            try:
                candles = kite.historical_data(
                    instrument_token=token,
                    from_date=from_str,
                    to_date=to_str,
                    interval="day"
                )
                if candles and len(candles) >= 2:
                    # If market is open or today's candle is in progress:
                    # candles[-1] is today's bar, candles[-2] is yesterday's completed close
                    # If market is closed on weekend, candles[-1] is Friday's completed close
                    # Let's verify by checking date of candles[-1]
                    last_c_date = str(candles[-1]["date"])[:10]
                    if last_c_date == today_str and len(candles) >= 3:
                        # Today's incomplete candle
                        prev_close = float(candles[-2]["close"])
                        week_idx = -7 if len(candles) >= 7 else 0
                        month_idx = -23 if len(candles) >= 23 else 0
                    else:
                        # Completed day or weekend
                        prev_close = float(candles[-2]["close"]) if len(candles) >= 2 else float(candles[-1]["close"])
                        week_idx = -6 if len(candles) >= 6 else 0
                        month_idx = -22 if len(candles) >= 22 else 0

                    week_ago_close = float(candles[week_idx]["close"])
                    month_ago_close = float(candles[month_idx]["close"])
                elif candles:
                    prev_close = float(candles[-1]["close"])
                    week_ago_close = prev_close
                    month_ago_close = prev_close
            except Exception as he:
                logger.warning(f"Failed historical fetch for {sym} (token {token}): {he}")
                failed_symbols.append(sym)

        # Fallback for prev_close if still zero
        if prev_close <= 0 and q_prev > 0:
            prev_close = q_prev
        if ltp <= 0 and prev_close > 0:
            ltp = prev_close
        if week_ago_close <= 0:
            week_ago_close = prev_close
        if month_ago_close <= 0:
            month_ago_close = week_ago_close

        # Compute percentage returns
        daily_pct = round(((ltp - prev_close) / prev_close) * 100.0, 2) if prev_close > 0 else 0.0
        weekly_pct = round(((ltp - week_ago_close) / week_ago_close) * 100.0, 2) if week_ago_close > 0 else 0.0
        monthly_pct = round(((ltp - month_ago_close) / month_ago_close) * 100.0, 2) if month_ago_close > 0 else 0.0

        doc = {
            "symbol": sym,
            "ltp": ltp,
            "prev_close": prev_close,
            "week_ago_close": week_ago_close,
            "month_ago_close": month_ago_close,
            "daily_change_pct": daily_pct,
            "weekly_change_pct": weekly_pct,
            "monthly_change_pct": monthly_pct,
            "date": today_str,
            "updated_at": time.time(),
            "updated_at_ist": get_now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
        }

        dm.db["stock_returns_cache"].update_one({"symbol": sym}, {"$set": doc}, upsert=True)
        synced_records.append(doc)

        if idx % 25 == 0 or idx == len(clean_symbols):
            logger.info(f"Progress: {idx}/{len(clean_symbols)} stocks synced ({round(time.time() - t0, 1)}s)")

    logger.info(f"Sync complete: {len(synced_records)} records updated in stock_returns_cache ({round(time.time() - t0, 1)}s).")
    return {
        "status": "success",
        "synced_count": len(synced_records),
        "failed_count": len(failed_symbols),
        "date": today_str,
        "sample": synced_records[:3] if synced_records else []
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sync Stock Returns Cache from Zerodha")
    parser.add_argument("--force", action="store_true", help="Force re-fetch all historical daily candles")
    args = parser.parse_args()
    res = sync_stock_returns_cache(force=args.force)
    print("\nResult:", res["status"], "| Synced:", res["synced_count"])
    for s in res.get("sample", []):
        print(f"  {s['symbol']:12s} | LTP: ₹{s['ltp']} | Prev: ₹{s['prev_close']} ({s['daily_change_pct']:+0.2f}%) | Week: ₹{s['week_ago_close']} ({s['weekly_change_pct']:+0.2f}%) | Month: ₹{s['month_ago_close']} ({s['monthly_change_pct']:+0.2f}%)")
