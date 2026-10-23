"""
===============================================================================
5-MINUTE IN-MEMORY CHART GENERATOR & TELEGRAM ALERT DISPATCHER
===============================================================================
Description:
    1. Fetches 5-minute historical candle data strictly via Zerodha Kite Connect API.
       (Never uses yfinance per project Market Data Rules).
    2. Calculates On-Balance Volume (OBV) with moving average and True Strength Index (TSI)
       with signal line & zero line.
    3. Programmatically renders high-resolution multi-panel candlestick charts
       directly into an in-memory buffer (io.BytesIO) using mplfinance/matplotlib.
    4. Dispatches photo alerts with accompanying breakout analysis to Telegram via
       the Telegram Bot API (/sendPhoto) with automatic caption length handling.
===============================================================================
"""

import os
import io
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import pandas as pd
import numpy as np
import requests
from dotenv import load_dotenv

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

load_dotenv(dotenv_path=project_root / ".env")
logger = logging.getLogger("ChartGenerator")

# Try importing mplfinance & matplotlib
try:
    import mplfinance as mpf
    import matplotlib.pyplot as plt
    MPLFINANCE_AVAILABLE = True
except ImportError:
    MPLFINANCE_AVAILABLE = False
    logger.warning("mplfinance or matplotlib not installed. In-memory charting will be disabled.")

# Try importing KiteConnect
try:
    from kiteconnect import KiteConnect
    KITE_AVAILABLE = True
except ImportError:
    KITE_AVAILABLE = False
    logger.warning("kiteconnect package not found.")


def get_kite_client() -> Optional["KiteConnect"]:
    """
    Returns an authenticated Zerodha KiteConnect instance using credentials from .env.
    """
    if not KITE_AVAILABLE:
        return None
    api_key = os.getenv("ZERODHA_API_KEY")
    access_token = os.getenv("ZERODHA_ACCESS_TOKEN")
    if api_key and access_token:
        try:
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            return kite
        except Exception as e:
            logger.error(f"Failed to initialize KiteConnect client: {e}")
            return None
    return None


def fetch_5min_candles_zerodha(
    symbol: str,
    days: int = 5,
    kite: Optional["KiteConnect"] = None
) -> pd.DataFrame:
    """
    Fetches 5-minute OHLCV historical candles strictly from Zerodha Kite Connect API.
    Does NOT use yfinance (adheres to Zerodha market data rule).
    """
    clean_sym = symbol.strip().upper().replace(".NS", "")
    kite = kite or get_kite_client()
    if not kite:
        logger.error(f"Cannot fetch 5m candles for {clean_sym}: Zerodha Kite client unauthenticated or missing credentials.")
        return pd.DataFrame()

    try:
        from tradingagents.dataflows.zerodha import get_instrument_token
        token = get_instrument_token(clean_sym)
    except Exception as e:
        logger.error(f"Failed to resolve instrument token for {clean_sym}: {e}")
        return pd.DataFrame()

    try:
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)
        raw_candles = kite.historical_data(
            instrument_token=token,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
            interval="5minute"
        )
        if not raw_candles:
            logger.warning(f"Zerodha returned empty 5m candle list for {clean_sym}")
            return pd.DataFrame()

        df = pd.DataFrame(raw_candles)
        # Parse date and convert to tz-naive IST for mplfinance compatibility
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.set_index("date")
        df = df.rename(columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume"
        })
        for col in ["Open", "High", "Low", "Close"]:
            df[col] = df[col].astype(float)
        df["Volume"] = df["Volume"].astype(int)

        return df
    except Exception as e:
        logger.error(f"Error fetching 5m historical data from Zerodha for {clean_sym}: {e}")
        return pd.DataFrame()


