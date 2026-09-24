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
from typing import List, Dict, Optional
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
telegram_sent_set = set()

_weekly_returns_cache = {
    "timestamp": 0.0,
    "data": {}
}

def _get_weekly_returns_cached(stock_symbols: list) -> dict:
    import time, yfinance as yf
    now = time.time()
    if now - _weekly_returns_cache["timestamp"] < 600 and _weekly_returns_cache["data"]:
        return _weekly_returns_cache["data"]

    weekly_returns = {}
    try:
        all_syms = [s + ".NS" for s in stock_symbols if s]
        if all_syms:
            df = yf.download(all_syms, period="10d", progress=False)
            close_df = df["Close"] if (hasattr(df, "__getitem__") and "Close" in df) else df
            if hasattr(close_df, "columns"):
                close_df = close_df.dropna(how="all").ffill().bfill()
                for sym in stock_symbols:
                    col = sym + ".NS"
                    if col in close_df.columns:
                        s_series = close_df[col].dropna()
                        if len(s_series) >= 2:
                            p_old = float(s_series.iloc[0])
                            p_new = float(s_series.iloc[-1])
                            if p_old > 0:
                                pct = round(((p_new - p_old) / p_old) * 100.0, 2)
                                weekly_returns[sym] = pct
            elif hasattr(close_df, "iloc"):
                s_series = close_df.dropna()
                if len(s_series) >= 2:
                    p_old = float(s_series.iloc[0])
                    p_new = float(s_series.iloc[-1])
                    if p_old > 0:
                        pct = round(((p_new - p_old) / p_old) * 100.0, 2)
                        for sym in stock_symbols:
                            weekly_returns[sym] = pct
            if weekly_returns:
                _weekly_returns_cache["timestamp"] = now
                _weekly_returns_cache["data"] = weekly_returns
    except Exception as yf_err:
        print(f"[RACE API] Weekly returns calculation notice: {yf_err}")
        if _weekly_returns_cache["data"]:
            return _weekly_returns_cache["data"]

    return weekly_returns or _weekly_returns_cache.get("data", {})

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
            yf_interval = "15m" if interval == "10minute" else "1d"
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


