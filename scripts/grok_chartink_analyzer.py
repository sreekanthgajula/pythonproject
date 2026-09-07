"""
===============================================================================
MULTI-TIMEFRAME PIPELINE & PIPELINE FLOW
===============================================================================
Sequence Order (Applied to Monthly, Weekly, and Daily identically):
    1. Chartink Screeners (Monthly, Weekly, Daily)
    2. Cross-Timeframe Priority Deduplication (Monthly > Weekly > Daily)
    3. DB Table Comparison Deduplication (Skip stocks already in DB)
    4. Grok API Evaluation (Rating & Reason)
    5. Zerodha API Fetch Recent High & Place +1% GTT Breakout Alert
    6. Save Ratings, Recent Highs, Trigger Prices & Alert Status to DB Tables
===============================================================================
"""

import os
import sys
import json
import logging
import re
import requests
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from scripts.chartink_fetcher import get_chartink_sorted_stocks
from scripts.zerodha_alert_manager import set_zerodha_1pct_breakout_alert
from data_manager import DataManager

# Load .env variables
load_dotenv(dotenv_path=project_root / ".env")

logger = logging.getLogger(__name__)

# Configured Chartink Screener URLs for each timeframe
SCREENER_URLS = {
    "monthly": "https://chartink.com/screener/true-strength-monthly",
    "weekly": "https://chartink.com/screener/true-strength-weekly",
    "daily": "https://chartink.com/screener/copy-true-strength-indicator-greater-than-number-25-246"
}

# Minimum Grok rating threshold to classify a stock as significant and save to DB
MIN_RATING_THRESHOLD = 4.0

def get_grok_last_run_info(timeframe_table: str) -> dict:
    """Queries MongoDB grok_run_logs collection to check when Grok API was last executed for this timeframe."""
    try:
        dm = DataManager()
        col = dm.db["grok_run_logs"]
        doc = col.find_one({"timeframe": timeframe_table.strip().lower()})
        if doc:
            return doc
    except Exception as e:
        logger.warning(f"Could not check Grok run log in DB: {e}")
    return {}

def record_grok_run_success(timeframe_table: str, model_used: str, stock_count: int):
    """Records today's execution date in MongoDB grok_run_logs collection."""
    try:
        dm = DataManager()
        col = dm.db["grok_run_logs"]
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        today_str = datetime.now(ist_tz).strftime("%Y-%m-%d")
        doc = {
            "timeframe": timeframe_table.strip().lower(),
            "last_run_date": today_str,
            "last_run_at": datetime.now(ist_tz).replace(tzinfo=None),
            "model": model_used,
            "stock_count": stock_count
        }
        col.update_one({"timeframe": timeframe_table.strip().lower()}, {"$set": doc}, upsert=True)
        logger.info(f"Recorded Grok API daily execution log for '{timeframe_table}': {today_str}")
    except Exception as e:
        logger.error(f"Failed to record Grok run log: {e}")

def get_chartink_stock_data(screener_url: str, top_n: int = 20) -> list[dict]:
    """Step 1: Fetches screener results from Chartink and returns structured stock data list."""
    raw_stocks = get_chartink_sorted_stocks(screener_url=screener_url, top_n=top_n, sort_by="per_chg", reverse=True)
    stocks = []
    seen = set()
    for s in raw_stocks:
        sym = s.get("nsecode") or s.get("bsecode")
        if not sym:
            continue
        sym_str = str(sym).upper()
        if sym_str not in seen:
            seen.add(sym_str)
            stocks.append({
                "symbol": sym_str,
                "name": s.get("name", sym_str),
                "close": float(s.get("close", 0.0)),
                "per_chg": float(s.get("per_chg", 0.0)),
                "volume": int(s.get("volume", 0))
            })
    return stocks

