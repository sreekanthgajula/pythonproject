import os
import sys
import logging
import pymongo
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def get_mongodb_uri() -> str:
    """
    Retrieve the MongoDB connection URI.
    Looks for environment variables and project configs, falling back to localhost.
    """
    # 1. Check environment variables
    uri = os.environ.get("TRADINGAGENTS_MONGODB_URI") or os.environ.get("MONGODB_URI")
    
    # 2. Try importing default configuration from tradingagents package
    if not uri:
        try:
            from tradingagents.default_config import DEFAULT_CONFIG
            uri = DEFAULT_CONFIG.get("mongodb_uri")
        except ImportError:
            pass
            
    # 3. Fallback to default local instance
    return uri or "mongodb://localhost:27017/"

def apply_validation_schemas(db) -> None:
    """
    Applies JSON schema validators to the 'instruments' and 'candles_10m' collections.
    If the collections do not exist, they are created with the schemas.
    If they already exist, they are modified to enforce the schemas.
    Failure to apply schemas is logged as a warning, allowing the script to continue.
    """
    # Define validator schema for instruments
    instruments_schema = {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["_id", "trading_symbol", "exchange"],
            "properties": {
                "_id": {
                    "bsonType": ["int", "long"],
                    "description": "must be an integer (Zerodha instrument_token) and is required"
                },
                "trading_symbol": {
                    "bsonType": "string",
                    "description": "must be a string trading symbol (e.g. INFY, SBIN) and is required"
                },
                "exchange": {
                    "bsonType": "string",
                    "description": "must be a string exchange name (e.g. NSE, BSE) and is required"
                }
            }
        }
    }

    # Define validator schema for candles_10m
    candles_schema = {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["instrument_token", "timestamp", "open", "high", "low", "close", "volume"],
            "properties": {
                "instrument_token": {
                    "bsonType": ["int", "long"],
                    "description": "must be an integer referencing the instrument and is required"
                },
                "timestamp": {
                    "bsonType": "date",
                    "description": "must be a datetime object (start of the candle) and is required"
                },
                "open": {
                    "bsonType": "double",
                    "description": "must be a float (double) representing the open price and is required"
                },
                "high": {
                    "bsonType": "double",
                    "description": "must be a float (double) representing the high price and is required"
                },
                "low": {
                    "bsonType": "double",
                    "description": "must be a float (double) representing the low price and is required"
                },
                "close": {
                    "bsonType": "double",
                    "description": "must be a float (double) representing the close price and is required"
                },
                "volume": {
                    "bsonType": ["int", "long"],
                    "description": "must be an integer representing the trading volume and is required"
                }
            }
        }
    }

    existing_collections = db.list_collection_names()

    # Apply instruments validation
    try:
        if "instruments" not in existing_collections:
            db.create_collection("instruments", validator=instruments_schema)
            logger.info("Created 'instruments' collection with schema validation.")
        else:
            db.command("collMod", "instruments", validator=instruments_schema)
            logger.info("Applied schema validation to existing 'instruments' collection.")
    except Exception as e:
        logger.warning(f"Could not apply schema validation to 'instruments' collection: {e}")

    # Apply candles_10m validation
    try:
        if "candles_10m" not in existing_collections:
            db.create_collection("candles_10m", validator=candles_schema)
            logger.info("Created 'candles_10m' collection with schema validation.")
        else:
            db.command("collMod", "candles_10m", validator=candles_schema)
            logger.info("Applied schema validation to existing 'candles_10m' collection.")
    except Exception as e:
        logger.warning(f"Could not apply schema validation to 'candles_10m' collection: {e}")


def setup_database(uri: str = None, db_name: str = "trading_data") -> MongoClient:
    """
    Connects to MongoDB, checks connection, and sets up collections and indexes.
    
    Args:
        uri (str, optional): Connection URI. Defaults to get_mongodb_uri().
        db_name (str, optional): Target database name. Defaults to "trading_data".
        
    Returns:
        MongoClient: Configured and connected client instance.
    """
    if not uri:
        uri = get_mongodb_uri()

    logger.info(f"Initiating MongoDB setup on database '{db_name}' using URI: {uri}")

    # Initialize client with a fast-fail server selection timeout of 3 seconds
    client = MongoClient(uri, serverSelectionTimeoutMS=3000)

    # 1. Connection check
    try:
        # The 'ping' command is simple and fast, checking server liveliness
        client.admin.command("ping")
        logger.info("Connection check passed. MongoDB is active.")
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(
            "Connection failed. Please ensure MongoDB is running locally on port 27017 "
            "or verify your TRADINGAGENTS_MONGODB_URI/MONGODB_URI config."
        )
        logger.error(f"Error details: {e}")
        sys.exit(1)

    # 2. Access database
    db = client[db_name]
    logger.info(f"Accessing database: '{db_name}'")

    # 3. Setup collections with validation schemas
    apply_validation_schemas(db)

    # 4. Create indexes on candles_10m (idempotent operations)
    candles_col = db["candles_10m"]
    
    # UNIQUE index on [instrument_token, timestamp] (ascending/ascending)
    logger.info(f"Creating/verifying unique compound index on '{db_name}.candles_10m' [instrument_token (ASC), timestamp (ASC)]...")
    unique_idx = candles_col.create_index(
        [("instrument_token", pymongo.ASCENDING), ("timestamp", pymongo.ASCENDING)],
        unique=True
    )
    logger.info(f"Unique index active: '{unique_idx}'")

    # Retrieval index on [instrument_token, timestamp] (ascending/descending) for fast historical query
    logger.info(f"Creating/verifying retrieval index on '{db_name}.candles_10m' [instrument_token (ASC), timestamp (DESC)]...")
    retrieval_idx = candles_col.create_index(
        [("instrument_token", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)]
    )
    logger.info(f"Retrieval index active: '{retrieval_idx}'")

    logger.info(f"Database setup for '{db_name}' completed successfully.")
    return client


if __name__ == "__main__":
    setup_database()
