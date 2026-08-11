"""LangGraph checkpoint support for resumable analysis runs.

Supports SQLite files (default) or MongoDB (when TRADINGAGENTS_MONGODB_URI is set).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver

from tradingagents.dataflows.utils import safe_ticker_component


def _db_path(data_dir: str | Path, ticker: str) -> Path:
    """Return the SQLite checkpoint DB path for a ticker."""
    # Reject ticker values that would escape the checkpoints directory.
    safe = safe_ticker_component(ticker).upper()
    p = Path(data_dir) / "checkpoints"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{safe}.db"


def thread_id(ticker: str, date: str) -> str:
    """Deterministic thread ID for a ticker+date pair."""
    return hashlib.sha256(f"{ticker.upper()}:{date}".encode()).hexdigest()[:16]


@contextmanager
def get_checkpointer(
    data_dir: str | Path,
    ticker: str,
    mongodb_uri: str | None = None
) -> Generator[BaseCheckpointSaver, None, None]:
    """Context manager yielding a checkpointer (MongoDBSaver or SqliteSaver)."""
    if mongodb_uri is None:
        mongodb_uri = os.environ.get("TRADINGAGENTS_MONGODB_URI") or os.environ.get("MONGODB_URI")
    if mongodb_uri is None:
        try:
            from tradingagents.default_config import DEFAULT_CONFIG
            mongodb_uri = DEFAULT_CONFIG.get("mongodb_uri")
        except ImportError:
            pass

    if mongodb_uri:
        from pymongo import MongoClient
        from langgraph.checkpoint.mongodb import MongoDBSaver
        
        client = MongoClient(mongodb_uri)
        try:
            saver = MongoDBSaver(client=client, db_name="tradingagents")
            yield saver
        finally:
            client.close()
    else:
        db = _db_path(data_dir, ticker)
        conn = sqlite3.connect(str(db), check_same_thread=False)
        try:
            saver = SqliteSaver(conn)
            saver.setup()
            yield saver
        finally:
            conn.close()


def has_checkpoint(
    data_dir: str | Path,
    ticker: str,
    date: str,
    mongodb_uri: str | None = None
) -> bool:
    """Check whether a resumable checkpoint exists for ticker+date."""
    return checkpoint_step(data_dir, ticker, date, mongodb_uri=mongodb_uri) is not None


def checkpoint_step(
    data_dir: str | Path,
    ticker: str,
    date: str,
    mongodb_uri: str | None = None
) -> int | None:
    """Return the step number of the latest checkpoint, or None if none exists."""
    # Resolve mongodb_uri to decide whether we check file existence
    if mongodb_uri is None:
        mongodb_uri = os.environ.get("TRADINGAGENTS_MONGODB_URI") or os.environ.get("MONGODB_URI")
    if mongodb_uri is None:
        try:
            from tradingagents.default_config import DEFAULT_CONFIG
            mongodb_uri = DEFAULT_CONFIG.get("mongodb_uri")
        except ImportError:
            pass

    if not mongodb_uri:
        db = _db_path(data_dir, ticker)
        if not db.exists():
            return None

    tid = thread_id(ticker, date)
    with get_checkpointer(data_dir, ticker, mongodb_uri=mongodb_uri) as saver:
        config = {"configurable": {"thread_id": tid}}
        cp = saver.get_tuple(config)
        if cp is None:
            return None
        return cp.metadata.get("step")


def clear_all_checkpoints(
    data_dir: str | Path,
    mongodb_uri: str | None = None
) -> int:
    """Remove all checkpoints. Returns number of records/files deleted."""
    if mongodb_uri is None:
        mongodb_uri = os.environ.get("TRADINGAGENTS_MONGODB_URI") or os.environ.get("MONGODB_URI")
    if mongodb_uri is None:
        try:
            from tradingagents.default_config import DEFAULT_CONFIG
            mongodb_uri = DEFAULT_CONFIG.get("mongodb_uri")
        except ImportError:
            pass

    if mongodb_uri:
        from pymongo import MongoClient
        client = MongoClient(mongodb_uri)
        try:
            db = client["tradingagents"]
            cp_count = db["checkpoints"].count_documents({})
            writes_count = db["checkpoint_writes"].count_documents({})
            
            db["checkpoints"].delete_many({})
            db["checkpoint_writes"].delete_many({})
            return cp_count + writes_count
        finally:
            client.close()
    else:
        cp_dir = Path(data_dir) / "checkpoints"
        if not cp_dir.exists():
            return 0
        dbs = list(cp_dir.glob("*.db"))
        for db in dbs:
            db.unlink()
        return len(dbs)


def clear_checkpoint(
    data_dir: str | Path,
    ticker: str,
    date: str,
    mongodb_uri: str | None = None
) -> None:
    """Remove checkpoint for a specific ticker+date."""
    if mongodb_uri is None:
        mongodb_uri = os.environ.get("TRADINGAGENTS_MONGODB_URI") or os.environ.get("MONGODB_URI")
    if mongodb_uri is None:
        try:
            from tradingagents.default_config import DEFAULT_CONFIG
            mongodb_uri = DEFAULT_CONFIG.get("mongodb_uri")
        except ImportError:
            pass

    if mongodb_uri:
        from pymongo import MongoClient
        tid = thread_id(ticker, date)
        client = MongoClient(mongodb_uri)
        try:
            db = client["tradingagents"]
            db["checkpoints"].delete_many({"thread_id": tid})
            db["checkpoint_writes"].delete_many({"thread_id": tid})
        finally:
            client.close()
    else:
        db = _db_path(data_dir, ticker)
        if not db.exists():
            return
        tid = thread_id(ticker, date)
        conn = sqlite3.connect(str(db))
        try:
            for table in ("writes", "checkpoints"):
                conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (tid,))
            conn.commit()
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()

