import unittest
import pymongo
from data_manager import DataManager
from db_setup import setup_database

class TestRatingTables(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use local MongoDB test database
        cls.test_db_name = "trading_data_test_ratings"
        try:
            cls.client = pymongo.MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=2000)
            cls.client.admin.command("ping")
            setup_database(db_name=cls.test_db_name)
            cls.db_available = True
        except Exception:
            cls.db_available = False

    @classmethod
    def tearDownClass(cls):
        if cls.db_available:
            cls.client.drop_database(cls.test_db_name)
            cls.client.close()

    def setUp(self):
        if not self.db_available:
            self.skipTest("Local MongoDB instance not accessible on port 27017")
        self.dm = DataManager(db_name=self.test_db_name)

    def tearDown(self):
        if self.db_available:
            self.dm.close()

    def test_save_and_get_monthly_rating(self):
        success = self.dm.save_stock_rating(
            table_name="monthly",
            symbol="WELCORP",
            rating=4.8,
            reason="Monthly TSI cross above zero with 15% volume expansion."
        )
        self.assertTrue(success)

        records = self.dm.get_stock_ratings("monthly", symbol="WELCORP")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["symbol"], "WELCORP")
        self.assertEqual(records[0]["rating"], 4.8)
        self.assertIn("Monthly TSI", records[0]["reason"])

    def test_save_and_get_weekly_rating(self):
        success = self.dm.save_stock_rating(
            table_name="weekly",
            symbol="AEROFLEX",
            rating=4.2,
            reason="Weekly breakout with strong OBV accumulation."
        )
        self.assertTrue(success)

        records = self.dm.get_stock_ratings("weekly", symbol="AEROFLEX")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["symbol"], "AEROFLEX")
        self.assertEqual(records[0]["rating"], 4.2)

    def test_save_and_get_daily_rating(self):
        success = self.dm.save_stock_rating(
            table_name="daily",
            symbol="KERNEX",
            rating=3.9,
            reason="Daily price consolidation near 20-period EMA."
        )
        self.assertTrue(success)

        records = self.dm.get_stock_ratings("daily")
        self.assertGreaterEqual(len(records), 1)
        symbols = [r["symbol"] for r in records]
        self.assertIn("KERNEX", symbols)

    def test_invalid_table_name_raises_error(self):
        with self.assertRaises(ValueError):
            self.dm.save_stock_rating("hourly", "WELCORP", 4.0, "Test reason")

if __name__ == "__main__":
    unittest.main()
