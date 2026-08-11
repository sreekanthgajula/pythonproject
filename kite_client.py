import logging
import time
import threading
import random
from datetime import datetime, timezone, timedelta
import pandas as pd

try:
    from kiteconnect import KiteConnect, KiteTicker
    KITE_AVAILABLE = True
except ImportError:
    KITE_AVAILABLE = False

import config
from data_manager import DataManager
import indicators

logger = logging.getLogger(__name__)

def get_candle_start_time(dt: datetime) -> datetime:
    """
    Aligns a datetime to the start of a 10-minute candle,
    incorporating the standard 5-minute offset (e.g., 9:15, 9:25, 9:35, etc.)
    """
    minute = dt.minute
    candle_minute = ((minute - 5) // 10) * 10 + 5
    if candle_minute < 0:
        # Wrap to the 55th minute of the previous hour
        dt_prev = dt - timedelta(hours=1)
        return dt_prev.replace(minute=55, second=0, microsecond=0)
    else:
        return dt.replace(minute=candle_minute, second=0, microsecond=0)


class MockKiteConnect:
    """Mock KiteConnect client for test and demonstration mode."""
    def __init__(self, api_key=None, access_token=None):
        self.api_key = api_key
        self.access_token = access_token
        
    def historical_data(self, instrument_token, from_date, to_date, interval, continuous=False, oi=False):
        """Generates random walk mock candles for testing."""
        logger.info(f"[MOCK-REST] Generating mock historical candles from {from_date} to {to_date}")
        candles = []
        current_time = from_date
        price = 1500.0
        
        # Step through 10-minute intervals
        while current_time < to_date:
            change = random.uniform(-5.0, 5.0)
            open_p = price
            close_p = price + change
            high_p = max(open_p, close_p) + random.uniform(0.0, 2.0)
            low_p = min(open_p, close_p) - random.uniform(0.0, 2.0)
            vol = random.randint(5000, 15000)
            
            candles.append({
                "date": current_time,
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": vol
            })
            price = close_p
            current_time += timedelta(minutes=10)
        return candles


class MockKiteTicker:
    """Mock KiteTicker WebSocket implementation for live tick simulation."""
    def __init__(self, api_key, access_token):
        self.api_key = api_key
        self.access_token = access_token
        self.on_ticks = None
        self.on_connect = None
        self.on_close = None
        self.on_error = None
        self.on_reconnect = None
        self._running = False
        self._thread = None
        self.MODE_FULL = "full"

    def enable_reconnect(self, reconnect_interval=5, reconnect_tries=50):
        logger.info(f"[MOCK-WS] Enabled auto reconnection. Interval: {reconnect_interval}s.")

    def connect(self, threaded=False):
        logger.info("[MOCK-WS] MockKiteTicker connecting...")
        self._running = True
        
        if self.on_connect:
            self.on_connect(self, {"status": "success"})
            
        if threaded:
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
        else:
            self._run_loop()

    def _run_loop(self):
        logger.info("[MOCK-WS] Mock tick feed started. Injecting ticks every 1 second.")
        price = 1520.0
        cum_volume = 120000
        
        while self._running:
            try:
                time.sleep(1.0)
                price_change = random.uniform(-1.5, 1.5)
                price += price_change
                qty = random.randint(1, 40)
                cum_volume += qty
                
                tick = {
                    "instrument_token": config.DEFAULT_INSTRUMENT_TOKEN,
                    "last_price": price,
                    "volume": cum_volume,
                    "last_traded_quantity": qty,
                    "timestamp": datetime.now(timezone.utc).replace(tzinfo=None)
                }
                
                if self.on_ticks:
                    self.on_ticks(self, [tick])
            except Exception as e:
                logger.error(f"[MOCK-WS] Error in tick generation: {e}")
                if self.on_error:
                    self.on_error(self, 500, str(e))
                break

    def close(self):
        logger.info("[MOCK-WS] MockKiteTicker closing.")
        self._running = False
        if self.on_close:
            self.on_close(self, 1000, "Closed by user")

    def subscribe(self, tokens):
        logger.info(f"[MOCK-WS] Subscribed to tokens: {tokens}")

    def set_mode(self, mode, tokens):
        logger.info(f"[MOCK-WS] Mode '{mode}' set for tokens: {tokens}")


class KiteEngine:
    def __init__(self, data_manager: DataManager, mock_mode: bool = False):
        """
        Orchestrator for Kite Connect API & WebSocket Streaming.
        
        Args:
            data_manager (DataManager): Instance of data manager.
            mock_mode (bool): Forces Mock clients even if real keys exist.
        """
        self.data_manager = data_manager
        self.mock_mode = mock_mode or not KITE_AVAILABLE or not config.ZERODHA_API_KEY or not config.ZERODHA_ACCESS_TOKEN
        
        self.kite = None
        self.kws = None
        self.rolling_df = pd.DataFrame()
        self.current_candle = None
        self.on_candle_closed = None  # Callback function: (candle_doc, rolling_df) -> None
        
        self._initialize_clients()

    def _initialize_clients(self):
        """Initialize Zerodha clients based on mock settings."""
        if self.mock_mode:
            logger.info("Initializing in MOCK mode.")
            self.kite = MockKiteConnect(config.ZERODHA_API_KEY, config.ZERODHA_ACCESS_TOKEN)
            self.kws = MockKiteTicker(config.ZERODHA_API_KEY, config.ZERODHA_ACCESS_TOKEN)
        else:
            logger.info("Initializing in REAL mode with Zerodha API.")
            self.kite = KiteConnect(api_key=config.ZERODHA_API_KEY)
            self.kite.set_access_token(config.ZERODHA_ACCESS_TOKEN)
            self.kws = KiteTicker(config.ZERODHA_API_KEY, config.ZERODHA_ACCESS_TOKEN)

    def bootstrap(self, instrument_token: int):
        """
        Phase 1: Startup bootstrap.
        Queries the database for existing candles and fetches missing gaps from Zerodha.
        Calculates initial indicators to warm up rolling memory.
        """
        # Get existing data and check for required gaps/staleness
        df, fetch_from, fetch_to = self.data_manager.bootstrap_data(instrument_token)
        self.rolling_df = df

        if fetch_from and fetch_to:
            try:
                # Retrieve missing historical records
                api_candles = self.kite.historical_data(
                    instrument_token=instrument_token,
                    from_date=fetch_from,
                    to_date=fetch_to,
                    interval=config.TIMEFRAME
                )
                
                logger.info(f"Phase 1 bootstrap: Fetched {len(api_candles)} candles from REST API.")
                
                # Parse and cache REST data
                for c in api_candles:
                    dt = c["date"]
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                        
                    candle_doc = {
                        "instrument_token": instrument_token,
                        "timestamp": dt,
                        "open": float(c["open"]),
                        "high": float(c["high"]),
                        "low": float(c["low"]),
                        "close": float(c["close"]),
                        "volume": int(c["volume"])
                    }
                    # Save to MongoDB
                    self.data_manager.save_closed_candle(candle_doc)
                    # Update in-memory rolling window
                    self.rolling_df = self.data_manager.update_memory(self.rolling_df, candle_doc)
            except Exception as e:
                logger.error(f"Failed to fetch REST bootstrap candles: {e}")
                logger.warning("Continuing bootstrap with cached DB records only.")

        # Warm up indicators on loaded dataset
        if not self.rolling_df.empty:
            logger.info("Warming up technical indicators (TSI, OBV)...")
            self.rolling_df = indicators.append_indicators(self.rolling_df)
            logger.info(f"Warm-up complete. Current memory size: {len(self.rolling_df)}")
        else:
            logger.warning("Memory DataFrame is empty after bootstrap. Indicators cannot be computed.")

    def finalize_current_candle(self):
        """Finalize the current candle in memory, save it, and update indices."""
        if not self.current_candle:
            return

        candle_doc = {
            "instrument_token": int(self.current_candle["instrument_token"]),
            "timestamp": self.current_candle["timestamp"],
            "open": float(self.current_candle["open"]),
            "high": float(self.current_candle["high"]),
            "low": float(self.current_candle["low"]),
            "close": float(self.current_candle["close"]),
            "volume": int(self.current_candle["volume"])
        }
        
        # 1. Persist to MongoDB
        self.data_manager.save_closed_candle(candle_doc)
        
        # 2. Append to rolling DataFrame in memory
        self.rolling_df = self.data_manager.update_memory(self.rolling_df, candle_doc)
        
        # 3. Recalculate indicators
        self.rolling_df = indicators.append_indicators(self.rolling_df)
        
        logger.info(f"Candle closed and indicators calculated for: {candle_doc['timestamp']}")
        
        # 4. Trigger callback if registered
        if self.on_candle_closed:
            self.on_candle_closed(candle_doc, self.rolling_df)

    def process_tick(self, tick: dict):
        """
        Aggregates tick data into a 10-minute candle and handles the rollover.
        
        Args:
            tick (dict): Tick object from KiteTicker callback.
        """
        # Parse timestamp
        tick_time = tick.get("exchange_timestamp") or tick.get("timestamp")
        if not tick_time:
            tick_time = datetime.now(timezone.utc).replace(tzinfo=None)
        elif tick_time.tzinfo is not None:
            tick_time = tick_time.astimezone(timezone.utc).replace(tzinfo=None)

        last_price = float(tick["last_price"])
        tick_cum_volume = int(tick.get("volume", 0))
        last_traded_qty = int(tick.get("last_traded_quantity", 0))
        instrument_token = tick["instrument_token"]

        candle_start = get_candle_start_time(tick_time)

        # 1. Initialize candle
        if self.current_candle is None:
            self.current_candle = {
                "instrument_token": instrument_token,
                "timestamp": candle_start,
                "open": last_price,
                "high": last_price,
                "low": last_price,
                "close": last_price,
                "volume": last_traded_qty,
                "start_cum_volume": tick_cum_volume,
                "first_tick_volume": last_traded_qty
            }
            logger.info(f"Initialized first tick-candle for {candle_start}")
            
        # 2. Rollover
        elif candle_start > self.current_candle["timestamp"]:
            self.finalize_current_candle()
            
            # Start new candle
            self.current_candle = {
                "instrument_token": instrument_token,
                "timestamp": candle_start,
                "open": last_price,
                "high": last_price,
                "low": last_price,
                "close": last_price,
                "volume": last_traded_qty,
                "start_cum_volume": tick_cum_volume,
                "first_tick_volume": last_traded_qty
            }
            logger.info(f"Rollover triggered! Starting candle for {candle_start}")
            
        # 3. Normal update
        else:
            self.current_candle["high"] = max(self.current_candle["high"], last_price)
            self.current_candle["low"] = min(self.current_candle["low"], last_price)
            self.current_candle["close"] = last_price
            
            # Use cumulative volume subtraction if available, else sum trade quantities
            if tick_cum_volume > 0 and self.current_candle["start_cum_volume"] > 0:
                calc_volume = tick_cum_volume - self.current_candle["start_cum_volume"] + self.current_candle["first_tick_volume"]
                self.current_candle["volume"] = max(calc_volume, self.current_candle["volume"])
            else:
                self.current_candle["volume"] += last_traded_qty

    def start_websocket(self, instrument_token: int):
        """
        Phase 2: Set up WebSocket feed for streaming data.
        Register callbacks and handle auto reconnection.
        """
        # Set up callbacks
        def _on_ticks(ws, ticks):
            for tick in ticks:
                if tick.get("instrument_token") == instrument_token:
                    self.process_tick(tick)

        def _on_connect(ws, response):
            logger.info(f"WebSocket connected. Subscribing to token {instrument_token}.")
            ws.subscribe([instrument_token])
            ws.set_mode(ws.MODE_FULL, [instrument_token])

        def _on_close(ws, code, reason):
            logger.warning(f"WebSocket connection closed. Code: {code}, Reason: {reason}")

        def _on_error(ws, code, reason):
            logger.error(f"WebSocket error. Code: {code}, Reason: {reason}")

        def _on_reconnect(ws, attempt_count):
            logger.info(f"Reconnecting to WebSocket... Attempt: {attempt_count}")

        # Bind callbacks
        self.kws.on_ticks = _on_ticks
        self.kws.on_connect = _on_connect
        self.kws.on_close = _on_close
        self.kws.on_error = _on_error
        self.kws.on_reconnect = _on_reconnect

        # Enable auto-reconnection
        self.kws.enable_reconnect(reconnect_interval=5, reconnect_tries=100)

        logger.info("Starting WebSocket streaming feed...")
        # Start connection (blocking, or threaded)
        self.kws.connect(threaded=True)
        
    def stop_websocket(self):
        """Stop the streaming client."""
        if self.kws:
            self.kws.close()
            logger.info("WebSocket client closed.")
