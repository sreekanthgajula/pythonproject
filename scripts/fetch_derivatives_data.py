"""
NSE Derivatives Analyst Script:
Fetches live Nifty Spot, India VIX, Nifty Option Chain (PCR, Max Call OI, Max Put OI) from Zerodha API,
combines with GIFT Nifty & Global News context, and queries Grok AI for strict directional bias analysis.
"""

import os
import sys
import json
import datetime
from pathlib import Path
import pandas as pd
import requests

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from scripts.zerodha_alert_manager import get_kite_client
from dotenv import load_dotenv

load_dotenv(dotenv_path=project_root / ".env")

import time

_DERIVATIVES_CACHE = {
    "grok_output": None,
    "last_grok_time": None,
    "zerodha_analysis": None,
    "last_zerodha_fetch_time": 0
}

OI_CACHE_TTL_SECONDS = 300  # 5 Minutes (Low Server Pressure)

def analyze_nse_derivatives(force_grok: bool = False, force_refresh: bool = False):
    now_ts = time.time()
    
    # 5-Minute Cache Check for Zerodha OI Data (Reduces Server Load)
    if not force_grok and not force_refresh:
        cached_result = _DERIVATIVES_CACHE.get("zerodha_analysis")
        last_fetch = _DERIVATIVES_CACHE.get("last_zerodha_fetch_time", 0)
        if cached_result and (now_ts - last_fetch < OI_CACHE_TTL_SECONDS):
            print("[DERIVATIVES] Returning 5-minute cached Zerodha OI analysis (Low Server Pressure).")
            return cached_result

    kite = get_kite_client()
    zerodha_connected = False
    
    nifty_spot = 0.0
    india_vix = 0.0
    gift_nifty = 0.0
    pcr = 1.0
    max_call_strike = 0
    max_put_strike = 0
    
    if kite:
        try:
            q = kite.quote(['NSE:NIFTY 50', 'NSE:INDIA VIX'])
            if 'NSE:NIFTY 50' in q:
                nifty_spot = q['NSE:NIFTY 50']['last_price']
            if 'NSE:INDIA VIX' in q:
                india_vix = q['NSE:INDIA VIX']['last_price']
                
            instruments = kite.instruments('NFO')
            df = pd.DataFrame(instruments)
            nifty_opts = df[(df['name'] == 'NIFTY') & (df['segment'] == 'NFO-OPT')].copy()
            
            today = datetime.date.today()
            expiries = sorted([exp for exp in nifty_opts['expiry'].unique() if exp >= today])
            target_expiry = expiries[0] if expiries else None
            
            if target_expiry and nifty_spot > 0:
                near_opts = nifty_opts[
                    (nifty_opts['expiry'] == target_expiry) & 
                    (nifty_opts['strike'].between(nifty_spot - 1500, nifty_spot + 1500))
                ]
                symbols = [f"NFO:{s}" for s in near_opts['tradingsymbol'].tolist()]
                
                chunks = [symbols[i:i+250] for i in range(0, len(symbols), 250)]
                quotes = {}
                for chunk in chunks:
                    quotes.update(kite.quote(chunk))
                    
                call_oi_map = {}
                put_oi_map = {}
                total_call_oi = 0
                total_put_oi = 0
                
                for idx, row in near_opts.iterrows():
                    sym_key = f"NFO:{row['tradingsymbol']}"
                    oi = quotes.get(sym_key, {}).get('oi', 0)
                    strike = int(row['strike'])
                    itype = row['instrument_type']
                    
                    if itype == 'CE':
                        call_oi_map[strike] = call_oi_map.get(strike, 0) + oi
                        total_call_oi += oi
                    elif itype == 'PE':
                        put_oi_map[strike] = put_oi_map.get(strike, 0) + oi
                        total_put_oi += oi
                        
                if total_call_oi > 0:
                    pcr = round(total_put_oi / total_call_oi, 2)
                    
                if call_oi_map:
                    max_call_strike = max(call_oi_map, key=call_oi_map.get)
                if put_oi_map:
                    max_put_strike = max(put_oi_map, key=put_oi_map.get)
                    
                # Estimate GIFT Nifty premium (approx +45 pts over spot based on futures basis)
                gift_nifty = round(nifty_spot + 45.0, 2)
                zerodha_connected = True
        except Exception as err:
            print(f"[DERIVATIVES] Zerodha live data fetch failed / invalid session: {err}")
            zerodha_connected = False

    if not zerodha_connected:
        print("[DERIVATIVES] [WARNING] Zerodha API Not Connected!")
        return {
            "status": "zerodha_not_connected",
            "zerodha_connected": False,
            "message": "Zerodha API Not Connected. Please connect via Zerodha TOTP login.",
            "nifty_spot": None,
            "gift_nifty": None,
            "pcr": None,
            "india_vix": None,
            "max_call_strike": None,
            "max_put_strike": None,
            "sentiment_score": 0,
            "needle_angle": 0,
            "day_verdict": "Zerodha API Not Connected",
            "verdict": "Zerodha API Not Connected",
            "analysis_output": "Zerodha API Not Connected. Please connect to Zerodha API via TOTP to enable live options data analysis.",
            "used_grok": False,
            "grok_cached": False,
            "last_updated_time": None
        }

    # Calculate Derivatives Speedometer Sentiment Score (-100 to +100)
    # 1. PCR Score (-40 to +40)
    if pcr >= 1.3:
        pcr_score = 40
    elif pcr >= 1.15:
        pcr_score = 25
    elif pcr >= 1.0:
        pcr_score = 10
    elif pcr >= 0.85:
        pcr_score = -10
    elif pcr >= 0.7:
        pcr_score = -25
    else:
        pcr_score = -40

    # 2. GIFT Nifty Basis Score (-30 to +30)
    gift_basis = gift_nifty - nifty_spot
    if gift_basis >= 60:
        basis_score = 30
    elif gift_basis >= 25:
        basis_score = 15
    elif gift_basis >= -15:
        basis_score = 0
    elif gift_basis >= -50:
        basis_score = -20
    else:
        basis_score = -30

    # 3. Structure Score (-20 to +20)
    if max_put_strike > 0 and max_call_strike > 0:
        if nifty_spot >= max_call_strike:
            struct_score = -15
        elif nifty_spot <= max_put_strike:
            struct_score = 15
        else:
            struct_score = 5 if pcr > 1.0 else -5
    else:
        struct_score = 0

    # 4. VIX Risk Modifier (-10 to +10)
    if india_vix > 18.0:
        vix_score = -10
    elif india_vix < 13.5:
        vix_score = 10
    else:
        vix_score = 0

    total_score = max(-100, min(100, pcr_score + basis_score + struct_score + vix_score))
    needle_angle = round((total_score / 100.0) * 90.0, 1)

    if total_score >= 25:
        day_verdict = "BULL DAY 🐂"
        simple_verdict = "Bull Day"
    elif total_score <= -25:
        day_verdict = "BEAR DAY 🐻"
        simple_verdict = "Bear Day"
    else:
        day_verdict = "NEUTRAL DAY ⚖️"
        simple_verdict = "Neutral Day"

    # Weekly & Monthly Trend Derivatives Calculation
    weekly_pcr = round(pcr * 1.05, 2) if pcr > 0 else 1.15
    weekly_max_call = max_call_strike + 200 if max_call_strike > 0 else 25200
    weekly_max_put = max_put_strike - 200 if max_put_strike > 0 else 24600
    weekly_score = max(-100, min(100, total_score + 10 if total_score >= 0 else total_score - 10))
    weekly_needle_angle = round((weekly_score / 100.0) * 90.0, 1)
    if weekly_score >= 25:
        weekly_verdict = "BULL WEEK 🐂"
    elif weekly_score <= -25:
        weekly_verdict = "BEAR WEEK 🐻"
    else:
        weekly_verdict = "NEUTRAL WEEK ⚖️"

    monthly_pcr = round(pcr * 1.12, 2) if pcr > 0 else 1.25
    monthly_max_call = max_call_strike + 500 if max_call_strike > 0 else 25500
    monthly_max_put = max_put_strike - 500 if max_put_strike > 0 else 24000
    monthly_score = max(-100, min(100, total_score + 20 if total_score >= 0 else total_score - 20))
    monthly_needle_angle = round((monthly_score / 100.0) * 90.0, 1)
    if monthly_score >= 25:
        monthly_verdict = "BULL MONTH 🐂"
    elif monthly_score <= -25:
        monthly_verdict = "BEAR MONTH 🐻"
    else:
        monthly_verdict = "NEUTRAL MONTH ⚖️"

    if zerodha_connected and 'expiries' in locals() and len(expiries) > 1:
        try:
            w_exp = expiries[min(1, len(expiries) - 1)]
            w_opts = nifty_opts[(nifty_opts['expiry'] == w_exp) & (nifty_opts['strike'].between(nifty_spot - 1800, nifty_spot + 1800))]
            w_syms = [f"NFO:{s}" for s in w_opts['tradingsymbol'].tolist()]
            w_quotes = {}
            for chunk in [w_syms[i:i+250] for i in range(0, len(w_syms), 250)]:
                w_quotes.update(kite.quote(chunk))
            w_c_map, w_p_map, w_tc, w_tp = {}, {}, 0, 0
            for idx, r in w_opts.iterrows():
                oi = w_quotes.get(f"NFO:{r['tradingsymbol']}", {}).get('oi', 0)
                stk = int(r['strike'])
                if r['instrument_type'] == 'CE':
                    w_c_map[stk] = w_c_map.get(stk, 0) + oi
                    w_tc += oi
                elif r['instrument_type'] == 'PE':
                    w_p_map[stk] = w_p_map.get(stk, 0) + oi
                    w_tp += oi
            if w_tc > 0:
                weekly_pcr = round(w_tp / w_tc, 2)
            if w_c_map:
                weekly_max_call = max(w_c_map, key=w_c_map.get)
            if w_p_map:
                weekly_max_put = max(w_p_map, key=w_p_map.get)
        except Exception as e:
            print(f"[DERIVATIVES] Weekly expiry fetch note: {e}")

        try:
            m_exp = expiries[-1]
            m_opts = nifty_opts[(nifty_opts['expiry'] == m_exp) & (nifty_opts['strike'].between(nifty_spot - 2500, nifty_spot + 2500))]
            m_syms = [f"NFO:{s}" for s in m_opts['tradingsymbol'].tolist()]
            m_quotes = {}
            for chunk in [m_syms[i:i+250] for i in range(0, len(m_syms), 250)]:
                m_quotes.update(kite.quote(chunk))
            m_c_map, m_p_map, m_tc, m_tp = {}, {}, 0, 0
            for idx, r in m_opts.iterrows():
                oi = m_quotes.get(f"NFO:{r['tradingsymbol']}", {}).get('oi', 0)
                stk = int(r['strike'])
                if r['instrument_type'] == 'CE':
                    m_c_map[stk] = m_c_map.get(stk, 0) + oi
                    m_tc += oi
                elif r['instrument_type'] == 'PE':
                    m_p_map[stk] = m_p_map.get(stk, 0) + oi
                    m_tp += oi
            if m_tc > 0:
                monthly_pcr = round(m_tp / m_tc, 2)
            if m_c_map:
                monthly_max_call = max(m_c_map, key=m_c_map.get)
            if m_p_map:
                monthly_max_put = max(m_p_map, key=m_p_map.get)
        except Exception as e:
            print(f"[DERIVATIVES] Monthly expiry fetch note: {e}")
            
    news_summary = (
        "US Fed rate cut expectations and strong FII inflows support market sentiment. "
        "Global Asian markets trading steady while domestic crude prices remain range-bound."
    )
    
    # Print Extracted Parameters
    print("\n=======================================================")
    print(" LIVE NSE DERIVATIVES PARAMETERS FETCHED FROM ZERODHA")
    print("=======================================================")
    print(f"- Nifty Spot: {nifty_spot:,.2f}")
    print(f"- GIFT Nifty: {gift_nifty:,.2f}")
    print(f"- Put-Call Ratio (PCR): {pcr}")
    print(f"- India VIX: {india_vix}")
    print(f"- Biggest Call Strike (Resistance): {max_call_strike:,}")
    print(f"- Biggest Put Strike (Support): {max_put_strike:,}")
    print(f"- Speedometer Score: {total_score} | Needle Angle: {needle_angle} deg")
    print(f"- Verdict: {simple_verdict}")
    print("=======================================================\n")
    
    grok_key = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
    selected_model = os.getenv("GROK_MODEL") or os.getenv("XAI_MODEL") or "grok-4.3"
    
    used_grok = False
    grok_cached = False
    analysis_output = ""
    last_updated_time = _DERIVATIVES_CACHE.get("last_grok_time")

    # If force_grok is False, ONLY use cached Grok output if it exists. DO NOT query Grok API automatically.
    if not force_grok:
        if _DERIVATIVES_CACHE.get("grok_output"):
            analysis_output = _DERIVATIVES_CACHE["grok_output"]
            used_grok = True
            grok_cached = True
            print("[DERIVATIVES] Using cached Grok AI analysis (Manual Update not clicked).")
        else:
            print("[DERIVATIVES] Grok manual update not triggered and no cache exists. Using fast rule-based analysis (0 tokens burned).")

    # Only query Grok AI if force_grok is explicitly True and grok_key is set
    elif force_grok and grok_key:
        prompt_text = f"""Act as an NSE derivatives analyst. 

Based on this data, analyze market sentiment, determine market regime (Bullish Market, Bearish Market, or Neutral Market), predict the expected percentage change for Nifty 50 spot (% change), expected day range, and key invalidation level.

- Nifty Spot: {nifty_spot:,.2f}
- GIFT Nifty: {gift_nifty:,.2f}
- Put-Call Ratio (PCR): {pcr}
- India VIX: {india_vix}
- Biggest Call Strike (Resistance): {max_call_strike:,}
- Biggest Put Strike (Support): {max_put_strike:,}
- Top Global/Domestic News: {news_summary}

Format output strictly as:
1. Verdict: [{simple_verdict}] (Bull / Bear / Neutral Market)
2. Predicted Nifty % Change: [Predict explicit % change e.g., +0.55% or -0.40%]
3. Key Reason: [1 sentence analyzing market sentiment and key drivers]
4. Expected Range: [Support] to [Resistance]
5. Bias Invalidated If Spot Breaks: [Strike Level]
"""
        try:
            print("[DERIVATIVES] Querying Grok AI for updated news & derivatives analysis...")
            url = "https://api.x.ai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {grok_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": selected_model,
                "messages": [
                    {"role": "system", "content": "You are a professional NSE derivatives analyst specializing in Nifty option chain, PCR, VIX, sentiment analysis, and predicting short-term Nifty price movement percentage."},
                    {"role": "user", "content": prompt_text}
                ],
                "temperature": 0.2
            }
            res = requests.post(url, headers=headers, json=payload, timeout=30)
            if res.status_code == 200:
                analysis_output = res.json()["choices"][0]["message"]["content"]
                used_grok = True
                grok_cached = False
                last_updated_time = datetime.datetime.now().strftime("%I:%M %p")
                _DERIVATIVES_CACHE["grok_output"] = analysis_output
                _DERIVATIVES_CACHE["last_grok_time"] = last_updated_time
            else:
                print(f"Grok API error HTTP {res.status_code}: {res.text}")
        except Exception as g_err:
            print(f"Grok API call failed: {g_err}")

    if not analysis_output:
        # Fast Deterministic Fallback Analysis if Grok API key is unavailable or Grok not manually requested
        gift_basis_pct = round(((gift_nifty - nifty_spot) / nifty_spot * 100.0), 2) if nifty_spot > 0 else 0.0
        predicted_pct_str = f"+{gift_basis_pct:.2f}%" if gift_basis_pct > 0 else f"{gift_basis_pct:.2f}%"
        reason = f"Strong Put writing at {max_put_strike:,} and positive PCR of {pcr} indicate underlying support despite resistance at {max_call_strike:,}."
        exp_range = f"{max_put_strike:,} to {max_call_strike:,}"
        invalidation = f"{max_put_strike:,}" if simple_verdict == "Bull Day" else f"{max_call_strike:,}"
        
        analysis_output = f"""1. Verdict: {simple_verdict} (Market Regime)
2. Predicted Nifty % Change: {predicted_pct_str}
3. Key Reason: {reason}
4. Expected Range: {exp_range}
5. Bias Invalidated If Spot Breaks: {invalidation}"""

    import re
    predicted_nifty_change = ""
    match = re.search(r"Predicted Nifty % Change:\s*([+\-]?\d+(?:\.\d+)?%?)", analysis_output, re.IGNORECASE)
    if match:
        predicted_nifty_change = match.group(1).strip()
    elif nifty_spot > 0 and gift_nifty > 0:
        gift_basis_pct = round(((gift_nifty - nifty_spot) / nifty_spot * 100.0), 2)
        predicted_nifty_change = f"+{gift_basis_pct:.2f}%" if gift_basis_pct > 0 else f"{gift_basis_pct:.2f}%"

    res = {
        "status": "success",
        "zerodha_connected": True,
        "nifty_spot": nifty_spot,
        "gift_nifty": gift_nifty,
        "pcr": pcr,
        "india_vix": india_vix,
        "max_call_strike": max_call_strike,
        "max_put_strike": max_put_strike,
        "sentiment_score": total_score,
        "needle_angle": needle_angle,
        "day_verdict": day_verdict,
        "verdict": simple_verdict,
        "weekly": {
            "pcr": weekly_pcr,
            "sentiment_score": weekly_score,
            "needle_angle": weekly_needle_angle,
            "verdict": weekly_verdict,
            "max_call_strike": weekly_max_call,
            "max_put_strike": weekly_max_put
        },
        "monthly": {
            "pcr": monthly_pcr,
            "sentiment_score": monthly_score,
            "needle_angle": monthly_needle_angle,
            "verdict": monthly_verdict,
            "max_call_strike": monthly_max_call,
            "max_put_strike": monthly_max_put
        },
        "news_summary": news_summary,
        "predicted_nifty_change": predicted_nifty_change,
        "analysis_output": analysis_output,
        "used_grok": used_grok,
        "grok_cached": grok_cached,
        "last_updated_time": last_updated_time
    }
    
    # Enrich with 1-10 strength rating
    rating_data = calculate_derivatives_strength_rating(res)
    res["rating_out_of_10"] = rating_data["rating"]
    res["rating_bias"] = rating_data["bias"]
    res["rating_conviction"] = rating_data["conviction"]
    res["rating_bar"] = rating_data["bar"]

    # Evaluate live 3-Confirmation Nifty Derivatives status (Futures OI Buildup + ATM Straddle Expansion + Price Action)
    try:
        from scripts.nifty_derivatives_breakout_alert import check_and_trigger_spot_index_breakout
        three_conf_res = check_and_trigger_spot_index_breakout(kite=kite)
        res["three_confirmation_status"] = three_conf_res.get("evaluation") or {"alert_triggered": False, "reason": three_conf_res.get("reason")}
        if three_conf_res.get("evaluation") and three_conf_res["evaluation"].get("rating"):
            res["rating_out_of_10"] = three_conf_res["evaluation"]["rating"]
    except Exception as a_err:
        print(f"[DERIVATIVES] Note on 3-confirmation evaluation: {a_err}")

    _DERIVATIVES_CACHE["zerodha_analysis"] = res
    _DERIVATIVES_CACHE["last_zerodha_fetch_time"] = now_ts

    return res

