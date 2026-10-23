"""
===============================================================================
TRADING AGENTS - TIMEZONE & MARKET TIMING ENGINE (IST vs SYDNEY)
===============================================================================
Handles Indian Stock Market (NSE/BSE) trading sessions synchronized with
traders operating from Sydney, Australia (AEST/AEDT).

Indian Market Timings (IST - Asia/Kolkata, UTC+05:30):
  - Normal Trading Hours: 09:15 AM - 03:30 PM IST (Mon - Fri)
  - Morning Exhaustion & VWAP Reversion Scanner Window:
      09:15 AM - 11:30 AM IST
      (Sydney: ~02:45 PM - 05:00 PM AEDT / ~01:45 PM - 04:00 PM AEST)
  - Evening Professional Buying & BTST Accumulation Scanner Window:
      02:30 PM - 03:30 PM IST (14:30 - 15:30 IST)
      (Sydney: ~08:00 PM - 09:00 PM AEDT / ~07:00 PM - 08:00 PM AEST)
===============================================================================
"""

import zoneinfo
from datetime import datetime, time, timezone, timedelta
from typing import Optional, Tuple, Dict, Any

TZ_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
TZ_SYDNEY = zoneinfo.ZoneInfo("Australia/Sydney")


def get_now_ist() -> datetime:
    """Returns the current timezone-aware datetime in Indian Standard Time (IST)."""
    return datetime.now(TZ_IST)


def get_now_sydney() -> datetime:
    """Returns the current timezone-aware datetime in Sydney, Australia (AEST/AEDT)."""
    return datetime.now(TZ_SYDNEY)


def format_dual_timezone_stamp(dt_ist: Optional[datetime] = None) -> str:
    """
    Returns a formatted string showing both IST and Sydney times.
    Example: 'IST: 09:45 AM | Sydney: 03:15 PM AEDT'
    """
    if dt_ist is None:
        dt_ist = get_now_ist()
    dt_syd = dt_ist.astimezone(TZ_SYDNEY)
    return (
        f"IST: {dt_ist.strftime('%I:%M %p')} ({dt_ist.strftime('%d-%b-%Y')}) | "
        f"Sydney: {dt_syd.strftime('%I:%M %p %Z')} ({dt_syd.strftime('%d-%b-%Y')})"
    )


def is_trading_day(dt_ist: Optional[datetime] = None) -> bool:
    """
    Returns True if the given IST datetime falls on an Indian market trading day (Monday - Friday).
    """
    if dt_ist is None:
        dt_ist = get_now_ist()
    return dt_ist.weekday() < 5  # 0=Monday, ..., 4=Friday


def is_market_open(dt_ist: Optional[datetime] = None) -> bool:
    """
    Returns True if the Indian market is currently open for regular trading (09:15 - 15:30 IST on Mon-Fri).
    """
    if dt_ist is None:
        dt_ist = get_now_ist()

    if not is_trading_day(dt_ist):
        return False

    t = dt_ist.time()
    return time(9, 15) <= t <= time(15, 30)


