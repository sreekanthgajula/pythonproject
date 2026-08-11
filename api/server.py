import sys
import os
from pathlib import Path
import threading
import time
import numpy as np

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict
import uuid
import datetime
import pandas as pd

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.zerodha import get_zerodha_stock_df
from momentum_volume_monitor import analyze_market_data

app = FastAPI(title="TradingAgents API")

# Allow all origins for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for analysis jobs
jobs: Dict[str, dict] = {}

# Watchlist & Active Alerts storage
watchlist = {"RELIANCE.NS"}
active_alerts = []
last_alerted_candle = {}

class WatchlistRequest(BaseModel):
    ticker: str

def get_benchmark_ticker(ticker: str) -> str:
    ticker = ticker.upper()
    if ticker.endswith(".NS"):
        return "^NSEI"
    elif ticker.endswith(".BO"):
        return "^BSESN"
    else:
        return "SPY"

def fetch_history(ticker: str, start_date: str, end_date: str, interval: str = "10minute") -> pd.DataFrame:
    df = pd.DataFrame()
    zerodha_configured = False
    try:
        from tradingagents.dataflows.zerodha import get_zerodha_credentials
        creds = get_zerodha_credentials()
        if creds.get("api_key") and (creds.get("access_token") or creds.get("request_token")):
            zerodha_configured = True
    except Exception:
        pass

    if zerodha_configured:
        try:
            df = get_zerodha_stock_df(ticker.upper(), start_date, end_date, interval=interval)
        except Exception as e:
            print(f"[WARNING] Failed to fetch {interval} chart data from Zerodha for {ticker}: {e}")

    if df.empty:
        try:
            import yfinance as yf
            from tradingagents.dataflows.symbol_utils import normalize_symbol
            from tradingagents.dataflows.stockstats_utils import yf_retry
            canonical = normalize_symbol(ticker)
            ticker_obj = yf.Ticker(canonical)
            yf_interval = "10m" if interval == "10minute" else "1d"
            hist = yf_retry(lambda: ticker_obj.history(start=start_date, end=end_date, interval=yf_interval))
            if not hist.empty:
                hist = hist.reset_index()
                date_col = None
                for candidate in ("Datetime", "Date", "index", "date"):
                    if candidate in hist.columns:
                        date_col = candidate
                        break
                if date_col:
                    hist = hist.rename(columns={date_col: "Date"})
                df = hist[["Date", "Open", "High", "Low", "Close", "Volume"]]
        except Exception as e:
            print(f"[WARNING] Failed to fetch yfinance data for {ticker}: {e}")
            
    if not df.empty:
        df = df.rename(columns={"Date": "timestamp"})
        df.columns = [c.lower() for c in df.columns]
    return df