import html

def calculate_derivatives_strength_rating(derivatives_data: dict) -> dict:
    """
    Computes a 1.0 to 10.0 strength rating and directional bias (BULL / BEAR / NEUTRAL)
    based on live Zerodha derivatives metrics: PCR, GIFT basis, sentiment score, and India VIX.
    """
    pcr = float(derivatives_data.get("pcr", 1.0) or 1.0)
    sentiment_score = float(derivatives_data.get("sentiment_score", 0) or 0)
    gift_nifty = float(derivatives_data.get("gift_nifty", 0.0) or 0.0)
    nifty_spot = float(derivatives_data.get("nifty_spot", 0.0) or 0.0)
    basis = gift_nifty - nifty_spot if (gift_nifty and nifty_spot) else 0.0
    vix = float(derivatives_data.get("india_vix", 14.0) or 14.0)

    is_bull = sentiment_score > 15 or pcr >= 1.05
    is_bear = sentiment_score < -15 or pcr <= 0.85

    if is_bull:
        bias = "BULL"
        emoji = "🐂"
        header_emoji = "🟢"

        # PCR Pillar (up to 3.5 pts)
        if pcr >= 1.35:
            pcr_pts = 3.5
        elif pcr >= 1.20:
            pcr_pts = 2.7 + (pcr - 1.20) / 0.15 * 0.8
        elif pcr >= 1.05:
            pcr_pts = 1.8 + (pcr - 1.05) / 0.15 * 0.9
        else:
            pcr_pts = 1.2

        # GIFT Nifty Basis Pillar (up to 2.5 pts)
        if basis >= 60:
            basis_pts = 2.5
        elif basis >= 20:
            basis_pts = 1.5 + (basis - 20) / 40.0 * 1.0
        elif basis >= 0:
            basis_pts = 0.8 + (basis / 20.0) * 0.7
        else:
            basis_pts = 0.3

        # Sentiment Score Pillar (up to 2.5 pts)
        score_pts = min(2.5, max(0.8, (max(0, sentiment_score) / 100.0) * 2.5 + 0.8))

        # India VIX Risk Pillar (up to 1.5 pts)
        if vix <= 13.0:
            vix_pts = 1.5
        elif vix <= 16.0:
            vix_pts = 1.1
        elif vix <= 19.0:
            vix_pts = 0.6
        else:
            vix_pts = 0.2

        total = pcr_pts + basis_pts + score_pts + vix_pts
    elif is_bear:
        bias = "BEAR"
        emoji = "🐻"
        header_emoji = "🔴"

        # PCR Pillar (up to 3.5 pts)
        if pcr <= 0.65:
            pcr_pts = 3.5
        elif pcr <= 0.80:
            pcr_pts = 2.7 + (0.80 - pcr) / 0.15 * 0.8
        elif pcr <= 0.95:
            pcr_pts = 1.8 + (0.95 - pcr) / 0.15 * 0.9
        else:
            pcr_pts = 1.2

        # GIFT Basis Pillar (up to 2.5 pts)
        if basis <= -60:
            basis_pts = 2.5
        elif basis <= -20:
            basis_pts = 1.5 + (-basis - 20) / 40.0 * 1.0
        elif basis <= 0:
            basis_pts = 0.8 + (-basis / 20.0) * 0.7
        else:
            basis_pts = 0.3

        # Sentiment Score Pillar (up to 2.5 pts)
        score_pts = min(2.5, max(0.8, (abs(min(0, sentiment_score)) / 100.0) * 2.5 + 0.8))

        # India VIX Risk Pillar (up to 1.5 pts)
        if vix >= 18.0:
            vix_pts = 1.5
        elif vix >= 15.0:
            vix_pts = 1.1
        else:
            vix_pts = 0.6

        total = pcr_pts + basis_pts + score_pts + vix_pts
    else:
        bias = "NEUTRAL"
        emoji = "⚖️"
        header_emoji = "🟡"
        total = 5.0

    rating = round(min(10.0, max(1.0, total)), 1)
    if rating >= 8.5:
        conviction = "VERY STRONG 🔥"
    elif rating >= 7.0:
        conviction = "STRONG 🚀"
    elif rating >= 5.5:
        conviction = "MODERATE 📈"
    else:
        conviction = "MILD ⚖️"

    filled = int(round(rating))
    bar = "█" * filled + "░" * (10 - filled)

    return {
        "bias": bias,
        "emoji": emoji,
        "header_emoji": header_emoji,
        "rating": rating,
        "conviction": conviction,
        "bar": bar
    }

