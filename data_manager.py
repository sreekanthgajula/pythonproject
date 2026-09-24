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

    def save_stock_rating(self, table_name: str, symbol: str, rating: float | str, reason: str) -> bool:
        """
        Saves or updates a stock potential rating and reason in the specified timeframe table (monthly, weekly, daily).
        
        Args:
            table_name (str): Target table name ('monthly', 'weekly', or 'daily').
            symbol (str): Stock symbol (e.g. 'WELCORP').
            rating (float | str): Rating indicating future potential.
            reason (str): Analysis rationale or explanation.
            
        Returns:
            bool: True if saved successfully, False otherwise.
        """
        valid_tables = {"monthly", "weekly", "daily", "manual", "darvas"}
        clean_table = table_name.strip().lower()
        if clean_table not in valid_tables:
            raise ValueError(f"Invalid table name '{table_name}'. Must be one of {valid_tables}")

        clean_symbol = symbol.strip().upper()
        doc = {
            "symbol": clean_symbol,
            "rating": rating,
            "reason": reason,
            "updated_at": datetime.now(timezone.utc).replace(tzinfo=None)
        }

        col = self.db[clean_table]
        try:
            # Upsert record based on unique symbol
            col.update_one({"symbol": clean_symbol}, {"$set": doc}, upsert=True)
            logger.info(f"Saved rating to '{clean_table}': Symbol={clean_symbol}, Rating={rating}")
            return True
        except Exception as e:
            logger.error(f"Error saving stock rating to '{clean_table}': {e}")
            return False

    def get_stock_ratings(self, table_name: str, symbol: str = None) -> list[dict]:
        """
        Queries stock ratings and reasons from the specified timeframe table (monthly, weekly, daily).
        
        Args:
            table_name (str): Target table name ('monthly', 'weekly', or 'daily').
            symbol (str, optional): Specific stock symbol to filter by.
            
        Returns:
            list[dict]: List of rating records.
        """
        valid_tables = {"monthly", "weekly", "daily", "manual", "darvas"}
        clean_table = table_name.strip().lower()
        if clean_table not in valid_tables:
            raise ValueError(f"Invalid table name '{table_name}'. Must be one of {valid_tables}")

        col = self.db[clean_table]
        query = {}
        if symbol:
            query["symbol"] = symbol.strip().upper()

        records = list(col.find(query, {"_id": 0}))
        return records

    def delete_stock_rating(self, table_name: str, symbol: str) -> bool:
        """Deletes a single stock document from the specified timeframe table and cancels any associated Zerodha GTT alert."""
        valid_tables = {"monthly", "weekly", "daily", "manual", "darvas"}
        clean_table = table_name.strip().lower()
        if clean_table not in valid_tables:
            raise ValueError(f"Invalid table name '{table_name}'. Must be one of {valid_tables}")

        clean_symbol = symbol.strip().upper()
        col = self.db[clean_table]
        try:
            # Check for existing document to see if Zerodha GTT ID is attached
            doc = col.find_one({"$or": [{"symbol": clean_symbol}, {"symbol": f"{clean_symbol}.NS"}]})
            if doc and doc.get("gtt_id"):
                gtt_id = doc.get("gtt_id")
                try:
                    from scripts.zerodha_alert_manager import get_kite_client
                    kite = get_kite_client()
                    if kite:
                        kite.delete_gtt(int(gtt_id))
                        logger.info(f"[ZERODHA GTT CANCEL] Successfully cancelled Zerodha GTT #{gtt_id} for {clean_symbol}")
                except Exception as gtt_err:
                    logger.warning(f"Could not cancel Zerodha GTT #{gtt_id} for {clean_symbol}: {gtt_err}")

            res = col.delete_one({"$or": [{"symbol": clean_symbol}, {"symbol": f"{clean_symbol}.NS"}]})
            logger.info(f"Deleted symbol '{clean_symbol}' from '{clean_table}': Count={res.deleted_count}")
            return res.deleted_count > 0
        except Exception as e:
            logger.error(f"Failed to delete symbol '{clean_symbol}' from '{clean_table}': {e}")
            return False

    def clear_all_stock_ratings(self, table_name: str) -> int:
        """Deletes all stock documents from the specified timeframe table and cancels their active Zerodha GTT alerts."""
        valid_tables = {"monthly", "weekly", "daily", "manual", "darvas"}
        clean_table = table_name.strip().lower()
        if clean_table not in valid_tables:
            raise ValueError(f"Invalid table name '{table_name}'. Must be one of {valid_tables}")

        col = self.db[clean_table]
        try:
            # Cancel active Zerodha GTTs for all documents in this collection
            docs = list(col.find({"gtt_id": {"$exists": True, "$ne": None}}))
            if docs:
                try:
                    from scripts.zerodha_alert_manager import get_kite_client
                    kite = get_kite_client()
                    if kite:
                        for d in docs:
                            gtt_id = d.get("gtt_id")
                            sym = d.get("symbol", "UNKNOWN")
                            if gtt_id:
                                try:
                                    kite.delete_gtt(int(gtt_id))
                                    logger.info(f"[ZERODHA GTT CANCEL] Cancelled Zerodha GTT #{gtt_id} for {sym}")
                                except Exception as ge:
                                    logger.warning(f"Could not cancel Zerodha GTT #{gtt_id} for {sym}: {ge}")
                except Exception as kite_err:
                    logger.warning(f"Failed to initialize Zerodha client for bulk GTT cancellation: {kite_err}")

            res = col.delete_many({})
            logger.info(f"Cleared all records from '{clean_table}': Count={res.deleted_count}")
            return res.deleted_count
        except Exception as e:
            logger.error(f"Failed to clear records from '{clean_table}': {e}")
            return 0

    def delete_batch_stock_ratings(self, table_name: str, symbols: list) -> int:
        """Deletes a list of stock symbols from the specified timeframe table and cancels any active Zerodha GTT alerts for them."""
        valid_tables = {"monthly", "weekly", "daily", "manual", "darvas"}
        clean_table = table_name.strip().lower()
        if clean_table not in valid_tables:
            raise ValueError(f"Invalid table name '{table_name}'. Must be one of {valid_tables}")

        if not symbols:
            return 0

        clean_symbols = [s.strip().upper() for s in symbols if s]
        col = self.db[clean_table]
        deleted_total = 0

        try:
            from scripts.zerodha_alert_manager import get_kite_client
            kite = get_kite_client()
        except Exception:
            kite = None

        for sym in clean_symbols:
            try:
                # Check for existing document to see if Zerodha GTT ID is attached
                doc = col.find_one({"$or": [{"symbol": sym}, {"symbol": f"{sym}.NS"}]})
                if doc and doc.get("gtt_id"):
                    gtt_id = doc.get("gtt_id")
                    if kite and gtt_id:
                        try:
                            kite.delete_gtt(int(gtt_id))
                            logger.info(f"[ZERODHA GTT CANCEL] Cancelled Zerodha GTT #{gtt_id} for batch symbol {sym}")
                        except Exception as gtt_err:
                            logger.warning(f"Could not cancel Zerodha GTT #{gtt_id} for {sym}: {gtt_err}")

                res = col.delete_one({"$or": [{"symbol": sym}, {"symbol": f"{sym}.NS"}]})
                deleted_total += res.deleted_count
            except Exception as e:
                logger.error(f"Failed to delete symbol '{sym}' from '{clean_table}': {e}")

        logger.info(f"Batch deleted {deleted_total} symbols from '{clean_table}'")
        return deleted_total



    def add_manual_stock(self, symbol: str, reason: str = "Manually added high-potency candidate") -> dict:
        """
        Adds a stock symbol manually to the 'manual' collection.
        Checks for duplicates (blocks addition if symbol already exists).
        Automatically places a 1% Zerodha GTT breakout alert.
        """
        clean_sym = symbol.strip().upper().replace(".NS", "").replace("-EQ", "")
        if not clean_sym:
            raise ValueError("Stock symbol cannot be empty.")

        col = self.db["manual"]
        # Duplicate check across all tables
        for tbl in ["monthly", "weekly", "daily", "manual"]:
            existing = self.db[tbl].find_one({"$or": [{"symbol": clean_sym}, {"symbol": f"{clean_sym}.NS"}]})
            if existing:
                raise ValueError(f"Stock '{clean_sym}' already exists in '{tbl}' table! Duplicate additions are not allowed.")

        # Place 1% Zerodha GTT breakout alert & upsert document into 'manual' collection
        from scripts.zerodha_alert_manager import set_zerodha_1pct_breakout_alert
        gtt_res = set_zerodha_1pct_breakout_alert(
            symbol=clean_sym,
            timeframe="manual"
        )

        # Update record with manual metadata & reason
        col.update_one(
            {"symbol": clean_sym},
            {"$set": {
                "symbol": clean_sym,
                "rating": 10.0,
                "reason": reason,
                "source": "manual",
                "updated_at": datetime.now(timezone.utc).replace(tzinfo=None)
            }},
            upsert=True
        )

        doc = col.find_one({"symbol": clean_sym}, {"_id": 0})
        logger.info(f"[MANUAL STOCK ADDED] Symbol='{clean_sym}', Trigger={doc.get('alert_trigger_price')}, GTT_ID={doc.get('gtt_id')}")

        return {
            "status": "success",
            "is_duplicate": False,
            "message": f"Successfully added '{clean_sym}' to Manual watchlist & set 1% Zerodha GTT alert!",
            "symbol": clean_sym,
            "stock": doc,
            "gtt_details": gtt_res
        }

    def reset_stock_1pct_gtt(self, symbol: str, timeframe: str = None) -> dict:
        """
        Fetches current live trading price for symbol, cancels any previous Zerodha GTT,
        and sets a new 1% Zerodha GTT breakout alert from the current trading price.
        Applicable to monthly, weekly, daily, and manual stocks.
        """
        clean_sym = symbol.strip().upper().replace(".NS", "").replace("-EQ", "")
        if not clean_sym:
            raise ValueError("Symbol cannot be empty.")

        target_tf = timeframe.lower() if timeframe else None
        doc = None
        if not target_tf:
            for tf in ["monthly", "weekly", "daily", "manual"]:
                doc = self.db[tf].find_one({"symbol": clean_sym})
                if doc:
                    target_tf = tf
                    break
        else:
            doc = self.db[target_tf].find_one({"symbol": clean_sym})

        if not target_tf:
            target_tf = "monthly"

        # Fetch current live trading price (LTP)
        current_ltp = 0.0
        try:
            from scripts.zerodha_alert_manager import get_kite_client
            kite = get_kite_client()
            if kite:
                quotes = kite.quote([f"NSE:{clean_sym}", f"BSE:{clean_sym}"])
                for k, q in quotes.items():
                    if q.get("last_price", 0) > 0:
                        current_ltp = float(q["last_price"])
                        break
        except Exception as q_err:
            logger.warning(f"Could not fetch live LTP from Zerodha for {clean_sym}: {q_err}")

        # Fallback if Zerodha live quote unavailable
        if current_ltp <= 0 and doc:
            current_ltp = float(doc.get("recent_high") or 0.0)
            if current_ltp <= 0 and doc.get("alert_trigger_price"):
                current_ltp = float(doc["alert_trigger_price"]) / 1.01

        if current_ltp <= 0:
            import yfinance as yf
            try:
                t = yf.Ticker(f"{clean_sym}.NS")
                fi = t.fast_info
                current_ltp = float(fi.get("lastPrice") or 0.0)
            except Exception:
                pass

        if current_ltp <= 0:
            raise ValueError(f"Could not determine current trading price for '{clean_sym}'.")

        # Place new 1% Zerodha GTT alert from current_ltp (set_zerodha_1pct_breakout_alert automatically cancels previous GTT)
        from scripts.zerodha_alert_manager import set_zerodha_1pct_breakout_alert
        res = set_zerodha_1pct_breakout_alert(
            symbol=clean_sym,
            timeframe=target_tf,
            override_recent_high=current_ltp
        )

        return {
            "status": "success",
            "message": f"Successfully reset 1% GTT alert for '{clean_sym}' from current trading price ₹{current_ltp:.2f}!",
            "symbol": clean_sym,
            "timeframe": target_tf,
            "current_trading_price": current_ltp,
            "recent_high": res.get("recent_high", current_ltp),
            "alert_trigger_price": res.get("alert_trigger_price"),
            "gtt_id": res.get("gtt_id"),
            "gtt_status": res.get("status") or res.get("gtt_status")
        }

    def reset_all_timeframe_gtts(self, timeframe: str) -> dict:
        """
        Resets 1% GTT alerts for ALL stocks in a given timeframe (monthly, weekly, daily, manual)
        from their current trading prices, cancelling previous GTTs.
        """
        tf_clean = timeframe.strip().lower()
        if tf_clean not in ["monthly", "weekly", "daily", "manual"]:
            raise ValueError(f"Invalid timeframe '{timeframe}'.")

        col = self.db[tf_clean]
        docs = list(col.find({}))
        if not docs:
            return {"status": "success", "reset_count": 0, "message": f"No stocks found in {tf_clean} table."}

        results = []
        for doc in docs:
            sym = doc.get("symbol")
            if not sym:
                continue
            try:
                r = self.reset_stock_1pct_gtt(sym, timeframe=tf_clean)
                results.append(r)
            except Exception as err:
                logger.error(f"Error resetting GTT for {sym}: {err}")

        return {
            "status": "success",
            "timeframe": tf_clean,
            "reset_count": len(results),
            "details": results,
            "message": f"Successfully set new 1% GTT alerts for {len(results)} stocks in {tf_clean} table from current trading prices (previous GTTs removed)!"
        }

    def sync_and_clean_zerodha_gtts(self) -> dict:
        """
        Deletes ALL existing GTT orders on Zerodha and creates new +1% GTT breakout orders
        based on live current trading prices for all tracked stocks in monthly, weekly, daily,
        and manual watchlists.
        """
        try:
            from scripts.zerodha_alert_manager import get_kite_client
            kite = get_kite_client()
        except Exception as ke:
            raise ValueError(f"Zerodha Kite client unavailable: {ke}")

        if not kite:
            raise ValueError("Zerodha Kite client is not connected.")

        # 1. Fetch all existing GTT orders on Zerodha
        gtts = kite.get_gtts()
        initial_gtt_count = len(gtts)

        # 2. Delete ALL existing active GTT orders on Zerodha
        deleted_gtt_count = 0
        deleted_details = []
        for g in gtts:
            g_id = g.get("id")
            g_status = str(g.get("status") or "").lower()
            if g_id and g_status in ["active", ""]:
                try:
                    kite.delete_gtt(int(g_id))
                    deleted_gtt_count += 1
                    cond = g.get("condition") or {}
                    ts = cond.get("tradingsymbol") or "UNKNOWN"
                    deleted_details.append({"symbol": ts, "gtt_id": g_id})
                    logger.info(f"[SYNC GTTS] Deleted existing GTT #{g_id} for {ts}")
                except Exception as err:
                    logger.warning(f"Error deleting GTT #{g_id}: {err}")

        # 3. Collect all tracked stocks from database
        tracked_stocks = []
        seen_symbols = set()
        for tf in ['monthly', 'weekly', 'daily', 'manual']:
            for doc in self.db[tf].find({}):
                sym = doc.get('symbol', '').strip().upper().replace('.NS', '').replace('-EQ', '')
                if sym and sym not in seen_symbols:
                    seen_symbols.add(sym)
                    tracked_stocks.append((sym, tf))

        if not tracked_stocks:
            return {
                "status": "success",
                "deleted_gtt_count": deleted_gtt_count,
                "created_gtt_count": 0,
                "total_tracked_stocks": 0,
                "message": f"Sync Complete! Deleted {deleted_gtt_count} existing GTTs. No tracked stocks found in database to set new GTTs."
            }

        # 4. Batch fetch current live trading prices (LTP) from Zerodha
        nse_symbols = [f"NSE:{sym}" for sym, _ in tracked_stocks]
        ltp_map = {}
        if kite and nse_symbols:
            try:
                chunk_size = 200
                for i in range(0, len(nse_symbols), chunk_size):
                    chunk = nse_symbols[i:i + chunk_size]
                    quotes = kite.quote(chunk)
                    for key, q_data in quotes.items():
                        s = key.replace("NSE:", "").replace("BSE:", "")
                        lp = float(q_data.get("last_price") or 0.0)
                        if lp > 0:
                            ltp_map[s] = lp
            except Exception as q_err:
                logger.warning(f"[SYNC GTTS] Batch quote fetch notice: {q_err}")

        # 5. Create new +1% GTT breakout alert for each tracked stock from live price
        created_gtt_count = 0
        created_details = []
        failed_stocks = []

        from scripts.zerodha_alert_manager import set_zerodha_1pct_breakout_alert

        for sym, tf in tracked_stocks:
            current_ltp = ltp_map.get(sym, 0.0)
            try:
                if current_ltp > 0:
                    res = set_zerodha_1pct_breakout_alert(
                        symbol=sym,
                        timeframe=tf,
                        override_recent_high=current_ltp
                    )
                else:
                    res = self.reset_stock_1pct_gtt(sym, timeframe=tf)

                if res.get("gtt_id"):
                    created_gtt_count += 1
                    created_details.append({
                        "symbol": sym,
                        "timeframe": tf,
                        "gtt_id": res.get("gtt_id"),
                        "ltp": current_ltp or res.get("current_trading_price"),
                        "alert_trigger_price": res.get("alert_trigger_price")
                    })
                else:
                    created_details.append({
                        "symbol": sym,
                        "timeframe": tf,
                        "status": res.get("status"),
                        "ltp": current_ltp or res.get("current_trading_price")
                    })
            except Exception as err:
                logger.error(f"[SYNC GTTS] Error placing new GTT for {sym}: {err}")
                failed_stocks.append({"symbol": sym, "error": str(err)})

        # 6. Fetch final count of active GTTs on Zerodha
        try:
            final_gtts = kite.get_gtts()
            final_active_count = len([g for g in final_gtts if str(g.get("status") or "").lower() == "active"])
        except Exception:
            final_active_count = created_gtt_count

        msg = (
            f"Sync Complete! Deleted {deleted_gtt_count} existing GTTs and created "
            f"{created_gtt_count} new 1% GTT breakout alerts based on current trading prices "
            f"(+1% above LTP) for {len(tracked_stocks)} tracked stocks. "
            f"Total Active GTTs on Zerodha: {final_active_count}."
        )

        return {
            "status": "success",
            "initial_gtt_count": initial_gtt_count,
            "deleted_gtt_count": deleted_gtt_count,
            "created_gtt_count": created_gtt_count,
            "total_tracked_stocks": len(tracked_stocks),
            "final_active_gtt_count": final_active_count,
            "failed_stocks": failed_stocks,
            "created_details": created_details,
            "message": msg
        }


