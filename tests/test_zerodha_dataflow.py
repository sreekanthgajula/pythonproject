import os
import unittest
from unittest.mock import patch, MagicMock
import pandas as pd

from tradingagents.dataflows.zerodha import (
    get_instrument_token,
    get_zerodha_credentials,
    get_access_token,
    get_zerodha_stock_df,
    get_stock_data,
    ZerodhaNotConfiguredError,
)
from tradingagents.dataflows.symbol_utils import NoMarketDataError


class TestZerodhaDataflow(unittest.TestCase):
    def setUp(self):
        # Clear env variables that might affect tests
        self.env_patches = {
            "ZERODHA_API_KEY": "y75il3qx4rl245mb",
            "ZERODHA_API_SECRET": "7rf96lmz89d9e2bdp2n1vo0aj3mlf4yj",
            "ZERODHA_API_URL": "https://api.kite.trade",
            "ZERODHA_ACCESS_TOKEN": None,
            "ZERODHA_REQUEST_TOKEN": None,
        }
        self.patchers = []
        for key, val in self.env_patches.items():
            p = patch.dict(os.environ, {key: val} if val is not None else {})
            p.start()
            self.patchers.append(p)

    def tearDown(self):
        for p in self.patchers:
            p.stop()

    @patch("tradingagents.dataflows.zerodha._get_instruments_df")
    def test_get_instrument_token_ns(self, mock_get_instruments):
        # Mock instruments list
        mock_data = pd.DataFrame([
            {"instrument_token": 12345, "tradingsymbol": "RELIANCE", "exchange": "NSE"},
            {"instrument_token": 67890, "tradingsymbol": "RELIANCE", "exchange": "BSE"},
            {"instrument_token": 11111, "tradingsymbol": "INFY", "exchange": "NSE"}
        ])
        mock_get_instruments.return_value = mock_data

        # Test resolving INFY.NS
        token = get_instrument_token("INFY.NS")
        self.assertEqual(token, 11111)

        # Test resolving RELIANCE.NS vs RELIANCE.BO
        token_ns = get_instrument_token("RELIANCE.NS")
        self.assertEqual(token_ns, 12345)
        
        token_bo = get_instrument_token("RELIANCE.BO")
        self.assertEqual(token_bo, 67890)

    @patch("tradingagents.dataflows.zerodha._get_instruments_df")
    def test_get_instrument_token_not_found(self, mock_get_instruments):
        mock_data = pd.DataFrame([
            {"instrument_token": 12345, "tradingsymbol": "RELIANCE", "exchange": "NSE"}
        ])
        mock_get_instruments.return_value = mock_data

        with self.assertRaises(NoMarketDataError):
            get_instrument_token("INVALID")

    def test_get_zerodha_credentials(self):
        creds = get_zerodha_credentials()
        self.assertEqual(creds["api_key"], "y75il3qx4rl245mb")
        self.assertEqual(creds["api_secret"], "7rf96lmz89d9e2bdp2n1vo0aj3mlf4yj")
        self.assertEqual(creds["api_url"], "https://api.kite.trade")

    @patch("tradingagents.dataflows.zerodha.is_token_valid")
    @patch("requests.post")
    @patch("tradingagents.dataflows.zerodha._update_env_file")
    def test_get_access_token_via_request_token(self, mock_update_env, mock_post, mock_is_token_valid):
        mock_is_token_valid.return_value = True
        # Setup env to have request_token but no access_token
        with patch.dict(os.environ, {"ZERODHA_REQUEST_TOKEN": "some_req_token", "ZERODHA_ACCESS_TOKEN": ""}):
            # Mock success response from Zerodha session token endpoint
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": "success",
                "data": {
                    "access_token": "obtained_access_token_123"
                }
            }
            mock_post.return_value = mock_response

            token = get_access_token()
            self.assertEqual(token, "obtained_access_token_123")
            mock_update_env.assert_called_with("ZERODHA_ACCESS_TOKEN", "obtained_access_token_123")

    def test_get_access_token_missing_raises_error(self):
        # Setup env to have neither token
        with patch.dict(os.environ, {"ZERODHA_REQUEST_TOKEN": "", "ZERODHA_ACCESS_TOKEN": ""}):
            with self.assertRaises(ZerodhaNotConfiguredError) as ctx:
                get_access_token()
            
            # Verify the exception message includes instructions
            self.assertIn("Zerodha access token is missing", str(ctx.exception))
            self.assertIn("https://kite.zerodha.com/connect/login", str(ctx.exception))

    @patch("requests.get")
    @patch("tradingagents.dataflows.zerodha.get_access_token")
    @patch("tradingagents.dataflows.zerodha.get_instrument_token")
    def test_get_zerodha_stock_df(self, mock_get_token, mock_get_access_token, mock_get):
        mock_get_token.return_value = 12345
        mock_get_access_token.return_value = "valid_access_token"
        
        # Mock Zerodha candle data response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "candles": [
                    ["2026-06-01T00:00:00+0530", 100.5, 105.0, 99.0, 102.5, 5000, 0],
                    ["2026-06-02T00:00:00+0530", 102.5, 103.0, 101.0, 101.5, 3000, 0]
                ]
            }
        }
        mock_get.return_value = mock_response

        df = get_zerodha_stock_df("RELIANCE.NS", "2026-06-01", "2026-06-02")
        
        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(len(df), 2)
        self.assertEqual(list(df.columns), ["Date", "Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(df.iloc[0]["Date"], "2026-06-01")
        self.assertEqual(df.iloc[0]["Close"], 102.5)

    @patch("tradingagents.dataflows.zerodha.get_zerodha_stock_df")
    def test_get_stock_data_csv(self, mock_get_df):
        mock_df = pd.DataFrame([
            {"Date": "2026-06-01", "Open": 100.511, "High": 105.011, "Low": 99.011, "Close": 102.511, "Volume": 5000}
        ])
        mock_get_df.return_value = mock_df

        csv_str = get_stock_data("RELIANCE.NS", "2026-06-01", "2026-06-01")
        
        self.assertIn("# Stock data for RELIANCE.NS", csv_str)
        self.assertIn("# Total records: 1", csv_str)
        self.assertIn("102.51", csv_str)  # Verify rounding