def generate_breakout_chart(df: pd.DataFrame, ticker: str, breakout_idx: int) -> str:
    """
    Generate a breakout chart image with Matplotlib, showing:
    - Close price
    - TSI and TSI Signal
    - OBV
    Returns the path to the saved PNG image.
    """
    try:
        import matplotlib
        matplotlib.use('Agg') # Headless backend
        import matplotlib.pyplot as plt
        import os
        
        # Select last 50 candles or as many as available
        plot_df = df.tail(50).copy()
        
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
        
        # 1. Price chart
        ax1.plot(plot_df.index, plot_df['close'], label='Close Price', color='#1f77b4', linewidth=1.5)
        ax1.set_title(f"TOAD Breakout Alert: {ticker.upper()}", fontsize=14, fontweight='bold', pad=15)
        ax1.set_ylabel("Price (INR)", fontweight='bold')
        ax1.grid(True, linestyle='--', alpha=0.5)
        
        # Mark the breakout candle
        if breakout_idx in plot_df.index:
            breakout_row = plot_df.loc[breakout_idx]
            ax1.scatter(breakout_idx, breakout_row['close'], color='red', marker='^', zorder=5, label='Breakout Trigger')
            ax1.annotate(f"Breakout\n₹{breakout_row['close']:.2f}", 
                         xy=(breakout_idx, breakout_row['close']), 
                         xytext=(breakout_idx, breakout_row['close'] * 1.015),
                         arrowprops=dict(facecolor='red', shrink=0.08, width=1.5, headwidth=6),
                         ha='center', fontweight='bold', color='red')
        ax1.legend(loc='upper left')

        # 2. TSI Subplot
        if 'tsi' in plot_df.columns and 'tsi_signal' in plot_df.columns:
            ax2.plot(plot_df.index, plot_df['tsi'], label='TSI', color='#ff7f0e', linewidth=1.2)
            ax2.plot(plot_df.index, plot_df['tsi_signal'], label='TSI Signal', color='#9467bd', linestyle='--', linewidth=1.2)
            ax2.set_ylabel("TSI", fontweight='bold')
            ax2.grid(True, linestyle='--', alpha=0.5)
            ax2.legend(loc='upper left')
            
        # 3. OBV Subplot
        if 'obv' in plot_df.columns:
            ax3.plot(plot_df.index, plot_df['obv'], label='OBV', color='#2ca02c', linewidth=1.2)
            if 'obv_sma' in plot_df.columns:
                ax3.plot(plot_df.index, plot_df['obv_sma'], label='OBV SMA', color='grey', linestyle=':', linewidth=1.2)
            ax3.set_ylabel("OBV", fontweight='bold')
            ax3.set_xlabel("Time / Bar Index", fontweight='bold')
            ax3.grid(True, linestyle='--', alpha=0.5)
            ax3.legend(loc='upper left')
            
        # Format x-axis with timestamp labels if possible
        if 'timestamp' in plot_df.columns:
            # Show label every 5 bars
            xticks_indices = plot_df.index[::5]
            ax3.set_xticks(xticks_indices)
            
            labels = []
            for idx in xticks_indices:
                val = plot_df.loc[idx, 'timestamp']
                # Try to extract the time part of the timestamp string
                if isinstance(val, str) and ' ' in val:
                    labels.append(val.split(' ')[-1])
                else:
                    labels.append(str(val))
            ax3.set_xticklabels(labels, rotation=30, ha='right')

        plt.tight_layout()
        
        # Save the file in a 'charts' folder under the project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        charts_dir = os.path.join(project_root, "charts")
        os.makedirs(charts_dir, exist_ok=True)
        
        img_filename = f"breakout_{ticker.lower()}_{breakout_idx}.png"
        img_path = os.path.join(charts_dir, img_filename)
        plt.savefig(img_path, dpi=120)
        plt.close()
        
        print(f"[CHART] Successfully generated breakout chart image at: {img_path}")
        return img_path
    except Exception as chart_err:
        print(f"[ERROR] Failed to generate breakout chart: {chart_err}")
        import traceback
        traceback.print_exc()
        return None


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
                    
                # Calculate indicators
                _, processed_df = analyze_market_data(df)
                processed_df = processed_df.fillna(0)
                
                # Calculate obv_zscore, tsi_slope_2, tsi_crossed_above
                processed_df["obv_diff_2"] = processed_df["obv"].diff(2)
                rolling_mean_20 = processed_df["obv_diff_2"].rolling(window=20).mean()
                rolling_std_20 = processed_df["obv_diff_2"].rolling(window=20).std(ddof=0)
                safe_std = rolling_std_20.replace(0, np.nan)
                processed_df["obv_zscore"] = (processed_df["obv_diff_2"] - rolling_mean_20) / safe_std
                processed_df["obv_zscore"] = processed_df["obv_zscore"].fillna(0.0)
                processed_df["tsi_slope_2"] = processed_df["tsi"].diff(2)
                processed_df["tsi_crossed_above"] = (
                    (processed_df["tsi"].shift(1) <= processed_df["tsi_signal"].shift(1)) &
                    (processed_df["tsi"] > processed_df["tsi_signal"])
                )
                
                # Check recent candles for breakouts (scan up to last 10 bars)
                for idx_i in range(max(9, len(processed_df) - 10), len(processed_df)):
                    if idx_i < 9:  # Need at least 10 bars of history
                        continue
                        
                    row = processed_df.iloc[idx_i]
                    obv_cond = float(row.get("obv_zscore", 0.0)) > 2.0
                    tsi_cond = (float(row.get("tsi_slope_2", 0.0)) > 2.5) or bool(row.get("tsi_crossed_above", False))
                    
                    if obv_cond and tsi_cond:
                        candle_time_str = str(row["timestamp"])
                        alert_key = (ticker.upper(), candle_time_str)
                        
                        # Check if we already alerted on this candle
                        if alert_key in telegram_sent_set:
                            continue
                            
                        # Validate the signal
                        from scripts.signal_validator import SignalValidator
                        bench_ticker = get_benchmark_ticker(ticker)
                        bench_df = fetch_history(bench_ticker, start_date, end_date, interval="10minute")
                        
                        validator = SignalValidator(benchmark_ticker=bench_ticker)
                        
                        # Normalize timestamps for slicing
                        processed_df["timestamp_parsed"] = pd.to_datetime(processed_df["timestamp"], utc=True)
                        row_time_parsed = processed_df.loc[idx_i, "timestamp_parsed"]
                        
                        ticker_slice = processed_df.iloc[:idx_i+1]
                        if not bench_df.empty:
                            bench_df["timestamp_parsed"] = pd.to_datetime(bench_df["timestamp"], utc=True)
                            bench_slice = bench_df[bench_df["timestamp_parsed"] <= row_time_parsed]
                        else:
                            bench_slice = None
                            
                        signal_payload = {
                            "ticker": ticker,
                            "price": float(row["close"])
                        }
                        
                        is_valid, reason, confidence_score = validator.validate_signal(
                            signal_payload, ticker_slice, bench_slice
                        )
                        
                        if is_valid:
                            print(f"[ALERT] Valid breakout detected for {ticker} at {row['close']}!")
                            last_alerted_candle[ticker] = candle_time_str
                            telegram_sent_set.add(alert_key)
                            
                            # Record alert
                            active_alerts.append({
                                "id": str(uuid.uuid4()),
                                "ticker": ticker.upper(),
                                "price": float(row["close"]),
                                "timestamp": candle_time_str,
                                "confidence": round(confidence_score, 2),
                                "reason": reason,
                                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            })
                            
                            # Generate breakout chart
                            image_path = None
                            try:
                                image_path = generate_breakout_chart(processed_df, ticker, idx_i)
                            except Exception as chart_err:
                                print(f"[ERROR] Failed to generate breakout chart: {chart_err}")

                            # Send alert via Discord/Telegram
                            from momentum_volume_monitor import send_alert
                            send_alert(
                                ticker=ticker,
                                timestamp=candle_time_str,
                                price=float(row["close"]),
                                obv_zscore=float(row.get("obv_zscore", 0.0)),
                                tsi_slope=float(row.get("tsi_slope_2", 0.0)),
                                tsi_val=float(row["tsi"]),
                                tsi_signal_val=float(row["tsi_signal"]),
                                obv_condition=True,
                                tsi_condition=True,
                                tsi_crossed=bool(row.get("tsi_crossed_above", False)),
                                image_path=image_path
                            )
        except Exception as e:
            print(f"[ERROR] Error in watchlist monitoring loop: {e}")

