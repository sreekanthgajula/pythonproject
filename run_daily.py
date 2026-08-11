import os
from pathlib import Path
import json
import urllib.request
import urllib.parse
from datetime import datetime
from bs4 import BeautifulSoup
import argparse

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# Configuration
CHARTINK_URL = "https://chartink.com/screener/true-strength-weekly"
PROCESS_URL = "https://chartink.com/screener/process"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

def fetch_top_tickers(limit=40):
    """Fetch the top N stock tickers from the Chartink screener."""
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    
    print(f"[{datetime.now()}] Fetching Chartink screener page...")
    req = urllib.request.Request(CHARTINK_URL, headers=HEADERS)
    with opener.open(req) as response:
        html = response.read().decode('utf-8')
        
    soup = BeautifulSoup(html, "html.parser")
    csrf_token = soup.find("meta", {"name": "csrf-token"})["content"]
    
    scanner = soup.find("scanner")
    if not scanner:
        raise Exception("Scanner element not found in Chartink HTML.")
        
    scan_json_str = scanner.get(":scan-json")
    if not scan_json_str:
        raise Exception(":scan-json attribute not found.")
        
    scan_data = json.loads(scan_json_str)
    scan_clause = scan_data["atlas_query"]
    
    # Perform POST to get the JSON result
    post_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "x-csrf-token": csrf_token,
        "Referer": CHARTINK_URL,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
    }
    post_data = urllib.parse.urlencode({"scan_clause": scan_clause}).encode('utf-8')
    post_req = urllib.request.Request(PROCESS_URL, data=post_data, headers=post_headers, method="POST")
    
    print(f"[{datetime.now()}] Posting scan clause to retrieve stock data...")
    with opener.open(post_req) as post_response:
        res_data = post_response.read().decode('utf-8')
        
    res_json = json.loads(res_data)
    records = res_json.get("data", [])
    
    # Extract and format tickers
    ignored_patterns = ["CNX", "NIFTY", "BANKNIFTY", "MOMENTM", "ALPHA"]
    
    all_stocks = []
    for r in records:
        nse_code = r.get("nsecode")
        if not nse_code:
            continue
            
        # Filter out index codes
        if any(pat in nse_code.upper() for pat in ignored_patterns):
            continue
            
        all_stocks.append({
            "ticker": f"{nse_code.upper()}.NS",
            "name": r.get("name"),
            "close": r.get("close"),
            "change": float(r.get("per_chg") or 0.0),
            "volume": int(r.get("volume") or 0)
        })
        
    # Sort the ENTIRE stock list by percentage change descending
    all_stocks.sort(key=lambda x: x["change"], reverse=True)
    
    # Take the top N
    return all_stocks[:limit]

def run_daily_analysis(limit=40, test_mode=False):
    """Run analysis on the top tickers and save a consolidated summary."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    print("====================================================")
    print(f"Starting Daily Run for {today_str}")
    print("====================================================")
    
    # Fetch tickers
    try:
        tickers = fetch_top_tickers(limit=limit)
    except Exception as e:
        print(f"Error fetching tickers from Chartink: {e}")
        return
        
    print(f"Found {len(tickers)} stock tickers to analyze.")
    
    if test_mode:
        print("TEST MODE: Running only the first 2 tickers.")
        tickers = tickers[:2]
        
    # Check for API keys
    # Load dotenv if present
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
        
    # Check if we have credentials
    has_credentials = any(k in os.environ for k in ["OPENAI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "TRADINGAGENTS_LLM_PROVIDER"])
    if not has_credentials and not os.environ.get("TRADINGAGENTS_LLM_PROVIDER") == "ollama":
        print("[WARNING] No LLM API keys found in the environment. The agents will fail to execute unless a local Ollama server is configured.")
        
    # Initialize TradingAgentsGraph
    config = DEFAULT_CONFIG.copy()
    
    # We enable checkpointing to allow resuming in case of individual ticker failure or LLM rate limits
    config["checkpoint_enabled"] = True
    
    ta = TradingAgentsGraph(debug=False, config=config)
    
    results = []
    
    # Ensure reports directory exists
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    summary_file = reports_dir / f"daily_summary_{today_str}.md"
    
    for idx, item in enumerate(tickers, 1):
        ticker = item["ticker"]
        name = item["name"]
        print(f"\n[{idx}/{len(tickers)}] Analyzing {ticker} ({name}) - Close: {item['close']}, Change: {item['change']}%")
        
        try:
            # Propagate graph to get decision
            final_state, decision = ta.propagate(ticker, today_str)
            
            # Extract final recommendation details
            recommendation = decision.get("action") or "Unknown"
            quantity = decision.get("quantity") or 0
            reason = decision.get("reason") or "No reason provided."
            
            print(f"Result for {ticker}: {recommendation} (Qty: {quantity})")
            results.append({
                "ticker": ticker,
                "name": name,
                "close": item["close"],
                "change": item["change"],
                "recommendation": recommendation,
                "quantity": quantity,
                "reason": reason,
                "status": "Success"
            })
        except Exception as e:
            print(f"Error analyzing {ticker}: {e}")
            results.append({
                "ticker": ticker,
                "name": name,
                "close": item["close"],
                "change": item["change"],
                "recommendation": "ERROR",
                "quantity": 0,
                "reason": str(e),
                "status": "Failed"
            })
            
    # Write summary markdown report
    print(f"\n[{datetime.now()}] Writing consolidated summary to {summary_file}...")
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(f"# Daily Trading Agents Summary: {today_str}\n\n")
        f.write(f"Analyzed {len(results)} stocks from Chartink's True Strength Weekly screener.\n\n")
        
        f.write("## Decisions Table\n\n")
        f.write("| Ticker | Name | Close | Change | Recommendation | Quantity | Status |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for r in results:
            f.write(f"| `{r['ticker']}` | {r['name']} | {r['close']} | {r['change']}% | **{r['recommendation']}** | {r['quantity']} | {r['status']} |\n")
            
        f.write("\n## Detailed Recommendations\n\n")
        for r in results:
            f.write(f"### {r['ticker']} - {r['name']}\n")
            f.write(f"- **Close**: {r['close']} (Change: {r['change']}%)\n")
            f.write(f"- **Action**: **{r['recommendation']}** (Qty: {r['quantity']})\n")
            f.write(f"- **Reasoning**: {r['reason']}\n\n")
            f.write("---\n\n")
            
    print(f"Daily run completed. Summary saved to {summary_file.resolve()}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run daily TradingAgents analysis for Chartink top stocks.")
    parser.add_argument("--limit", type=int, default=40, help="Max number of tickers to analyze (default: 40)")
    parser.add_argument("--test", action="store_true", help="Run in test mode (analyzes only 2 tickers)")
    args = parser.parse_args()
    
    run_daily_analysis(limit=args.limit, test_mode=args.test)