def monitor_watchlist():
    print("[MONITOR] Starting background watchlist monitoring thread...")
    while True:
        try:
            # Check every 60 seconds
            time.sleep(60)
            
            tickers_to_check = list(watchlist)
            if not tickers_to_check:
                continue
                
            end_date = datetime.datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.datetime.now() - datetime.timedelta(days=15)).strftime("%Y-%m-%d")
            
            for ticker in tickers_to_check:
                print(f"[MONITOR] Checking {ticker} for breakouts...")
                df = fetch_history(ticker, start_date, end_date, interval="10minute")
                if df.empty or len(df) < 30:
                    continue
                    
                # Run TSI-OBV divergence pattern detector
                from scripts.tsi_obv_divergence import detect_toad_pattern
                df_result, signals = detect_toad_pattern(df)
                
                if signals.empty:
                    continue
                    
                # Check for recent signal (index >= len(df) - 2)
                latest_signals = signals[signals["index"] >= len(df) - 2]
                if latest_signals.empty:
                    continue
                    
                latest_sig = latest_signals.iloc[-1]
                candle_time_str = str(latest_sig["time"])
                
                # Check if we already alerted on this candle
                if last_alerted_candle.get(ticker) == candle_time_str:
                    continue
                    
                # Validate the signal
                from scripts.signal_validator import SignalValidator
                bench_ticker = get_benchmark_ticker(ticker)
                bench_df = fetch_history(bench_ticker, start_date, end_date, interval="10minute")
                
                validator = SignalValidator(benchmark_ticker=bench_ticker)
                signal_payload = {
                    "ticker": ticker,
                    "price": float(latest_sig["price"])
                }
                
                is_valid, reason, confidence_score = validator.validate_signal(
                    signal_payload, df_result, bench_df
                )
                
                if is_valid:
                    print(f"[ALERT] Valid breakout detected for {ticker} at {latest_sig['price']}!")
                    last_alerted_candle[ticker] = candle_time_str
                    
                    # Calculate obv_zscore and tsi_slope for send_alert
                    df_result["obv_diff_2"] = df_result["obv"].diff(2)
                    rolling_mean_20 = df_result["obv_diff_2"].rolling(window=20).mean()
                    rolling_std_20 = df_result["obv_diff_2"].rolling(window=20).std(ddof=0)
                    safe_std = rolling_std_20.replace(0, np.nan)
                    df_result["obv_zscore"] = (df_result["obv_diff_2"] - rolling_mean_20) / safe_std
                    df_result["obv_zscore"] = df_result["obv_zscore"].fillna(0.0)
                    df_result["tsi_slope_2"] = df_result["tsi"].diff(2)
                    df_result["tsi_crossed_above"] = (
                        (df_result["tsi"].shift(1) <= df_result["tsi_signal"].shift(1)) &
                        (df_result["tsi"] > df_result["tsi_signal"])
                    )
                    
                    latest_row = df_result.iloc[-1]
                    
                    # Record alert
                    active_alerts.append({
                        "id": str(uuid.uuid4()),
                        "ticker": ticker.upper(),
                        "price": float(latest_sig["price"]),
                        "timestamp": candle_time_str,
                        "confidence": round(confidence_score, 2),
                        "reason": reason,
                        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    
                    # Send alert via Discord/Telegram
                    from momentum_volume_monitor import send_alert
                    send_alert(
                        ticker=ticker,
                        timestamp=candle_time_str,
                        price=float(latest_sig["price"]),
                        obv_zscore=float(latest_row.get("obv_zscore", 0.0)),
                        tsi_slope=float(latest_row.get("tsi_slope_2", 0.0)),
                        tsi_val=float(latest_row["tsi"]),
                        tsi_signal_val=float(latest_row["tsi_signal"]),
                        obv_condition=True,
                        tsi_condition=True,
                        tsi_crossed=bool(latest_row.get("tsi_crossed_above", False))
                    )
        except Exception as e:
            print(f"[ERROR] Error in watchlist monitoring loop: {e}")

@app.on_event("startup")
def startup_event():
    # Verify Zerodha connection and trigger login if invalid
    try:
        from tradingagents.dataflows.zerodha import get_access_token, get_zerodha_credentials, is_token_valid
        creds = get_zerodha_credentials()
        api_key = creds.get("api_key")
        access_token = creds.get("access_token")
        api_url = creds.get("api_url", "https://api.kite.trade")
        
        if api_key:
            if not is_token_valid(api_key, access_token, api_url):
                print("[STARTUP] Zerodha access token is expired or invalid. Initiating re-authentication...")
                # This will automatically prompt for OTP on standard input if user credentials are configured
                get_access_token()
            else:
                print("[STARTUP] Zerodha API connection is working successfully!")
    except Exception as e:
        print(f"[STARTUP] Error during Zerodha authentication check: {e}")

    threading.Thread(target=monitor_watchlist, daemon=True).start()

@app.get("/api/watchlist")
def get_watchlist():
    return list(watchlist)

@app.post("/api/watchlist/add")
def add_to_watchlist(req: WatchlistRequest):
    ticker_clean = req.ticker.strip().upper()
    if not ticker_clean:
        raise HTTPException(status_code=400, detail="Invalid ticker name")
    watchlist.add(ticker_clean)
    return {"status": "success", "watchlist": list(watchlist)}

@app.post("/api/watchlist/remove")
def remove_from_watchlist(req: WatchlistRequest):
    ticker_clean = req.ticker.strip().upper()
    if ticker_clean in watchlist:
        watchlist.remove(ticker_clean)
    return {"status": "success", "watchlist": list(watchlist)}

@app.get("/api/alerts")
def get_alerts():
    return active_alerts

class TotpRequest(BaseModel):
    totp: str

@app.get("/api/zerodha/status")
def get_zerodha_status():
    from tradingagents.dataflows.zerodha import get_zerodha_credentials, is_token_valid
    creds = get_zerodha_credentials()
    api_key = creds.get("api_key")
    api_secret = creds.get("api_secret")
    access_token = creds.get("access_token")
    api_url = creds.get("api_url", "https://api.kite.trade")
    
    user_id = os.environ.get("ZERODHA_USERNAME")
    password = os.environ.get("ZERODHA_PASSWORD")

    if not api_key or not api_secret:
        return {"configured": False, "status": "no_credentials"}
        
    valid = is_token_valid(api_key, access_token, api_url)
    if valid:
        return {"configured": True, "status": "valid"}
    else:
        if user_id and password:
            return {"configured": True, "status": "expired"}
        else:
            return {"configured": True, "status": "no_user_creds"}

@app.post("/api/zerodha/login")
def post_zerodha_login(req: TotpRequest):
    from tradingagents.dataflows.zerodha import (
        get_zerodha_credentials,
        get_request_token_via_totp,
        _exchange_request_token,
        _update_env_file,
    )
    creds = get_zerodha_credentials()
    api_key = creds.get("api_key")
    api_secret = creds.get("api_secret")
    api_url = creds.get("api_url", "https://api.kite.trade")
    
    user_id = os.environ.get("ZERODHA_USERNAME")
    password = os.environ.get("ZERODHA_PASSWORD")
    
    if not api_key or not api_secret or not user_id or not password:
        raise HTTPException(status_code=400, detail="Missing Zerodha credentials (API keys, username, or password) in environment.")
        
    try:
        request_token = get_request_token_via_totp(user_id, password, api_key, twofa_pin=req.totp)
        _update_env_file("ZERODHA_REQUEST_TOKEN", request_token)
        os.environ["ZERODHA_REQUEST_TOKEN"] = request_token
        
        access_token = _exchange_request_token(api_key, request_token, api_secret, api_url)
        return {"status": "success", "access_token": access_token}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class AnalyzeRequest(BaseModel):
    ticker: str
    asset_type: str = "stock"
    analysts: List[str] = ["market", "social", "news", "fundamentals"]

def run_analysis_background(job_id: str, ticker: str, asset_type: str, analysts: List[str]):
    try:
        config = DEFAULT_CONFIG.copy()
        set_config(config)
        
        # Initialize the LangGraph-based TradingAgentsGraph
        graph = TradingAgentsGraph(selected_analysts=analysts, config=config, debug=False)
        
        analysis_date = datetime.datetime.now().strftime("%Y-%m-%d")
        
        instrument_context = graph.resolve_instrument_context(ticker, asset_type)
        init_agent_state = graph.propagator.create_initial_state(
            ticker, analysis_date, asset_type=asset_type, instrument_context=instrument_context
        )
        args = graph.propagator.get_graph_args()

        final_state = {}
        for chunk in graph.graph.stream(init_agent_state, **args):
            final_state.update(chunk)
            jobs[job_id]["state"] = final_state
        
        jobs[job_id]["status"] = "completed"
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)

@app.post("/api/analyze")
def start_analysis(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "state": {}}
    background_tasks.add_task(run_analysis_background, job_id, req.ticker.upper(), req.asset_type, req.analysts)
    return {"job_id": job_id}

@app.get("/api/status/{job_id}")
def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]

