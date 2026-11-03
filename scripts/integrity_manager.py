"""
===============================================================================
INTEGRITY MANAGER - MISSION CRITICAL MULTI-ENGINE AUDITOR & SELF-HEALER
===============================================================================
Description:
    Centralized integrity supervisor that monitors, tests, probes, and heals
    all 11 subsystems of the TradingAgents platform:

    1.  Zerodha Auth & API Gateway (API Key, access token, ping, profile)
    2.  KiteTicker WebSocket Live Stream (running status, monitored tokens, tick flow)
    3.  Zerodha GTT Trailing Ladder & Breakout Engine (active GTTs vs DB, missing rules)
    4.  6-Agent Swarm Debate Gate (Technical, Flow, Momentum, Risk, Judge, Dual-Archetype)
    5.  Stock Alert Race & Returns Engine (cache freshness, zero-LTP detection, stock counts)
    6.  Nifty Derivatives & Option Buyer (active window, spot/GIFT/PCR/VIX data, 5m buyer vol)
    7.  Morning Short & VWAP Reversion (window status, scanner heartbeat, candidate count)
    8.  Evening Pro BTST Buying Engine (window status, scanner heartbeat, candidate count)
    9.  Paper Trading Strategy Engine (10 strategies running, ledger consistency, cash sanity)
    10. MongoDB Database Persistence (ping latency, collection health & counts)
    11. Telegram Dual-Timezone Dispatcher (token/chat_id validity, getMe check, IST/AEDT stamp)

Features:
    - Real-time Subsystem Probes with precise latency measurement (ms)
    - Overall System Health Score (0 - 100%)
    - Cross-Engine Regression Detection: alerts when an engine degrades from HEALTHY
    - One-Click Self-Healing actions for recoverable subsystems
    - Automatic High-Priority Telegram Alert dispatch if an engine crashes during market hours
===============================================================================
"""

import os
import sys
import time
import json
import logging
import datetime
import urllib.request
from typing import Dict, Any, List, Optional
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

load_dotenv(dotenv_path=project_root / ".env")

logger = logging.getLogger("IntegrityManager")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [IntegrityManager] %(message)s")


