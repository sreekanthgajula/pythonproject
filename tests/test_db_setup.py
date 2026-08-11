import unittest
from datetime import datetime, timezone, timedelta
import pymongo
from pymongo.errors import WriteError, DuplicateKeyError
from db_setup import setup_database

class TestDBSetup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_name = "trading_data_test"
        cls.client = setup_database(db_name=cls.db_name)
        cls.db = cls.client[cls.db_name]

    @classmethod
    def tearDownClass(cls):
        # Clean up the test database entirely after all tests are finished
        cls.client.drop_database(cls.db_name)
        cls.client.close()

    def setUp(self):
        # Empty collections before each test for clean isolation
        self.db["instruments"].delete_many({})
        self.db["candles_10m"].delete_many({})

    def test_database_and_collections_created(self):
        """Verify that collections exist after running setup_database."""
        collections = self.db.list_collection_names()
        self.assertIn("instruments", collections)
        self.assertIn("candles_10m", collections)

    def test_indexes_exist(self):
        """Verify the correct indexes are created on the candles_10m collection."""
        indexes = self.db["candles_10m"].index_information()
        
        # Verify unique index on [instrument_token, timestamp] ascending
        unique_idx_found = False
        retrieval_idx_found = False
        
        for name, info in indexes.items():
            key = info.get("key")
            # key is a list of tuples like [('instrument_token', 1), ('timestamp', 1)]
            if key == [("instrument_token", 1), ("timestamp", 1)]:
                self.assertTrue(info.get("unique", False))
                unique_idx_found = True
            elif key == [("instrument_token", 1), ("timestamp", -1)]:
                retrieval_idx_found = True

        self.assertTrue(unique_idx_found, "Unique index [instrument_token (ASC), timestamp (ASC)] not found.")
        self.assertTrue(retrieval_idx_found, "Retrieval index [instrument_token (ASC), timestamp (DESC)] not found.")

    def test_instruments_valid_insert(self):
        """Test inserting a valid instrument document."""
        instruments_col = self.db["instruments"]
        doc = {
            "_id": 123456,  # Instrument token as integer
            "trading_symbol": "INFY",
            "exchange": "NSE"
        }
        result = instruments_col.insert_one(doc)
        self.assertEqual(result.inserted_id, 123456)
        
        # Verify retrieval
        retrieved = instruments_col.find_one({"_id": 123456})
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["trading_symbol"], "INFY")
        self.assertEqual(retrieved["exchange"], "NSE")

    def test_instruments_schema_validation_failures(self):
        """Test that invalid instrument documents fail validation constraints."""
        instruments_col = self.db["instruments"]
        
        # Scenario 1: missing required field (exchange)
        invalid_doc_1 = {
            "_id": 111,
            "trading_symbol": "SBIN"
        }
        with self.assertRaises(WriteError):
            instruments_col.insert_one(invalid_doc_1)

        # Scenario 2: wrong type for _id (string instead of int)
        invalid_doc_2 = {
            "_id": "invalid_id_string",
            "trading_symbol": "SBIN",
            "exchange": "NSE"
        }
        with self.assertRaises(WriteError):
            instruments_col.insert_one(invalid_doc_2)

    def test_instruments_uniqueness(self):
        """Test that _id uniqueness constraint is enforced on instruments collection."""
        instruments_col = self.db["instruments"]
        doc1 = {"_id": 999, "trading_symbol": "RELIANCE", "exchange": "NSE"}
        doc2 = {"_id": 999, "trading_symbol": "REL_DUP", "exchange": "NSE"}
        
        instruments_col.insert_one(doc1)
        with self.assertRaises(DuplicateKeyError):
            instruments_col.insert_one(doc2)

    def test_candles_valid_insert(self):
        """Test inserting a valid candle document."""
        candles_col = self.db["candles_10m"]
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        doc = {
            "instrument_token": 123456,
            "timestamp": now,
            "open": 1500.50,
            "high": 1515.00,
            "low": 1495.20,
            "close": 1510.00,
            "volume": 25000
        }
        result = candles_col.insert_one(doc)
        self.assertIsNotNone(result.inserted_id)

    def test_candles_schema_validation_failures(self):
        """Test that invalid candle documents fail validation constraints."""
        candles_col = self.db["candles_10m"]
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Scenario 1: missing close price
        invalid_doc_1 = {
            "instrument_token": 123456,
            "timestamp": now,
            "open": 1500.50,
            "high": 1515.00,
            "low": 1495.20,
            "volume": 25000
        }
        with self.assertRaises(WriteError):
            candles_col.insert_one(invalid_doc_1)

        # Scenario 2: wrong type for volume (float/double instead of int)
        invalid_doc_2 = {
            "instrument_token": 123456,
            "timestamp": now,
            "open": 1500.50,
            "high": 1515.00,
            "low": 1495.20,
            "close": 1510.00,
            "volume": 25000.50
        }
        with self.assertRaises(WriteError):
            candles_col.insert_one(invalid_doc_2)

    def test_candles_unique_compound_index(self):
        """Test that compound index [(instrument_token, timestamp)] enforces uniqueness."""
        candles_col = self.db["candles_10m"]
        now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) # MongoDB date resolution is milliseconds, so strip microseconds to make comparison exact
        
        doc1 = {
            "instrument_token": 99999,
            "timestamp": now,
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 101.0,
            "volume": 1000
        }
        doc2 = {
            "instrument_token": 99999,
            "timestamp": now,
            "open": 102.0,
            "high": 107.0,
            "low": 97.0,
            "close": 103.0,
            "volume": 2000
        }
        
        candles_col.insert_one(doc1)
        with self.assertRaises(DuplicateKeyError):
            candles_col.insert_one(doc2)

    def test_candles_retrieval_ordering(self):
        """Test that we can retrieve candles ordered by timestamp descending efficiently."""
        candles_col = self.db["candles_10m"]
        token = 88888
        base_time = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        
        # Insert 3 candles with different timestamps
        candles = []
        for i in range(3):
            candles.append({
                "instrument_token": token,
                "timestamp": base_time + timedelta(minutes=10 * i),
                "open": 100.0 + i,
                "high": 105.0 + i,
                "low": 95.0 + i,
                "close": 101.0 + i,
                "volume": 1000 * (i + 1)
            })
        
        candles_col.insert_many(candles)
        
        # Query using the retrieval index ordering: timestamp descending
        results = list(candles_col.find({"instrument_token": token}).sort("timestamp", pymongo.DESCENDING))
        
        self.assertEqual(len(results), 3)
        # The first item should be the latest timestamp (i=2)
        self.assertEqual(results[0]["timestamp"], base_time + timedelta(minutes=20))
        self.assertEqual(results[0]["close"], 103.0)
        
        # The last item should be the earliest timestamp (i=0)
        self.assertEqual(results[2]["timestamp"], base_time)
        self.assertEqual(results[2]["close"], 101.0)

if __name__ == "__main__":
    unittest.main()