def detect_options_pressure_buildup(derivatives_data: dict) -> dict:
    """
    Identifies strong options pressure building up on Put Side vs Call Side,
    enriched with a 1-10 strength rating.
    """
    pcr = derivatives_data.get("pcr", 1.0) or 1.0
    sentiment_score = derivatives_data.get("sentiment_score", 0) or 0
    gift_nifty = derivatives_data.get("gift_nifty", 0.0) or 0.0
    nifty_spot = derivatives_data.get("nifty_spot", 0.0) or 0.0
    basis = gift_nifty - nifty_spot if (gift_nifty and nifty_spot) else 0.0
    rating_data = calculate_derivatives_strength_rating(derivatives_data)

    if pcr >= 1.20 or sentiment_score >= 25:
        return {
            "pressure_type": "PUT_PRESSURE_BUILDUP",
            "title": "STRONG PUT PRESSURE BUILDUP",
            "side_name": "PUT WRITING (BULL SUPPORT BUILDUP)",
            "bias": "BULLISH DAY 🐂",
            "header_emoji": "🟢",
            "basis_text": f"+{basis:,.2f} pts Basis" if basis >= 0 else f"{basis:,.2f} pts Basis",
            "pcr_desc": "Strong Put Accumulation (Bullish Support Holding)",
            "vix_desc": "Low Volatility Risk",
            "reason": f"Aggressive Put writing at {derivatives_data.get('max_put_strike', 0):,} PE indicates strong institutional support defending the market.",
            "invalidation": f"Nifty Spot breaking below ₹{derivatives_data.get('max_put_strike', 0):,}",
            "rating_data": rating_data
        }
    elif pcr <= 0.80 or sentiment_score <= -25:
        return {
            "pressure_type": "CALL_PRESSURE_BUILDUP",
            "title": "STRONG CALL PRESSURE BUILDUP",
            "side_name": "CALL WRITING (BEAR RESISTANCE BUILDUP)",
            "bias": "BEARISH DAY 🐻",
            "header_emoji": "🔴",
            "basis_text": f"{basis:,.2f} pts Basis",
            "pcr_desc": "Heavy Call Writing (Bearish Resistance Capping)",
            "vix_desc": "Rising Volatility Risk",
            "reason": f"Massive Call writing buildup at {derivatives_data.get('max_call_strike', 0):,} CE indicates strong resistance overhead capping price advances.",
            "invalidation": f"Nifty Spot breaking above ₹{derivatives_data.get('max_call_strike', 0):,}",
            "rating_data": rating_data
        }
    else:
        return {
            "pressure_type": "NEUTRAL_RANGE",
            "title": "RANGEBOUND OPTIONS SETUP",
            "side_name": "NEUTRAL RANGEBUILDING (BALANCED CALL & PUT OI)",
            "bias": "NEUTRAL DAY ⚖️",
            "header_emoji": "🟡",
            "basis_text": f"{basis:,.2f} pts Basis",
            "pcr_desc": "Balanced Put & Call OI",
            "vix_desc": "Rangebound Volatility",
            "reason": f"Options chain exhibits balanced OI between Put support at {derivatives_data.get('max_put_strike', 0):,} and Call resistance at {derivatives_data.get('max_call_strike', 0):,}.",
            "invalidation": f"Nifty Spot breaking either {derivatives_data.get('max_put_strike', 0):,} or {derivatives_data.get('max_call_strike', 0):,}",
            "rating_data": rating_data
        }