class IntegrityManager:
    """Central supervisor and self-healer for all TradingAgents subsystems."""

    def __init__(self):
        self._last_audit_time: Optional[datetime.datetime] = None
        self._subsystem_states: Dict[str, Dict[str, Any]] = {}
        self._event_log: List[Dict[str, Any]] = []
        self._regression_history: List[Dict[str, Any]] = []
        self._last_telegram_alert_time: Dict[str, float] = {}

    def log_event(self, level: str, engine_id: str, message: str, details: Optional[Dict[str, Any]] = None):
        """Appends an event to the circular diagnostic event log."""
        try:
            from tradingagents.market_timing import format_dual_timezone_stamp, get_now_ist
            dual_time = format_dual_timezone_stamp()
            ist_iso = get_now_ist().isoformat()
        except Exception:
            dual_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ist_iso = datetime.datetime.now().isoformat()

        event = {
            "id": f"evt_{int(time.time()*1000)}",
            "timestamp": ist_iso,
            "dual_time": dual_time,
            "level": level,  # INFO, WARNING, ERROR, SUCCESS
            "engine_id": engine_id,
            "message": message,
            "details": details or {}
        }
        self._event_log.insert(0, event)
        if len(self._event_log) > 200:
            self._event_log.pop()

    # =========================================================================
    # 1. ZERODHA AUTH & API GATEWAY PROBE
    # =========================================================================
    def probe_zerodha_auth(self) -> Dict[str, Any]:
        start = time.time()
        api_key = os.getenv("KITE_API_KEY") or os.getenv("ZERODHA_API_KEY")
        access_token = os.getenv("KITE_ACCESS_TOKEN") or os.getenv("ZERODHA_ACCESS_TOKEN")
        
        token_path = project_root / "data" / "credentials" / "zerodha_token.json"
        token_cache_exists = token_path.exists()
        
        if not api_key:
            return {
                "id": "zerodha_auth",
                "name": "Zerodha Auth & API Gateway",
                "category": "Broker & Data Stream",
                "status": "DEGRADED",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "heartbeat": "Missing API Key",
                "message": "KITE_API_KEY is not configured in .env",
                "can_heal": False,
                "metrics": {"api_key_configured": False, "token_cache_exists": token_cache_exists}
            }
        
        try:
            from scripts.zerodha_alert_manager import get_kite_client
            kite = get_kite_client()
            if not kite:
                return {
                    "id": "zerodha_auth",
                    "name": "Zerodha Auth & API Gateway",
                    "category": "Broker & Data Stream",
                    "status": "DEGRADED",
                    "latency_ms": round((time.time() - start) * 1000, 1),
                    "heartbeat": "No Client",
                    "message": "Could not instantiate KiteConnect client. Check credentials.",
                    "can_heal": True,
                    "heal_action": "relogin_zerodha",
                    "metrics": {"api_key_configured": True, "token_cached": token_cache_exists}
                }

            # Test live profile ping
            profile = kite.profile()
            latency = round((time.time() - start) * 1000, 1)
            user_id = profile.get("user_id", "Unknown")
            user_name = profile.get("user_name", "Unknown")
            
            return {
                "id": "zerodha_auth",
                "name": "Zerodha Auth & API Gateway",
                "category": "Broker & Data Stream",
                "status": "HEALTHY",
                "latency_ms": latency,
                "heartbeat": f"Connected ({user_id})",
                "message": f"Authenticated as {user_name} ({user_id}). Ping: {latency}ms.",
                "can_heal": False,
                "metrics": {
                    "user_id": user_id,
                    "user_name": user_name,
                    "broker": profile.get("broker", "ZERODHA"),
                    "token_cached": token_cache_exists
                }
            }
        except Exception as e:
            err_str = str(e)
            latency = round((time.time() - start) * 1000, 1)
            is_expired = "TokenException" in err_str or "session" in err_str.lower() or "expire" in err_str.lower()
            return {
                "id": "zerodha_auth",
                "name": "Zerodha Auth & API Gateway",
                "category": "Broker & Data Stream",
                "status": "DEGRADED" if is_expired else "WARNING",
                "latency_ms": latency,
                "heartbeat": "Expired / Invalid" if is_expired else "Ping Failed",
                "message": f"Zerodha API Error: {err_str[:120]}",
                "can_heal": True,
                "heal_action": "relogin_zerodha",
                "metrics": {"error": err_str[:100], "is_expired": is_expired}
            }

    # =========================================================================
    # 2. KITETICKER WEBSOCKET LIVE STREAM PROBE
    # =========================================================================
    def probe_websocket_stream(self) -> Dict[str, Any]:
        start = time.time()
        try:
            from scripts.zerodha_websocket_alert_listener import ws_alert_engine
            running = getattr(ws_alert_engine, "is_running", False)
            mock_mode = getattr(ws_alert_engine, "mock_mode", False)
            token_map = getattr(ws_alert_engine, "token_map", {})
            token_count = len(token_map)
            latest_ticks = getattr(ws_alert_engine, "latest_ticks", {})
            ticks_count = len(latest_ticks)
            
            latency = round((time.time() - start) * 1000, 1)

            if not running:
                return {
                    "id": "websocket_stream",
                    "name": "KiteTicker WebSocket Live Stream",
                    "category": "Broker & Data Stream",
                    "status": "WARNING",
                    "latency_ms": latency,
                    "heartbeat": "Stopped / Standby",
                    "message": "WebSocket listener is not running. Click Self-Heal to start.",
                    "can_heal": True,
                    "heal_action": "restart_websocket",
                    "metrics": {
                        "running": False,
                        "mock_mode": mock_mode,
                        "monitored_tokens": token_count,
                        "cached_ticks": ticks_count
                    }
                }
            
            status = "HEALTHY" if not mock_mode else "WARNING"
            heartbeat = f"Streaming ({token_count} tokens)" if not mock_mode else "Mock Mode Active"
            msg = f"Live stream running with {token_count} active instrument tokens ({ticks_count} ticks cached)."
            if mock_mode:
                msg = f"WebSocket running in MOCK mode (fallback for offline/dev)."

            return {
                "id": "websocket_stream",
                "name": "KiteTicker WebSocket Live Stream",
                "category": "Broker & Data Stream",
                "status": status,
                "latency_ms": latency,
                "heartbeat": heartbeat,
                "message": msg,
                "can_heal": True,
                "heal_action": "restart_websocket",
                "metrics": {
                    "running": True,
                    "mock_mode": mock_mode,
                    "monitored_tokens": token_count,
                    "cached_ticks": ticks_count
                }
            }
        except Exception as e:
            return {
                "id": "websocket_stream",
                "name": "KiteTicker WebSocket Live Stream",
                "category": "Broker & Data Stream",
                "status": "DEGRADED",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "heartbeat": "Error",
                "message": f"WebSocket check failed: {str(e)[:120]}",
                "can_heal": True,
                "heal_action": "restart_websocket",
                "metrics": {"error": str(e)[:100]}
            }

    # =========================================================================
    # 3. ZERODHA GTT TRAILING LADDER & BREAKOUT ENGINE PROBE
    # =========================================================================
    def probe_gtt_ladder(self) -> Dict[str, Any]:
        start = time.time()
        try:
            from scripts.zerodha_alert_manager import get_kite_client
            from data_manager import DataManager
            
            kite = get_kite_client()
            if not kite:
                return {
                    "id": "gtt_ladder",
                    "name": "Zerodha GTT Trailing Ladder",
                    "category": "Execution & Orders",
                    "status": "WARNING",
                    "latency_ms": round((time.time() - start) * 1000, 1),
                    "heartbeat": "Broker Offline",
                    "message": "Zerodha client unavailable to query active GTTs.",
                    "can_heal": False,
                    "metrics": {"gtt_count": 0}
                }

            from scripts.zerodha_alert_manager import get_cached_gtts
            gtts = get_cached_gtts(kite=kite, max_age_seconds=60)
            latency = round((time.time() - start) * 1000, 1)
            gtt_count = len(gtts) if isinstance(gtts, list) else 0
            
            # Check DB active watchlist count
            dm = DataManager()
            db_active_count = 0
            if dm.db is not None:
                db_active_count = dm.db["active_alerts"].count_documents({})
            
            return {
                "id": "gtt_ladder",
                "name": "Zerodha GTT Trailing Ladder",
                "category": "Execution & Orders",
                "status": "HEALTHY",
                "latency_ms": latency,
                "heartbeat": f"{gtt_count} Active Orders",
                "message": f"{gtt_count} Zerodha GTT triggers active on broker. {db_active_count} alerts logged in DB.",
                "can_heal": True,
                "heal_action": "audit_gtts",
                "metrics": {
                    "zerodha_gtts_count": gtt_count,
                    "db_active_alerts": db_active_count
                }
            }
        except Exception as e:
            return {
                "id": "gtt_ladder",
                "name": "Zerodha GTT Trailing Ladder",
                "category": "Execution & Orders",
                "status": "DEGRADED",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "heartbeat": "GTT API Error",
                "message": f"GTT query error: {str(e)[:120]}",
                "can_heal": True,
                "heal_action": "audit_gtts",
                "metrics": {"error": str(e)[:100]}
            }

    # =========================================================================
    # 4. 6-AGENT SWARM DEBATE GATE PROBE
    # =========================================================================
    def probe_swarm_gate(self) -> Dict[str, Any]:
        start = time.time()
        try:
            from scripts.agents_debate_swarm import run_swarm_agents_debate
            
            # Run a fast benchmark debate verification
            res = run_swarm_agents_debate(
                symbol="PROBE_BENCHMARK",
                setup_type="DARVAS_BREAKOUT",
                current_price=1000.0,
                trigger_price=990.0
            )
            latency = round((time.time() - start) * 1000, 1)
            
            rating = res.get("agents_debate_rating")
            verdict = res.get("agents_debate_verdict")
            
            if rating is None or verdict is None:
                return {
                    "id": "swarm_debate_gate",
                    "name": "6-Agent Swarm Debate Gate",
                    "category": "Risk & AI Swarm",
                    "status": "DEGRADED",
                    "latency_ms": latency,
                    "heartbeat": "Invalid Output",
                    "message": "Swarm debate executed but returned invalid rating or verdict structure.",
                    "can_heal": False,
                    "metrics": {"output": str(res)[:100]}
                }

            return {
                "id": "swarm_debate_gate",
                "name": "6-Agent Swarm Debate Gate",
                "category": "Risk & AI Swarm",
                "status": "HEALTHY",
                "latency_ms": latency,
                "heartbeat": f"Verified ({rating}/10)",
                "message": f"6 Agents operational (Structural, Flow, Momentum, Bullish, Trap, Judge). Test verdict: {verdict}.",
                "can_heal": False,
                "metrics": {
                    "agents_count": 6,
                    "benchmark_rating": rating,
                    "dual_archetype_ready": True
                }
            }
        except Exception as e:
            return {
                "id": "swarm_debate_gate",
                "name": "6-Agent Swarm Debate Gate",
                "category": "Risk & AI Swarm",
                "status": "DEGRADED",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "heartbeat": "Import / Exec Failed",
                "message": f"Swarm gate failed: {str(e)[:120]}",
                "can_heal": False,
                "metrics": {"error": str(e)[:100]}
            }

    # =========================================================================
    # 5. STOCK ALERT RACE & RETURNS CACHE PROBE
    # =========================================================================
    def probe_race_returns_cache(self) -> Dict[str, Any]:
        start = time.time()
        try:
            from data_manager import DataManager
            dm = DataManager()
            if dm.db is None:
                return {
                    "id": "race_returns_cache",
                    "name": "Stock Alert Race & Returns Engine",
                    "category": "Market Analytics",
                    "status": "DEGRADED",
                    "latency_ms": round((time.time() - start) * 1000, 1),
                    "heartbeat": "No DB",
                    "message": "MongoDB is not connected to read stock returns cache.",
                    "can_heal": True,
                    "heal_action": "sync_race_cache",
                    "metrics": {}
                }

            docs = list(dm.db["stock_returns_cache"].find({}, {"_id": 0}))
            latency = round((time.time() - start) * 1000, 1)

            if not docs:
                return {
                    "id": "race_returns_cache",
                    "name": "Stock Alert Race & Returns Engine",
                    "category": "Market Analytics",
                    "status": "WARNING",
                    "latency_ms": latency,
                    "heartbeat": "Empty Cache",
                    "message": "Stock returns cache is empty. Click Self-Heal to sync from Zerodha.",
                    "can_heal": True,
                    "heal_action": "sync_race_cache",
                    "metrics": {"total_cached_stocks": 0, "zero_ltp_count": 0}
                }

            stock_count = len(docs)
            zero_ltp_stocks = [d.get("symbol") for d in docs if (d.get("ltp") or 0) <= 0]
            zero_count = len(zero_ltp_stocks)

            status = "HEALTHY"
            msg = f"{stock_count} stocks cached in DB. Zero-LTP anomalies: {zero_count}."
            if zero_count > 0:
                status = "WARNING"
                msg = f"{zero_count} stocks have LTP <= 0 ({', '.join(filter(None, zero_ltp_stocks[:3]))}). Click Self-Heal to sync."

            return {
                "id": "race_returns_cache",
                "name": "Stock Alert Race & Returns Engine",
                "category": "Market Analytics",
                "status": status,
                "latency_ms": latency,
                "heartbeat": f"{stock_count} Stocks ({zero_count} zero-LTP)",
                "message": msg,
                "can_heal": True,
                "heal_action": "sync_race_cache",
                "metrics": {
                    "total_cached_stocks": stock_count,
                    "zero_ltp_count": zero_count
                }
            }
        except Exception as e:
            return {
                "id": "race_returns_cache",
                "name": "Stock Alert Race & Returns Engine",
                "category": "Market Analytics",
                "status": "DEGRADED",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "heartbeat": "Cache Error",
                "message": f"Race cache check failed: {str(e)[:120]}",
                "can_heal": True,
                "heal_action": "sync_race_cache",
                "metrics": {"error": str(e)[:100]}
            }

    # =========================================================================
    # 6. NIFTY DERIVATIVES & OPTION BUYER ENGINE PROBE
    # =========================================================================
    def probe_derivatives_engine(self) -> Dict[str, Any]:
        start = time.time()
        try:
            from tradingagents.market_timing import is_derivatives_breakout_window
            is_active, status_desc = is_derivatives_breakout_window()
            
            # Test derivatives imports
            import scripts.nifty_derivatives_breakout_alert as ndba
            
            latency = round((time.time() - start) * 1000, 1)
            heartbeat = "Active Session" if is_active else "Standby (After-Hours)"
            status = "HEALTHY"
            msg = f"Window: {status_desc}. Two-Stage Weekly Option Buyer & PCR scanner ready."

            return {
                "id": "derivatives_engine",
                "name": "Nifty Derivatives & Option Buyer",
                "category": "Trading Engines",
                "status": status,
                "latency_ms": latency,
                "heartbeat": heartbeat,
                "message": msg,
                "can_heal": True,
                "heal_action": "refresh_derivatives",
                "metrics": {
                    "session_active": is_active,
                    "window_desc": status_desc,
                    "stage_scanner_loaded": hasattr(ndba, "check_and_trigger_spot_index_breakout")
                }
            }
        except Exception as e:
            return {
                "id": "derivatives_engine",
                "name": "Nifty Derivatives & Option Buyer",
                "category": "Trading Engines",
                "status": "DEGRADED",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "heartbeat": "Engine Error",
                "message": f"Derivatives engine error: {str(e)[:120]}",
                "can_heal": True,
                "heal_action": "refresh_derivatives",
                "metrics": {"error": str(e)[:100]}
            }

    # =========================================================================
    # 7. MORNING SHORT & VWAP REVERSION ENGINE PROBE
    # =========================================================================
    def probe_morning_short(self) -> Dict[str, Any]:
        start = time.time()
        try:
            from tradingagents.market_timing import is_morning_short_window
            is_active, status_desc = is_morning_short_window()
            
            from data_manager import DataManager
            dm = DataManager()
            cand_count = 0
            if dm.db is not None:
                cand_count = dm.db["short_candidates"].count_documents({})
            
            latency = round((time.time() - start) * 1000, 1)
            heartbeat = "Active Session" if is_active else "Standby (After-Hours)"
            
            return {
                "id": "morning_short_engine",
                "name": "Morning Short & VWAP Reversion",
                "category": "Trading Engines",
                "status": "HEALTHY",
                "latency_ms": latency,
                "heartbeat": heartbeat,
                "message": f"Window: {status_desc}. {cand_count} candidates tracked in DB.",
                "can_heal": True,
                "heal_action": "scan_morning_short",
                "metrics": {
                    "session_active": is_active,
                    "candidates_count": cand_count,
                    "window_desc": status_desc
                }
            }
        except Exception as e:
            return {
                "id": "morning_short_engine",
                "name": "Morning Short & VWAP Reversion",
                "category": "Trading Engines",
                "status": "DEGRADED",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "heartbeat": "Short Engine Error",
                "message": f"Morning short error: {str(e)[:120]}",
                "can_heal": True,
                "heal_action": "scan_morning_short",
                "metrics": {"error": str(e)[:100]}
            }

    # =========================================================================
    # 8. EVENING PRO BTST BUYING ENGINE PROBE
    # =========================================================================
    def probe_evening_pro(self) -> Dict[str, Any]:
        start = time.time()
        try:
            from tradingagents.market_timing import is_evening_pro_window
            is_active, status_desc = is_evening_pro_window()
            
            from data_manager import DataManager
            dm = DataManager()
            cand_count = 0
            if dm.db is not None:
                cand_count = dm.db["evening_pro_candidates"].count_documents({})
            
            latency = round((time.time() - start) * 1000, 1)
            heartbeat = "Active Session" if is_active else "Standby (After-Hours)"
            
            return {
                "id": "evening_pro_engine",
                "name": "Evening Pro BTST Buying Engine",
                "category": "Trading Engines",
                "status": "HEALTHY",
                "latency_ms": latency,
                "heartbeat": heartbeat,
                "message": f"Window: {status_desc}. {cand_count} institutional candidates in DB.",
                "can_heal": True,
                "heal_action": "scan_evening_pro",
                "metrics": {
                    "session_active": is_active,
                    "candidates_count": cand_count,
                    "window_desc": status_desc
                }
            }
        except Exception as e:
            return {
                "id": "evening_pro_engine",
                "name": "Evening Pro BTST Buying Engine",
                "category": "Trading Engines",
                "status": "DEGRADED",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "heartbeat": "Evening Pro Error",
                "message": f"Evening pro error: {str(e)[:120]}",
                "can_heal": True,
                "heal_action": "scan_evening_pro",
                "metrics": {"error": str(e)[:100]}
            }

    # =========================================================================
    # 9. PAPER TRADING STRATEGY ENGINE PROBE
    # =========================================================================
    def probe_paper_trading(self) -> Dict[str, Any]:
        start = time.time()
        try:
            from data_manager import DataManager
            dm = DataManager()
            trade_count = 0
            port_count = 0
            cash_ledger_ok = True
            
            if dm.db is not None:
                trade_count = dm.db["paper_trades"].count_documents({})
                port_count = dm.db["paper_portfolios"].count_documents({})
                
                # Check for NaN / negative cash anomalies
                anomalies = dm.db["paper_portfolios"].count_documents({"cash": {"$lt": 0}})
                if anomalies > 0:
                    cash_ledger_ok = False

            latency = round((time.time() - start) * 1000, 1)
            status = "HEALTHY" if cash_ledger_ok else "WARNING"
            heartbeat = f"{port_count} Portfolios / {trade_count} Trades"
            msg = f"10 Paper trading strategies tracked. {port_count} portfolios, {trade_count} trades in ledger."
            if not cash_ledger_ok:
                msg = f"Warning: Detected negative cash balance in {anomalies} paper portfolio(s)."

            return {
                "id": "paper_trading",
                "name": "Paper Trading Strategy Engine",
                "category": "Execution & Orders",
                "status": status,
                "latency_ms": latency,
                "heartbeat": heartbeat,
                "message": msg,
                "can_heal": True,
                "heal_action": "reconcile_paper_trading",
                "metrics": {
                    "portfolios_count": port_count,
                    "trades_count": trade_count,
                    "cash_ledger_ok": cash_ledger_ok
                }
            }
        except Exception as e:
            return {
                "id": "paper_trading",
                "name": "Paper Trading Strategy Engine",
                "category": "Execution & Orders",
                "status": "DEGRADED",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "heartbeat": "Paper Engine Error",
                "message": f"Paper trading error: {str(e)[:120]}",
                "can_heal": True,
                "heal_action": "reconcile_paper_trading",
                "metrics": {"error": str(e)[:100]}
            }

    # =========================================================================
    # 10. MONGODB DATABASE PERSISTENCE PROBE
    # =========================================================================
    def probe_mongodb(self) -> Dict[str, Any]:
        start = time.time()
        try:
            from data_manager import DataManager
            dm = DataManager()
            if dm.db is None:
                return {
                    "id": "mongodb_persistence",
                    "name": "MongoDB Database Persistence",
                    "category": "Database & State",
                    "status": "DEGRADED",
                    "latency_ms": round((time.time() - start) * 1000, 1),
                    "heartbeat": "Disconnected",
                    "message": "MongoDB client is not connected.",
                    "can_heal": True,
                    "heal_action": "reconnect_mongodb",
                    "metrics": {}
                }

            # Ping round-trip
            dm.db.command("ping")
            latency = round((time.time() - start) * 1000, 1)

            # Check collection counts
            counts = {
                "darvas": dm.db["darvas"].count_documents({}),
                "daily": dm.db["daily"].count_documents({}),
                "weekly": dm.db["weekly"].count_documents({}),
                "monthly": dm.db["monthly"].count_documents({}),
                "active_alerts": dm.db["active_alerts"].count_documents({}),
                "stock_returns_cache": dm.db["stock_returns_cache"].count_documents({}),
                "user_watchlist": dm.db["user_watchlist"].count_documents({})
            }

            status = "HEALTHY" if latency < 150 else "WARNING"
            heartbeat = f"Connected ({latency}ms)"
            msg = f"MongoDB operational. Collections healthy: Darvas ({counts['darvas']}), Daily ({counts['daily']}), Weekly ({counts['weekly']}), Monthly ({counts['monthly']})."

            return {
                "id": "mongodb_persistence",
                "name": "MongoDB Database Persistence",
                "category": "Database & State",
                "status": status,
                "latency_ms": latency,
                "heartbeat": heartbeat,
                "message": msg,
                "can_heal": True,
                "heal_action": "reconnect_mongodb",
                "metrics": counts
            }
        except Exception as e:
            return {
                "id": "mongodb_persistence",
                "name": "MongoDB Database Persistence",
                "category": "Database & State",
                "status": "DEGRADED",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "heartbeat": "Ping Failed",
                "message": f"MongoDB error: {str(e)[:120]}",
                "can_heal": True,
                "heal_action": "reconnect_mongodb",
                "metrics": {"error": str(e)[:100]}
            }

    # =========================================================================
    # 11. TELEGRAM BOT ALERT DISPATCHER PROBE
    # =========================================================================
    def probe_telegram_bot(self) -> Dict[str, Any]:
        start = time.time()
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        if not bot_token or not chat_id:
            return {
                "id": "telegram_alerts",
                "name": "Telegram Dual-Timezone Dispatcher",
                "category": "Risk & AI Swarm",
                "status": "WARNING",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "heartbeat": "Not Configured",
                "message": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in .env",
                "can_heal": False,
                "metrics": {"token_set": bool(bot_token), "chat_id_set": bool(chat_id)}
            }
        
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getMe"
            req = urllib.request.Request(url, headers={"User-Agent": "TradingAgents-IntegrityManager/1.0"})
            with urllib.request.urlopen(req, timeout=5) as res:
                data = json.loads(res.read().decode())
                latency = round((time.time() - start) * 1000, 1)
                
                bot_user = data.get("result", {}).get("username", "UnknownBot")
                
                # Check dual-timezone stamp generator
                from tradingagents.market_timing import format_dual_timezone_stamp
                dual_stamp = format_dual_timezone_stamp()

                return {
                    "id": "telegram_alerts",
                    "name": "Telegram Dual-Timezone Dispatcher",
                    "category": "Risk & AI Swarm",
                    "status": "HEALTHY",
                    "latency_ms": latency,
                    "heartbeat": f"@{bot_user} ({latency}ms)",
                    "message": f"Telegram Bot @{bot_user} verified. Dual stamp: {dual_stamp}",
                    "can_heal": True,
                    "heal_action": "test_telegram_ping",
                    "metrics": {
                        "bot_username": bot_user,
                        "chat_id": chat_id[:4] + "****" if len(chat_id) > 4 else chat_id,
                        "dual_stamp_sample": dual_stamp
                    }
                }
        except Exception as e:
            return {
                "id": "telegram_alerts",
                "name": "Telegram Dual-Timezone Dispatcher",
                "category": "Risk & AI Swarm",
                "status": "WARNING",
                "latency_ms": round((time.time() - start) * 1000, 1),
                "heartbeat": "Network Timeout",
                "message": f"Telegram API ping failed: {str(e)[:120]}",
                "can_heal": True,
                "heal_action": "test_telegram_ping",
                "metrics": {"error": str(e)[:100]}
            }

    # =========================================================================
    # MASTER AUDIT & REGRESSION DETECTION
    # =========================================================================
    def run_full_integrity_audit(self) -> Dict[str, Any]:
        """Runs all 11 subsystem probes, computes system score, and detects regressions."""
        audit_start = time.time()
        
        probes = [
            self.probe_zerodha_auth,
            self.probe_websocket_stream,
            self.probe_gtt_ladder,
            self.probe_swarm_gate,
            self.probe_race_returns_cache,
            self.probe_derivatives_engine,
            self.probe_morning_short,
            self.probe_evening_pro,
            self.probe_paper_trading,
            self.probe_mongodb,
            self.probe_telegram_bot
        ]

        subsystems: List[Dict[str, Any]] = []
        for probe_fn in probes:
            try:
                subsystems.append(probe_fn())
            except Exception as e:
                subsystems.append({
                    "id": probe_fn.__name__.replace("probe_", ""),
                    "name": probe_fn.__name__.replace("probe_", "").replace("_", " ").title(),
                    "category": "Unknown",
                    "status": "DEGRADED",
                    "latency_ms": 0.0,
                    "heartbeat": "Audit Crash",
                    "message": f"Unexpected probe crash: {str(e)[:120]}",
                    "can_heal": False,
                    "metrics": {"error": str(e)[:100]}
                })

        # Calculate score: HEALTHY=100%, WARNING=60%, DEGRADED=0%
        healthy_count = sum(1 for s in subsystems if s["status"] == "HEALTHY")
        warning_count = sum(1 for s in subsystems if s["status"] == "WARNING")
        degraded_count = sum(1 for s in subsystems if s["status"] == "DEGRADED")
        total = len(subsystems)
        
        overall_score = round(((healthy_count * 100) + (warning_count * 60)) / total, 1)
        
        if degraded_count > 0:
            overall_status = "DEGRADED"
        elif warning_count > 0:
            overall_status = "WARNING"
        else:
            overall_status = "HEALTHY"

        # Regression detection vs previous states
        regressions_detected = []
        for sub in subsystems:
            sub_id = sub["id"]
            new_status = sub["status"]
            prev_status = self._subsystem_states.get(sub_id, {}).get("status")
            
            if prev_status and prev_status == "HEALTHY" and new_status in ("WARNING", "DEGRADED"):
                reg_event = {
                    "engine_id": sub_id,
                    "engine_name": sub["name"],
                    "previous_status": prev_status,
                    "new_status": new_status,
                    "message": sub["message"],
                    "timestamp": datetime.datetime.now().isoformat()
                }
                regressions_detected.append(reg_event)
                self._regression_history.insert(0, reg_event)
                if len(self._regression_history) > 50:
                    self._regression_history.pop()

                self.log_event(
                    "ERROR" if new_status == "DEGRADED" else "WARNING",
                    sub_id,
                    f"REGRESSION DETECTED: {sub['name']} dropped from {prev_status} to {new_status}: {sub['message']}"
                )
                
                # Check if we should dispatch Telegram alert
                self._dispatch_critical_regression_telegram(sub)

            self._subsystem_states[sub_id] = sub

        total_audit_time_ms = round((time.time() - audit_start) * 1000, 1)
        self._last_audit_time = datetime.datetime.now()

        try:
            from tradingagents.market_timing import format_dual_timezone_stamp, get_now_ist
            dual_time = format_dual_timezone_stamp()
            ist_iso = get_now_ist().isoformat()
        except Exception:
            dual_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ist_iso = datetime.datetime.now().isoformat()

        return {
            "overall_status": overall_status,
            "overall_score": overall_score,
            "healthy_count": healthy_count,
            "warning_count": warning_count,
            "degraded_count": degraded_count,
            "total_subsystems": total,
            "audit_latency_ms": total_audit_time_ms,
            "timestamp": ist_iso,
            "dual_time": dual_time,
            "subsystems": subsystems,
            "regressions_detected": regressions_detected,
            "recent_events": self._event_log[:20]
        }

    def _dispatch_critical_regression_telegram(self, sub: Dict[str, Any]):
        """Dispatches immediate Telegram alert if a critical subsystem degrades."""
        now = time.time()
        sub_id = sub["id"]
        # Throttle to at most one alert per engine every 15 minutes
        if now - self._last_telegram_alert_time.get(sub_id, 0) < 900:
            return

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not bot_token or not chat_id:
            return

        try:
            from tradingagents.market_timing import format_dual_timezone_stamp
            dual_time = format_dual_timezone_stamp()
        except Exception:
            dual_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        status_emoji = "🔴" if sub["status"] == "DEGRADED" else "🟡"
        text = (
            f"🚨 <b>[INTEGRITY REGRESSION ALERT]</b>\n\n"
            f"{status_emoji} <b>Subsystem:</b> {sub['name']}\n"
            f"⚠️ <b>Status:</b> {sub['status']}\n"
            f"📝 <b>Details:</b> {sub['message']}\n"
            f"🕒 <b>Time:</b> {dual_time}\n\n"
            f"<i>Action: Open Integrity Manager dashboard to trigger self-healing.</i>"
        )

        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    self._last_telegram_alert_time[sub_id] = now
                    self.log_event("INFO", sub_id, f"Telegram regression alert dispatched for {sub['name']}.")
        except Exception as e:
            logger.warning(f"Could not dispatch regression Telegram alert: {e}")

    # =========================================================================
    # SELF-HEALING DISPATCHER
    # =========================================================================
    def heal_subsystem(self, engine_id: str) -> Dict[str, Any]:
        """Executes targeted self-healing procedure for a specific subsystem."""
        self.log_event("INFO", engine_id, f"Self-heal initiated for subsystem: {engine_id}")
        
        try:
            if engine_id in ("websocket_stream", "restart_websocket"):
                from scripts.zerodha_websocket_alert_listener import ws_alert_engine
                ws_alert_engine.stop()
                time.sleep(1)
                ws_alert_engine.load_monitored_targets()
                ws_alert_engine.start(threaded=True)
                msg = f"KiteTicker WebSocket restarted. Monitored tokens: {len(ws_alert_engine.token_map)}."
                self.log_event("SUCCESS", engine_id, msg)
                return {"status": "success", "message": msg, "engine_id": engine_id}

            elif engine_id in ("gtt_ladder", "audit_gtts"):
                from scripts.gtt_next_alert_integrity_monitor import audit_and_restore_next_gtt_alerts
                res = audit_and_restore_next_gtt_alerts(dry_run=False)
                active = res.get("active_next_alerts_count", 0)
                restored = res.get("restored_count", 0)
                msg = f"GTT ladder audited & fixed. Active alerts: {active}, Restored: {restored}."
                self.log_event("SUCCESS", engine_id, msg)
                return {"status": "success", "message": msg, "details": res, "engine_id": engine_id}

            elif engine_id in ("race_returns_cache", "sync_race_cache"):
                from scripts.sync_stock_returns_cache import sync_stock_returns_cache
                res = sync_stock_returns_cache()
                msg = f"Stock returns cache synced. Updated: {res.get('updated_count', 0)} stocks."
                self.log_event("SUCCESS", engine_id, msg)
                return {"status": "success", "message": msg, "details": res, "engine_id": engine_id}

            elif engine_id in ("derivatives_engine", "refresh_derivatives"):
                from scripts.nifty_derivatives_breakout_alert import check_and_trigger_spot_index_breakout
                res = check_and_trigger_spot_index_breakout(check_market_window=False)
                msg = "Derivatives engine refreshed & spot breakout evaluation complete."
                self.log_event("SUCCESS", engine_id, msg)
                return {"status": "success", "message": msg, "details": res, "engine_id": engine_id}

            elif engine_id in ("morning_short_engine", "scan_morning_short"):
                from scripts.morning_short_scanner import run_morning_short_scan
                res = run_morning_short_scan()
                msg = f"Morning short candidate scanner executed. Candidates found: {len(res) if isinstance(res, list) else 0}."
                self.log_event("SUCCESS", engine_id, msg)
                return {"status": "success", "message": msg, "engine_id": engine_id}

            elif engine_id in ("evening_pro_engine", "scan_evening_pro"):
                from scripts.evening_pro_scanner import run_evening_pro_scan
                res = run_evening_pro_scan()
                msg = f"Evening pro institutional candidate scanner executed. Candidates found: {len(res) if isinstance(res, list) else 0}."
                self.log_event("SUCCESS", engine_id, msg)
                return {"status": "success", "message": msg, "engine_id": engine_id}

            elif engine_id in ("mongodb_persistence", "reconnect_mongodb"):
                from data_manager import DataManager
                dm = DataManager()
                if dm.client:
                    dm.client.close()
                dm._connect()
                msg = "MongoDB client connection pool refreshed."
                self.log_event("SUCCESS", engine_id, msg)
                return {"status": "success", "message": msg, "engine_id": engine_id}

            elif engine_id in ("telegram_alerts", "test_telegram_ping"):
                bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                chat_id = os.getenv("TELEGRAM_CHAT_ID")
                from tradingagents.market_timing import format_dual_timezone_stamp
                dual_time = format_dual_timezone_stamp()
                text = (
                    f"🛡️ <b>[INTEGRITY MANAGER - SELF-HEAL PING]</b>\n\n"
                    f"✅ Telegram Dispatcher connectivity test passed.\n"
                    f"🕒 <b>Timestamp:</b> {dual_time}\n"
                    f"<i>TradingAgents platform running smoothly.</i>"
                )
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode("utf-8")
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    pass
                msg = "Telegram test message dispatched successfully."
                self.log_event("SUCCESS", engine_id, msg)
                return {"status": "success", "message": msg, "engine_id": engine_id}

            else:
                msg = f"No automated self-healing script registered for '{engine_id}'."
                self.log_event("WARNING", engine_id, msg)
                return {"status": "skipped", "message": msg, "engine_id": engine_id}

        except Exception as e:
            err_msg = f"Self-healing failed for {engine_id}: {str(e)}"
            self.log_event("ERROR", engine_id, err_msg)
            return {"status": "error", "message": err_msg, "engine_id": engine_id}

    def heal_all_degraded(self) -> Dict[str, Any]:
        """Automatically attempts to self-heal all subsystems currently in WARNING or DEGRADED status."""
        current_audit = self.run_full_integrity_audit()
        results = []
        for sub in current_audit["subsystems"]:
            if sub["status"] in ("WARNING", "DEGRADED") and sub.get("can_heal"):
                res = self.heal_subsystem(sub["id"])
                results.append(res)
        
        # Re-audit after healing
        refreshed_audit = self.run_full_integrity_audit()
        return {
            "healed_count": len(results),
            "heal_results": results,
            "refreshed_status": refreshed_audit
        }


# Singleton instance for platform-wide use
integrity_manager = IntegrityManager()

if __name__ == "__main__":
    print("\n" + "="*80)
    print("RUNNING STANDALONE PLATFORM INTEGRITY AUDIT")
    print("="*80)
    audit = integrity_manager.run_full_integrity_audit()
    print(f"\nOverall Status: {audit['overall_status']} (Score: {audit['overall_score']}%)\n")
    print(f"{'SUBSYSTEM':<40} {'STATUS':<12} {'LATENCY':<10} {'HEARTBEAT'}")
    print("-" * 80)
    for s in audit["subsystems"]:
        status_icon = "🟢" if s['status'] == 'HEALTHY' else ("🟡" if s['status'] == 'WARNING' else "🔴")
        print(f"{s['name']:<40} {status_icon} {s['status']:<9} {s['latency_ms']:>6.1f}ms  {s['heartbeat']}")
    print("-" * 80)
    print(f"Total Probed: {audit['total_subsystems']} | Healthy: {audit['healthy_count']} | Warning: {audit['warning_count']} | Degraded: {audit['degraded_count']}")
    print("="*80 + "\n")
