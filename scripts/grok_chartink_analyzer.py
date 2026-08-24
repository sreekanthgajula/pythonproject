"""
===============================================================================
GROK API & CHARTINK SCREENER INTEGRATION
===============================================================================
Description:
    1. Extracts the top 20 stock symbols from a Chartink screener link
       (sorted by % price increase).
    2. Formats the list of symbols and passes them to xAI's Grok API
       (https://api.x.ai/v1/chat/completions) for AI market analysis.
===============================================================================
"""

import os
import sys
import json
import logging
import requests
from pathlib import Path
from dotenv import load_dotenv

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from scripts.chartink_fetcher import get_chartink_sorted_stocks

# Load .env variables
load_dotenv(dotenv_path=project_root / ".env")

logger = logging.getLogger(__name__)

def get_chartink_symbols(screener_url: str = "https://chartink.com/screener/true-strength-monthly", top_n: int = 20) -> list[str]:
    """
    Fetches the screener result from Chartink, sorts by % gain, and extracts
    just the symbol list (e.g. ['WELCORP', 'AEROFLEX', 'KERNEX', ...]).
    
    Args:
        screener_url (str): Chartink screener URL.
        top_n (int): Number of top symbols to extract. Default 20.
        
    Returns:
        list[str]: Clean list of stock ticker symbols.
    """
    stocks = get_chartink_sorted_stocks(screener_url=screener_url, top_n=top_n, sort_by="per_chg", reverse=True)
    symbols = []
    for s in stocks:
        sym = s.get("nsecode") or s.get("bsecode")
        if sym and sym not in symbols:
            symbols.append(str(sym).upper())
    return symbols

def analyze_symbols_with_grok(
    symbols: list[str],
    api_key: str = None,
    model: str = "grok-2-latest",
    custom_prompt: str = None
) -> str:
    """
    Sends the list of stock symbols to xAI Grok API for AI technical/fundamental analysis.
    
    Args:
        symbols (list[str]): List of stock symbols (e.g. ['WELCORP', 'AEROFLEX', ...]).
        api_key (str, optional): Grok/xAI API key. Defaults to GROK_API_KEY or XAI_API_KEY in .env.
        model (str, optional): Grok model name. Defaults to 'grok-2-latest'.
        custom_prompt (str, optional): Custom prompt instructions for Grok.
        
    Returns:
        str: AI analysis response from Grok.
    """
    # Fallback to env keys
    grok_key = api_key or os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
    if not grok_key:
        raise ValueError(
            "Grok API Key not found! Please set GROK_API_KEY or XAI_API_KEY in your .env file, "
            "or pass api_key parameter to analyze_symbols_with_grok()."
        )

    symbols_str = ", ".join(symbols)

    if not custom_prompt:
        custom_prompt = (
            f"You are an expert quantitative technical analyst. Here are 20 high-momentum stock symbols "
            f"scanned from Chartink based on True Strength Index (TSI) and Volume Flow:\n\n"
            f"Symbols: {symbols_str}\n\n"
            f"Please perform a rapid analysis on these stocks and provide:\n"
            f"1. A breakdown of the top 3 highest probability breakout setups.\n"
            f"2. Key technical drivers (TSI momentum, OBV volume accumulation, key resistance levels).\n"
            f"3. Risk management guidelines (recommended Stop-Loss % and Risk-to-Reward targets)."
        )

    # Grok API Endpoint (xAI / OpenAI compatible)
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
                "content": "You are Grok, an advanced AI financial analyst specializing in stock market momentum, volume flow, and technical breakouts."
            },
            {
                "role": "user",
                "content": custom_prompt
            }
        ],
        "temperature": 0.2
    }

    print(f"Sending {len(symbols)} symbols to Grok API ({model})...\n")
    response = requests.post(url, headers=headers, json=payload)

    if response.status_code == 200:
        res_json = response.json()
        content = res_json["choices"][0]["message"]["content"]
        return content
    else:
        err_msg = f"Grok API request failed with status {response.status_code}: {response.text}"
        logger.error(err_msg)
        return err_msg

if __name__ == "__main__":
    screener_link = "https://chartink.com/screener/true-strength-monthly"
    print(f"=== Chartink + Grok API Pipeline ===")
    
    # 1. Grab symbols column from Chartink screener
    symbols = get_chartink_symbols(screener_link, top_n=20)
    print(f"Extracted {len(symbols)} symbols from Chartink:")
    print(symbols)
    print("-" * 60)
    
    # 2. Check if Grok API Key is available before attempting API call
    grok_key = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
    if grok_key:
        analysis = analyze_symbols_with_grok(symbols, api_key=grok_key)
        print("\n=== Grok AI Analysis Result ===")
        print(analysis)
    else:
        print("\n[NOTE] To execute live Grok API analysis, add your key to .env:")
        print("GROK_API_KEY=xai-xxxxxxxxxxxxxxxxxxxxxxxx")
