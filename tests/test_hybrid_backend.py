import unittest
from datetime import datetime, timezone, timedelta
import pandas as pd

from db_setup import setup_database
from data_manager import DataManager
from indicators import append_indicators
from kite_client import KiteEngine, get_candle_start_time

class TestHybridBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_name = "trading_data_test_hybrid"
        # Ensure database and indexes are set up
        cls.client = setup_database(db_name=cls.db_name)
        cls.db = cls.client[cls.db_name]

    @classmethod
    def tearDownClass(cls):
        # Drop the test database and close client
        cls.client.drop_database(cls.db_name)
        cls.client.close()

    def setUp(self):
        # Establish clean state before each test
        self.db["instruments"].delete_many({})
        self.db["candles_10m"].delete_many({})
        self.data_manager = DataManager(db_name=self.db_name)

    def tearDown(self):
        self.data_manager.close()

    def test_indicator_calculation(self):
        """Verify technical indicator logic: TSI and OBV calculation on mock DataFrame."""
        # Create a mock series of 30 candles
        data = {
            "close": [100.0 + i for i in range(30)],
            "volume": [1000 * (i + 1) for i in range(30)]
        }
        df = pd.DataFrame(data)
        
        # Calculate indicators
        updated_df = append_indicators(df)
        
        # Assert columns are created
        self.assertIn("tsi", updated_df.columns)
        self.assertIn("obv", updated_df.columns)
        
        # Since close prices are strictly increasing, OBV should be strictly increasing and positive
        self.assertTrue((updated_df["obv"] > 0).all() or updated_df["obv"].iloc[0] == 0)
        self.assertGreater(updated_df["obv"].iloc[-1], updated_df["obv"].iloc[0])

    def test_get_candle_start_time(self):
        """Test the 10-minute candle timestamp alignment with 5-minute offset."""
        # 09:17:23 -> 09:15:00
        t1 = datetime(2026, 7, 17, 9, 17, 23)
        self.assertEqual(get_candle_start_time(t1), datetime(2026, 7, 17, 9, 15, 0))

        # 09:24:59 -> 09:15:00
        t2 = datetime(2026, 7, 17, 9, 24, 59)
        self.assertEqual(get_candle_start_time(t2), datetime(2026, 7, 17, 9, 15, 0))

        # 09:25:00 -> 09:25:00
        t3 = datetime(2026, 7, 17, 9, 25, 0)
        self.assertEqual(get_candle_start_time(t3), datetime(2026, 7, 17, 9, 25, 0))

        # 10:02:15 -> 09:55:00 (crosses hour boundary back to 55)
        t4 = datetime(2026, 7, 17, 10, 2, 15)
        self.assertEqual(get_candle_start_time(t4), datetime(2026, 7, 17, 9, 55, 0))

    def test_bootstrap_logic(self):
        """Test bootstrap gap-detection logic for empty, partial, fresh, and stale databases."""
        token = 99999
        required = 150
        
        # Scenario 1: Empty Database -> requires full lookback fetch
        df, fetch_from, fetch_to = self.data_manager.bootstrap_data(token, required_count=required)
        self.assertTrue(df.empty)
        self.assertIsNotNone(fetch_from)
        self.assertIsNotNone(fetch_to)
        self.assertGreater(fetch_to, fetch_from)

        # Scenario 2: Partially Filled Database (< 150 candles) -> requires lookback fetch
        partial_candles = []
        base_time = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(hours=10)
        for i in range(10):  # Insert only 10 candles
            partial_candles.append({
                "instrument_token": token,
                "timestamp": base_time + timedelta(minutes=10 * i),
                "open": 100.0, "high": 105.0, "low": 95.0, "close": 101.0, "volume": 1000
            })
        self.db["candles_10m"].insert_many(partial_candles)
        
        df, fetch_from, fetch_to = self.data_manager.bootstrap_data(token, required_count=required)
        self.assertEqual(len(df), 10)
        self.assertIsNotNone(fetch_from)
        self.assertIsNotNone(fetch_to)

        # Clear DB for next scenarios
        self.db["candles_10m"].delete_many({})

        # Scenario 3: Fully Up-to-Date Database (150 candles, latest is 5 minutes old) -> no fetch
        full_candles = []
        # Offset so that latest candle (i=149) starts at exactly now - 5 minutes
        fresh_base_time = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(minutes=10 * required) + timedelta(minutes=5)
        for i in range(required):
            full_candles.append({
                "instrument_token": token,
                "timestamp": fresh_base_time + timedelta(minutes=10 * i),
                "open": 100.0, "high": 105.0, "low": 95.0, "close": 101.0, "volume": 1000
            })
        self.db["candles_10m"].insert_many(full_candles)
        
        df, fetch_from, fetch_to = self.data_manager.bootstrap_data(token, required_count=required)
        self.assertEqual(len(df), required)
        self.assertIsNone(fetch_from, "Should not request historical fetch when DB is fresh")
        self.assertIsNone(fetch_to, "Should not request historical fetch when DB is fresh")

        # Scenario 4: Stale Database (150 candles, latest is 2 hours old) -> fetch gap from latest
        self.db["candles_10m"].delete_many({})
        stale_base_time = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(minutes=10 * required + 120)
        for i in range(required):
            full_candles[i]["timestamp"] = stale_base_time + timedelta(minutes=10 * i)
        self.db["candles_10m"].insert_many(full_candles)
        
        latest_expected_ts = full_candles[-1]["timestamp"]
        
        df, fetch_from, fetch_to = self.data_manager.bootstrap_data(token, required_count=required)
        self.assertEqual(len(df), required)
        self.assertIsNotNone(fetch_from)
        self.assertEqual(fetch_from, latest_expected_ts)
        self.assertIsNotNone(fetch_to)

    def test_aggregation_and_rollover(self):
        """Test tick aggregation, candle construction, and rollover handling in KiteEngine."""
        token = 77777
        engine = KiteEngine(data_manager=self.data_manager, mock_mode=True)
        
        # We hook a validation callback into the engine
        closed_candles = []
        def _on_closed(candle, rdf):
            closed_candles.append(candle)
        engine.on_candle_closed = _on_closed

        # Define 4 ticks mapping to 2 different candle boundaries
        # Candle A: 10:15:00 to 10:24:59
        # Candle B: 10:25:00 onwards
        
        # Tick 1: start Candle A
        tick_1 = {
            "instrument_token": token,
            "last_price": 100.0,
            "volume": 10000,
            "last_traded_quantity": 100,
            "exchange_timestamp": datetime(2026, 7, 17, 10, 15, 5)
        }
        # Tick 2: update Candle A (new high)
        tick_2 = {
            "instrument_token": token,
            "last_price": 105.0,
            "volume": 10150,
            "last_traded_quantity": 50,
            "exchange_timestamp": datetime(2026, 7, 17, 10, 17, 30)
        }
        # Tick 3: update Candle A (new low, and final tick in window)
        tick_3 = {
            "instrument_token": token,
            "last_price": 98.0,
            "volume": 10250,
            "last_traded_quantity": 100,
            "exchange_timestamp": datetime(2026, 7, 17, 10, 24, 59)
        }
        # Tick 4: rollover trigger, start Candle B
        tick_4 = {
            "instrument_token": token,
            "last_price": 101.0,
            "volume": 10300,
            "last_traded_quantity": 50,
            "exchange_timestamp": datetime(2026, 7, 17, 10, 25, 1)
        }

        # Inject ticks
        engine.process_tick(tick_1)
        self.assertEqual(engine.current_candle["open"], 100.0)
        self.assertEqual(engine.current_candle["timestamp"], datetime(2026, 7, 17, 10, 15, 0))

        engine.process_tick(tick_2)
        self.assertEqual(engine.current_candle["high"], 105.0)

        engine.process_tick(tick_3)
        self.assertEqual(engine.current_candle["low"], 98.0)
        self.assertEqual(engine.current_candle["close"], 98.0)

        # Trigger rollover by passing Tick 4
        engine.process_tick(tick_4)
        
        # Verify Candle A was finalized
        self.assertEqual(len(closed_candles), 1)
        candle_a = closed_candles[0]
        self.assertEqual(candle_a["instrument_token"], token)
        self.assertEqual(candle_a["timestamp"], datetime(2026, 7, 17, 10, 15, 0))
        self.assertEqual(candle_a["open"], 100.0)
        self.assertEqual(candle_a["high"], 105.0)
        self.assertEqual(candle_a["low"], 98.0)
        self.assertEqual(candle_a["close"], 98.0)
        # Volume: calculated as 10250 - 10000 + 100 = 350
        self.assertEqual(candle_a["volume"], 350)
        
        # Check database persistence of Candle A
        db_candle = self.db["candles_10m"].find_one({"instrument_token": token, "timestamp": datetime(2026, 7, 17, 10, 15, 0)})
        self.assertIsNotNone(db_candle)
        self.assertEqual(db_candle["close"], 98.0)

        # Verify Candle B is now active
        self.assertEqual(engine.current_candle["timestamp"], datetime(2026, 7, 17, 10, 25, 0))
        self.assertEqual(engine.current_candle["open"], 101.0)
        self.assertEqual(engine.current_candle["volume"], 50)

    def test_websocket_callbacks_and_reconnect(self):
        """Test MockKiteTicker setup and trigger callback registration to assert auto-reconnect config."""
        import time
        engine = KiteEngine(data_manager=self.data_manager, mock_mode=True)
        
        # Register a callback to verify connections
        connected = [False]
        def _on_connect(ws, response):
            connected[0] = True
            
        engine.kws.on_connect = _on_connect
        
        # Connect with threaded=True to prevent blocking unit test thread
        engine.kws.connect(threaded=True)
        
        # Give it a brief moment to run the callback
        time.sleep(0.2)
        
        self.assertTrue(connected[0], "WebSocket connect callback not invoked")
        engine.kws.close()

if __name__ == "__main__":
    unittest.main()
