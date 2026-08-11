"""
===============================================================================
QUANTITATIVE ASSET MONITOR: MOMENTUM & VOLUME SPIKE DETECTOR
===============================================================================

Description:
------------
This standalone backend script continuously monitors asset prices on a 10-minute
timeframe using the Zerodha Kite Connect API. It identifies high-probability 
momentum breakouts by detecting simultaneous spikes in volume-driven capital flow
(OBV Z-Score > 2.0) and trend momentum acceleration (TSI Slope > 2.5 or TSI Bullish Crossover).

Mathematical Logic & Signal Rules:
----------------------------------
1. On-Balance Volume (OBV) & OBV Z-Score:
   - OBV measures cumulative volume direction:
       OBV_t = OBV_{t-1} + sign(Close_t - Close_{t-1}) * Volume_t
   - OBV 2-Period Change:
       ΔOBV_t = OBV_t - OBV_{t-2}
   - OBV Z-Score (20-period rolling mean μ and standard deviation σ):
       Z_OBV_t = (ΔOBV_t - μ_{20, t}) / σ_{20, t}
   - OBV Condition = (Z_OBV_t > 2.0)

2. True Strength Index (TSI):
   - Parameters: fast = 13, slow = 25, signal = 13
   - Price Change m_t = Close_t - Close_{t-1}
   - Double Smoothed PC = EMA_13(EMA_25(m))
   - Double Smoothed Absolute PC = EMA_13(EMA_25(|m|))
   - TSI Line_t = 100 * (Double Smoothed PC / Double Smoothed Absolute PC)
   - Signal Line_t = EMA_13(TSI Line)
   - TSI 2-Period Slope:
       ΔTSI_t = TSI Line_t - TSI Line_{t-2}
   - TSI Bullish Crossover:
       (TSI_{t-1} <= Signal_{t-1}) AND (TSI_t > Signal_t)
   - TSI Condition = (ΔTSI_t > 2.5) OR (TSI Bullish Crossover)

3. Final Trigger:
   - Buy Signal = (OBV Condition == True) AND (TSI Condition == True)
   - Evaluated strictly on the most recently closed 10-minute candle.

Required Environment Variables (.env):
--------------------------------------
- ZERODHA_API_KEY       : Your Zerodha Kite Connect API key
- ZERODHA_ACCESS_TOKEN  : Valid Zerodha access token
- ZERODHA_API_SECRET    : (Optional) Secret key if exchanging request tokens
- DISCORD_WEBHOOK_URL   : Discord channel Webhook URL for real-time alerts
- TELEGRAM_BOT_TOKEN    : (Optional) Telegram bot token for alerts
- TELEGRAM_CHAT_ID      : (Optional) Telegram chat ID for alerts
- TICKER_SYMBOL         : Instrument symbol (e.g., INFY, RELIANCE, NIFTY)
- INSTRUMENT_TOKEN      : (Optional) Zerodha numeric instrument token (e.g. 408065)

===============================================================================
"""

import os
import sys
import time
import logging
import argparse
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

# Attempt to load pandas_ta if available
try:
    import pandas_ta as pta  # type: ignore # noqa: F401
    PANDAS_TA_AVAILABLE = True
except ImportError:
    PANDAS_TA_AVAILABLE = False

# Attempt to load kiteconnect
try:
    from kiteconnect import KiteConnect
    KITECONNECT_AVAILABLE = True
except ImportError:
    KITECONNECT_AVAILABLE = False

# Attempt to load mplfinance if available
try:
    import mplfinance as mpf
    MPLFINANCE_AVAILABLE = True
except ImportError:
    MPLFINANCE_AVAILABLE = False

# Configure application logger with UTF-8 stream handling
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("MomentumVolumeMonitor")

# Load environment variables from .env file
env_file_path = Path(__file__).parent.resolve() / ".env"
load_dotenv(dotenv_path=env_file_path)


# =============================================================================
# 1. TECHNICAL INDICATOR CALCULATIONS
# =============================================================================

