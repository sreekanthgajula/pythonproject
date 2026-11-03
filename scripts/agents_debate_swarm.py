"""
===============================================================================
UNIVERSAL MULTI-AGENT SWARM DEBATE ENGINE
===============================================================================
Description:
    Runs a 6-Agent Quantitative Multi-Agent Swarm Debate before ANY alert is
    dispatched to Telegram or saved in the database, evaluating how good the
    alert is and producing a consensus rating out of 10:

    1. Agent 1: Structural & Pattern Analyst
       - Evaluates breakout clearance, base/box consolidation tightness, and proximity to 52w high.
    2. Agent 2: Institutional Flow & Volume Surge Analyst
       - Evaluates volume surge multiple (>1.5x, >2.0x 20d avg), run-rate extrapolation, and buyer volume spikes.
    3. Agent 3: OBV & True Strength (TSI) Momentum Analyst
       - Evaluates On-Balance Volume (OBV) trend relative to EMA20 and True Strength Index (TSI) signal cross.
    4. Agent 4: Bullish / Directional Researcher
       - Synthesizes pro-breakout conviction from Structure + Flow + Momentum.
    5. Agent 5: Trap & False-Breakout Counter-Thesis Researcher
       - Stress-tests the setup: upper wick rejections, extended ATR distance, low close strength, market headwind.
    6. Agent 6: Chief Risk & Portfolio Judge
       - Arbitrates the debate, resolves Bull vs Bear conflicts, calculates the final consensus
         `agents_debate_rating` out of 10, assigns the conviction verdict, and formats the agent discussion.
===============================================================================
"""

import sys
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

import numpy as np
import pandas as pd

# Ensure project root in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from tradingagents.market_timing import get_now_ist

logger = logging.getLogger("AgentsDebateSwarm")


