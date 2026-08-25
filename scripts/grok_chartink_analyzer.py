"""
===============================================================================
MULTI-TIMEFRAME GROK API & CHARTINK SCREENER PIPELINE
===============================================================================
Description:
    1. Fetches top 20 stock symbols for Monthly, Weekly, and Daily Chartink screeners.
    2. Sends symbols for each timeframe to Grok API with the context:
       "I will list stock symbols. I want you to judge which stock has higher
        potential based on its future prediction, current spike in volume, and news."
    3. Parses structured JSON (symbol, rating, reason) returned by Grok.
    4. Automatically saves results into their respective MongoDB database tables
       ('monthly', 'weekly', and 'daily').
===============================================================================
"""

import os
import sys
import json
import logging
import re
import requests
from pathlib import Path
from dotenv import load_dotenv

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from scripts.chartink_fetcher import get_chartink_sorted_stocks
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
    """
    Fetches screener results from Chartink, sorts by % gain, and extracts
    just the symbol list (e.g. ['BTML', 'SIGACHI', 'APOLLOPIPE', ...]).
    """
    stocks = get_chartink_sorted_stocks(screener_url=screener_url, top_n=top_n, sort_by="per_chg", reverse=True)
    symbols = []
    for s in stocks:
        sym = s.get("nsecode") or s.get("bsecode")
        if sym and sym not in symbols:
            symbols.append(str(sym).upper())
    return symbols

def analyze_and_rate_with_grok(
    symbols: list[str],
    timeframe_table: str,
    api_key: str = None,
    model: str = "grok-2-latest"
) -> list[dict]:
    """
    Passes symbols to Grok API using your prompt context, receives structured rating & reason,
    and inserts records directly into the specified database table ('monthly', 'weekly', 'daily').
    """
    grok_key = api_key or os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
    if not grok_key:
        raise ValueError(
            "Grok API Key not found! Please set GROK_API_KEY or XAI_API_KEY in your .env file."
        )

    symbols_str = ", ".join(symbols)

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

    print(f"[{timeframe_table.upper()}] Sending {len(symbols)} symbols to Grok API ({model})...")
    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        logger.error(f"Grok API request failed for {timeframe_table}: {response.status_code} - {response.text}")
        return []

    res_json = response.json()
    raw_content = res_json["choices"][0]["message"]["content"].strip()

    # Extract JSON substring if wrapped in markdown ```json ... ```
    json_match = re.search(r"\[\s*\{.*\}\s*\]", raw_content, re.DOTALL)
    if json_match:
        json_str = json_match.group(0)
    else:
        json_str = raw_content

    try:
        ratings_data = json.loads(json_str)
    except Exception as e:
        logger.error(f"Failed to parse Grok JSON response for {timeframe_table}: {e}\nRaw text: {raw_content[:300]}")
        return []

    # Insert/update parsed ratings into specified database table ('monthly', 'weekly', or 'daily')
    try:
        dm = DataManager()
        saved_count = 0
        for item in ratings_data:
            sym = item.get("symbol")
            rating = item.get("rating")
            reason = item.get("reason")
            if sym and rating and reason:
                if dm.save_stock_rating(table_name=timeframe_table, symbol=sym, rating=rating, reason=reason):
                    saved_count += 1
        print(f"[{timeframe_table.upper()}] Successfully saved {saved_count} stock ratings into '{timeframe_table}' database table!\n")
    except Exception as db_err:
        logger.error(f"Database insertion failed for {timeframe_table}: {db_err}")

    return ratings_data

def run_all_screeners(api_key: str = None, top_n: int = 20):
    """
    Executes the full automated pipeline across Monthly, Weekly, and Daily screeners.
    Applies strict priority deduplication (Monthly > Weekly > Daily):
      - Monthly keeps all top_n symbols.
      - Weekly removes any symbols already present in Monthly.
      - Daily removes any symbols already present in Monthly or Weekly.
    """
    grok_key = api_key or os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
    
    print("\n=======================================================")
    print(" 1. FETCHING & DEDUPLICATING SCREENER SYMBOLS")
    print(" Priority Rule: MONTHLY > WEEKLY > DAILY")
    print("=======================================================")
    
    # 1. Fetch raw symbols from Chartink screeners
    raw_monthly = get_chartink_symbols(SCREENER_URLS["monthly"], top_n=top_n)
    raw_weekly = get_chartink_symbols(SCREENER_URLS["weekly"], top_n=top_n)
    raw_daily = get_chartink_symbols(SCREENER_URLS["daily"], top_n=top_n)

    # 2. Priority Deduplication
    seen_symbols = set()

    # Monthly keeps highest priority
    final_monthly = list(raw_monthly)
    seen_symbols.update(final_monthly)

    # Weekly filters out symbols in Monthly
    final_weekly = [s for s in raw_weekly if s not in seen_symbols]
    removed_weekly = [s for s in raw_weekly if s in seen_symbols]
    seen_symbols.update(final_weekly)

    # Daily filters out symbols in Monthly or Weekly
    final_daily = [s for s in raw_daily if s not in seen_symbols]
    removed_daily = [s for s in raw_daily if s in seen_symbols]

    print(f"\n[MONTHLY] ({len(final_monthly)} symbols): {final_monthly}")
    
    print(f"\n[WEEKLY]  ({len(final_weekly)} symbols, {len(removed_weekly)} duplicates removed): {final_weekly}")
    if removed_weekly:
        print(f"          Duplicates removed (kept in Monthly): {removed_weekly}")

    print(f"\n[DAILY]   ({len(final_daily)} symbols, {len(removed_daily)} duplicates removed): {final_daily}")
    if removed_daily:
        print(f"          Duplicates removed (kept in Monthly/Weekly): {removed_daily}")

    deduped_symbols = {
        "monthly": final_monthly,
        "weekly": final_weekly,
        "daily": final_daily
    }

    # 3. Process with Grok API & insert into DB
    results = {}
    for timeframe, symbols in deduped_symbols.items():
        print(f"\n=======================================================")
        print(f" PROCESSING TIMEFRAME: {timeframe.upper()} ({len(symbols)} unique symbols)")
        print(f"=======================================================")
        
        if not symbols:
            print(f"[{timeframe.upper()}] No unique symbols to analyze.")
            results[timeframe] = []
            continue

        if grok_key:
            ratings = analyze_and_rate_with_grok(symbols, timeframe_table=timeframe, api_key=grok_key)
            results[timeframe] = ratings
        else:
            print(f"[NOTE] Add GROK_API_KEY to .env to execute live Grok rating & save to '{timeframe}' table.")
            results[timeframe] = symbols

    return results

if __name__ == "__main__":
    print("=== Multi-Timeframe Chartink + Grok API + DB Pipeline (With Priority Deduplication) ===")
    grok_key = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
    run_all_screeners(api_key=grok_key, top_n=20)