def calculate_obv(df: pd.DataFrame) -> pd.Series:
    """
    Calculate On-Balance Volume (OBV).
    
    Formula:
        OBV_t = OBV_{t-1} + sign(Close_t - Close_{t-1}) * Volume_t
    """
    if PANDAS_TA_AVAILABLE and hasattr(df, "ta"):
        try:
            obv = df.ta.obv(close="close", volume="volume")
            if obv is not None and not obv.empty:
                return obv
        except Exception as e:
            logger.debug(f"pandas_ta OBV calculation fallback to pandas: {e}")

    # Pure pandas calculation fallback
    close_diff = df["close"].diff()
    direction = np.where(close_diff > 0, 1, np.where(close_diff < 0, -1, 0))
    obv = (direction * df["volume"]).cumsum()
    return pd.Series(obv, index=df.index, name="OBV")


def calculate_tsi(df: pd.DataFrame, fast: int = 13, slow: int = 25, signal: int = 13) -> pd.DataFrame:
    """
    Calculate True Strength Index (TSI) and its Signal Line.
    
    Formula:
        m = Close_t - Close_{t-1}
        Double_Smoothed_m = EMA_fast(EMA_slow(m))
        Double_Smoothed_abs_m = EMA_fast(EMA_slow(|m|))
        TSI = 100 * (Double_Smoothed_m / Double_Smoothed_abs_m)
        Signal = EMA_signal(TSI)
        
    Returns:
        pd.DataFrame with columns ['tsi', 'tsi_signal']
    """
    if PANDAS_TA_AVAILABLE and hasattr(df, "ta"):
        try:
            tsi_df = df.ta.tsi(close="close", fast=fast, slow=slow, signal=signal)
            if tsi_df is not None and not tsi_df.empty:
                cols = tsi_df.columns
                # pandas_ta column naming standard: TSI_13_25_13 and TSIs_13_25_13
                tsi_col = [c for c in cols if c.startswith("TSI_") and not c.startswith("TSIs_")]
                sig_col = [c for c in cols if c.startswith("TSIs_")]
                
                if tsi_col and sig_col:
                    res = pd.DataFrame({
                        "tsi": tsi_df[tsi_col[0]],
                        "tsi_signal": tsi_df[sig_col[0]]
                    }, index=df.index)
                    return res
        except Exception as e:
            logger.debug(f"pandas_ta TSI calculation fallback to pandas: {e}")

    # Pure pandas EMA calculation fallback
    pc = df["close"].diff()
    abs_pc = pc.abs()

    # Double smoothing using Exponential Moving Average (EMA)
    pc_ema1 = pc.ewm(span=slow, min_periods=slow, adjust=False).mean()
    pc_ema2 = pc_ema1.ewm(span=fast, min_periods=fast, adjust=False).mean()

    abs_pc_ema1 = abs_pc.ewm(span=slow, min_periods=slow, adjust=False).mean()
    abs_pc_ema2 = abs_pc_ema1.ewm(span=fast, min_periods=fast, adjust=False).mean()

    # Avoid division by zero
    abs_pc_ema2 = abs_pc_ema2.replace(0, np.nan)
    tsi_line = 100.0 * (pc_ema2 / abs_pc_ema2)
    tsi_signal = tsi_line.ewm(span=signal, min_periods=signal, adjust=False).mean()

    return pd.DataFrame({
        "tsi": tsi_line,
        "tsi_signal": tsi_signal
    }, index=df.index)


# =============================================================================
# 2. SIGNAL ENGINE & MATHEMATICAL LOGIC
# =============================================================================

