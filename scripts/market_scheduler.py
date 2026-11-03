"""
===============================================================================
MASTER MARKET SCHEDULER & EVENT ORCHESTRATOR
===============================================================================
Description:
    Consolidates multiple independent background loops into a single,
    synchronized, thread-safe Master Market Orchestrator:

    1.  Integrity Probe & Regression Watch (every 60s)
    2.  Nifty Derivatives & Option Pressure Monitor (every 3m during 09:15-15:30 IST)
    3.  Morning Short & VWAP Reversion Scanner (every 5m during 09:15-10:30 IST)
    4.  Evening Pro BTST Buying Scanner (every 5m during 15:00-15:30 IST)
    5.  Paper Trading Strategy Engine (every 5m during 09:15-15:30 IST)
    6.  GTT Trailing Ladder Audit & Stale GTT Purge (every 30m)
    7.  Stock Returns Cache Background Sync (every 30m)
    8.  Daily Zerodha Token Check (daily / every 12h)

Benefits:
    - Eliminates thread contention, duplicate queries, and uncoordinated DB reads.
    - Accurately tracks last execution time and status for every task.
    - Completely non-blocking: each scheduled task executes safely with exception containment.
===============================================================================
"""

import os
import sys
import time
import logging
import datetime
from pathlib import Path
from typing import Dict, Any, Optional

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from tradingagents.market_timing import (
    get_now_ist,
    format_dual_timezone_stamp,
    is_derivatives_breakout_window,
    is_morning_short_window,
    is_evening_pro_window,
    is_market_open,
)

logger = logging.getLogger("MarketScheduler")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [MarketScheduler] %(message)s")