@app.get("/api/chart/{ticker}")
def get_chart_data(ticker: str):
    try:
        ticker_clean = ticker.strip().upper()
        if ticker_clean:
            watchlist.add(ticker_clean)
            
        end_date = datetime.datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        
        # Fetch from Zerodha or fallback to yfinance
        df = pd.DataFrame()
        zerodha_configured = False
        try:
            from tradingagents.dataflows.zerodha import get_zerodha_credentials
            creds = get_zerodha_credentials()
            if creds.get("api_key") and (creds.get("access_token") or creds.get("request_token")):
                zerodha_configured = True
        except Exception:
            pass

        if zerodha_configured:
            try:
                # Fetch 10minute candles from Zerodha
                df = get_zerodha_stock_df(ticker.upper(), start_date, end_date, interval="10minute")
            except Exception as e:
                print(f"[WARNING] Failed to fetch 10minute chart data from Zerodha: {e}. Falling back to yfinance.")

        if df.empty:
            import yfinance as yf
            from tradingagents.dataflows.symbol_utils import normalize_symbol
            from tradingagents.dataflows.stockstats_utils import yf_retry
            canonical = normalize_symbol(ticker)
            ticker_obj = yf.Ticker(canonical)
            # Use 10m interval for intraday data
            hist = yf_retry(lambda: ticker_obj.history(start=start_date, end=end_date, interval="10m"))
            if not hist.empty:
                hist = hist.reset_index()
                # Find date/datetime column
                date_col = None
                for candidate in ("Datetime", "Date", "index", "date"):
                    if candidate in hist.columns:
                        date_col = candidate
                        break
                if date_col:
                    hist = hist.rename(columns={date_col: "Date"})
                df = hist[["Date", "Open", "High", "Low", "Close", "Volume"]]

        if df.empty:
            raise HTTPException(status_code=404, detail="No data found")
            
        # Format for analyze_market_data
        df = df.rename(columns={"Date": "timestamp"})
        df.columns = [c.lower() for c in df.columns]
        
        # This will calculate obv, tsi, tsi_signal, etc.
        # It returns (signal_dict, processed_df)
        _, processed_df = analyze_market_data(df)
        
        processed_df = processed_df.fillna(0)
        
        chart_data = []
        for _, row in processed_df.iterrows():
            ts = row["timestamp"]
            if isinstance(ts, str):
                ts = pd.to_datetime(ts)
            
            if hasattr(ts, "timestamp"):
                epoch_seconds = int(ts.timestamp())
            else:
                epoch_seconds = int(ts)
                
            obv_cond = float(row.get("obv_zscore", 0.0)) > 2.0
            tsi_cond = (float(row.get("tsi_slope_2", 0.0)) > 2.5) or bool(row.get("tsi_crossed_above", False))
            is_breakout = obv_cond and tsi_cond
                
            chart_data.append({
                "time": epoch_seconds,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "obv": row["obv"],
                "tsi": row["tsi"],
                "tsi_signal": row["tsi_signal"],
                "is_breakout": is_breakout
            })
            
        return chart_data
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True)
