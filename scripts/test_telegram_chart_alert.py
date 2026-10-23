"""
===============================================================================
TEST SCRIPT: TELEGRAM 5-MINUTE CHART ALERT DISPATCHER
===============================================================================
Usage:
    python scripts/test_telegram_chart_alert.py --symbol RELIANCE
    python scripts/test_telegram_chart_alert.py --symbol INFY
===============================================================================
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from scripts.chart_generator import send_telegram_chart_alert, generate_5min_chart_buffer


def main():
    parser = argparse.ArgumentParser(description="Test Telegram 5m Chart Alert")
    parser.add_argument("--symbol", type=str, default="RELIANCE", help="Stock ticker symbol (default: RELIANCE)")
    parser.add_argument("--trigger", type=float, default=None, help="Optional trigger price")
    args = parser.parse_args()

    symbol = args.symbol.strip().upper()
    print(f"[*] Preparing test 5-Minute Chart alert for {symbol}...")

    # Formulate sample breakout alert message
    sample_text = (
        f"⚡ <b>TEST DARVAS BREAKOUT ALERT</b> - <b>{symbol}</b>\n\n"
        f"📊 <b>Timeframe</b>: 5-Minute Candlestick Chart\n"
        f"📈 <b>Technical Indicators</b>:\n"
        f"   • <b>Volume</b>: Real-time 5m candle volume\n"
        f"   • <b>OBV</b>: On-Balance Volume + 20-period EMA\n"
        f"   • <b>True Strength</b>: TSI (13, 25, 13) + Signal Line\n\n"
        f"🚀 <i>Direct In-Memory Programmatic Chart Generation (io.BytesIO) via Zerodha API</i>"
    )

    print(f"[*] Fetching Zerodha 5m data and generating in-memory chart buffer...")
    res = send_telegram_chart_alert(
        symbol=symbol,
        message_text=sample_text,
        trigger_price=args.trigger,
        parse_mode="HTML"
    )

    print(f"[*] Result: {res}")
    if res.get("sent"):
        print(f"[SUCCESS] Telegram alert with 5-minute chart sent successfully for {symbol}!")
    else:
        print(f"[ERROR] Failed to send Telegram alert: {res.get('error') or res.get('message')}")


if __name__ == "__main__":
    main()