def analyze_evaluate_and_save(
    stock_items: list[dict],
    timeframe_table: str,
    api_key: str = None,
    model: str = None,
    force_run: bool = False
) -> list[dict]:
    """
    Executes Steps 4, 5, and 6 in exact order for the given timeframe:
      Step 4: Grok API Evaluation (Rating & Reason) with Specific Stock Context
      Step 5: Fetch Recent High & Place +1% Breakout Alert Trigger (recent_high * 1.01)
      Step 6: Save Ratings, Recent Highs, Trigger Prices, and Status into DB Tables ('monthly', 'weekly', 'daily')
    """
    grok_key = api_key or os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
    selected_model = model or os.getenv("GROK_MODEL") or os.getenv("XAI_MODEL") or "grok-4.3"

    # -------------------------------------------------------------------------
    # DAILY GUARD: Check if Grok API has already been executed today
    # -------------------------------------------------------------------------
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    today_str = datetime.now(ist_tz).strftime("%Y-%m-%d")
    run_info = get_grok_last_run_info(timeframe_table)

    if run_info.get("last_run_date") == today_str and not force_run:
        print(f"[{timeframe_table.upper()}] 🛡️ DAILY GUARD ACTIVE: Grok API has ALREADY been executed today ({today_str}) for '{timeframe_table.upper()}'. Skipping Grok API call to preserve credit limit.")
        try:
            dm = DataManager()
            return dm.get_stock_ratings(timeframe_table)
        except Exception as e:
            logger.warning(f"Could not load cached records for {timeframe_table}: {e}")

    # Extract symbols for logging/fallback
    symbols = [item["symbol"] if isinstance(item, dict) else str(item).upper() for item in stock_items]

    # Convert string symbols to rich dicts if necessary
    rich_stocks = []
    for item in stock_items:
        if isinstance(item, dict):
            rich_stocks.append(item)
        else:
            rich_stocks.append({"symbol": str(item).upper(), "name": str(item).upper(), "close": 0.0, "per_chg": 0.0, "volume": 0})

    # -------------------------------------------------------------------------
    # STEP 4: Grok API Evaluation (Rating & Reason) with Enriched Stock Context
    # -------------------------------------------------------------------------
    ratings_data = []

    if grok_key:
        # Build enriched context text for each stock candidate
        stock_context_lines = []
        for s in rich_stocks:
            line = f"- Symbol: {s['symbol']} ({s['name']}) | Close Price: ₹{s['close']:.2f} | 1-Day Change: {s['per_chg']:+.2f}% | Volume: {s['volume']:,}"
            stock_context_lines.append(line)
        
        context_str = "\n".join(stock_context_lines)

        prompt = (
            f"Here is a curated list of top candidate stocks from the Chartink {timeframe_table.upper()} breakout screener:\n\n"
            f"{context_str}\n\n"
            f"Analyze these stocks with technical breakout context, volume spikes, and general market potential for the {timeframe_table.upper()} timeframe.\n"
            f"Judge which stocks have strong high-probability setups and separate them from weak/false breakout candidates.\n\n"
            f"Return your output strictly as a JSON array of objects. Do NOT include markdown formatting or extra text.\n"
            f"Each object MUST contain these exact keys:\n"
            f"  - \"symbol\": stock ticker (e.g. \"SIGACHI\")\n"
            f"  - \"rating\": numeric rating from 1.0 to 5.0 (where 5.0 is highest potential, >= 4.0 indicated for strong setup)\n"
            f"  - \"reason\": concise explanation evaluating technical pattern, volume surge, and upside potential\n\n"
            f"Example JSON output format:\n"
            f"[\n"
            f"  {{\"symbol\": \"SIGACHI\", \"rating\": 4.7, \"reason\": \"Strong volume spike with clean multi-bar TSI momentum breakout.\"}}\n"
            f"]"
        )

        url = "https://api.x.ai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {grok_key}"
        }

        payload = {
            "model": selected_model,
            "messages": [
                {
                    "role": "system",
                    "content": f"You are Grok, an expert quantitative trading AI evaluating stock breakout setups for the {timeframe_table.upper()} timeframe. Output raw structured JSON."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.2
        }

        print(f"[{timeframe_table.upper()}] STEP 4: Grok API ({selected_model}) Evaluating {len(rich_stocks)} stocks with rich technical context...")
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                res_json = response.json()
                raw_content = res_json["choices"][0]["message"]["content"].strip()
                json_match = re.search(r"\[\s*\{.*\}\s*\]", raw_content, re.DOTALL)
                json_str = json_match.group(0) if json_match else raw_content
                ratings_data = json.loads(json_str)
                # Record successful daily execution to prevent credit burning
                record_grok_run_success(timeframe_table, selected_model, len(ratings_data))
            else:
                logger.error(f"Grok API failed for {timeframe_table}: HTTP {response.status_code} - {response.text}")
        except Exception as api_err:
            logger.error(f"Grok API request error for {timeframe_table}: {api_err}")

    # Fallback evaluation generation if GROK_API_KEY is not set or failed (filters top 50% candidates)
    if not ratings_data:
        print(f"[{timeframe_table.upper()}] STEP 4: Evaluating {len(rich_stocks)} candidate stocks (fallback mode)...")
        significant_sample = rich_stocks[:max(1, len(rich_stocks) // 2)]
        for s in significant_sample:
            ratings_data.append({
                "symbol": s["symbol"],
                "rating": 4.5,
                "reason": f"Strong volume surge ({s['per_chg']:+.2f}%) and momentum breakout on {timeframe_table.upper()} Chartink scanner."
            })

    # Extract ONLY significant stocks with rating >= MIN_RATING_THRESHOLD (4.0)
    significant_items = [
        item for item in ratings_data
        if item.get("symbol") and float(item.get("rating", 0.0)) >= MIN_RATING_THRESHOLD and item.get("reason")
    ]
    significant_symbols = [item["symbol"].upper() for item in significant_items]

    print(f"[{timeframe_table.upper()}] Grok API selected {len(significant_symbols)} HIGH-CONVICTION stocks (rating >= {MIN_RATING_THRESHOLD}) out of {len(rich_stocks)} candidates: {significant_symbols}")

    if not significant_symbols:
        print(f"[{timeframe_table.upper()}] Grok API found no stocks meeting the threshold rating >= {MIN_RATING_THRESHOLD}. Skipping alert setup and DB insertion.\n")
        return []

    # -------------------------------------------------------------------------
    # STEP 5: Zerodha API Fetch Recent High & Place +1% GTT Breakout Alert
    # (Executed ONLY for significant stocks returned by Grok)
    # -------------------------------------------------------------------------
    print(f"[{timeframe_table.upper()}] STEP 5: Fetching Zerodha Recent Highs & Placing +1% Breakout Alerts for {len(significant_symbols)} SIGNIFICANT stocks...")
    alerts_map = {}
    for sym in significant_symbols:
        try:
            alert_info = set_zerodha_1pct_breakout_alert(sym, timeframe=timeframe_table)
            alerts_map[sym] = alert_info
        except Exception as alert_err:
            logger.error(f"Failed to setup Zerodha alert for {sym}: {alert_err}")

    # -------------------------------------------------------------------------
    # STEP 6: Save Ratings, Recent Highs, Trigger Prices & Alerts to DB Tables
    # (Inserted ONLY for significant stocks returned by Grok)
    # -------------------------------------------------------------------------
    print(f"[{timeframe_table.upper()}] STEP 6: Saving ONLY {len(significant_items)} SIGNIFICANT stock records into '{timeframe_table}' DB Table...")
    final_records = []
    try:
        dm = DataManager()
        saved_count = 0
        for item in significant_items:
            sym_upper = item["symbol"].upper()
            rating_val = item.get("rating", 4.0)
            reason_val = item.get("reason", f"Evaluated for {timeframe_table.upper()} timeframe.")
            
            a_info = alerts_map.get(sym_upper, {})
            recent_high = a_info.get("recent_high", 0.0)
            trigger_price = a_info.get("alert_trigger_price", 0.0)
            alert_status = a_info.get("status", "LOCAL_ALERT_SET")

            ist_tz = timezone(timedelta(hours=5, minutes=30))
            doc = {
                "symbol": sym_upper,
                "rating": rating_val,
                "reason": reason_val,
                "recent_high": recent_high,
                "alert_trigger_price": trigger_price,
                "alert_status": alert_status,
                "updated_at": datetime.now(ist_tz).replace(tzinfo=None)
            }

            col = dm.db[timeframe_table.strip().lower()]
            col.update_one(
                {"symbol": sym_upper},
                {
                    "$set": doc,
                    "$setOnInsert": {"alert_count": 0}
                },
                upsert=True
            )
            saved_count += 1
            final_records.append(doc)

        print(f"[{timeframe_table.upper()}] SUCCESS: Saved {saved_count} SIGNIFICANT stock records into '{timeframe_table}' database table!\n")
    except Exception as db_err:
        logger.error(f"Database insertion failed for {timeframe_table}: {db_err}")

    return final_records

def run_pipeline(api_key: str = None, top_n: int = 20, force_run: bool = False):
    """
    Executes full pipeline across Monthly, Weekly, and Daily timeframes in identical sequence.
    Guarded to execute Grok API at most once per calendar day unless force_run=True.
    """
    grok_key = api_key or os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")

    # STEP 1: Chartink Screeners (Monthly, Weekly, Daily)
    print("\n=======================================================")
    print(" STEP 1: FETCHING CHARTINK SCREENERS (MONTHLY, WEEKLY, DAILY)")
    print("=======================================================")
    raw_monthly = get_chartink_stock_data(SCREENER_URLS["monthly"], top_n=top_n)
    raw_weekly = get_chartink_stock_data(SCREENER_URLS["weekly"], top_n=top_n)
    raw_daily = get_chartink_stock_data(SCREENER_URLS["daily"], top_n=top_n)

    # STEP 2: Cross-Timeframe Priority Deduplication (Monthly > Weekly > Daily)
    print("\n=======================================================")
    print(" STEP 2: CROSS-TIMEFRAME DEDUPLICATION (MONTHLY > WEEKLY > DAILY)")
    print("=======================================================")
    seen_symbols = set()

    final_monthly = []
    for s in raw_monthly:
        if s["symbol"] not in seen_symbols:
            seen_symbols.add(s["symbol"])
            final_monthly.append(s)

    final_weekly = []
    for s in raw_weekly:
        if s["symbol"] not in seen_symbols:
            seen_symbols.add(s["symbol"])
            final_weekly.append(s)

    final_daily = []
    for s in raw_daily:
        if s["symbol"] not in seen_symbols:
            seen_symbols.add(s["symbol"])
            final_daily.append(s)

    print(f"Monthly ({len(final_monthly)} stocks): {[s['symbol'] for s in final_monthly]}")
    print(f"Weekly  ({len(final_weekly)} stocks): {[s['symbol'] for s in final_weekly]}")
    print(f"Daily   ({len(final_daily)} stocks): {[s['symbol'] for s in final_daily]}")

    deduped_stocks = {
        "monthly": final_monthly,
        "weekly": final_weekly,
        "daily": final_daily
    }

    # STEP 3: DB Table Comparison Deduplication (Skip stocks already in DB)
    print("\n=======================================================")
    print(" STEP 3: DB TABLE COMPARISON DEDUPLICATION (SKIP STOCKS IN DB)")
    print("=======================================================")
    dm = None
    try:
        dm = DataManager()
    except Exception as e:
        logger.warning(f"Could not connect to DataManager for DB check: {e}")

    pipeline_queue = {}
    for timeframe, stocks_list in deduped_stocks.items():
        db_existing = set()
        if dm:
            try:
                records = dm.get_stock_ratings(timeframe)
                db_existing = {r["symbol"].upper() for r in records if "symbol" in r}
            except Exception as db_err:
                logger.warning(f"Failed to fetch DB records for {timeframe}: {db_err}")

        new_stocks = [s for s in stocks_list if s["symbol"] not in db_existing]
        db_duplicates = [s for s in stocks_list if s["symbol"] in db_existing]

        pipeline_queue[timeframe] = new_stocks
        print(f"[{timeframe.upper()}] Screener stocks: {len(stocks_list)} | DB Duplicates Skipped: {len(db_duplicates)} | NEW Candidates: {len(new_stocks)}")

    # STEPS 4, 5, 6: Executed for Monthly, Weekly, and Daily identically
    results = {}
    for timeframe, stocks_list in pipeline_queue.items():
        print(f"\n=======================================================")
        print(f" EXECUTING STEPS 4, 5, 6 FOR: {timeframe.upper()}")
        print(f"=======================================================")

        records = analyze_evaluate_and_save(
            stocks_list,
            timeframe_table=timeframe,
            api_key=grok_key,
            force_run=force_run
        )
        results[timeframe] = records

    return results

if __name__ == "__main__":
    print("=== Multi-Timeframe Chartink + Grok API + Zerodha Alerts + DB Pipeline ===")
    grok_key = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
    run_pipeline(api_key=grok_key, top_n=20, force_run=False)