def analyze_market_data(df: pd.DataFrame) -> dict:
    """
    Performs full mathematical signal analysis on 10-minute candle DataFrame.
    
    Required DataFrame columns: ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    """
    if len(df) < 30:
        raise ValueError(f"Insufficient candles for signal calculation. Found {len(df)}, required at least 30.")

    # Standardize column names to lowercase
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    
    # Ensure numeric types
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 1. Calculate Technical Indicators
    df["obv"] = calculate_obv(df)
    tsi_res = calculate_tsi(df, fast=13, slow=25, signal=13)
    df["tsi"] = tsi_res["tsi"]
    df["tsi_signal"] = tsi_res["tsi_signal"]

    # 2. Calculate OBV Spike Logic (Z-Score of 2-period OBV Difference)
    # Difference over last 2 periods: ΔOBV_t = OBV_t - OBV_{t-2}
    df["obv_diff_2"] = df["obv"].diff(2)
    
    # 20-period rolling mean and standard deviation
    rolling_mean_20 = df["obv_diff_2"].rolling(window=20).mean()
    rolling_std_20 = df["obv_diff_2"].rolling(window=20).std(ddof=0)
    
    # Calculate Z-Score: (ΔOBV - μ) / σ
    # Protect against zero standard deviation
    safe_std = rolling_std_20.replace(0, np.nan)
    df["obv_zscore"] = (df["obv_diff_2"] - rolling_mean_20) / safe_std
    df["obv_zscore"] = df["obv_zscore"].fillna(0.0)

    # 3. Calculate TSI Momentum Logic (2-period slope & Crossover)
    # Slope over 2 periods: ΔTSI_t = TSI_t - TSI_{t-2}
    df["tsi_slope_2"] = df["tsi"].diff(2)

    # Detect TSI Crossover above Signal line on latest candle
    # Bullish Cross: Previous TSI <= Previous Signal AND Current TSI > Current Signal
    df["tsi_crossed_above"] = (
        (df["tsi"].shift(1) <= df["tsi_signal"].shift(1)) &
        (df["tsi"] > df["tsi_signal"])
    )

    # 4. Evaluate Signal Conditions on the Most Recently Closed Candle (iloc[-1])
    latest = df.iloc[-1]
    
    obv_zscore_val = float(latest.get("obv_zscore", 0.0))
    tsi_slope_val = float(latest.get("tsi_slope_2", 0.0))
    tsi_val = float(latest.get("tsi", 0.0))
    tsi_signal_val = float(latest.get("tsi_signal", 0.0))
    tsi_crossed = bool(latest.get("tsi_crossed_above", False))
    close_price = float(latest["close"])
    candle_time = latest.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # Conditions Evaluation:
    # Condition A: OBV Z-Score > 2.0
    obv_condition = obv_zscore_val > 2.0
    
    # Condition B: TSI Slope > 2.5 OR TSI Just Crossed Above Signal Line
    tsi_condition = (tsi_slope_val > 2.5) or tsi_crossed
    
    # Final Trigger: Both OBV condition AND TSI condition are met
    buy_signal = obv_condition and tsi_condition

    return {
        "buy_signal": buy_signal,
        "obv_condition": obv_condition,
        "tsi_condition": tsi_condition,
        "obv_zscore": round(obv_zscore_val, 4),
        "tsi_slope": round(tsi_slope_val, 4),
        "tsi_val": round(tsi_val, 4),
        "tsi_signal_val": round(tsi_signal_val, 4),
        "tsi_crossed": tsi_crossed,
        "close_price": round(close_price, 2),
        "timestamp": str(candle_time),
        "total_candles": len(df)
    }, df


# =============================================================================
# 3. ALERTING SYSTEM (DISCORD & TELEGRAM)
# =============================================================================

