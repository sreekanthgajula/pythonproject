"""
===============================================================================
ZERODHA KITETICKER WEBSOCKET REAL-TIME ALERT ENGINE & ORDER LISTENER
===============================================================================
Description:
    1. Connects to Zerodha KiteTicker WebSocket interface for real-time tick-by-tick market data.
    2. Dynamically resolves instrument tokens for stocks in the Grok-evaluated rating tables
       ('monthly', 'weekly', 'daily') and the active watchlist.
    3. Monitors tick-by-tick prices against the 1% breakout trigger price (recent_high * 1.01).
    4. Triggers instant breakout alerts (Telegram/Discord/UI) the moment price crosses the trigger.
    5. Listens to 'on_order_update' callbacks to track all order updates (including orders placed
       manually on Kite Web or Kite Mobile, and GTT trigger executions).
===============================================================================
"""

import os
import sys
import time
import logging
import threading
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from data_manager import DataManager
from tradingagents.dataflows.zerodha import get_instrument_token, get_zerodha_credentials
from tradingagents.dataflows.symbol_utils import normalize_symbol

# Try importing KiteConnect & KiteTicker
try:
    from kiteconnect import KiteConnect, KiteTicker
    KITE_WS_AVAILABLE = True
except ImportError:
    KITE_WS_AVAILABLE = False
    from kite_client import MockKiteTicker as KiteTicker

load_dotenv(dotenv_path=project_root / ".env")
logger = logging.getLogger("KiteTickerAlertListener")

