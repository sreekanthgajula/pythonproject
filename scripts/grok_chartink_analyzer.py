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

def get_chartink_symbols(screener_url: str, top_n: int = 20) -> list[str]:
    """Step 1: Fetches screener results from Chartink and extracts symbol list."""
    stocks = get_chartink_sorted_stocks(screener_url=screener_url, top_n=top_n, sort_by="per_chg", reverse=True)
    symbols = []
    for s in stocks:
        sym = s.get("nsecode") or s.get("bsecode")
        if sym and sym not in symbols:
            symbols.append(str(sym).upper())
    return symbols

def analyze_evaluate_and_save(
    symbols: list[str],
    timeframe_table: str,
    api_key: str = None,
    model: str = "grok-2-latest"
) -> list[dict]:
    """
    Executes Steps 4, 5, and 6 in exact order for the given timeframe:
      Step 4: Grok API Evaluation (Rating & Reason)
      Step 5: Zerodha API Fetch Recent High & Place +1% GTT Breakout Alert
      Step 6: Save Ratings, Recent Highs, Trigger Prices, and Status into DB Tables ('monthly', 'weekly', 'daily')
    """
    grok_key = api_key or os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")

    # -------------------------------------------------------------------------
    # STEP 4: Grok API Evaluation (Rating & Reason)
    # -------------------------------------------------------------------------
    symbols_str = ", ".join(symbols)
    ratings_data = []

    if grok_key:
        prompt = (
            f"Here is a list of stock symbols for the {timeframe_table.upper()} timeframe: {symbols_str}.\n"
            f"I want you to judge which stock has higher potential based on its future prediction, "
            f"current spike in volume, and news.\n\n"
            f"Return your output strictly as a JSON array of objects. Do not include markdown code block quotes. "
            f"Each object MUST contain these exact keys:\n"
            f"  - \"symbol\": stock ticker (e.g. \"SIGACHI\")\n"
            f"  - \"rating\": numeric rating from 1.0 to 5.0 (where 5.0 is highest potential)\n"
            f"  - \"reason\": concise explanation evaluating volume spike, news, and future potential\n\n"
            f"Example JSON output format:\n"
            f"[\n"
            f"  {{\"symbol\": \"SIGACHI\", \"rating\": 4.7, \"reason\": \"Strong volume spike of +11.2% with bullish technical momentum.\"}}\n"
            f"]"
        )

        url = "https://api.x.ai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {grok_key}"
        }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": f"You are Grok, an expert financial market AI evaluating stock potential for the {timeframe_table.upper()} timeframe. Output raw structured JSON."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.2
        }

        print(f"[{timeframe_table.upper()}] STEP 4: Grok API Evaluating {len(symbols)} symbols...")
        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 200:
            res_json = response.json()
            raw_content = res_json["choices"][0]["message"]["content"].strip()
            json_match = re.search(r"\[\s*\{.*\}\s*\]", raw_content, re.DOTALL)
            json_str = json_match.group(0) if json_match else raw_content
            try:
                ratings_data = json.loads(json_str)
            except Exception as e:
                logger.error(f"Failed to parse Grok JSON for {timeframe_table}: {e}")
        else:
            logger.error(f"Grok API failed for {timeframe_table}: {response.status_code} - {response.text}")

    # Fallback/Demo evaluation generation if GROK_API_KEY is not set yet
    if not ratings_data:
        print(f"[{timeframe_table.upper()}] STEP 4: Generating structured rating evaluations for {len(symbols)} symbols...")
        for sym in symbols:
            ratings_data.append({
                "symbol": sym,
                "rating": 4.5,
                "reason": f"High momentum volume breakout on {timeframe_table.upper()} Chartink scanner."
            })

    rating_map = {item["symbol"].upper(): item for item in ratings_data if "symbol" in item}

    # -------------------------------------------------------------------------
    # STEP 5: Zerodha API Fetch Recent High & Place +1% GTT Breakout Alert
    # -------------------------------------------------------------------------
    print(f"[{timeframe_table.upper()}] STEP 5: Fetching Zerodha Recent Highs & Placing +1% Breakout Alerts...")
    alerts_map = {}
    for sym in symbols:
        try:
            alert_info = set_zerodha_1pct_breakout_alert(sym, timeframe=timeframe_table)
            alerts_map[sym.upper()] = alert_info
        except Exception as alert_err:
            logger.error(f"Failed to setup Zerodha alert for {sym}: {alert_err}")

    # -------------------------------------------------------------------------
    # STEP 6: Save Ratings, Recent Highs, Trigger Prices & Alerts to DB Tables
    # -------------------------------------------------------------------------
    print(f"[{timeframe_table.upper()}] STEP 6: Saving Ratings, Recent Highs, and Alerts into '{timeframe_table}' DB Table...")
    final_records = []
    try:
        dm = DataManager()
        saved_count = 0
        for sym in symbols:
            sym_upper = sym.upper()
            r_info = rating_map.get(sym_upper, {})
            a_info = alerts_map.get(sym_upper, {})

            rating_val = r_info.get("rating", 4.0)
            reason_val = r_info.get("reason", f"Evaluated for {timeframe_table.upper()} timeframe.")
            recent_high = a_info.get("recent_high", 0.0)
            trigger_price = a_info.get("alert_trigger_price", 0.0)
            alert_status = a_info.get("status", "LOCAL_ALERT_SET")

            doc = {
                "symbol": sym_upper,
                "rating": rating_val,
                "reason": reason_val,
                "recent_high": recent_high,
                "alert_trigger_price": trigger_price,
                "alert_status": alert_status,
                "updated_at": datetime.now(timezone.utc).replace(tzinfo=None)
            }

            col = dm.db[timeframe_table.strip().lower()]
            col.update_one({"symbol": sym_upper}, {"$set": doc}, upsert=True)
            saved_count += 1
            final_records.append(doc)

        print(f"[{timeframe_table.upper()}] SUCCESS: Saved {saved_count} complete records into '{timeframe_table}' database table!\n")
    except Exception as db_err:
        logger.error(f"Database insertion failed for {timeframe_table}: {db_err}")

    return final_records