def send_alert(
    ticker: str,
    timestamp: str,
    price: float,
    obv_zscore: float,
    tsi_slope: float,
    tsi_val: float,
    tsi_signal_val: float,
    obv_condition: bool,
    tsi_condition: bool,
    tsi_crossed: bool,
    webhook_url: str = None,
    image_path: str = None
) -> bool:
    """
    Sends a formatted alert message (with optional breakout chart image) to Discord Webhook and/or Telegram.
    """
    discord_sent = False
    telegram_sent = False

    # 1. Discord Webhook Alert
    if not webhook_url:
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    if webhook_url:
        status_icon = "🚨 BUY SIGNAL DETECTED"
        embed_color = 0x00FF00  # Bright Green

        payload = {
            "username": "Quant Momentum Bot",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/4256/4256900.png",
            "embeds": [
                {
                    "title": f"{status_icon} - {ticker.upper()}",
                    "description": "Simultaneous OBV Volume Spike and TSI Momentum Acceleration detected on **10-minute** timeframe.",
                    "color": embed_color,
                    "fields": [
                        {
                            "name": "💵 Current Price",
                            "value": f"**₹{price:,.2f}**",
                            "inline": True
                        },
                        {
                            "name": "📊 OBV Z-Score",
                            "value": f"**{obv_zscore:+.2f}**\n({'✅ > 2.0' if obv_condition else '❌ <= 2.0'})",
                            "inline": True
                        },
                        {
                            "name": "📈 TSI 2-Period Slope",
                            "value": f"**{tsi_slope:+.2f}**\n({'✅ > 2.5' if tsi_slope > 2.5 else 'Crossed: ' + str(tsi_crossed)})",
                            "inline": True
                        },
                        {
                            "name": "📐 TSI / Signal Line",
                            "value": f"TSI: `{tsi_val:.2f}` | Signal: `{tsi_signal_val:.2f}`",
                            "inline": False
                        },
                        {
                            "name": "⏰ Candle Time (UTC/IST)",
                            "value": f"`{timestamp}`",
                            "inline": False
                        }
                    ],
                    "footer": {
                        "text": "Quantitative Trading Engine • 10m System"
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            ]
        }

        # Handle image attachment if generated
        files = {}
        file_handle = None
        if image_path and os.path.exists(image_path):
            file_name = os.path.basename(image_path)
            try:
                file_handle = open(image_path, "rb")
                files = {
                    "file": (file_name, file_handle, "image/png")
                }
                payload["embeds"][0]["image"] = {
                    "url": f"attachment://{file_name}"
                }
            except Exception as e:
                logger.error(f"Failed to prepare chart file attachment: {e}")

        try:
            if files:
                import json
                post_data = {
                    "payload_json": json.dumps(payload)
                }
                response = requests.post(webhook_url, data=post_data, files=files, timeout=15)
            else:
                response = requests.post(webhook_url, json=payload, timeout=10)

            if response.status_code in [200, 204]:
                logger.info(f"Successfully sent Discord alert for {ticker} at {timestamp}.")
                discord_sent = True
            else:
                logger.error(f"Failed to send Discord alert. Status: {response.status_code}, Body: {response.text}")
        except Exception as e:
            logger.error(f"Exception while dispatching Discord webhook alert: {e}")
        finally:
            if file_handle:
                file_handle.close()
    else:
        logger.warning("No DISCORD_WEBHOOK_URL set in environment. Skipping Discord notification.")

    # 2. Telegram Bot Alert
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if telegram_token and telegram_chat_id:
        tg_text = (
            f"🚨 *BUY SIGNAL DETECTED* - *{ticker.upper()}*\n\n"
            f"Simultaneous OBV Volume Spike and TSI Momentum Acceleration detected on *10-minute* timeframe.\n\n"
            f"💵 *Current Price*: ₹{price:,.2f}\n"
            f"📊 *OBV Z-Score*: {obv_zscore:+.2f} ({'✅ > 2.0' if obv_condition else '❌ <= 2.0'})\n"
            f"📈 *TSI 2-Period Slope*: {tsi_slope:+.2f} ({'✅ > 2.5' if tsi_slope > 2.5 else 'Crossed: ' + str(tsi_crossed)})\n"
            f"📐 *TSI / Signal*: TSI: {tsi_val:.2f} | Signal: {tsi_signal_val:.2f}\n"
            f"⏰ *Candle Time*: `{timestamp}`"
        )
        try:
            if image_path and os.path.exists(image_path):
                tg_url = f"https://api.telegram.org/bot{telegram_token}/sendPhoto"
                with open(image_path, "rb") as photo_file:
                    tg_files = {
                        "photo": (os.path.basename(image_path), photo_file, "image/png")
                    }
                    tg_payload = {
                        "chat_id": telegram_chat_id,
                        "caption": tg_text,
                        "parse_mode": "Markdown"
                    }
                    tg_resp = requests.post(tg_url, data=tg_payload, files=tg_files, timeout=15)
            else:
                tg_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                tg_payload = {
                    "chat_id": telegram_chat_id,
                    "text": tg_text,
                    "parse_mode": "Markdown"
                }
                tg_resp = requests.post(tg_url, json=tg_payload, timeout=10)

            if tg_resp.status_code == 200:
                logger.info(f"Successfully sent Telegram alert for {ticker} at {timestamp}.")
                telegram_sent = True
            else:
                logger.error(f"Failed to send Telegram alert. Status: {tg_resp.status_code}, Body: {tg_resp.text}")
        except Exception as e:
            logger.error(f"Exception while dispatching Telegram alert: {e}")
    else:
        logger.debug("Telegram credentials not configured. Skipping Telegram notification.")

    return discord_sent or telegram_sent


# =============================================================================
# 4. ZERODHA DATA FETCHING & MOCK ENGINE
# =============================================================================

def _exchange_zerodha_request_token(api_key: str, request_token: str, api_secret: str, api_url: str = "https://api.kite.trade") -> str:
    """
    Exchanges a Zerodha request_token for a fresh access_token and updates .env file.
    """
    import hashlib
    checksum_str = api_key + request_token + api_secret
    checksum = hashlib.sha256(checksum_str.encode("utf-8")).hexdigest()

    url = f"{api_url}/session/token"
    data = {
        "api_key": api_key,
        "request_token": request_token,
        "checksum": checksum
    }

    logger.info("Exchanging Zerodha request_token for a new access_token...")
    resp = requests.post(url, data=data, timeout=10)
    if resp.status_code != 200:
        try:
            err = resp.json().get("message", resp.text)
        except Exception:
            err = resp.text
        raise ValueError(f"Zerodha session exchange failed: {err}")

    resp_json = resp.json()
    if resp_json.get("status") == "success":
        new_access_token = resp_json["data"]["access_token"]
        logger.info("Successfully obtained new Zerodha access_token!")
        
        # Save to current process environment
        os.environ["ZERODHA_ACCESS_TOKEN"] = new_access_token
        
        # Persist to root .env file
        try:
            env_path = Path(__file__).parent.resolve() / ".env"
            if env_path.exists():
                lines = env_path.read_text(encoding="utf-8").splitlines()
                updated = False
                new_lines = []
                for line in lines:
                    if line.strip().startswith("ZERODHA_ACCESS_TOKEN="):
                        new_lines.append(f"ZERODHA_ACCESS_TOKEN={new_access_token}")
                        updated = True
                    else:
                        new_lines.append(line)
                if not updated:
                    new_lines.append(f"ZERODHA_ACCESS_TOKEN={new_access_token}")
                env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                logger.info("Persisted new ZERODHA_ACCESS_TOKEN to .env file.")
        except Exception as e:
            logger.warning(f"Could not persist access token to .env: {e}")

        return new_access_token
    else:
        err = resp_json.get("message", "Unknown session exchange error")
        raise ValueError(f"Zerodha request token exchange failed: {err}")


def fetch_zerodha_data(
    api_key: str,
    access_token: str,
    instrument_token: int,
    days: int = 5,
    api_url: str = "https://api.kite.trade"
) -> pd.DataFrame:
    """
    Fetches 10-minute historical candle data directly from Zerodha Kite API.
    Auto-refreshes access token if request_token and api_secret are provided.
    """
    api_secret = os.getenv("ZERODHA_API_SECRET", "")
    request_token = os.getenv("ZERODHA_REQUEST_TOKEN", "")

    # If access_token is empty but request_token is available, perform session exchange
    if (not access_token or access_token.startswith("your_")) and request_token and api_secret:
        try:
            access_token = _exchange_zerodha_request_token(api_key, request_token, api_secret, api_url)
        except Exception as e:
            logger.warning(f"Initial request token exchange failed: {e}")

    to_date = datetime.now()
    from_date = to_date - timedelta(days=days)

    from_str = from_date.strftime("%Y-%m-%d %H:%M:%S")
    to_str = to_date.strftime("%Y-%m-%d %H:%M:%S")

    def _execute_api_fetch(token_to_use: str):
        # 1. Try KiteConnect official client if available
        if KITECONNECT_AVAILABLE and api_key and token_to_use:
            try:
                kite = KiteConnect(api_key=api_key)
                kite.set_access_token(token_to_use)
                raw_candles = kite.historical_data(
                    instrument_token=instrument_token,
                    from_date=from_date,
                    to_date=to_date,
                    interval="10minute"
                )
                if raw_candles:
                    df = pd.DataFrame(raw_candles)
                    df = df.rename(columns={"date": "timestamp"})
                    return df[["timestamp", "open", "high", "low", "close", "volume"]]
            except Exception as e:
                logger.debug(f"KiteConnect library fetch attempt failed ({e}). Trying REST HTTPS fallback...")

        # 2. Direct HTTP REST request using Zerodha endpoints
        url = f"{api_url}/instruments/historical/{instrument_token}/10minute"
        headers = {
            "X-Kite-Version": "3",
            "Authorization": f"token {api_key}:{token_to_use}"
        }
        params = {
            "from": from_str,
            "to": to_str
        }

        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()

        data = resp.json()
        if data.get("status") != "success":
            error_msg = data.get("message", "Unknown API error")
            raise RuntimeError(f"Zerodha API response error: {error_msg}")

        candles = data.get("data", {}).get("candles", [])
        if not candles:
            raise ValueError(f"No candle data returned from Zerodha for instrument token {instrument_token}.")

        records = []
        for c in candles:
            # c format: [timestamp, open, high, low, close, volume, open_interest]
            records.append({
                "timestamp": c[0],
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": int(c[5])
            })

        return pd.DataFrame(records)

    try:
        return _execute_api_fetch(access_token)
    except requests.exceptions.HTTPError as http_err:
        # If 403 Forbidden (token expired), attempt to exchange request_token if available
        if http_err.response is not None and http_err.response.status_code in [403, 401]:
            if request_token and api_secret:
                logger.warning("Access token expired/invalid (403 Forbidden). Attempting automatic request_token exchange...")
                try:
                    fresh_access_token = _exchange_zerodha_request_token(api_key, request_token, api_secret, api_url)
                    return _execute_api_fetch(fresh_access_token)
                except Exception as ex:
                    logger.error(f"Automatic session exchange failed: {ex}")
            else:
                login_url = f"https://kite.zerodha.com/connect/login?api_key={api_key}&v=3"
                logger.error(
                    f"Zerodha access token expired. Please log in at:\n  {login_url}\n"
                    f"Copy the `request_token` parameter from the redirect URL and set ZERODHA_REQUEST_TOKEN in `.env`."
                )
        raise


def generate_mock_candles(count: int = 150) -> pd.DataFrame:
    """
    Generates realistic synthetic 10-minute candles with a forced breakout spike
    at the final candle for demonstration & test mode.
    """
    logger.info("[MOCK MODE] Generating synthetic 10-minute price & volume candles...")
    np.random.seed(42)
    start_time = datetime.now() - timedelta(minutes=10 * count)

    timestamps = [start_time + timedelta(minutes=10 * i) for i in range(count)]
    price = 1500.0
    records = []

    for i in range(count):
        # Force a strong bullish volume & price spike on the final candles
        if i >= count - 2:
            price_change = np.random.uniform(15.0, 25.0)  # Strong price jump
            volume = int(np.random.uniform(80000, 120000)) # Huge volume spike
        else:
            price_change = np.random.uniform(-3.0, 3.2)
            volume = int(np.random.uniform(5000, 15000))

        open_p = price
        close_p = price + price_change
        high_p = max(open_p, close_p) + np.random.uniform(0.5, 2.0)
        low_p = min(open_p, close_p) - np.random.uniform(0.5, 2.0)
        price = close_p

        records.append({
            "timestamp": timestamps[i].strftime("%Y-%m-%d %H:%M:%S"),
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "volume": volume
        })

    return pd.DataFrame(records)


def generate_breakout_chart(df: pd.DataFrame, ticker: str) -> Path:
    """
    Generates a high-quality candlestick and technical indicator breakout chart 
    using mplfinance and saves it to the local project directories.
    """
    if not MPLFINANCE_AVAILABLE:
        logger.warning("mplfinance is not available. Skipping chart generation.")
        return None

    try:
        # Create charts directory if not exists
        charts_dir = Path(__file__).parent.resolve() / "charts"
        charts_dir.mkdir(exist_ok=True)

        # Retrieve last 50 periods for clarity on the chart
        chart_df = df.tail(50).copy()
        
        # Ensure timestamp is datetime and set as index
        chart_df["timestamp"] = pd.to_datetime(chart_df["timestamp"])
        chart_df = chart_df.set_index("timestamp")
        
        # Map columns to match mplfinance requirements
        chart_df = chart_df.rename(columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume"
        })

        # Addplots list
        ap = []

        # 1. TSI Panel plots (TSI line + Signal line) - Panel 2
        ap.append(mpf.make_addplot(chart_df["tsi"], panel=2, color="#2962FF", width=1.5, ylabel="TSI (13,25,13)"))
        ap.append(mpf.make_addplot(chart_df["tsi_signal"], panel=2, color="#FF6D00", width=1.0))

        # 2. OBV Z-Score breakout panel - Panel 3
        ap.append(mpf.make_addplot(chart_df["obv_zscore"], panel=3, color="#7B1FA2", width=1.5, ylabel="OBV Z-Score"))
        
        # Threshold horizontal line at 2.0
        threshold_line = pd.Series(2.0, index=chart_df.index)
        ap.append(mpf.make_addplot(threshold_line, panel=3, color="#D32F2F", width=1.0, linestyle="dashed"))

        # 3. Buy signal trigger marker arrow (pointing upward under the last candle's low)
        markers = [np.nan] * len(chart_df)
        markers[-1] = chart_df["Low"].iloc[-1] * 0.995  # slightly below low price
        ap.append(mpf.make_addplot(markers, type="scatter", marker="^", markersize=120, color="#2E7D32", panel=0))

        # Generate filename with date
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{ticker.lower()}_breakout_{timestamp_str}.png"
        output_path = charts_dir / filename

        # Customizing visual theme
        mc = mpf.make_marketcolors(
            up="#26a69a", down="#ef5350",
            edge="inherit",
            wick="inherit",
            volume="inherit",
            inherit=True
        )
        custom_style = mpf.make_mpf_style(
            base_mpf_style="charles",
            marketcolors=mc,
            gridcolor="#e0e0e0",
            gridstyle="--"
        )

        # Plot and save
        mpf.plot(
            chart_df,
            type="candle",
            volume=True,
            addplot=ap,
            title=f"\n{ticker.upper()} - Momentum & Volume Breakout (10m Timeframe)",
            style=custom_style,
            savefig=dict(fname=str(output_path), dpi=150, bbox_inches="tight"),
            volume_panel=1
        )

        logger.info(f"Breakout chart successfully generated and saved to: {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"Failed to generate breakout chart with mplfinance: {e}", exc_info=True)
        return None


# =============================================================================
# 5. EXECUTION & MONITORING LOOP
# =============================================================================

def run_monitor_iteration(
    api_key: str,
    access_token: str,
    instrument_token: int,
    ticker: str,
    webhook_url: str,
    mock_mode: bool = False
):
    """
    Executes a single fetch-calculate-signal-alert pass.
    """
    logger.info(f"--- Running 10-Minute Pipeline Check for [{ticker}] at {datetime.now().strftime('%H:%M:%S')} ---")

    try:
        if mock_mode or not api_key or not access_token:
            if not mock_mode:
                logger.warning("Zerodha credentials missing or unconfigured. Running in MOCK test mode.")
            df = generate_mock_candles(count=150)
        else:
            df = fetch_zerodha_data(api_key, access_token, instrument_token, days=5)

        # Execute Math & Indicator Signal Analysis
        analysis, df_analyzed = analyze_market_data(df)

        logger.info(
            f"Candle Time: {analysis['timestamp']} | Close: INR {analysis['close_price']} | "
            f"OBV Z-Score: {analysis['obv_zscore']:+.2f} (Cond: {analysis['obv_condition']}) | "
            f"TSI Slope: {analysis['tsi_slope']:+.2f} (Cond: {analysis['tsi_condition']})"
        )

        if analysis["buy_signal"]:
            logger.info("[SIGNAL ALERT] BUY SIGNAL CONFIRMED! Dispatching alert...")
            
            # Generate Breakout Chart with mplfinance
            chart_path = None
            if MPLFINANCE_AVAILABLE:
                chart_path = generate_breakout_chart(df_analyzed, ticker)
                
            send_alert(
                ticker=ticker,
                timestamp=analysis["timestamp"],
                price=analysis["close_price"],
                obv_zscore=analysis["obv_zscore"],
                tsi_slope=analysis["tsi_slope"],
                tsi_val=analysis["tsi_val"],
                tsi_signal_val=analysis["tsi_signal_val"],
                obv_condition=analysis["obv_condition"],
                tsi_condition=analysis["tsi_condition"],
                tsi_crossed=analysis["tsi_crossed"],
                webhook_url=webhook_url,
                image_path=str(chart_path) if chart_path else None
            )
        else:
            logger.info("No Buy Signal triggered on this candle.")

    except Exception as e:
        logger.error(f"Error during iteration for {ticker}: {e}", exc_info=True)


def main():
    parser = argparse.ArgumentParser(description="10-Minute Momentum & Volume Spike Monitor")
    parser.add_argument("--mock", action="store_true", help="Force synthetic mock data mode for testing")
    parser.add_argument("--once", action="store_true", help="Run a single pass and exit (ideal for automated cron/testing)")
    parser.add_argument("--interval", type=int, default=600, help="Monitoring interval in seconds (default: 600s = 10 minutes)")
    args = parser.parse_args()

    # Retrieve settings from environment
    api_key = os.getenv("ZERODHA_API_KEY", "")
    access_token = os.getenv("ZERODHA_ACCESS_TOKEN", "")
    ticker = os.getenv("TICKER_SYMBOL", "INFY").upper()
    instrument_token_str = os.getenv("INSTRUMENT_TOKEN", "")
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # Resolve instrument token from ticker dynamically if not explicitly specified
    if not instrument_token_str:
        try:
            from tradingagents.dataflows.zerodha import get_instrument_token as ta_get_instrument_token
            logger.info(f"Attempting to dynamically resolve Zerodha instrument token for '{ticker}'...")
            instrument_token = ta_get_instrument_token(ticker)
            logger.info(f"Successfully resolved '{ticker}' to token: {instrument_token}")
        except Exception as e:
            logger.warning(
                f"Could not resolve instrument token for '{ticker}' via project database: {e}. "
                "Falling back to default INFY token (408065)."
            )
            instrument_token = 408065
    else:
        try:
            instrument_token = int(instrument_token_str)
        except ValueError:
            logger.error(f"Invalid INSTRUMENT_TOKEN '{instrument_token_str}'. Must be an integer.")
            sys.exit(1)

    logger.info("=========================================================================")
    logger.info("  STARTING QUANTITATIVE MOMENTUM & VOLUME MONITOR (10-MIN TIMEFRAME)   ")
    logger.info("=========================================================================")
    logger.info(f"Target Ticker      : {ticker} (Token: {instrument_token})")
    logger.info(f"Mode               : {'MOCK SIMULATION' if args.mock else 'LIVE ZERODHA API'}")
    logger.info(f"Execution Interval : {args.interval} seconds (10 minutes)")
    logger.info(
        f"Webhook/Bot Alerts : "
        f"{'Discord Webhook' if webhook_url else ''}"
        f"{' & ' if webhook_url and telegram_token else ''}"
        f"{'Telegram Bot' if telegram_token else ''}"
        f"{'NOT CONFIGURED' if not webhook_url and not telegram_token else ''}"
    )
    logger.info("=========================================================================")

    if args.once:
        run_monitor_iteration(api_key, access_token, instrument_token, ticker, webhook_url, mock_mode=args.mock)
        logger.info("Single pass execution completed.")
        return

    # Continuous loop executing every 10 minutes (600 seconds)
    while True:
        try:
            start_time = time.time()
            run_monitor_iteration(api_key, access_token, instrument_token, ticker, webhook_url, mock_mode=args.mock)
            
            # Calculate sleep duration to maintain exact 10-minute cadence
            elapsed = time.time() - start_time
            sleep_duration = max(1, args.interval - elapsed)
            logger.info(f"Sleeping for {sleep_duration:.1f} seconds until next 10-minute candle check...\n")
            time.sleep(sleep_duration)

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Stopping monitor gracefully.")
            break
        except Exception as e:
            logger.critical(f"Unhandled exception in continuous loop: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
