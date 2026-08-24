"""
===============================================================================
GROK API & CHARTINK SCREENER PIPELINE (WITH DB PERSISTENCE)
===============================================================================
Description:
    1. Extracts the top 20 stock symbols from Chartink screener.
    2. Sends the symbols to Grok API with the context:
       "I will list stock symbols. I want you to judge which stock has higher
        potential based on its future prediction, current spike in volume, and news."
    3. Parses the Grok JSON response (stock name, rating, reason).
    4. Automatically saves the structured ratings into your MongoDB database table
       ('monthly', 'weekly', or 'daily').
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

def get_chartink_symbols(screener_url: str = "https://chartink.com/screener/true-strength-monthly", top_n: int = 20) -> list[str]:
    """
    Fetches screener results from Chartink, sorts by % gain, and extracts
    just the symbol list (e.g. ['WELCORP', 'AEROFLEX', 'KERNEX', ...]).
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
    timeframe_table: str = "monthly",
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
        f"Here is a list of stock symbols: {symbols_str}.\n"
        f"I want you to judge which stock has higher potential based on its future prediction, "
        f"current spike in volume, and news.\n\n"
        f"Return your output strictly as a JSON array of objects. Do not include markdown code block quotes. "
        f"Each object MUST contain these exact keys:\n"
        f"  - \"symbol\": stock ticker (e.g. \"WELCORP\")\n"
        f"  - \"rating\": numeric rating from 1.0 to 5.0 (where 5.0 is highest potential)\n"
        f"  - \"reason\": concise explanation evaluating volume spike, news, and future potential\n\n"
        f"Example JSON output format:\n"
        f"[\n"
        f"  {{\"symbol\": \"WELCORP\", \"rating\": 4.8, \"reason\": \"Strong volume spike of +15.3% with bullish order pipeline.\"}}\n"
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
                "content": "You are Grok, an expert financial market AI that evaluates stock potential and outputs raw structured JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.2
    }

    print(f"Sending {len(symbols)} symbols to Grok API ({model})...\n")
    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        logger.error(f"Grok API request failed: {response.status_code} - {response.text}")
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
        logger.error(f"Failed to parse Grok JSON response: {e}\nRaw text: {raw_content[:300]}")
        return []

    # Insert/update parsed ratings into MongoDB database table
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
        print(f"\nSuccessfully inserted {saved_count} stock ratings into '{timeframe_table}' database table!")
    except Exception as db_err:
        logger.error(f"Database insertion failed: {db_err}")

    return ratings_data

if __name__ == "__main__":
    screener_link = "https://chartink.com/screener/true-strength-monthly"
    print(f"=== Chartink + Grok API + DB Persistence Pipeline ===")
    
    # 1. Grab symbols from Chartink screener
    symbols = get_chartink_symbols(screener_link, top_n=20)
    print(f"Extracted {len(symbols)} symbols from Chartink:")
    print(symbols)
    print("-" * 70)
    
    # 2. Call Grok API and persist to 'monthly' table if key present
    grok_key = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
    if grok_key:
        ratings = analyze_and_rate_with_grok(symbols, timeframe_table="monthly", api_key=grok_key)
        print("\n=== Parsed Ratings & Database Status ===")
        for r in ratings[:10]:
            print(f"Symbol: {r.get('symbol'):<12} | Rating: {r.get('rating'):<5} | Reason: {r.get('reason')}")
    else:
        print("\n[NOTE] To execute live Grok API analysis & save to your DB table, add your key to .env:")
        print("GROK_API_KEY=xai-xxxxxxxxxxxxxxxxxxxxxxxx")
