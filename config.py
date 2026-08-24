import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from the root .env file
env_path = Path(__file__).parent.resolve() / ".env"
load_dotenv(dotenv_path=env_path)

# Zerodha API credentials
ZERODHA_API_KEY = os.getenv("ZERODHA_API_KEY")
ZERODHA_API_SECRET = os.getenv("ZERODHA_API_SECRET")
ZERODHA_ACCESS_TOKEN = os.getenv("ZERODHA_ACCESS_TOKEN")
ZERODHA_API_URL = os.getenv("ZERODHA_API_URL", "https://api.kite.trade")

# MongoDB connection URI (falls back to localhost)
MONGODB_URI = os.getenv("TRADINGAGENTS_MONGODB_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/"
DATABASE_NAME = "trading_data"

# Trading bot and indicator configuration
TIMEFRAME = "10minute"
CANDLE_COUNT = 150
ROLLING_WINDOW_MAX_LEN = 200

# Default instrument configuration (e.g. INFY token is typically around 1000-500000 range in NSE)
# 408065 is INFOSYS (INFY) on NSE typically, but can be overridden as needed
DEFAULT_INSTRUMENT_TOKEN = 408065  