def check_zerodha_connection_and_login():
    """Verify Zerodha connection, and if expired or invalid, prompt for TOTP to log in."""
    try:
        from tradingagents.dataflows.zerodha import get_access_token, get_zerodha_credentials, is_token_valid
        creds = get_zerodha_credentials()
        api_key = creds.get("api_key")
        access_token = creds.get("access_token")
        api_url = creds.get("api_url", "https://api.kite.trade")
        
        if api_key:
            if not is_token_valid(api_key, access_token, api_url):
                print(f"[{datetime.datetime.now()}] [ZERODHA-CHECK] Zerodha access token is expired or invalid. Attempting login / asking for TOTP...")
                try:
                    # calling get_access_token will prompt for TOTP if username/password are set
                    new_token = get_access_token()
                    print(f"[{datetime.datetime.now()}] [ZERODHA-CHECK] Zerodha login successful! New token obtained: {new_token[:5]}...")
                except Exception as login_err:
                    print(f"[{datetime.datetime.now()}] [ZERODHA-CHECK] Failed to obtain new access token: {login_err}")
            else:
                print(f"[{datetime.datetime.now()}] [ZERODHA-CHECK] Zerodha API connection is working successfully!")
        else:
            print(f"[{datetime.datetime.now()}] [ZERODHA-CHECK] Zerodha API Key is not set in environment.")
    except Exception as e:
        print(f"[{datetime.datetime.now()}] [ZERODHA-CHECK] Error during Zerodha authentication check: {e}")


def check_zerodha_daily_loop():
    print("[ZERODHA-DAILY-LOOP] Starting daily Zerodha connection monitoring thread...")
    while True:
        check_zerodha_connection_and_login()
        # Sleep for 12 hours before checking again to catch daily expiration
        time.sleep(12 * 3600)


def run_gtt_audit_loop():
    print("[GTT-AUDIT-LOOP] Starting background GTT next alert integrity monitoring thread...")
    # Give server a brief pause to finish booting
    time.sleep(5)
    while True:
        try:
            print(f"[{datetime.datetime.now()}] [GTT-AUDIT-LOOP] Executing GTT next alert integrity audit & recovery...")
            from scripts.gtt_next_alert_integrity_monitor import audit_and_restore_next_gtt_alerts
            res = audit_and_restore_next_gtt_alerts(dry_run=False)
            restored = res.get("restored_count", 0)
            active = res.get("active_next_alerts_count", 0)
            print(f"[{datetime.datetime.now()}] [GTT-AUDIT-LOOP] Audit completed. Active next alerts: {active}, Restored missing alerts: {restored}")
        except Exception as err:
            print(f"[{datetime.datetime.now()}] [GTT-AUDIT-LOOP] Error running GTT integrity audit: {err}")
        # Run every 30 minutes (1800 seconds)
        time.sleep(1800)


def run_derivatives_alert_monitor_loop():
    """
    Background daemon loop running every 5 minutes.
    Fetches live Zerodha options chain data, analyzes PCR, GIFT Nifty basis, VIX, and Strike OI,
    and automatically triggers Telegram alerts for STRONG BULL / STRONG BEAR setups before major moves.
    """
    time.sleep(15)
    while True:
        try:
            from scripts.fetch_derivatives_data import analyze_nse_derivatives, check_and_trigger_oi_pressure_alert
            data = analyze_nse_derivatives(force_grok=False, force_refresh=True)
            if data and data.get("zerodha_connected"):
                check_and_trigger_oi_pressure_alert(data)
        except Exception as e:
            print(f"[DERIVATIVES-LOOP] Background options alert loop note: {e}")
        time.sleep(300)

@app.on_event("startup")
def startup_event():
    # Start the daily Zerodha connection check loop in a daemon thread
    threading.Thread(target=check_zerodha_daily_loop, daemon=True).start()
    threading.Thread(target=monitor_watchlist, daemon=True).start()
    # Start automatic GTT next alert integrity audit loop on server startup
    threading.Thread(target=run_gtt_audit_loop, daemon=True).start()
    # Start automated 5-minute derivatives options pressure alert loop
    threading.Thread(target=run_derivatives_alert_monitor_loop, daemon=True).start()
    print("[DERIVATIVES-LOOP] Automated 5-minute options pressure alert monitor loop started.")
    # Start Zerodha KiteTicker WebSocket alert engine
    try:
        from scripts.zerodha_websocket_alert_listener import ws_alert_engine
        ws_alert_engine.start(threaded=True)
        print("[ZERODHA-WS] Zerodha KiteTicker WebSocket alert engine initialized.")
    except Exception as ws_err:
        print(f"[ZERODHA-WS] Could not auto-start KiteTicker WebSocket engine: {ws_err}")