def is_telegram_darvas_breakout_allowed(symbol: str, price: float = None) -> tuple[bool, str]:
    """
    STRICT TELEGRAM ALERT FILTER:
    Telegram notifications across the TradingAgents platform are ONLY sent if:
    1. The stock exists in the 'darvas' MongoDB database table.
    2. The stock hits or exceeds a 1% breakout level above box_top (price >= box_top * 1.01 or price >= alert_trigger_price).
    
    Returns:
        tuple[bool, str]: (is_allowed, reason_message)
    """
    if not symbol:
        return False, "Symbol is empty or invalid."
        
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("-EQ", "")
    
    try:
        dm = DataManager()
        darvas_doc = dm.db["darvas"].find_one({"symbol": clean_sym})
        if not darvas_doc:
            return False, f"Symbol '{clean_sym}' is NOT in the Darvas Box (darvas) database table."
            
        box_top = darvas_doc.get("box_top") or darvas_doc.get("recent_high")
        alert_trigger_price = darvas_doc.get("alert_trigger_price")
        
        if alert_trigger_price is not None and float(alert_trigger_price) > 0:
            trigger_level = float(alert_trigger_price)
        elif box_top is not None and float(box_top) > 0:
            trigger_level = round(float(box_top) * 1.01, 2)
        else:
            trigger_level = None
            
        if price is not None and float(price) > 0 and trigger_level is not None:
            if float(price) < trigger_level:
                return False, f"Symbol '{clean_sym}' price ₹{float(price):,.2f} has NOT reached 1% breakout level ₹{trigger_level:,.2f} (Box Top: ₹{box_top or 0:,.2f})."
                
        return True, f"Symbol '{clean_sym}' qualified for Darvas 1% breakout Telegram alert (Price: ₹{float(price) if price else 0:,.2f} >= Trigger: ₹{trigger_level or 0:,.2f})."
    except Exception as e:
        logger.error(f"Error checking Darvas 1% breakout status for {clean_sym}: {e}")
        return False, f"Error checking Darvas status: {e}"