def calculate_chart_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates technical indicators for chart plotting:
      1. On-Balance Volume (OBV) and OBV 20-period EMA
      2. True Strength Index (TSI: 13, 25) and TSI Signal Line (13) + Zero Line
      3. 9-period and 21-period Exponential Moving Averages on Close price
    """
    if df.empty or len(df) < 2:
        return df

    out_df = df.copy()

    # 1. Price EMAs
    out_df["EMA_9"] = out_df["Close"].ewm(span=9, adjust=False).mean()
    out_df["EMA_21"] = out_df["Close"].ewm(span=21, adjust=False).mean()

    # 2. On-Balance Volume (OBV)
    close_diff = out_df["Close"].diff()
    direction = np.where(close_diff > 0, 1, np.where(close_diff < 0, -1, 0))
    direction[0] = 0
    out_df["OBV"] = (direction * out_df["Volume"]).cumsum()
    out_df["OBV_EMA20"] = out_df["OBV"].ewm(span=20, adjust=False).mean()

    # 3. True Strength Index (TSI)
    # Double smoothing of price change and absolute price change: slow=25, fast=13
    pc = out_df["Close"].diff()
    abs_pc = pc.abs()

    pc_ema_slow = pc.ewm(span=25, min_periods=25, adjust=False).mean()
    pc_ema_fast = pc_ema_slow.ewm(span=13, min_periods=13, adjust=False).mean()

    abs_pc_ema_slow = abs_pc.ewm(span=25, min_periods=25, adjust=False).mean()
    abs_pc_ema_fast = abs_pc_ema_slow.ewm(span=13, min_periods=13, adjust=False).mean()

    abs_pc_ema_fast_safe = abs_pc_ema_fast.replace(0, np.nan)
    out_df["TSI"] = 100.0 * (pc_ema_fast / abs_pc_ema_fast_safe)
    out_df["TSI"] = out_df["TSI"].fillna(0.0)

    # Signal Line: 13-period EMA of TSI
    out_df["TSI_Signal"] = out_df["TSI"].ewm(span=13, min_periods=13, adjust=False).mean()
    out_df["TSI_Signal"] = out_df["TSI_Signal"].fillna(0.0)
    out_df["Zero"] = 0.0

    return out_df


def generate_5min_chart_buffer(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    trigger_price: Optional[float] = None,
    num_candles: int = 60,
    kite: Optional["KiteConnect"] = None,
    title_suffix: str = ""
) -> Optional[io.BytesIO]:
    """
    Renders a 5-minute candlestick chart with Volume, True Strength Index (TSI),
    and On-Balance Volume (OBV) directly to an in-memory buffer (io.BytesIO).

    Args:
        symbol: Stock ticker (e.g. 'RELIANCE' or 'INFY.NS')
        df: Optional pre-fetched 5m DataFrame. If None, fetches from Zerodha.
        trigger_price: Optional breakout trigger price to draw a horizontal guideline.
        num_candles: Number of recent 5-minute candles to display (default 60 = ~5 hours).
        kite: Optional authenticated KiteConnect instance.
        title_suffix: Optional extra text in chart title.

    Returns:
        io.BytesIO buffer positioned at start (ready to read/send), or None if generation failed.
    """
    if not MPLFINANCE_AVAILABLE:
        logger.error("mplfinance not installed, cannot generate chart buffer.")
        return None

    clean_sym = symbol.strip().upper().replace(".NS", "")

    # Fetch 5-minute candles from Zerodha if not provided
    if df is None or df.empty:
        df = fetch_5min_candles_zerodha(clean_sym, days=5, kite=kite)

    if df.empty or len(df) < 15:
        logger.warning(f"Insufficient candle data ({len(df)} candles) to generate chart for {clean_sym}.")
        return None

    try:
        # Calculate indicators on the full dataset for warmup
        full_df = calculate_chart_indicators(df)

        # Slice the most recent candles for display
        plot_df = full_df.tail(num_candles).copy()

        # Build addplots list
        ap = []

        # Panel 0 (Price Chart): EMA 9 (Cyan) & EMA 21 (Yellow)
        ap.append(mpf.make_addplot(plot_df["EMA_9"], panel=0, color="#00E5FF", width=1.1))
        ap.append(mpf.make_addplot(plot_df["EMA_21"], panel=0, color="#FFD600", width=1.1))

        # Panel 0 guideline for breakout trigger price if provided
        if trigger_price and trigger_price > 0:
            trig_series = pd.Series(float(trigger_price), index=plot_df.index)
            ap.append(mpf.make_addplot(trig_series, panel=0, color="#FF1744", width=1.2, linestyle="--"))

        # Panel 0 trigger marker arrow under latest candle low
        markers = [np.nan] * len(plot_df)
        markers[-1] = plot_df["Low"].iloc[-1] * 0.997
        ap.append(mpf.make_addplot(markers, type="scatter", marker="^", markersize=140, color="#00E676", panel=0))

        # Panel 2: True Strength Index (TSI: Blue, Signal: Orange, Zero: Gray dashed)
        ap.append(mpf.make_addplot(plot_df["TSI"], panel=2, color="#2979FF", width=1.6, ylabel="TSI (13,25,13)"))
        ap.append(mpf.make_addplot(plot_df["TSI_Signal"], panel=2, color="#FF6D00", width=1.2))
        ap.append(mpf.make_addplot(plot_df["Zero"], panel=2, color="#90A4AE", width=0.8, linestyle="--"))

        # Panel 3: On-Balance Volume (OBV: Purple, OBV EMA20: Gold dashed)
        ap.append(mpf.make_addplot(plot_df["OBV"], panel=3, color="#AB47BC", width=1.6, ylabel="OBV"))
        ap.append(mpf.make_addplot(plot_df["OBV_EMA20"], panel=3, color="#FDD835", width=1.0, linestyle="--"))

        # Visual Styling (High-contrast dark trading terminal)
        mc = mpf.make_marketcolors(
            up="#26a69a",
            down="#ef5350",
            edge="inherit",
            wick="inherit",
            volume="inherit"
        )
        custom_style = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            marketcolors=mc,
            gridcolor="#262B33",
            gridstyle=":"
        )

        last_close = plot_df["Close"].iloc[-1]
        last_time_str = plot_df.index[-1].strftime("%d-%b %H:%M")
        chart_title = f"\n{clean_sym} (5m) • Close: ₹{last_close:,.2f} • {last_time_str} IST{title_suffix}"

        # Render directly to in-memory buffer
        buffer = io.BytesIO()
        mpf.plot(
            plot_df,
            type="candle",
            volume=True,
            addplot=ap,
            title=chart_title,
            style=custom_style,
            panel_ratios=(5, 1.8, 2.2, 2.2),
            figsize=(12, 8.5),
            savefig=dict(fname=buffer, format="png", dpi=120, bbox_inches="tight")
        )
        buffer.seek(0)

        # Release matplotlib figure memory
        plt.close("all")

        logger.info(f"Successfully generated in-memory 5m chart for {clean_sym} ({len(buffer.getvalue())} bytes).")
        return buffer

    except Exception as e:
        logger.error(f"Exception while generating in-memory chart for {clean_sym}: {e}", exc_info=True)
        try:
            plt.close("all")
        except Exception:
            pass
        return None


def send_telegram_chart_alert(
    symbol: str,
    message_text: str,
    chart_buffer: Optional[io.BytesIO] = None,
    trigger_price: Optional[float] = None,
    parse_mode: str = "HTML",
    kite: Optional["KiteConnect"] = None
) -> Dict[str, Any]:
    """
    Sends a formatted alert along with the in-memory 5-minute chart screenshot to Telegram.

    If chart_buffer is not provided, it automatically fetches 5m candles via Zerodha
    and renders the chart with Volume, OBV, and TSI.

    Handles Telegram's 1024-character caption limit automatically:
      - If text <= 1024 characters: sent directly as photo caption.
      - If text > 1024 characters: sends photo with summary caption, followed by the
        complete text via sendMessage so no information is lost.
      - If chart generation fails, falls back gracefully to text-only sendMessage.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("Telegram credentials (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID) not found in .env.")
        return {"status": "unconfigured", "sent": False, "message": "Missing Telegram credentials."}

    clean_sym = symbol.strip().upper().replace(".NS", "")

    # 1. Obtain or generate the in-memory chart buffer
    buf = chart_buffer
    if buf is None:
        try:
            buf = generate_5min_chart_buffer(
                symbol=clean_sym,
                trigger_price=trigger_price,
                kite=kite
            )
        except Exception as e:
            logger.error(f"Failed to generate chart buffer for Telegram alert: {e}")
            buf = None

    # 2. If chart buffer is available, dispatch via sendPhoto
    if buf is not None and len(buf.getvalue()) > 0:
        try:
            photo_url = f"https://api.telegram.org/bot{token}/sendPhoto"
            buf.seek(0)
            photo_bytes = buf.getvalue()

            # Telegram sendPhoto caption has a hard 1024-character limit
            if len(message_text) <= 1024:
                payload = {
                    "chat_id": chat_id,
                    "caption": message_text,
                    "parse_mode": parse_mode
                }
                files = {
                    "photo": (f"{clean_sym}_5m_chart.png", photo_bytes, "image/png")
                }
                resp = requests.post(photo_url, data=payload, files=files, timeout=20)
                if resp.status_code == 200:
                    logger.info(f"Successfully sent Telegram 5m chart alert with photo for {clean_sym}!")
                    return {"status": "success", "sent": True, "photo_sent": True}
                else:
                    logger.error(f"Telegram sendPhoto failed: {resp.status_code} - {resp.text}")
            else:
                # Caption exceeds 1024 chars -> send photo with concise summary, then send full text
                lines = message_text.split("\n")
                summary_lines = []
                total_len = 0
                for line in lines:
                    if total_len + len(line) + 1 > 950:
                        break
                    summary_lines.append(line)
                    total_len += len(line) + 1
                caption_summary = "\n".join(summary_lines)

                payload = {
                    "chat_id": chat_id,
                    "caption": caption_summary,
                    "parse_mode": parse_mode
                }
                files = {
                    "photo": (f"{clean_sym}_5m_chart.png", photo_bytes, "image/png")
                }
                resp = requests.post(photo_url, data=payload, files=files, timeout=20)

                # Send full text as follow-up message
                msg_url = f"https://api.telegram.org/bot{token}/sendMessage"
                msg_payload = {
                    "chat_id": chat_id,
                    "text": message_text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True
                }
                msg_resp = requests.post(msg_url, json=msg_payload, timeout=15)

                if resp.status_code == 200 or msg_resp.status_code == 200:
                    logger.info(f"Successfully dispatched Telegram 5m chart photo + detailed message for {clean_sym}!")
                    return {"status": "success", "sent": True, "photo_sent": (resp.status_code == 200)}
                else:
                    logger.error(f"Telegram photo dispatch failed: {resp.status_code} - {resp.text}")

        except Exception as e:
            logger.error(f"Exception during Telegram sendPhoto dispatch: {e}")

    # 3. Graceful Fallback to sendMessage if photo buffer wasn't available or sendPhoto failed
    try:
        logger.info(f"Sending text-only fallback Telegram alert for {clean_sym}...")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message_text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code == 200:
            logger.info(f"Successfully sent text-only Telegram alert for {clean_sym}.")
            return {"status": "success", "sent": True, "photo_sent": False}
        else:
            logger.error(f"Failed to send text-only Telegram alert: {res.status_code} - {res.text}")
            return {"status": "error", "sent": False, "photo_sent": False, "error": res.text}
    except Exception as e:
        logger.error(f"Exception during text-only Telegram dispatch: {e}")
        return {"status": "error", "sent": False, "photo_sent": False, "error": str(e)}