def is_morning_short_window(dt_ist: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    Checks if the current moment is inside the Morning Exhaustion & VWAP Reversion scanner window.
    
    Window: Monday - Friday, 09:15 AM - 11:30 AM IST
    Sydney: ~02:45 PM - 05:00 PM AEDT (~01:45 PM - 04:00 PM AEST)
    
    Returns:
        (is_active: bool, description: str)
    """
    if dt_ist is None:
        dt_ist = get_now_ist()

    dt_syd = dt_ist.astimezone(TZ_SYDNEY)
    syd_tz_name = dt_syd.strftime("%Z")
    
    if not is_trading_day(dt_ist):
        day_name = dt_ist.strftime("%A")
        return False, f"Weekend ({day_name}) - Indian stock market closed. Next session on Monday."

    t = dt_ist.time()
    morning_start = time(9, 15)
    morning_end = time(11, 30)

    if morning_start <= t <= morning_end:
        return True, (
            f"Active Morning Window (09:15 - 11:30 IST) | "
            f"Current: {dt_ist.strftime('%I:%M %p')} IST / {dt_syd.strftime('%I:%M %p')} {syd_tz_name}"
        )
    elif t < morning_start:
        return False, (
            f"Pre-Market (Market opens at 09:15 AM IST) | "
            f"Current: {dt_ist.strftime('%I:%M %p')} IST / {dt_syd.strftime('%I:%M %p')} {syd_tz_name}"
        )
    else:
        return False, (
            f"Morning Window Ended (Active window was 09:15 - 11:30 IST) | "
            f"Current: {dt_ist.strftime('%I:%M %p')} IST / {dt_syd.strftime('%I:%M %p')} {syd_tz_name}"
        )


def is_evening_pro_window(dt_ist: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    Checks if the current moment is inside the Evening Professional Buying (BTST) scanner window.
    
    Window: Monday - Friday, 02:30 PM - 03:30 PM IST (14:30 - 15:30 IST)
    Sydney: ~08:00 PM - 09:00 PM AEDT (~07:00 PM - 08:00 PM AEST)
    
    Returns:
        (is_active: bool, description: str)
    """
    if dt_ist is None:
        dt_ist = get_now_ist()

    dt_syd = dt_ist.astimezone(TZ_SYDNEY)
    syd_tz_name = dt_syd.strftime("%Z")

    if not is_trading_day(dt_ist):
        day_name = dt_ist.strftime("%A")
        return False, f"Weekend ({day_name}) - Indian stock market closed. Next session on Monday."

    t = dt_ist.time()
    evening_start = time(14, 30)
    evening_end = time(15, 30)

    if evening_start <= t <= evening_end:
        return True, (
            f"Active Evening BTST Window (02:30 PM - 03:30 PM IST) | "
            f"Current: {dt_ist.strftime('%I:%M %p')} IST / {dt_syd.strftime('%I:%M %p')} {syd_tz_name}"
        )
    elif t < evening_start:
        return False, (
            f"Before Evening BTST Window (Opens at 02:30 PM IST) | "
            f"Current: {dt_ist.strftime('%I:%M %p')} IST / {dt_syd.strftime('%I:%M %p')} {syd_tz_name}"
        )
    else:
        return False, (
            f"Market Closed for the day (03:30 PM IST) | "
            f"Current: {dt_ist.strftime('%I:%M %p')} IST / {dt_syd.strftime('%I:%M %p')} {syd_tz_name}"
        )


def get_market_timing_summary() -> Dict[str, Any]:
    """
    Comprehensive snapshot of market timings for both IST and Sydney,
    including the active status of the Morning Short and Evening Pro scanners.
    """
    now_ist = get_now_ist()
    now_syd = now_ist.astimezone(TZ_SYDNEY)
    syd_tz_name = now_syd.strftime("%Z")

    m_active, m_status = is_morning_short_window(now_ist)
    e_active, e_status = is_evening_pro_window(now_ist)
    trading_day = is_trading_day(now_ist)
    market_open = is_market_open(now_ist)

    # Compute approximate Sydney window representations
    # 09:15 IST and 11:30 IST converted to Sydney today
    m_start_ist = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    m_end_ist = now_ist.replace(hour=11, minute=30, second=0, microsecond=0)
    e_start_ist = now_ist.replace(hour=14, minute=30, second=0, microsecond=0)
    e_end_ist = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)

    m_start_syd = m_start_ist.astimezone(TZ_SYDNEY)
    m_end_syd = m_end_ist.astimezone(TZ_SYDNEY)
    e_start_syd = e_start_ist.astimezone(TZ_SYDNEY)
    e_end_syd = e_end_ist.astimezone(TZ_SYDNEY)

    return {
        "status": "success",
        "current_time": {
            "ist": now_ist.strftime("%Y-%m-%d %I:%M:%S %p IST"),
            "sydney": now_syd.strftime(f"%Y-%m-%d %I:%M:%S %p {syd_tz_name}"),
            "iso_ist": now_ist.isoformat(),
            "iso_sydney": now_syd.isoformat(),
            "user_location": "Sydney, Australia",
            "market_location": "NSE/BSE (Mumbai, India)"
        },
        "is_trading_day": trading_day,
        "is_market_open": market_open,
        "morning_short_scanner": {
            "is_active_now": m_active,
            "status_message": m_status,
            "schedule_ist": "09:15 AM - 11:30 AM IST (Mon-Fri)",
            "schedule_sydney": f"{m_start_syd.strftime('%I:%M %p')} - {m_end_syd.strftime('%I:%M %p')} {syd_tz_name} (Mon-Fri)",
            "frequency": "Every 5 minutes during active window"
        },
        "evening_pro_scanner": {
            "is_active_now": e_active,
            "status_message": e_status,
            "schedule_ist": "02:30 PM - 03:30 PM IST (Mon-Fri)",
            "schedule_sydney": f"{e_start_syd.strftime('%I:%M %p')} - {e_end_syd.strftime('%I:%M %p')} {syd_tz_name} (Mon-Fri)",
            "frequency": "Every 5 minutes during active window"
        }
    }