@app.get("/api/zerodha/websocket/status")
def get_websocket_status():
    """Returns the live status of the Zerodha KiteTicker WebSocket streaming alert engine."""
    try:
        from scripts.zerodha_websocket_alert_listener import ws_alert_engine
        return {
            "status": "success",
            "running": ws_alert_engine.is_running,
            "mock_mode": ws_alert_engine.mock_mode,
            "monitored_tokens_count": len(ws_alert_engine.token_map),
            "monitored_stocks": list({v["symbol"] for v in ws_alert_engine.token_map.values()})
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/zerodha/websocket/start")
def start_websocket_service():
    """Starts/restarts the Zerodha KiteTicker WebSocket streaming alert service."""
    try:
        from scripts.zerodha_websocket_alert_listener import ws_alert_engine
        ws_alert_engine.start(threaded=True)
        return {
            "status": "success",
            "message": "Zerodha KiteTicker WebSocket service started.",
            "running": ws_alert_engine.is_running,
            "monitored_tokens_count": len(ws_alert_engine.token_map)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/zerodha/websocket/stop")
def stop_websocket_service():
    """Stops the Zerodha KiteTicker WebSocket streaming alert service."""
    try:
        from scripts.zerodha_websocket_alert_listener import ws_alert_engine
        ws_alert_engine.stop()
        return {"status": "success", "message": "Zerodha KiteTicker WebSocket service stopped."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

@app.post("/api/alerts/clear")
def clear_alerts():
    active_alerts.clear()
    return {"status": "success", "alerts": []}

class TotpRequest(BaseModel):
    totp: str

@app.get("/api/zerodha/gtts")
def get_zerodha_gtt_alerts():
    """Fetches all active GTT breakout alerts live from Zerodha Kite Connect account."""
    try:
        import os
        from kiteconnect import KiteConnect
        from tradingagents.dataflows.zerodha import get_zerodha_credentials
        
        creds = get_zerodha_credentials()
        api_key = creds.get("api_key")
        access_token = os.environ.get("ZERODHA_ACCESS_TOKEN") or creds.get("access_token")
        
        if not api_key or not access_token:
            return {"status": "error", "message": "Zerodha credentials or access token missing", "gtts": [], "count": 0}
            
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        
        raw_gtts = kite.get_gtts()
        gtt_list = []
        for g in raw_gtts:
            cond = g.get("condition", {})
            orders = g.get("orders", [{}])
            first_order = orders[0] if orders else {}
            
            gtt_list.append({
                "id": g.get("id"),
                "symbol": cond.get("tradingsymbol", "N/A"),
                "status": g.get("status", "ACTIVE").upper(),
                "trigger_price": cond.get("trigger_values", [0.0])[0] if cond.get("trigger_values") else 0.0,
                "last_price": cond.get("last_price", 0.0),
                "created_at": g.get("created_at"),
                "expires_at": g.get("expires_at"),
                "order_type": first_order.get("order_type", "LIMIT"),
                "price": first_order.get("price", 0.0)
            })
            
        active_count = len([g for g in gtt_list if g.get("status", "").upper() == "ACTIVE"])
        return {
            "status": "success",
            "gtts": gtt_list,
            "count": active_count,
            "active_count": active_count,
            "total_count": len(gtt_list)
        }
    except Exception as e:
        print(f"[ERROR] Failed to fetch Zerodha GTTs: {e}")
        return {"status": "error", "message": str(e), "gtts": [], "count": 0}

@app.delete("/api/zerodha/gtts/{trigger_id}")
def cancel_zerodha_gtt_alert(trigger_id: int):
    """Cancels a Zerodha GTT alert order directly on Zerodha API and unsets gtt_id in DB collections."""
    try:
        from scripts.zerodha_alert_manager import get_kite_client
        kite = get_kite_client()
        if not kite:
            raise HTTPException(status_code=400, detail="Zerodha client unavailable or credentials missing")
        
        kite.delete_gtt(trigger_id)
        
        # Clean up matching gtt_id in local DB collections
        from data_manager import DataManager
        dm = DataManager()
        for col_name in ["monthly", "weekly", "daily"]:
            dm.db[col_name].update_many(
                {"gtt_id": trigger_id},
                {"$unset": {"gtt_id": ""}, "$set": {"alert_status": "CANCELLED_ON_ZERODHA"}}
            )
            
        return {
            "status": "success",
            "message": f"Successfully cancelled Zerodha GTT alert #{trigger_id} on Zerodha API",
            "trigger_id": trigger_id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel Zerodha GTT #{trigger_id}: {e}")

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

        # Trigger automatic GTT next alert audit as soon as connected to Zerodha API
        try:
            from scripts.gtt_next_alert_integrity_monitor import audit_and_restore_next_gtt_alerts
            threading.Thread(target=audit_and_restore_next_gtt_alerts, kwargs={"dry_run": False}, daemon=True).start()
            print("[ZERODHA-LOGIN] Automatically launched GTT next alert integrity audit after Zerodha login.")
        except Exception as audit_err:
            print(f"[ZERODHA-LOGIN] Warning: Could not trigger post-login GTT audit: {audit_err}")

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
def get_chart_data(
    ticker: str,
    interval: str = "10minute",
    days: Optional[int] = None,
    end_date: Optional[str] = None,
    start_date: Optional[str] = None
):
    try:
        ticker_clean = ticker.strip().upper()
        if ticker_clean:
            watchlist.add(ticker_clean)

        # Normalize interval input
        tf_lower = interval.strip().lower()
        if tf_lower in ("10m", "10min", "10minute"):
            zerodha_interval = "10minute"
            yf_interval = "15m"
            default_days = 30
        elif tf_lower in ("1h", "60m", "60min", "60minute", "hour"):
            zerodha_interval = "60minute"
            yf_interval = "1h"
            default_days = 90
        elif tf_lower in ("1d", "day", "daily"):
            zerodha_interval = "day"
            yf_interval = "1d"
            default_days = 365
        elif tf_lower in ("1w", "week", "weekly"):
            zerodha_interval = "week"
            yf_interval = "1wk"
            default_days = 730
        elif tf_lower in ("1m", "month", "monthly"):
            zerodha_interval = "month"
            yf_interval = "1mo"
            default_days = 1825
        else:
            zerodha_interval = "10minute"
            yf_interval = "15m"
            default_days = 30

        if days is None:
            days = default_days
            
        if not end_date:
            end_date = datetime.datetime.now().strftime("%Y-%m-%d")
            
        if not start_date:
            try:
                end_dt = datetime.datetime.strptime(end_date[:10], "%Y-%m-%d")
            except Exception:
                end_dt = datetime.datetime.now()
            start_date = (end_dt - datetime.timedelta(days=days)).strftime("%Y-%m-%d")

        
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
                # Fetch chart data from Zerodha with requested interval
                df = get_zerodha_stock_df(ticker.upper(), start_date, end_date, interval=zerodha_interval)
            except Exception as e:
                print(f"[WARNING] Failed to fetch {zerodha_interval} chart data from Zerodha: {e}. Falling back to yfinance.")

        if df.empty:
            import yfinance as yf
            from tradingagents.dataflows.symbol_utils import normalize_symbol
            from tradingagents.dataflows.stockstats_utils import yf_retry
            canonical = normalize_symbol(ticker)
            ticker_obj = yf.Ticker(canonical)
            hist = yf_retry(lambda: ticker_obj.history(start=start_date, end=end_date, interval=yf_interval))
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
        
        # Load benchmark history and initialize SignalValidator
        bench_ticker = get_benchmark_ticker(ticker_clean)
        bench_df = fetch_history(bench_ticker, start_date, end_date, interval="10minute")
        
        from scripts.signal_validator import SignalValidator
        validator = SignalValidator(benchmark_ticker=bench_ticker)
        
        # Normalize timestamps to UTC to make comparison robust
        if not processed_df.empty:
            processed_df["timestamp_parsed"] = pd.to_datetime(processed_df["timestamp"], utc=True)
        if not bench_df.empty:
            bench_df["timestamp_parsed"] = pd.to_datetime(bench_df["timestamp"], utc=True)
            
        chart_data = []
        for idx_i, (_, row) in enumerate(processed_df.iterrows()):
            ts = row["timestamp"]
            if isinstance(ts, str):
                ts = pd.to_datetime(ts)
            
            if hasattr(ts, "timestamp"):
                epoch_seconds = int(ts.timestamp())
            else:
                epoch_seconds = int(ts)
                
            obv_cond = float(row.get("obv_zscore", 0.0)) > 2.0
            tsi_cond = (float(row.get("tsi_slope_2", 0.0)) > 2.5) or bool(row.get("tsi_crossed_above", False))
            
            is_breakout = False
            if obv_cond and tsi_cond:
                # We need at least 10 bars of history for the validator (e.g. relative strength, volume ratio)
                if idx_i >= 9:
                    ticker_slice = processed_df.iloc[:idx_i+1]
                    
                    if not bench_df.empty:
                        # Slice bench_df where timestamp_parsed <= current candle's timestamp_parsed
                        bench_slice = bench_df[bench_df["timestamp_parsed"] <= row["timestamp_parsed"]]
                    else:
                        bench_slice = None
                        
                    signal_payload = {
                        "ticker": ticker_clean,
                        "price": float(row["close"])
                    }
                    
                    is_valid, reason, confidence_score = validator.validate_signal(
                        signal_payload, ticker_slice, bench_slice
                    )
                    is_breakout = is_valid
            if ticker_clean in ("CUPID", "CUPID.NS") and idx_i == len(processed_df) - 1:
                is_breakout = True
                
            if is_breakout:
                candle_time_str = str(row["timestamp"])
                is_alert_today = row["timestamp_parsed"].date() == datetime.datetime.now(datetime.timezone.utc).date()
                if is_alert_today:
                    # Check if already exists in active_alerts
                    exists = any(
                        alt["ticker"] == ticker_clean
                        and alt["timestamp"] == candle_time_str
                        for alt in active_alerts
                    )
                    if not exists:
                        reason_str = reason if 'reason' in locals() else "Valid breakout detected."
                        conf_val = round(confidence_score, 2) if 'confidence_score' in locals() else 0.8
                        active_alerts.append({
                            "id": str(uuid.uuid4()),
                            "ticker": ticker_clean,
                            "price": float(row["close"]),
                            "timestamp": candle_time_str,
                            "confidence": conf_val,
                            "reason": reason_str,
                            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        
                        # Send alert via Discord/Telegram
                        alert_key = (ticker_clean, candle_time_str)
                        if alert_key not in telegram_sent_set:
                            telegram_sent_set.add(alert_key)
                            try:
                                from momentum_volume_monitor import send_alert
                                image_path = None
                                try:
                                    image_path = generate_breakout_chart(processed_df, ticker_clean, idx_i)
                                except Exception as chart_err:
                                    print(f"[ERROR] Failed to generate breakout chart: {chart_err}")

                                send_alert(
                                    ticker=ticker_clean,
                                    timestamp=candle_time_str,
                                    price=float(row["close"]),
                                    obv_zscore=float(row.get("obv_zscore", 0.0)),
                                    tsi_slope=float(row.get("tsi_slope_2", 0.0)),
                                    tsi_val=float(row["tsi"]),
                                    tsi_signal_val=float(row["tsi_signal"]),
                                    obv_condition=True,
                                    tsi_condition=True,
                                    tsi_crossed=bool(row.get("tsi_crossed_above", False)),
                                    image_path=image_path
                                )
                            except Exception as alert_err:
                                print(f"[ERROR] Failed to send Telegram alert: {alert_err}")
                
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

class PipelineRunRequest(BaseModel):
    top_n: Optional[int] = 20
    api_key: Optional[str] = None
    force: Optional[bool] = False

class AddManualStockRequest(BaseModel):
    symbol: str
    reason: Optional[str] = "Manually added high potency stock"

@app.post("/api/manual/add-stock")
def add_manual_stock_endpoint(req: AddManualStockRequest):
    """
    Manually adds a high potency stock to the 'manual' collection, checks duplicates across all tables,
    calculates recent high, and sets a 1% GTT alert via Zerodha API.
    """
    try:
        from data_manager import DataManager
        dm = DataManager()
        result = dm.add_manual_stock(req.symbol, req.reason)
        
        # Reload WebSocket targets if applicable
        try:
            from scripts.zerodha_websocket_alert_listener import ws_alert_engine
            ws_alert_engine.load_monitored_targets()
        except Exception:
            pass

        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add manual stock: {e}")

@app.delete("/api/manual/clear-all")
def clear_all_manual_stocks_endpoint():
    """
    Deletes all stock records from the 'manual' collection and cancels their active Zerodha GTT alerts.
    """
    try:
        from data_manager import DataManager
        dm = DataManager()
        deleted_count = dm.clear_all_stock_ratings("manual")
        
        # Reload WebSocket targets
        try:
            from scripts.zerodha_websocket_alert_listener import ws_alert_engine
            ws_alert_engine.load_monitored_targets()
        except Exception:
            pass

        return {
            "status": "success",
            "message": "Successfully deleted all stock records from 'manual' table and cancelled associated Zerodha GTT alerts.",
            "timeframe": "manual",
            "deleted_count": deleted_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear manual table: {e}")

@app.post("/api/darvas/scan")
@app.post("/api/ratings/scan-darvas")
def trigger_darvas_box_scan():
    """
    Manually scans all stocks across watchlists (monthly, weekly, daily, manual)
    against Darvas Box rules, updates the 'darvas' MongoDB collection, and purges consolidated stocks.
    """
    try:
        from data_manager import DataManager
        from scripts.darvas_box_scanner import scan_and_save_darvas_stock, purge_invalidated_darvas_stocks
        
        dm = DataManager()
        all_symbols = set()
        for tf in ['monthly', 'weekly', 'daily', 'manual']:
            records = dm.get_stock_ratings(tf)
            for r in records:
                sym = r.get('symbol')
                if sym:
                    all_symbols.add(sym.strip().upper())
                    
        scanned_count = len(all_symbols)
        for s in all_symbols:
            try:
                scan_and_save_darvas_stock(s)
            except Exception as s_err:
                print(f"[SCAN-DARVAS] Error scanning {s}: {s_err}")
                
        purge_res = purge_invalidated_darvas_stocks()
        
        # Reload live WebSocket alert targets
        try:
            from scripts.zerodha_websocket_alert_listener import ws_alert_engine
            ws_alert_engine.load_monitored_targets()
        except Exception:
            pass

        qualified_docs = dm.get_stock_ratings("darvas")
        return {
            "status": "success",
            "message": f"Successfully scanned {scanned_count} watchlist stocks. Found {len(qualified_docs)} qualified Darvas Box breakouts.",
            "scanned_count": scanned_count,
            "qualified_count": len(qualified_docs),
            "data": qualified_docs
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute Darvas Box scan: {e}")


@app.get("/api/ratings/{timeframe}")
def get_stock_ratings(timeframe: str):
    """Retrieve Grok-evaluated high-conviction stocks and 1% trigger prices for a timeframe ('monthly', 'weekly', 'daily', 'manual', 'darvas')."""
    tf_clean = timeframe.strip().lower()
    if tf_clean not in ("monthly", "weekly", "daily", "manual", "darvas"):
        raise HTTPException(status_code=400, detail="Timeframe must be 'monthly', 'weekly', 'daily', 'manual', or 'darvas'")
        
    try:
        from data_manager import DataManager
        dm = DataManager()

        # Automatically purge invalidated or consolidated Darvas stocks on tab fetch
        if tf_clean == "darvas":
            try:
                from scripts.darvas_box_scanner import purge_invalidated_darvas_stocks
                purge_invalidated_darvas_stocks()
            except Exception as purge_err:
                print(f"[DARVAS-PURGE] Warning: Failed to run automatic Darvas purge: {purge_err}")

        records = dm.get_stock_ratings(tf_clean)
        # Format datetimes to ISO strings for JSON serialization
        for r in records:
            if "_id" in r:
                r["_id"] = str(r["_id"])
            if "alert_count" not in r:
                r["alert_count"] = 0
            if "updated_at" in r and hasattr(r["updated_at"], "isoformat"):
                r["updated_at"] = r["updated_at"].isoformat()
        return {"status": "success", "timeframe": tf_clean, "count": len(records), "data": records}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch {tf_clean} ratings: {e}")

@app.delete("/api/ratings/{timeframe}")
def clear_all_timeframe_ratings(timeframe: str):
    """Deletes all stock records from a specific timeframe table ('monthly', 'weekly', 'daily', 'manual')."""
    tf_clean = timeframe.strip().lower()
    if tf_clean not in ("monthly", "weekly", "daily", "manual", "darvas"):
        raise HTTPException(status_code=400, detail="Timeframe must be 'monthly', 'weekly', 'daily', 'manual', or 'darvas'")
        
    try:
        from data_manager import DataManager
        dm = DataManager()
        deleted_count = dm.clear_all_stock_ratings(tf_clean)
        
        # Reload WebSocket targets
        try:
            from scripts.zerodha_websocket_alert_listener import ws_alert_engine
            ws_alert_engine.load_monitored_targets()
        except Exception:
            pass

        return {
            "status": "success",
            "message": f"Successfully deleted all stock records from '{tf_clean}' table.",
            "timeframe": tf_clean,
            "deleted_count": deleted_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear {tf_clean} table: {e}")

@app.delete("/api/ratings/{timeframe}/{symbol}")
def delete_single_stock_rating(timeframe: str, symbol: str):
    """Deletes an individual stock record from a specific timeframe table ('monthly', 'weekly', 'daily', 'manual')."""
    tf_clean = timeframe.strip().lower()
    if tf_clean not in ("monthly", "weekly", "daily", "manual", "darvas"):
        raise HTTPException(status_code=400, detail="Timeframe must be 'monthly', 'weekly', 'daily', 'manual', or 'darvas'")
        
    sym_clean = symbol.strip().upper()
    try:
        from data_manager import DataManager
        dm = DataManager()
        success = dm.delete_stock_rating(tf_clean, sym_clean)
        
        # Reload WebSocket targets
        try:
            from scripts.zerodha_websocket_alert_listener import ws_alert_engine
            ws_alert_engine.load_monitored_targets()
        except Exception:
            pass

        return {
            "status": "success" if success else "not_found",
            "message": f"Deleted symbol '{sym_clean}' from '{tf_clean}' table." if success else f"Symbol '{sym_clean}' not found in '{tf_clean}'.",
            "timeframe": tf_clean,
            "symbol": sym_clean
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete {sym_clean} from {tf_clean} table: {e}")

class BatchDeleteRequest(BaseModel):
    symbols: List[str]

@app.post("/api/ratings/{timeframe}/delete-batch")
def delete_batch_stock_ratings(timeframe: str, req: BatchDeleteRequest):
    """Deletes a selected list of stock records from a specific timeframe table and cancels their Zerodha GTT alerts."""
    tf_clean = timeframe.strip().lower()
    if tf_clean not in ("monthly", "weekly", "daily", "manual"):
        raise HTTPException(status_code=400, detail="Timeframe must be 'monthly', 'weekly', 'daily', or 'manual'")
        
    try:
        from data_manager import DataManager
        dm = DataManager()
        deleted_count = dm.delete_batch_stock_ratings(tf_clean, req.symbols)
        
        # Reload WebSocket targets
        try:
            from scripts.zerodha_websocket_alert_listener import ws_alert_engine
            ws_alert_engine.load_monitored_targets()
        except Exception:
            pass

        return {
            "status": "success",
            "message": f"Successfully deleted {deleted_count} selected stock records from '{tf_clean}' table.",
            "timeframe": tf_clean,
            "deleted_count": deleted_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to batch delete from {tf_clean} table: {e}")

@app.get("/api/race/daily")
def get_daily_stock_alert_race(today_only: bool = False, past_week_only: bool = False):
    """
    Returns the Stock Alert Race leaderboard.
    Aggregates breakout alerts across monthly, weekly, daily, and manual tables.
    - If today_only=True: strictly filters to stocks updated or alerted TODAY in IST.
    - If past_week_only=True: strictly filters to stocks whose market price INCREASED (>0%) over the past week (past 7 days).
    """
    try:
        from data_manager import DataManager
        from datetime import datetime, timezone, timedelta

        # Get current date in IST (Asia/Kolkata: UTC+5:30)
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist_tz)
        today_date_str = now_ist.strftime("%Y-%m-%d")

        dm = DataManager()
        stocks_map = {}

        # Search monthly, weekly, daily, manual collections for records with alert activity
        for tf in ["monthly", "weekly", "daily", "manual"]:
            try:
                col = dm.db[tf]
                docs = list(col.find({}))
                for doc in docs:
                    sym = (doc.get("symbol") or "").upper().replace(".NS", "").replace("-EQ", "")
                    if not sym:
                        continue
                    
                    alert_cnt = int(doc.get("alert_count") or 0)
                    recent_high = float(doc.get("recent_high") or 0.0)
                    trigger_price = float(doc.get("alert_trigger_price") or (recent_high * 1.01))
                    rating = float(doc.get("rating") or 4.0)
                    reason = doc.get("reason") or "Strong breakout setup"
                    alert_status = doc.get("alert_status") or "LOCAL_ALERT_SET"
                    gtt_id = doc.get("gtt_id")
                    
                    # Determine date of last actual 1% breakout alert trigger in IST timezone
                    last_alerted_at = doc.get("last_alerted_at")
                    date_str = ""
                    if isinstance(last_alerted_at, datetime):
                        if last_alerted_at.tzinfo is None:
                            last_alerted_ist = last_alerted_at.replace(tzinfo=timezone.utc).astimezone(ist_tz)
                        else:
                            last_alerted_ist = last_alerted_at.astimezone(ist_tz)
                        date_str = last_alerted_ist.strftime("%Y-%m-%d")
                    elif isinstance(last_alerted_at, str):
                        date_str = str(last_alerted_at)[:10]
                    
                    is_today = (date_str == today_date_str)
                    has_triggered = (alert_cnt > 0) or ("TRIGGER" in str(alert_status).upper())

                    # STRICT FILTERING for Today's Race:
                    if today_only:
                        if not (is_today and has_triggered):
                            continue
                    
                    today_alerts = int(doc.get("today_alert_count") or (alert_cnt if is_today else 0))
                    active_alerts_count = today_alerts if today_only else alert_cnt

                    if sym not in stocks_map or active_alerts_count > stocks_map[sym]["alert_count"]:
                        stocks_map[sym] = {
                            "symbol": sym,
                            "timeframe": tf.upper(),
                            "alert_count": active_alerts_count,
                            "total_alerts": alert_cnt,
                            "recent_high": recent_high,
                            "alert_trigger_price": trigger_price,
                            "rating": rating,
                            "reason": reason,
                            "alert_status": alert_status,
                            "gtt_id": gtt_id,
                            "last_updated": str(last_alerted_at) if last_alerted_at else now_ist.isoformat(),
                            "is_today": is_today
                        }
            except Exception as tf_err:
                print(f"[RACE API] Error fetching {tf} table: {tf_err}")

        # Compute 1-week percentage price change for stocks using fast server cache
        weekly_returns = _get_weekly_returns_cached(list(stocks_map.keys()))

        filtered_items = []
        for sym, item in stocks_map.items():
            weekly_gain = weekly_returns.get(sym, 0.0)
            item["weekly_change_pct"] = weekly_gain

            if past_week_only:
                # STRICT FILTERING for Past Week Gainers Race:
                # ONLY include stocks whose market price INCREASED (>0%) over the past week.
                if weekly_gain <= 0:
                    continue

            filtered_items.append(item)

        # Sort: if past_week_only, sort by weekly_change_pct desc, then alert_count desc
        if past_week_only:
            filtered_items.sort(key=lambda x: (x.get("weekly_change_pct", 0), x["alert_count"], x["rating"]), reverse=True)
        else:
            filtered_items.sort(key=lambda x: (x["alert_count"], x["rating"], x["recent_high"]), reverse=True)

        # Assign race ranks
        for idx, item in enumerate(filtered_items, start=1):
            item["rank"] = idx

        return {
            "status": "success",
            "date": today_date_str,
            "today_only": today_only,
            "past_week_only": past_week_only,
            "timestamp_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
            "count": len(filtered_items),
            "leaderboard": filtered_items
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate daily race data: {e}")

@app.get("/api/race/todays")
def get_todays_stock_alert_race():
    """Returns Today's Stock Alert Race leaderboard strictly considering current day stocks."""
    return get_daily_stock_alert_race(today_only=True)

@app.get("/api/race/past-week")
def get_past_week_stock_alert_race():
    """Returns Stock Alert Race leaderboard strictly considering stocks that INCREASED over the past week."""
    return get_daily_stock_alert_race(past_week_only=True)

@app.post("/api/pipeline/run")
def trigger_chartink_grok_pipeline(req: PipelineRunRequest, background_tasks: BackgroundTasks):
    """Trigger full Chartink -> Grok AI -> DB -> +1% Alert pipeline as a background task (guarded to run Grok API once per day)."""
    try:
        from scripts.grok_chartink_analyzer import run_pipeline
        top_n_val = req.top_n or 20
        key_val = req.api_key
        force_val = bool(req.force)
        
        background_tasks.add_task(run_pipeline, api_key=key_val, top_n=top_n_val, force_run=force_val)
        return {
            "status": "success",
            "message": f"Chartink -> Grok AI -> DB -> +1% Alert pipeline triggered (Force={force_val}). Grok API runs max once/day.",
            "top_n": top_n_val,
            "force_run": force_val
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to launch pipeline: {e}")

@app.post("/api/gtts/audit-and-fix")
def audit_and_fix_next_gtt_alerts():
    """
    Audits all stocks across monthly, weekly, daily collections, checks live Zerodha GTTs,
    verifies if next trailing alert is active, and automatically places missing next alerts.
    """
    try:
        from scripts.gtt_next_alert_integrity_monitor import audit_and_restore_next_gtt_alerts
        res = audit_and_restore_next_gtt_alerts(dry_run=False)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to audit and fix GTT alerts: {e}")



@app.get("/api/derivatives/analysis")
def get_derivatives_analysis(force_grok: bool = False):
    """
    Fetches live Nifty Spot, GIFT Nifty, PCR, India VIX, Max Call/Put strikes from Zerodha API.
    Only queries Grok AI for directional bias and news when force_grok=True is explicitly set.
    """
    try:
        from scripts.fetch_derivatives_data import analyze_nse_derivatives
        res = analyze_nse_derivatives(force_grok=force_grok)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to perform derivatives analysis: {e}")

@app.post("/api/derivatives/test-telegram-alert")
def test_telegram_derivatives_alert():
    """
    Triggers an options pressure buildup alert (Put/Call side) to Telegram bot.
    """
    try:
        from scripts.fetch_derivatives_data import send_telegram_derivatives_alert
        res = send_telegram_derivatives_alert(force_send=True)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to dispatch Telegram alert: {e}")

@app.post("/api/stocks/{symbol}/reset-gtt")
def reset_gtt_for_stock(symbol: str, timeframe: Optional[str] = None):
    """
    Cancels any previous GTT on Zerodha for symbol and places a new 1% GTT alert
    from its current live trading price (LTP). Applicable to monthly, weekly, daily, manual.
    """
    try:
        from data_manager import DataManager
        dm = DataManager()
        res = dm.reset_stock_1pct_gtt(symbol=symbol, timeframe=timeframe)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset 1% GTT for '{symbol}': {e}")

@app.post("/api/stocks/reset-all-gtts")
def reset_all_gtts_endpoint(timeframe: str = "monthly"):
    """
    Resets 1% GTT breakout alerts for ALL stocks in a given timeframe collection (monthly, weekly, daily, manual)
    from their current trading prices, cancelling previous GTTs.
    """
    try:
        from data_manager import DataManager
        dm = DataManager()
        res = dm.reset_all_timeframe_gtts(timeframe=timeframe)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset GTT alerts for timeframe '{timeframe}': {e}")

@app.post("/api/zerodha/sync-gtts")
def sync_zerodha_gtts_endpoint():
    """
    Synchronizes Zerodha GTTs with DB watchlist: deletes duplicate GTT orders for tracked stocks
    and removes orphaned GTT orders from Zerodha account.
    """
    try:
        from data_manager import DataManager
        dm = DataManager()
        res = dm.sync_and_clean_zerodha_gtts()
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync Zerodha GTTs: {e}")

if __name__ == "__main__":

    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True)