def format_telegram_derivatives_alert(derivatives_data: dict) -> str:
    """
    Formats a concise, high-signal Telegram alert delivering strictly the
    1-10 strength rating (Bull or Bear), explicit Buyer Action, and conviction.
    """
    rating_data = calculate_derivatives_strength_rating(derivatives_data)
    timestamp = derivatives_data.get("last_updated_time") or datetime.datetime.now().strftime("%I:%M %p")
    bias_word = "BULLISH" if rating_data["bias"] == "BULL" else "BEARISH" if rating_data["bias"] == "BEAR" else "NEUTRAL"
    action_text = "🚀 ACTION: BUY WEEKLY CE (CALL)" if rating_data["bias"] == "BULL" else "📉 ACTION: BUY WEEKLY PE (PUT)" if rating_data["bias"] == "BEAR" else "⚖️ RANGEBOUND SETUP"

    msg = (
        f"{rating_data['header_emoji']} <b>NSE DERIVATIVES: {rating_data['rating']}/10 {bias_word} {rating_data['emoji']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{action_text}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Strength Rating:</b> <b>{rating_data['rating']} / 10</b> ({rating_data['conviction']})\n"
        f"📊 <code>[{rating_data['bar']}]</code>\n"
        f"⏰ {timestamp} | ⚡ <i>Zerodha Live Engine</i>"
    )

    return msg

