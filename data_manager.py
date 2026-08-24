import logging
from datetime import datetime, timezone, timedelta
import pandas as pd
import pymongo
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
import config

logger = logging.getLogger(__name__)

class DataManager:
    def __init__(self, uri: str = None, db_name: str = None):
        """
        Initialize the DataManager to handle database access and memory management.
        
        Args:
            uri (str, optional): Connection URI. Defaults to config.MONGODB_URI.
            db_name (str, optional): Target database name. Defaults to config.DATABASE_NAME.
        """
        self.uri = uri or config.MONGODB_URI
        self.db_name = db_name or config.DATABASE_NAME
        self.client = None
        self.db = None
        self.connect()

    def connect(self):
        """Establish connection to MongoDB and ping to verify."""
        try:
            self.client = MongoClient(self.uri, serverSelectionTimeoutMS=3000)
            # The ping command checks connection readiness
            self.client.admin.command("ping")
            self.db = self.client[self.db_name]
            logger.info(f"DataManager connected to MongoDB at {self.uri}, Database: '{self.db_name}'")
        except Exception as e:
            logger.error(f"DataManager failed to connect to MongoDB: {e}")
            raise

    def close(self):
        """Close connection."""
        if self.client:
            self.client.close()
            logger.info("MongoDB client connection closed.")

    def bootstrap_data(self, instrument_token: int, required_count: int = None) -> tuple[pd.DataFrame, datetime | None, datetime | None]:
        """
        Queries MongoDB for the latest candles of the given instrument.
        Checks for data adequacy and staleness to determine if historical data needs to be fetched.
        
        Args:
            instrument_token (int): Token identifying the target stock.
            required_count (int, optional): Number of historical candles required. Defaults to config.CANDLE_COUNT.
            
        Returns:
            tuple:
                - pd.DataFrame: DataFrame containing existing candles sorted ascending.
                - datetime | None: Start datetime to fetch from Zerodha API, or None if no fetch is needed.
                - datetime | None: End datetime to fetch to, or None if no fetch is needed.
        """
        if required_count is None:
            required_count = config.CANDLE_COUNT

        candles_col = self.db["candles_10m"]
        
        # Query candles for instrument, sorted by timestamp descending
        cursor = candles_col.find({"instrument_token": instrument_token}).sort("timestamp", pymongo.DESCENDING).limit(required_count)
        db_candles = list(cursor)
        
        # Reverse to chronological order (ascending)
        db_candles.reverse()
        
        # Build DataFrame
        if db_candles:
            df = pd.DataFrame(db_candles)
            if "_id" in df.columns:
                df = df.drop(columns=["_id"])
        else:
            df = pd.DataFrame(columns=["instrument_token", "timestamp", "open", "high", "low", "close", "volume"])
            
        # Ensure timestamp is datetime type
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        
        # Determine if we need to fetch historical data
        if len(df) < required_count:
            # Case A: Not enough data in database. Fetch a broad window (e.g. last 7 days) to bootstrap.
            fetch_from = utc_now - timedelta(days=7)
            fetch_to = utc_now
            logger.info(f"Bootstrap: insufficient DB records ({len(df)} < {required_count}). Requesting historical data from {fetch_from} to {fetch_to}.")
        else:
            # Case B: Sufficient records. Check if the latest record is stale (older than 10 minutes)
            latest_ts = df["timestamp"].max()
            if hasattr(latest_ts, "to_pydatetime"):
                latest_ts = latest_ts.to_pydatetime()
            elif isinstance(latest_ts, str):
                latest_ts = datetime.fromisoformat(latest_ts)
            
            # Use 10 minutes threshold for staleness check
            if utc_now - latest_ts > timedelta(minutes=10):
                # Data is stale (e.g. system was offline). Fetch from latest DB timestamp to now.
                fetch_from = latest_ts
                fetch_to = utc_now
                logger.info(f"Bootstrap: DB is stale. Latest timestamp: {latest_ts}. Fetching gap to {fetch_to}.")
            else:
                # Up to date
                fetch_from = None
                fetch_to = None
                logger.info(f"Bootstrap: DB is up-to-date. Latest timestamp: {latest_ts}. No historical fetch needed.")
                
        return df, fetch_from, fetch_to

    def update_memory(self, df: pd.DataFrame, new_candle_dict: dict, max_len: int = None) -> pd.DataFrame:
        """
        Appends a newly closed candle to the rolling memory DataFrame and maintains maximum length.
        
        Args:
            df (pd.DataFrame): Current rolling DataFrame.
            new_candle_dict (dict): Dictionary with keys: instrument_token, timestamp, open, high, low, close, volume.
            max_len (int, optional): Max length of the rolling DataFrame. Defaults to config.ROLLING_WINDOW_MAX_LEN.
            
        Returns:
            pd.DataFrame: Updated rolling DataFrame.
        """
        if max_len is None:
            max_len = config.ROLLING_WINDOW_MAX_LEN

        # Normalize the incoming timestamp to timezone-naive UTC if it has tz info
        ts = new_candle_dict.get("timestamp")
        if isinstance(ts, datetime) and ts.tzinfo is not None:
            new_candle_dict["timestamp"] = ts.astimezone(timezone.utc).replace(tzinfo=None)

        new_row = pd.DataFrame([new_candle_dict])
        
        if df.empty:
            updated_df = new_row
        else:
            updated_df = pd.concat([df, new_row], ignore_index=True)
            
        # Ensure timestamp column is datetime object
        updated_df["timestamp"] = pd.to_datetime(updated_df["timestamp"])
        
        # De-duplicate timestamps (keeping the latest occurrence) and sort
        updated_df = updated_df.drop_duplicates(subset=["timestamp"], keep="last")
        updated_df = updated_df.sort_values(by="timestamp", ascending=True).reset_index(drop=True)
        
        # Enforce rolling window length
        if len(updated_df) > max_len:
            updated_df = updated_df.iloc[-max_len:].reset_index(drop=True)
            
        return updated_df

    def save_closed_candle(self, candle_doc: dict) -> bool:
        """
        Saves a completed 10-minute candle document to MongoDB candles_10m collection.
        Handles DuplicateKeyError gracefully in case of overlaps during recover/bootstrap.
        
        Args:
            candle_doc (dict): Document to be inserted.
            
        Returns:
            bool: True if inserted successfully, False if duplicate or failed.
        """
        # Ensure the timestamp is timezone-naive UTC
        ts = candle_doc.get("timestamp")
        if isinstance(ts, datetime) and ts.tzinfo is not None:
            candle_doc["timestamp"] = ts.astimezone(timezone.utc).replace(tzinfo=None)

        candles_col = self.db["candles_10m"]
        try:
            candles_col.insert_one(candle_doc)
            logger.info(f"Saved completed candle to DB: Token={candle_doc['instrument_token']}, Time={candle_doc['timestamp']}, C={candle_doc['close']}")
            return True
        except DuplicateKeyError:
            logger.warning(
                f"Duplicate candle detected for token {candle_doc['instrument_token']} "
                f"at timestamp {candle_doc['timestamp']}. Skipped insertion."
            )
            return False
        except Exception as e:
            logger.error(f"Error saving candle to MongoDB: {e}")
            return False