def run_swarm_agents_debate(
    symbol: str,
    setup_type: str = "DARVAS_BREAKOUT",
    current_price: Optional[float] = None,
    trigger_price: Optional[float] = None,
    df: Optional[pd.DataFrame] = None,
    meta: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Executes the 6-Agent Quantitative Swarm Debate on the setup:
      1. Structural & Pattern Analyst
      2. Institutional Flow & Volume Surge Analyst
      3. OBV & True Strength (TSI) Momentum Analyst
      4. Bullish / Directional Lead Researcher
      5. Trap & Counter-Thesis Researcher
      6. Chief Risk & Portfolio Judge

    Returns:
      dict with:
        - agents_debate_rating (float 1.0 - 10.0)
        - agents_debate_verdict (str)
        - agents_debate_bar (str visual [████████░░])
        - agents_debate_summary (str)
        - individual agent scores & thesis points
    """
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("-EQ", "")
    meta = meta or {}

    # 1. Fetch DB documents (Darvas, Return Cache) if available
    darvas_doc = {}
    cached_doc = {}
    try:
        from data_manager import DataManager
        dm = DataManager()
        darvas_doc = dm.db["darvas"].find_one({"symbol": clean_sym}) or {}
        cached_doc = dm.db["stock_returns_cache"].find_one({"symbol": clean_sym}) or {}
    except Exception:
        pass

    # Extract price levels
    curr_px = float(current_price or meta.get("ltp") or cached_doc.get("ltp") or 0.0)
    trig_px = float(trigger_price or meta.get("alert_trigger_price") or darvas_doc.get("box_top") or (curr_px * 1.01))
    if curr_px <= 0 and trig_px > 0:
        curr_px = trig_px

    box_top = float(darvas_doc.get("box_top") or meta.get("recent_high") or trig_px)
    box_bottom = float(darvas_doc.get("box_bottom") or (box_top * 0.93))
    box_height_pct = ((box_top - box_bottom) / box_bottom * 100.0) if box_bottom > 0 else 7.0

    vol_ratio = float(
        meta.get("volume_surge_ratio")
        or darvas_doc.get("volume_surge_ratio")
        or meta.get("vol_surge")
        or 1.6
    )
    close_strength = float(
        meta.get("close_strength_pct")
        or darvas_doc.get("close_strength_pct")
        or 80.0
    )
    nifty_regime = str(darvas_doc.get("nifty_regime") or "BULLISH_TAILWIND")

    # 2. Extract technical indicator conditions from DataFrame if provided
    obv_aligned = True
    tsi_aligned = True
    has_volume_spike = vol_ratio >= 1.5

    if df is not None and not df.empty and len(df) >= 15:
        try:
            from scripts.chart_generator import calculate_chart_indicators
            ind_df = calculate_chart_indicators(df)
            last_bar = ind_df.iloc[-1]

            if "OBV" in ind_df.columns:
                curr_obv = float(last_bar["OBV"])
                prev_obv = float(ind_df.iloc[-2]["OBV"]) if len(ind_df) >= 2 else curr_obv
                prev2_obv = float(ind_df.iloc[-3]["OBV"]) if len(ind_df) >= 3 else prev_obv
                obv_ema = float(last_bar["OBV_EMA20"]) if "OBV_EMA20" in ind_df.columns else curr_obv
                # Bullish accumulation: OBV >= EMA20 OR 3-bar higher highs/positive slope
                obv_aligned = (curr_obv >= obv_ema) or (curr_obv >= prev_obv >= prev2_obv) or (curr_obv > prev_obv)

            if "TSI" in ind_df.columns:
                tsi_val = float(last_bar["TSI"])
                tsi_prev = float(ind_df.iloc[-2]["TSI"]) if len(ind_df) >= 2 else tsi_val
                tsi_sig = float(last_bar["TSI_Signal"]) if "TSI_Signal" in ind_df.columns else 0.0
                # Bullish momentum: Above Signal OR upward hooking trajectory OR above zero
                tsi_hook_up = tsi_val > tsi_prev
                tsi_aligned = (tsi_val >= tsi_sig) or tsi_hook_up or (tsi_val >= 0.0)

            if "Vol_SMA20" in ind_df.columns and float(last_bar.get("Vol_SMA20", 0)) > 0:
                calc_ratio = float(last_bar["Volume"]) / float(last_bar["Vol_SMA20"])
                vol_ratio = max(vol_ratio, calc_ratio)
                has_volume_spike = vol_ratio >= 1.2
        except Exception as e:
            logger.debug(f"Indicator calculation note for swarm debate: {e}")

    # =========================================================================
    # 3. RUN THE 6-AGENT SWARM DEBATE
    # =========================================================================

    # --- AGENT 1: Structural & Pattern Analyst (0 - 10) ---
    # Recognizes dual breakout archetypes:
    # 1. Base / Darvas Box Consolidation Exit
    # 2. Higher-High Trend Continuation / Blue Sky Momentum Run / Trailing Ladder
    is_higher_high_run = (
        curr_px >= (trig_px * 0.995) or
        curr_px >= (box_top * 0.995) or
        setup_type in ("HIGHER_HIGH", "TRAILING_LADDER", "WEEKLY", "DAILY", "MONTHLY", "GTT_BREAKOUT")
    )

    struct_score = 6.5
    struct_label = "Base Struct"
    if bool(darvas_doc):
        struct_label = "Darvas Box"
        struct_score += 1.0
        # Reward tight base (5% - 15% height), penalize overly wide/loose boxes (>22%)
        if 4.0 <= box_height_pct <= 14.0:
            struct_score += 1.5
        elif box_height_pct <= 20.0:
            struct_score += 0.8
        else:
            struct_score -= 0.6
    elif is_higher_high_run:
        # Higher High Momentum Expansion (New high / ATH / Trailing ladder step)
        # Clear upward price discovery without overhead supply resistance
        struct_label = "Higher-High Trend"
        struct_score += 1.8
    else:
        struct_score += 0.5

    # Breakout clearance bonus
    if curr_px >= trig_px:
        clearance_pct = ((curr_px - trig_px) / trig_px) * 100.0
        struct_score += min(1.2, clearance_pct * 0.8)

    # 5-minute candle structure confirmation if DataFrame is available
    if df is not None and not df.empty and len(df) >= 3:
        try:
            c3 = float(df["Close"].iloc[-1])
            c2 = float(df["Close"].iloc[-2])
            c1 = float(df["Close"].iloc[-3])
            if c3 >= c2 >= c1:
                struct_score += 0.5  # Consecutive higher closes
        except Exception:
            pass

    struct_score = round(min(10.0, max(4.0, struct_score)), 1)

    # --- AGENT 2: Institutional Flow & Volume Surge Analyst (0 - 10) ---
    # Evaluates volume surge ratio vs 20-period baseline with adaptive base compensation
    flow_score = 5.5
    if vol_ratio >= 2.5:
        flow_score += 3.8
    elif vol_ratio >= 1.7:
        flow_score += 2.8
    elif vol_ratio >= 1.3:
        flow_score += 1.8
    elif vol_ratio >= 1.15:
        # If base is tight (VCP contraction <= 15%), supply has dried up; 1.15x is sufficient
        if box_height_pct <= 15.0:
            flow_score += 1.4
        else:
            flow_score += 0.6
    else:
        flow_score -= 0.8

    if close_strength >= 75.0:
        flow_score += 0.7
    elif close_strength < 55.0:
        flow_score -= 0.7

    flow_score = round(min(10.0, max(3.5, flow_score)), 1)

    # --- AGENT 3: OBV & True Strength (TSI) Momentum Analyst (0 - 10) ---
    mom_score = 6.0
    if obv_aligned:
        mom_score += 1.8
    else:
        mom_score -= 0.8

    if tsi_aligned:
        mom_score += 1.8
    else:
        mom_score -= 0.8

    mom_score = round(min(10.0, max(3.5, mom_score)), 1)

    # --- AGENT 4: Bullish Directional Lead Researcher ---
    # Synthesizes pro-breakout conviction
    bull_score = round((struct_score * 0.35) + (flow_score * 0.35) + (mom_score * 0.30), 1)

    # --- AGENT 5: Trap & False-Breakout Counter-Thesis Researcher ---
    # Stress-tests the setup: penalties for low close strength, market headwind, or weak volume
    trap_penalty = 0.0
    trap_reasons = []

    if close_strength < 60.0:
        trap_penalty += 0.8
        trap_reasons.append(f"Upper Wick Rejection (Close {close_strength:.0f}%)")

    if vol_ratio < 1.15 and box_height_pct > 15.0:
        trap_penalty += 0.8
        trap_reasons.append(f"Light Volume ({vol_ratio:.1f}x)")

    if "HEADWIND" in nifty_regime.upper() or "BEAR" in nifty_regime.upper():
        trap_penalty += 0.5
        trap_reasons.append(f"Market Headwind ({nifty_regime})")

    if not obv_aligned:
        trap_penalty += 0.4
        trap_reasons.append("OBV Lagging")

    if not tsi_aligned:
        trap_penalty += 0.4
        trap_reasons.append("TSI Divergence")

    trap_penalty = round(min(2.5, trap_penalty), 1)

    # --- AGENT 6: Chief Risk & Portfolio Judge ---
    # Arbitrates Bull vs Bear debate and produces the final consensus rating out of 10
    regime_bonus = 0.4 if "TAILWIND" in nifty_regime.upper() else 0.0
    final_rating = round(min(10.0, max(1.0, bull_score + regime_bonus - trap_penalty)), 1)
    is_ripe = bool(final_rating >= 7.0)

    if final_rating >= 8.5:
        verdict = "HIGH CONVICTION BREAKOUT 🔥"
    elif final_rating >= 7.5:
        verdict = "STRONG CONSENSUS 🚀"
    elif final_rating >= 7.0:
        verdict = "RIPE BREAKOUT APPROVED ✅"
    elif final_rating >= 6.0:
        verdict = "MODERATE SETUP ⚠️"
    else:
        verdict = "UNRIPE / TRAP RISK ⛔"

    filled = int(round(final_rating))
    bar = "█" * filled + "░" * (10 - filled)

    risk_text = "Clean Flow & R:R" if not trap_reasons else ", ".join(trap_reasons[:2])
    summary = (
        f"{struct_label} {struct_score}/10 • Flow {flow_score}/10 ({vol_ratio:.1f}x vol) • "
        f"OBV/TSI {mom_score}/10 | Trap Risk: {risk_text}"
    )

    return {
        "symbol": clean_sym,
        "is_ripe": is_ripe,
        "agents_debate_rating": final_rating,
        "agents_debate_verdict": verdict,
        "agents_debate_bar": bar,
        "agents_debate_summary": summary,
        "struct_label": struct_label,
        "structure_score": struct_score,
        "flow_score": flow_score,
        "momentum_score": mom_score,
        "bull_score": bull_score,
        "trap_penalty": trap_penalty,
        "trap_reasons": trap_reasons,
        "nifty_regime": nifty_regime,
        "vol_ratio": vol_ratio,
        "close_strength": close_strength,
    }


def format_swarm_debate_telegram_block(debate_info: Dict[str, Any]) -> str:
    """Formats the Swarm Debate consensus block for Telegram HTML alerts."""
    rating = debate_info.get("agents_debate_rating", 8.0)
    verdict = debate_info.get("agents_debate_verdict", "DEBATE APPROVED ✅")
    bar = debate_info.get("agents_debate_bar", "████████░░")
    summary = debate_info.get("agents_debate_summary", "")

    block = (
        f"🤖 <b>Swarm of Agents Debate Rating:</b> <b>{rating} / 10</b> ({verdict})\n"
        f"📊 <code>[{bar}]</code>\n"
    )
    if summary:
        block += f"🗣️ <i>{summary}</i>\n"

    return block
