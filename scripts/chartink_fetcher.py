"""
===============================================================================
CHARTINK SCREENER FETCHER & RANKING ENGINE
===============================================================================
Description:
    Fetches real-time stock screener results directly from any Chartink link
    (e.g., https://chartink.com/screener/true-strength-monthly).
    Extracts the dynamic atlas/scan query, requests Chartink's backend API,
    and returns top stocks sorted by percentage price gain.
===============================================================================
"""

import json
import html
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def get_chartink_sorted_stocks(screener_url: str, top_n: int = 20, sort_by: str = "per_chg", reverse: bool = True):
    """
    Fetches matching stocks from a Chartink screener URL and returns them sorted.
    
    Args:
        screener_url (str): Full Chartink screener URL (e.g. https://chartink.com/screener/true-strength-monthly)
        top_n (int): Number of top stocks to return. Default 20.
        sort_by (str): Stock dict key to sort by (e.g. 'per_chg', 'close', 'volume'). Default 'per_chg'.
        reverse (bool): True for descending (highest first), False for ascending. Default True.
        
    Returns:
        list[dict]: List of stock dictionaries containing nsecode, name, close, per_chg, volume, etc.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }

    session = requests.Session()
    try:
        response = session.get(screener_url, headers=headers)
        if response.status_code != 200:
            logger.error(f"Failed to fetch Chartink page: HTTP status {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract CSRF token
        csrf_meta = soup.find('meta', {'name': 'csrf-token'})
        csrf_token = csrf_meta['content'] if csrf_meta else ''

        # Extract scanner JSON attribute from Vue <scanner> tag
        scanner_tag = soup.find('scanner')
        if not scanner_tag or not scanner_tag.get(':scan-json'):
            logger.error("Could not find scan conditions on Chartink page HTML.")
            return []

        scan_json = json.loads(html.unescape(scanner_tag.get(':scan-json')))
        scan_clause = scan_json.get('atlas_query') or scan_json.get('scan_clause')

        if not scan_clause:
            logger.error("Failed to parse atlas query clause from Chartink JSON.")
            return []

        # Send POST request to Chartink AJAX endpoint
        api_url = 'https://chartink.com/screener/process'
        post_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'X-CSRF-TOKEN': csrf_token,
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': screener_url
        }

        res = session.post(api_url, data={'scan_clause': scan_clause}, headers=post_headers)
        if res.status_code == 200:
            stocks = res.json().get('data', [])
            # Sort stocks by requested field (default: per_chg)
            sorted_stocks = sorted(stocks, key=lambda x: float(x.get(sort_by, 0.0)), reverse=reverse)
            return sorted_stocks[:top_n]
        else:
            logger.error(f"Chartink API request failed with HTTP status {res.status_code}")
            return []
            
    except Exception as e:
        logger.exception(f"Error fetching Chartink screener: {e}")
        return []

if __name__ == "__main__":
    screener_url = "https://chartink.com/screener/true-strength-monthly"
    print(f"Fetching and sorting top stocks by % increase from: {screener_url}\n")
    top_stocks = get_chartink_sorted_stocks(screener_url, top_n=20)
    
    print(f"{'#':<3} | {'Symbol':<12} | {'Company Name':<38} | {'Close (INR)':<10} | {'% Increase':<12} | {'Volume':<12}")
    print("-" * 98)
    for i, stock in enumerate(top_stocks, 1):
        symbol = stock.get("nsecode") or stock.get("bsecode") or "N/A"
        name = stock.get("name", "N/A")
        close = float(stock.get("close", 0.0))
        per_chg = float(stock.get("per_chg", 0.0))
        volume = int(stock.get("volume", 0))
        print(f"{i:<3} | {symbol:<12} | {name:<38} | {close:<10.2f} | {per_chg:<+12.2f}% | {volume:<12,}")