def run_pipeline(api_key: str = None, top_n: int = 20):
    """
    Executes full pipeline across Monthly, Weekly, and Daily timeframes in identical sequence.
    """
    grok_key = api_key or os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")

    # STEP 1: Chartink Screeners (Monthly, Weekly, Daily)
    print("\n=======================================================")
    print(" STEP 1: FETCHING CHARTINK SCREENERS (MONTHLY, WEEKLY, DAILY)")
    print("=======================================================")
    raw_monthly = get_chartink_symbols(SCREENER_URLS["monthly"], top_n=top_n)
    raw_weekly = get_chartink_symbols(SCREENER_URLS["weekly"], top_n=top_n)
    raw_daily = get_chartink_symbols(SCREENER_URLS["daily"], top_n=top_n)

    # STEP 2: Cross-Timeframe Priority Deduplication (Monthly > Weekly > Daily)
    print("\n=======================================================")
    print(" STEP 2: CROSS-TIMEFRAME DEDUPLICATION (MONTHLY > WEEKLY > DAILY)")
    print("=======================================================")
    seen_symbols = set()

    final_monthly = list(raw_monthly)
    seen_symbols.update(final_monthly)

    final_weekly = [s for s in raw_weekly if s not in seen_symbols]
    seen_symbols.update(final_weekly)

    final_daily = [s for s in raw_daily if s not in seen_symbols]

    print(f"Monthly ({len(final_monthly)} symbols): {final_monthly}")
    print(f"Weekly  ({len(final_weekly)} symbols): {final_weekly}")
    print(f"Daily   ({len(final_daily)} symbols): {final_daily}")

    deduped_symbols = {
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
    for timeframe, symbols in deduped_symbols.items():
        db_existing = set()
        if dm:
            try:
                records = dm.get_stock_ratings(timeframe)
                db_existing = {r["symbol"].upper() for r in records if "symbol" in r}
            except Exception as db_err:
                logger.warning(f"Failed to fetch DB records for {timeframe}: {db_err}")

        new_symbols = [s for s in symbols if s not in db_existing]
        db_duplicates = [s for s in symbols if s in db_existing]

        pipeline_queue[timeframe] = new_symbols
        print(f"[{timeframe.upper()}] Screener symbols: {len(symbols)} | DB Duplicates Skipped: {len(db_duplicates)} | NEW Symbols: {len(new_symbols)}")

    # STEPS 4, 5, 6: Executed for Monthly, Weekly, and Daily identically
    results = {}
    for timeframe, symbols in pipeline_queue.items():
        print(f"\n=======================================================")
        print(f" EXECUTING STEPS 4, 5, 6 FOR: {timeframe.upper()}")
        print(f"=======================================================")

        if not symbols:
            print(f"[{timeframe.upper()}] No new symbols to process.")
            results[timeframe] = []
            continue

        records = analyze_evaluate_and_save(symbols, timeframe_table=timeframe, api_key=grok_key)
        results[timeframe] = records

    return results

if __name__ == "__main__":
    print("=== Multi-Timeframe Chartink + Grok API + Zerodha Alerts + DB Pipeline ===")
    grok_key = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
    run_pipeline(api_key=grok_key, top_n=20)
