"""
===============================================================================
TELEGRAM ALERT CONVICTION THRESHOLD MANAGER
===============================================================================
Allows the user to dynamically adjust the minimum 6-Agent Swarm Debate Rating
required for ANY alert to be dispatched to Telegram.

Features:
- In-memory cached lookup (0.0ms latency, zero performance penalty)
- Persistent storage in MongoDB ('system_settings' collection)
- Safe fallback to TELEGRAM_MIN_DEBATE_RATING in .env or default 7.5/10
- Universal coverage across all 4 alert engines (Derivatives, WebSocket Breakouts,
  Evening BTST, and Morning Shorts).
===============================================================================
"""

import os
import logging
from typing import Dict, Any

logger = logging.getLogger("TelegramSettings")

# In-memory cache for 0.0ms instant lookup across ticks
_cached_threshold: float = None


def get_threshold_label(rating: float) -> str:
    """Human-friendly conviction tier description."""
    if rating >= 9.0:
        return "Ultra-Sniper Only (Top 1%)"
    elif rating >= 8.5:
        return "Sniper Only (High Alpha)"
    elif rating >= 8.0:
        return "High Conviction (Strong Consensus)"
    elif rating >= 7.5:
        return "Approved Setup (Balanced Default)"
    elif rating >= 7.0:
        return "Moderate (Standard Ripe)"
    else:
        return "Permissive (All Setups)"


def get_telegram_threshold() -> float:
    """
    Returns the active user-configured minimum Swarm Debate Rating (1.0 to 10.0).
    Checks in-memory cache first, then MongoDB, then .env, with a safe default of 7.5.
    """
    global _cached_threshold
    if _cached_threshold is not None:
        return _cached_threshold

    # 1. Try reading from MongoDB system_settings
    try:
        from data_manager import DataManager
        dm = DataManager()
        doc = dm.db["system_settings"].find_one({"key": "telegram_min_debate_rating"})
        if doc and "value" in doc:
            val = float(doc["value"])
            if 1.0 <= val <= 10.0:
                _cached_threshold = val
                return _cached_threshold
    except Exception as e:
        logger.debug(f"Could not load telegram_min_debate_rating from MongoDB: {e}")

    # 2. Fallback to .env variable
    env_val = os.getenv("TELEGRAM_MIN_DEBATE_RATING")
    if env_val:
        try:
            val = float(env_val)
            if 1.0 <= val <= 10.0:
                _cached_threshold = val
                return _cached_threshold
        except ValueError:
            pass

    # 3. Default fallback
    _cached_threshold = 7.5
    return _cached_threshold


def set_telegram_threshold(value: float) -> Dict[str, Any]:
    """
    Updates the active Telegram conviction threshold in memory and persists to MongoDB.
    Enforces safe bounding [1.0, 10.0].
    """
    global _cached_threshold
    val = round(max(1.0, min(10.0, float(value))), 1)
    _cached_threshold = val

    # Persist to MongoDB
    try:
        from data_manager import DataManager
        from datetime import datetime, timezone
        dm = DataManager()
        dm.db["system_settings"].update_one(
            {"key": "telegram_min_debate_rating"},
            {"$set": {
                "key": "telegram_min_debate_rating",
                "value": val,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        logger.info(f"Persisted telegram_min_debate_rating = {val}/10 to MongoDB.")
    except Exception as e:
        logger.error(f"Failed to persist telegram_min_debate_rating to MongoDB: {e}")

    return {
        "status": "success",
        "threshold": val,
        "label": get_threshold_label(val)
    }
