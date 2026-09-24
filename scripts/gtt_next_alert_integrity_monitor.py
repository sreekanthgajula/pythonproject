"""
===============================================================================
ZERODHA GTT NEXT ALERT INTEGRITY MONITOR & AUTO-RECOVERY ENGINE
===============================================================================
Description:
    1. Audits all stock records across MongoDB collections ('monthly', 'weekly', 'daily').
    2. Fetches live GTT orders from Zerodha API via KiteConnect.
    3. Verifies whether every stock (especially triggered stocks) has its NEXT trailing
       GTT breakout alert actively set on Zerodha at the updated +1% trigger level.
    4. Automatically detects missing, expired, or triggered next alerts.
    5. Programmatically places the NEXT Zerodha GTT alert order (applying high-price
       qty=500 rules for stocks >= ₹5000 RS) and updates the database record.
===============================================================================
"""

import os
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from data_manager import DataManager
from scripts.zerodha_alert_manager import get_kite_client, set_zerodha_1pct_breakout_alert

load_dotenv(dotenv_path=project_root / ".env")
logger = logging.getLogger(__name__)

def audit_and_restore_next_gtt_alerts(dry_run: bool = False) -> dict:
    """
    Audits all tracked stocks across database tables and verifies if their NEXT GTT alert
    is active on Zerodha. Automatically places missing next GTT alerts.
    
    Returns:
        dict: Summary of audit results (total_tracked, active_gtts, restored_alerts, failed_alerts)
    """
    logger.info("[GTT INTEGRITY MONITOR] Starting Next Alert Audit across Zerodha & DB...")
    print(f"\n=======================================================")
    print(f" [GTT INTEGRITY MONITOR] ZERODHA GTT NEXT ALERT AUDIT")
    print(f"=======================================================")

    dm = DataManager()
    kite = get_kite_client()
    
    live_gtts_map = {}
    if kite:
        try:
            raw_gtts = kite.get_gtts()
            for g in raw_gtts:
                cond = g.get("condition", {})
                sym = (cond.get("tradingsymbol") or "").upper().replace(".NS", "").replace("-EQ", "").strip()
                status = (g.get("status") or "ACTIVE").upper()
                trig_val = cond.get("trigger_values", [0.0])[0] if cond.get("trigger_values") else 0.0
                g_id = g.get("id")
                
                if sym:
                    if sym not in live_gtts_map:
                        live_gtts_map[sym] = []
                    live_gtts_map[sym].append({
                        "id": g_id,
                        "status": status,
                        "trigger_price": trig_val,
                        "created_at": g.get("created_at")
                    })
            logger.info(f"[GTT INTEGRITY MONITOR] Fetched {len(raw_gtts)} live GTT orders from Zerodha for {len(live_gtts_map)} symbols.")
        except Exception as k_err:
            logger.warning(f"[GTT INTEGRITY MONITOR] Could not fetch live Zerodha GTTs: {k_err}")
    else:
        logger.warning("[GTT INTEGRITY MONITOR] Zerodha KiteConnect client unavailable. Audit running in local database verification mode.")

    total_tracked = 0
    active_count = 0
    restored_count = 0
    failed_count = 0
    restored_list = []

    ist_tz = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist_tz)

    for tf in ["monthly", "weekly", "daily"]:
        try:
            col = dm.db[tf]
            docs = list(col.find({}))
            print(f"\n--- Checking '{tf.upper()}' Collection ({len(docs)} stocks) ---")
            
            for doc in docs:
                sym = (doc.get("symbol") or "").upper().replace(".NS", "").replace("-EQ", "").strip()
                if not sym:
                    continue
                    
                total_tracked += 1
                recent_high = float(doc.get("recent_high") or 0.0)
                expected_trigger = float(doc.get("alert_trigger_price") or (recent_high * 1.01))
                alert_count = int(doc.get("alert_count") or 0)
                current_status = str(doc.get("alert_status") or "LOCAL_ALERT_SET")
                gtt_id = doc.get("gtt_id")
                
                # Check live Zerodha GTT status for this symbol
                sym_gtts = live_gtts_map.get(sym, [])
                active_gtt = next((g for g in sym_gtts if g["status"] == "ACTIVE"), None)

                # Next alert is valid if an active GTT exists on Zerodha for this symbol
                if active_gtt:
                    active_count += 1
                    print(f"  [ACTIVE] {sym:<12} | Status: ACTIVE (Zerodha GTT #{active_gtt['id']}) | Trigger: INR {active_gtt['trigger_price']:.2f}")
                else:
                    # Next alert is MISSING or TRIGGERED/DISABLED! Auto-restore required
                    print(f"  [MISSING] {sym:<12} | NEXT ALERT MISSING on Zerodha! (Last Status: {current_status}, Alerts Triggered: {alert_count})")
                    
                    if not dry_run:
                        print(f"     [AUTO-RESTORE] Placing NEXT Zerodha GTT breakout alert for {sym} at +1% level...")
                        restore_res = set_zerodha_1pct_breakout_alert(sym, timeframe=tf, override_recent_high=recent_high if recent_high > 0 else None)
                        
                        if restore_res.get("gtt_id") and "ZERODHA_GTT_ACTIVE" in restore_res.get("status", ""):
                            restored_count += 1
                            # Update alert_count and stamp last_alerted_at to current timestamp for Today's Race
                            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                            col.update_one(
                                {"symbol": sym},
                                {
                                    "$inc": {"alert_count": 1, "today_alert_count": 1},
                                    "$set": {"last_alerted_at": now_utc}
                                }
                            )
                            # Automatically trigger Darvas Box Scanner on GTT alerted stock
                            try:
                                from scripts.darvas_box_scanner import scan_and_save_darvas_stock
                                scan_and_save_darvas_stock(sym, timeframe=tf)
                            except Exception as d_err:
                                logger.warning(f"Darvas scan notice for {sym}: {d_err}")
                            restored_list.append({
                                "symbol": sym,
                                "timeframe": tf,
                                "gtt_id": restore_res.get("gtt_id"),
                                "trigger_price": restore_res.get("alert_trigger_price"),
                                "quantity": restore_res.get("gtt_quantity")
                            })
                            print(f"     [RESTORED] GTT #{restore_res.get('gtt_id')} set for {sym} (Qty: {restore_res.get('gtt_quantity')}) at INR {restore_res.get('alert_trigger_price')}")
                        else:
                            failed_count += 1
                            print(f"     [FAILED RESTORE] {sym}: {restore_res.get('status')}")
                    else:
                        restored_count += 1

        except Exception as tf_err:
            logger.error(f"[GTT INTEGRITY MONITOR] Error auditing '{tf}' collection: {tf_err}")

    summary = {
        "status": "success",
        "timestamp_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        "total_tracked": total_tracked,
        "active_gtts": active_count,
        "restored_next_alerts": restored_count,
        "failed_restorations": failed_count,
        "restored_items": restored_list
    }

    print(f"\n=======================================================")
    print(f" AUDIT COMPLETE SUMMARY")
    print(f" Total Tracked Stocks   : {total_tracked}")
    print(f" Active Zerodha GTTs    : {active_count}")
    print(f" Next Alerts Restored   : {restored_count}")
    print(f" Failed Restorations    : {failed_count}")
    print(f"=======================================================\n")

    return summary

def run_continuous_integrity_monitor(interval_seconds: int = 60):
    """
    Runs a continuous background loop auditing and restoring next GTT alerts every interval_seconds.
    """
    logger.info(f"[GTT INTEGRITY MONITOR] Starting continuous monitoring daemon loop (Audit Interval: {interval_seconds}s)...")
    print(f"🚀 GTT Next Alert Integrity Monitoring Daemon active. Checking every {interval_seconds} seconds...")
    
    while True:
        try:
            audit_and_restore_next_gtt_alerts(dry_run=False)
        except Exception as e:
            logger.error(f"[GTT INTEGRITY MONITOR] Error during periodic audit cycle: {e}")
            
        time.sleep(interval_seconds)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Zerodha GTT Next Alert Integrity Monitor")
    parser.add_argument("--daemon", action="store_true", help="Run in continuous monitoring daemon mode")
    parser.add_argument("--interval", type=int, default=60, help="Audit interval in seconds for daemon mode")
    parser.add_argument("--dry-run", action="store_true", help="Audit without placing new orders")
    args = parser.parse_args()

    if args.daemon:
        run_continuous_integrity_monitor(interval_seconds=args.interval)
    else:
        audit_and_restore_next_gtt_alerts(dry_run=args.dry_run)