class MasterMarketScheduler:
    """Master scheduler coordinating all platform background jobs."""

    def __init__(self):
        self.is_running = False
        self._thread = None
        self.tasks_status: Dict[str, Dict[str, Any]] = {
            "integrity_probe": {"last_run": 0.0, "interval_sec": 60, "status": "IDLE"},
            "derivatives_scanner": {"last_run": 0.0, "interval_sec": 180, "status": "IDLE"},
            "morning_short_scanner": {"last_run": 0.0, "interval_sec": 300, "status": "IDLE"},
            "evening_pro_scanner": {"last_run": 0.0, "interval_sec": 300, "status": "IDLE"},
            "paper_trading": {"last_run": 0.0, "interval_sec": 300, "status": "IDLE"},
            "gtt_integrity_audit": {"last_run": 0.0, "interval_sec": 1800, "status": "IDLE"},
            "race_cache_sync": {"last_run": 0.0, "interval_sec": 1800, "status": "IDLE"},
            "zerodha_token_check": {"last_run": 0.0, "interval_sec": 43200, "status": "IDLE"},
        }

    def start(self):
        """Starts the master orchestrator in a single background thread."""
        if self.is_running:
            return
        self.is_running = True
        import threading
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="MasterMarketSchedulerThread")
        self._thread.start()
        logger.info("Master Market Scheduler started successfully.")

    def stop(self):
        self.is_running = False

    def _run_loop(self):
        # Initial sleep to allow API server & DB connections to settle
        time.sleep(8)
        logger.info("Master Market Scheduler active. Monitoring market windows and tasks.")

        while self.is_running:
            now = time.time()
            try:
                # 1. INTEGRITY PROBE (Every 60s)
                if now - self.tasks_status["integrity_probe"]["last_run"] >= self.tasks_status["integrity_probe"]["interval_sec"]:
                    self._execute_integrity_probe(now)

                # 2. DERIVATIVES OPTION BUYER SCANNER (Every 3m during derivatives window)
                if now - self.tasks_status["derivatives_scanner"]["last_run"] >= self.tasks_status["derivatives_scanner"]["interval_sec"]:
                    self._execute_derivatives_scanner(now)

                # 3. MORNING SHORT & VWAP REVERSION (Every 5m during morning window)
                if now - self.tasks_status["morning_short_scanner"]["last_run"] >= self.tasks_status["morning_short_scanner"]["interval_sec"]:
                    self._execute_morning_short_scanner(now)

                # 4. EVENING PRO BTST BUYING (Every 5m during evening window)
                if now - self.tasks_status["evening_pro_scanner"]["last_run"] >= self.tasks_status["evening_pro_scanner"]["interval_sec"]:
                    self._execute_evening_pro_scanner(now)

                # 5. PAPER TRADING STRATEGY ENGINE (Every 5m during market open)
                if now - self.tasks_status["paper_trading"]["last_run"] >= self.tasks_status["paper_trading"]["interval_sec"]:
                    self._execute_paper_trading(now)

                # 6. GTT INTEGRITY AUDIT & STALE PURGE (Every 30m)
                if now - self.tasks_status["gtt_integrity_audit"]["last_run"] >= self.tasks_status["gtt_integrity_audit"]["interval_sec"]:
                    self._execute_gtt_audit(now)

                # 7. STOCK RETURNS CACHE SYNC (Every 30m)
                if now - self.tasks_status["race_cache_sync"]["last_run"] >= self.tasks_status["race_cache_sync"]["interval_sec"]:
                    self._execute_race_cache_sync(now)

                # 8. ZERODHA DAILY TOKEN CHECK (Every 12 hours)
                if now - self.tasks_status["zerodha_token_check"]["last_run"] >= self.tasks_status["zerodha_token_check"]["interval_sec"]:
                    self._execute_token_check(now)

            except Exception as loop_err:
                logger.error(f"Scheduler tick error: {loop_err}")

            time.sleep(10)  # Precision 10s tick

    # =========================================================================
    # TASK EXECUTORS
    # =========================================================================
    def _execute_integrity_probe(self, now: float):
        self.tasks_status["integrity_probe"]["last_run"] = now
        try:
            from scripts.integrity_manager import integrity_manager
            audit = integrity_manager.run_full_integrity_audit()
            regressions = audit.get("regressions_detected", [])
            self.tasks_status["integrity_probe"]["status"] = f"OK ({audit.get('overall_score')}%)"
            if regressions:
                for r in regressions:
                    logger.warning(f"[REGRESSION] {r['engine_name']} degraded to {r['new_status']}: {r['message']}")
        except Exception as e:
            self.tasks_status["integrity_probe"]["status"] = f"ERROR: {e}"

    def _execute_derivatives_scanner(self, now: float):
        self.tasks_status["derivatives_scanner"]["last_run"] = now
        try:
            is_active, desc = is_derivatives_breakout_window()
            if is_active:
                from scripts.nifty_derivatives_breakout_alert import check_and_trigger_spot_index_breakout
                res = check_and_trigger_spot_index_breakout(check_market_window=False)
                self.tasks_status["derivatives_scanner"]["status"] = "ACTIVE (Evaluated)"
            else:
                self.tasks_status["derivatives_scanner"]["status"] = f"STANDBY ({desc})"
        except Exception as e:
            self.tasks_status["derivatives_scanner"]["status"] = f"ERROR: {e}"

    def _execute_morning_short_scanner(self, now: float):
        self.tasks_status["morning_short_scanner"]["last_run"] = now
        try:
            is_active, desc = is_morning_short_window()
            if is_active:
                from scripts.morning_short_scanner import run_morning_short_scan
                candidates = run_morning_short_scan()
                self.tasks_status["morning_short_scanner"]["status"] = f"ACTIVE ({len(candidates) if isinstance(candidates, list) else 0} candidates)"
            else:
                self.tasks_status["morning_short_scanner"]["status"] = f"STANDBY ({desc})"
        except Exception as e:
            self.tasks_status["morning_short_scanner"]["status"] = f"ERROR: {e}"

    def _execute_evening_pro_scanner(self, now: float):
        self.tasks_status["evening_pro_scanner"]["last_run"] = now
        try:
            is_active, desc = is_evening_pro_window()
            if is_active:
                from scripts.evening_pro_scanner import run_evening_pro_scan
                candidates = run_evening_pro_scan()
                self.tasks_status["evening_pro_scanner"]["status"] = f"ACTIVE ({len(candidates) if isinstance(candidates, list) else 0} candidates)"
            else:
                self.tasks_status["evening_pro_scanner"]["status"] = f"STANDBY ({desc})"
        except Exception as e:
            self.tasks_status["evening_pro_scanner"]["status"] = f"ERROR: {e}"

    def _execute_paper_trading(self, now: float):
        self.tasks_status["paper_trading"]["last_run"] = now
        try:
            from api.server import execute_paper_trading_strategy_step, get_zerodha_status
            if is_market_open():
                execute_paper_trading_strategy_step()
                self.tasks_status["paper_trading"]["status"] = "ACTIVE (Step executed)"
            else:
                self.tasks_status["paper_trading"]["status"] = "STANDBY (Market Closed)"
        except Exception as e:
            self.tasks_status["paper_trading"]["status"] = f"ERROR: {e}"

    def _execute_gtt_audit(self, now: float):
        self.tasks_status["gtt_integrity_audit"]["last_run"] = now
        try:
            from scripts.gtt_next_alert_integrity_monitor import audit_and_restore_next_gtt_alerts
            res = audit_and_restore_next_gtt_alerts(dry_run=False)
            self.tasks_status["gtt_integrity_audit"]["status"] = f"OK (Active: {res.get('active_next_alerts_count', 0)}, Restored: {res.get('restored_count', 0)})"
        except Exception as e:
            self.tasks_status["gtt_integrity_audit"]["status"] = f"ERROR: {e}"

    def _execute_race_cache_sync(self, now: float):
        self.tasks_status["race_cache_sync"]["last_run"] = now
        try:
            from scripts.sync_stock_returns_cache import sync_stock_returns_cache
            res = sync_stock_returns_cache()
            self.tasks_status["race_cache_sync"]["status"] = f"OK (Updated: {res.get('synced_count', 0)})"
        except Exception as e:
            self.tasks_status["race_cache_sync"]["status"] = f"ERROR: {e}"

    def _execute_token_check(self, now: float):
        self.tasks_status["zerodha_token_check"]["last_run"] = now
        try:
            from api.server import check_zerodha_connection_and_login
            check_zerodha_connection_and_login()
            self.tasks_status["zerodha_token_check"]["status"] = "OK"
        except Exception as e:
            self.tasks_status["zerodha_token_check"]["status"] = f"ERROR: {e}"

    def get_summary(self) -> Dict[str, Any]:
        """Returns live status of all scheduled background jobs."""
        return {
            "is_running": self.is_running,
            "tasks": self.tasks_status,
            "current_time_ist": get_now_ist().strftime("%Y-%m-%d %H:%M:%S IST"),
            "dual_stamp": format_dual_timezone_stamp()
        }


# Global singleton
master_scheduler = MasterMarketScheduler()
