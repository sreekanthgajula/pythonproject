import sys
import time
import logging
import argparse
import config
from db_setup import setup_database
from data_manager import DataManager
from kite_client import KiteEngine

# Configure application-wide logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("main")

def main():
    parser = argparse.ArgumentParser(description="Zerodha Kite Algorithmic Trading Bot Core")
    parser.add_argument("--mock", action="store_true", help="Force mock mode (live simulation and mock REST)")
    parser.add_argument("--token", type=int, default=config.DEFAULT_INSTRUMENT_TOKEN, help="Zerodha instrument token to track")
    args = parser.parse_args()

    logger.info("=== Starting Zerodha Kite Algorithmic Trading Application ===")

    # Step 1: Ensure database schemas and indexes are established dynamically on startup
    try:
        logger.info("Verifying/Initializing database schema and indexes...")
        setup_database(uri=config.MONGODB_URI, db_name=config.DATABASE_NAME)
    except Exception as e:
        logger.critical(f"Failed to initialize database structures: {e}")
        sys.exit(1)

    # Step 2: Initialize core data manager and Kite execution engine
    data_manager = None
    engine = None
    try:
        data_manager = DataManager(uri=config.MONGODB_URI, db_name=config.DATABASE_NAME)
        engine = KiteEngine(data_manager=data_manager, mock_mode=args.mock)
        
        # Step 3: Run Phase 1 Bootstrap (REST fetch gaps & warm up indicators)
        logger.info("Phase 1: Startup bootstrap and indicator warm-up...")
        engine.bootstrap(instrument_token=args.token)
        
        # Register a callback to display updates on closed candles
        def on_candle_closed_callback(candle_doc, rolling_df):
            if not rolling_df.empty:
                last_row = rolling_df.iloc[-1]
                logger.info(
                    f"\n"
                    f"==================================================\n"
                    f"   [CANDLE CLOSED ALERT] Token: {last_row['instrument_token']}\n"
                    f"   Timestamp: {last_row['timestamp']}\n"
                    f"   OHLCV: O={last_row['open']:.2f} | H={last_row['high']:.2f} | L={last_row['low']:.2f} | C={last_row['close']:.2f} | V={last_row['volume']}\n"
                    f"   Indicators: TSI={last_row.get('tsi', float('nan')):.4f} | OBV={last_row.get('obv', 0):,}\n"
                    f"=================================================="
                )
        
        engine.on_candle_closed = on_candle_closed_callback

        # Step 4: Run Phase 2 Live WebSocket Aggregator
        logger.info("Phase 2: Connecting WebSocket stream & starting candle aggregator...")
        engine.start_websocket(instrument_token=args.token)

        # Keep main thread alive and await terminal signal
        logger.info("System is online and running. Press Ctrl+C to terminate.")
        while True:
            time.sleep(1.0)
            
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Initiating graceful shutdown...")
    except Exception as e:
        logger.exception(f"Unhandled error in execution thread: {e}")
    finally:
        # Graceful cleanup of background WebSocket connections and DB links
        if engine:
            engine.stop_websocket()
        if data_manager:
            data_manager.close()
        logger.info("Shutdown complete. Application terminated.")

if __name__ == "__main__":
    main()