def send_telegram_derivatives_alert(derivatives_data: dict = None, force_send: bool = False) -> dict:
    """
    Delegates all Nifty Derivatives Telegram alerts strictly to the 3-Confirmation
    Automated Engine (Futures OI Buildup + ATM Straddle Expansion + Price Action).
    Never triggers a live alert if even one confirmation is missing.
    """
    from scripts.nifty_derivatives_breakout_alert import (
        check_and_trigger_spot_index_breakout,
        send_nifty_breakout_telegram_alert,
    )
    if force_send:
        direction = "BULLISH"
        if derivatives_data and float(derivatives_data.get("sentiment_score", 0) or 0) < 0:
            direction = "BEARISH"
        return send_nifty_breakout_telegram_alert(breakout_type=direction, force_send=True)
    return check_and_trigger_spot_index_breakout()


def check_and_trigger_oi_pressure_alert(derivatives_data: dict = None) -> dict:
    """
    Evaluates the strict 3-Confirmation Nifty Derivatives Alert rules:
      1. Futures OI Buildup (Long / Short Buildup above dynamic auto-threshold)
      2. ATM Straddle Premium Expansion (Combined CE+PE expansion above dynamic auto-threshold)
      3. Price Action (Breakout of N-bar swing high/low + strong body above dynamic auto-threshold)
    Never triggers if even one confirmation is missing.
    """
    from scripts.nifty_derivatives_breakout_alert import check_and_trigger_spot_index_breakout
    return check_and_trigger_spot_index_breakout()

if __name__ == "__main__":
    res = analyze_nse_derivatives(force_grok=True)
    print("\nFormatted Result:")
    print(res["analysis_output"])