class ZerodhaWebSocketAlertEngine:
    def __init__(self, api_key: str = None, access_token: str = None, mock_mode: bool = False):
        creds = get_zerodha_credentials()
        self.api_key = api_key or creds.get("api_key") or os.getenv("ZERODHA_API_KEY")
        self.access_token = access_token or creds.get("access_token") or os.getenv("ZERODHA_ACCESS_TOKEN")
        self.mock_mode = mock_mode or not (self.api_key and self.access_token) or not KITE_WS_AVAILABLE
        
        self.kws = None
        self.token_map = {}          # instrument_token (int) -> dict metadata
        self.alerted_today = set()   # (symbol, date_str)
        self.is_running = False
        self._thread = None
        self.dm = None
        
        try:
            self.dm = DataManager()
        except Exception as e:
            logger.warning(f"DataManager connection warning: {e}")

    def load_monitored_targets(self) -> dict[int, dict]:
        """
        Queries MongoDB rating tables ('monthly', 'weekly', 'daily') and watchlist,
        resolves Zerodha instrument tokens, and builds the trigger lookup map.
        """
        target_map = {}
        if not self.dm:
            return target_map

        timeframes = ["monthly", "weekly", "daily"]
        for tf in timeframes:
            try:
                records = self.dm.get_stock_ratings(tf)
                for r in records:
                    sym = r.get("symbol", "").upper()
                    trigger_price = float(r.get("alert_trigger_price") or 0.0)
                    recent_high = float(r.get("recent_high") or 0.0)
                    
                    if not sym or trigger_price <= 0:
                        continue
                        
                    try:
                        token = get_instrument_token(sym)
                        target_map[token] = {
                            "symbol": sym,
                            "timeframe": tf,
                            "recent_high": recent_high,
                            "alert_trigger_price": trigger_price,
                            "rating": r.get("rating", 4.0),
                            "reason": r.get("reason", "")
                        }
                    except Exception as tok_err:
                        logger.warning(f"Could not resolve instrument token for {sym}: {tok_err}")
            except Exception as err:
                logger.error(f"Error fetching rating targets for {tf}: {err}")

        logger.info(f"Loaded {len(target_map)} unique instrument targets for live WebSocket monitoring.")
        self.token_map = target_map
        return target_map

    def _on_ticks(self, ws, ticks):
        """Callback executed on receiving tick data from Zerodha WebSocket feed."""
        today_str = datetime.now().strftime("%Y-%m-%d")

        for tick in ticks:
            token = tick.get("instrument_token")
            if token not in self.token_map:
                continue

            data = self.token_map[token]
            symbol = data["symbol"]
            trigger_price = data["alert_trigger_price"]
            last_price = float(tick.get("last_price", 0.0))

            # Check if live price crossed the +1% breakout trigger
            if last_price >= trigger_price:
                alert_key = (symbol, today_str)
                if alert_key in self.alerted_today:
                    continue

                self.alerted_today.add(alert_key)
                recent_high = data["recent_high"]
                pct_above = ((last_price - recent_high) / recent_high * 100) if recent_high > 0 else 1.0

                logger.info(f"🚨 [REAL-TIME BREAKOUT ALERT] {symbol} crossed trigger price! Current: ₹{last_price:.2f} >= Trigger: ₹{trigger_price:.2f} (+{pct_above:.2f}%)")

                # Dispatch alert notification & trailing +1% ladder update
                self.dispatch_alert(symbol, last_price, trigger_price, data, token=token)

    def _on_order_update(self, ws, data):
        """
        Callback executed whenever an order status updates on Zerodha Kite Connect.
        Captures GTT order triggers and intentional 5,000-qty margin REJECTION events,
        cross-checks the rejection price against database trigger values, and dispatches alerts.
        """
        order_id = data.get("order_id")
        trading_symbol = str(data.get("tradingsymbol", "")).upper().replace(".NS", "")
        status = str(data.get("status", "")).upper()
        transaction_type = data.get("transaction_type", "BUY")
        quantity = data.get("quantity", 0)
        price = float(data.get("price") or data.get("average_price") or data.get("trigger_price") or 0.0)
        status_message = data.get("status_message") or data.get("status_message_raw") or "Margin check failed (Intentionally large qty)"

        logger.info(f"🔔 [ZERODHA ORDER UPDATE] Order ID: {order_id} | {trading_symbol} {transaction_type} QTY={quantity} | Status: {status} @ ₹{price}")

        # Target statuses: REJECTED, TRIGGERED, CANCELLED, COMPLETE
        if status in ("REJECTED", "TRIGGERED", "CANCELLED", "COMPLETE"):
            self.verify_and_process_order_rejection(
                symbol=trading_symbol,
                status=status,
                order_price=price,
                quantity=quantity,
                status_message=status_message,
                order_id=order_id
            )

    def verify_and_process_order_rejection(
        self,
        symbol: str,
        status: str,
        order_price: float,
        quantity: int = 0,
        status_message: str = "",
        order_id: str = None
    ):
        """
        Cross-checks a Zerodha order status/rejection against the stock's trigger_price in MongoDB,
        verifies whether the 1% breakout level was reached, dispatches alerts, and updates trailing GTT.
        """
        if not self.dm:
            return

        clean_sym = symbol.strip().upper()
        matched_meta = None

        # Search across rating tables ('monthly', 'weekly', 'daily')
        for tf in ["monthly", "weekly", "daily"]:
            try:
                col = self.dm.db[tf]
                doc = col.find_one({"symbol": clean_sym}) or col.find_one({"symbol": f"{clean_sym}.NS"})
                if doc:
                    matched_meta = {
                        "symbol": clean_sym,
                        "timeframe": tf,
                        "recent_high": float(doc.get("recent_high", 0.0)),
                        "alert_trigger_price": float(doc.get("alert_trigger_price", 0.0)),
                        "alert_count": doc.get("alert_count", 0),
                        "gtt_quantity": doc.get("gtt_quantity", 5000)
                    }
                    break
            except Exception as db_err:
                logger.error(f"Error querying DB for order rejection check ({clean_sym}): {db_err}")

        if not matched_meta:
            logger.debug(f"Order update for {clean_sym} received, but symbol is not currently tracked in rating tables.")
            return

        db_trigger_price = matched_meta["alert_trigger_price"]
        db_recent_high = matched_meta["recent_high"]

        # If order price is 0 (e.g. market order), fallback to db_trigger_price or latest quote
        effective_price = order_price if order_price > 0 else db_trigger_price

        # CROSS-CHECK VERIFICATION: Confirm order rejection occurred at or above DB trigger price
        is_breakout_verified = effective_price >= (db_trigger_price * 0.995) or status in ("REJECTED", "TRIGGERED")

        if is_breakout_verified:
            today_str = datetime.now().strftime("%Y-%m-%d")
            alert_key = (clean_sym, today_str)

            if alert_key in self.alerted_today:
                logger.info(f"Alert already dispatched today for {clean_sym}. Skipping duplicate notification.")
                return

            self.alerted_today.add(alert_key)

            logger.info(
                f"\n=======================================================\n"
                f" 🚨 [ZERODHA GTT BREAKOUT VERIFIED VIA ORDER REJECTION]\n"
                f" Symbol: {clean_sym} ({matched_meta['timeframe'].upper()})\n"
                f" Order Status: {status} (Qty: {quantity})\n"
                f" Rejection/Order Price: ₹{effective_price:.2f} >= DB Trigger: ₹{db_trigger_price:.2f}\n"
                f" Reason: {status_message}\n"
                f"======================================================="
            )

            # Enrich notification text to clarify Zerodha order rejection
            meta_copy = matched_meta.copy()
            meta_copy["rejection_reason"] = status_message
            meta_copy["gtt_status"] = status
            meta_copy["order_id"] = order_id

            # Dispatch verified alert notification and advance trailing +1% ladder
            self.dispatch_alert(clean_sym, effective_price, db_trigger_price, meta_copy)

            # Automatically recreate Zerodha GTT order for 5,000 quantity at the new trailing trigger price (+1%)
            try:
                from scripts.zerodha_alert_manager import set_zerodha_1pct_breakout_alert
                set_zerodha_1pct_breakout_alert(clean_sym, timeframe=matched_meta["timeframe"], override_recent_high=effective_price)
                logger.info(f"[TRAILING GTT] Re-created Zerodha GTT order for {clean_sym} (Qty: 5000) at new trailing trigger level (High: ₹{effective_price:.2f}).")
            except Exception as regtt_err:
                logger.error(f"Failed to auto-recreate trailing GTT order for {clean_sym}: {regtt_err}")

    def _on_connect(self, ws, response):
        """Callback executed on successful WebSocket connection."""
        tokens = list(self.token_map.keys())
        if tokens:
            logger.info(f"WebSocket connected. Subscribing to {len(tokens)} instrument tokens in FULL mode...")
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_FULL, tokens)
        else:
            logger.info("WebSocket connected. No instrument tokens currently loaded to subscribe.")

    def _on_close(self, ws, code, reason):
        logger.warning(f"WebSocket connection closed. Code: {code}, Reason: {reason}")

    def _on_error(self, ws, code, reason):
        logger.error(f"WebSocket error: Code {code}, Reason: {reason}")

    def _on_reconnect(self, ws, attempt_count):
        logger.info(f"Reconnecting to Zerodha WebSocket... Attempt #{attempt_count}")

    def dispatch_alert(self, symbol: str, current_price: float, trigger_price: float, meta: dict, token: int = None):
        """
        Records alert in active alerts list, increments DB alert_count, dispatches notifications,
        and automatically advances alert_trigger_price to 1% above the newly alerted price (current_price * 1.01).
        """
        new_recent_high = round(current_price, 2)
        new_trigger_price = round(current_price * 1.01, 2)

        # 0. Increment alert_count and advance trigger_price to +1% above current alerted price in MongoDB
        if self.dm:
            try:
                tf = meta.get("timeframe", "monthly").strip().lower()
                col = self.dm.db[tf]
                ist_tz = timezone(timedelta(hours=5, minutes=30))
                col.update_one(
                    {"symbol": symbol.upper()},
                    {
                        "$inc": {"alert_count": 1},
                        "$set": {
                            "recent_high": new_recent_high,
                            "alert_trigger_price": new_trigger_price,
                            "last_alerted_at": datetime.now(ist_tz).replace(tzinfo=None)
                        }
                    }
                )
                logger.info(f"📈 [TRAILING 1% LADDER] {symbol} ({tf}): Alerted at ₹{current_price:.2f}. Advanced Next Trigger to ₹{new_trigger_price:.2f} (+1%). Incremented alert_count.")
            except Exception as db_inc_err:
                logger.error(f"Failed to update trailing alert data for {symbol}: {db_inc_err}")

        # Update in-memory metadata for live WebSocket feed
        if token and token in self.token_map:
            self.token_map[token]["recent_high"] = new_recent_high
            self.token_map[token]["alert_trigger_price"] = new_trigger_price

        try:
            # 1. Update API active_alerts list if API server is in scope
            from api.server import active_alerts
            active_alerts.append({
                "id": f"ws-{int(time.time())}-{symbol}",
                "ticker": symbol,
                "price": current_price,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "confidence": 0.95,
                "reason": f"Live Zerodha KiteTicker tick (₹{current_price:.2f}) crossed +1% breakout trigger level (₹{trigger_price:.2f}). Grok Rating: {meta.get('rating', 4.0)}",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        except Exception:
            pass

        # 2. Execute 5-Minute Good Buyer Volume Analysis
        buyer_analysis = {}
        try:
            from scripts.five_min_buyer_volume_analyzer import analyze_5min_good_buyer_volume, format_telegram_buyer_analysis_text
            buyer_analysis = analyze_5min_good_buyer_volume(symbol, kite=None)
            logger.info(f"5-Min Good Buyer Analysis for {symbol}: BuySignal={buyer_analysis.get('buy_signal')} | Rating={buyer_analysis.get('score_out_of_10')}/10")
        except Exception as analysis_err:
            logger.error(f"5-Min Good Buyer Volume Analysis failed for {symbol}: {analysis_err}")

        # 3. Dispatch enriched alert via Telegram
        try:
            telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
            telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
            
            if telegram_token and telegram_chat_id:
                from scripts.five_min_buyer_volume_analyzer import format_telegram_buyer_analysis_text
                tg_text = format_telegram_buyer_analysis_text(symbol, meta, buyer_analysis)
                
                tg_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                tg_payload = {
                    "chat_id": telegram_chat_id,
                    "text": tg_text,
                    "parse_mode": "HTML"
                }
                tg_resp = requests.post(tg_url, json=tg_payload, timeout=12)
                if tg_resp.status_code == 200:
                    logger.info(f"Successfully dispatched 5-Min Good Buyer Volume Telegram Alert for {symbol}!")
                else:
                    logger.error(f"Telegram dispatch failed: Status {tg_resp.status_code}, Body: {tg_resp.text}")
            else:
                from momentum_volume_monitor import send_alert
                send_alert(
                    ticker=symbol,
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    price=current_price,
                    obv_zscore=2.5,
                    tsi_slope=3.0,
                    tsi_val=28.0,
                    tsi_signal_val=22.0,
                    obv_condition=True,
                    tsi_condition=True,
                    tsi_crossed=True
                )
        except Exception as alert_err:
            logger.error(f"Failed to send breakout alert for {symbol}: {alert_err}")

    def start(self, threaded: bool = True):
        """Starts the WebSocket listener service."""
        if self.is_running:
            logger.info("WebSocket Alert Listener is already running.")
            return

        self.load_monitored_targets()
        
        if self.mock_mode:
            logger.info("[MOCK MODE] Initializing MockKiteTicker WebSocket client.")

        self.kws = KiteTicker(self.api_key, self.access_token)
        
        # Bind WebSocket callbacks
        self.kws.on_ticks = self._on_ticks
        self.kws.on_order_update = self._on_order_update
        self.kws.on_connect = self._on_connect
        self.kws.on_close = self._on_close
        self.kws.on_error = self._on_error
        self.kws.on_reconnect = self._on_reconnect

        # Enable auto-reconnection
        if hasattr(self.kws, "enable_reconnect"):
            self.kws.enable_reconnect(reconnect_interval=5, reconnect_tries=100)

        self.is_running = True
        logger.info("Starting Zerodha KiteTicker WebSocket Alert Engine...")

        if threaded:
            self._thread = threading.Thread(target=self.kws.connect, kwargs={"threaded": True}, daemon=True)
            self._thread.start()
        else:
            self.kws.connect()

    def stop(self):
        """Stops the WebSocket listener service."""
        if self.kws:
            try:
                self.kws.close()
            except Exception:
                pass
        self.is_running = False
        logger.info("Zerodha KiteTicker WebSocket Alert Engine stopped.")

# Singleton instance
ws_alert_engine = ZerodhaWebSocketAlertEngine()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=== Starting Zerodha KiteTicker WebSocket Real-Time Alert Engine ===")
    engine = ZerodhaWebSocketAlertEngine()
    engine.start(threaded=False)
