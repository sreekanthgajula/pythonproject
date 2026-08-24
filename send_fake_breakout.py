import os
import sys
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from dotenv import load_dotenv
load_dotenv(dotenv_path=project_root / ".env")

from api.server import fetch_history, get_benchmark_ticker, analyze_market_data
from scripts.signal_validator import SignalValidator

def main():
    ticker = "CUPID.NS"
    # Fetch last 5 days to ensure we have enough history for rolling zscores/slopes
    end_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    
    print(f"Fetching history for {ticker} from {start_date} to {end_date}...")
    df = fetch_history(ticker, start_date, end_date, interval="10minute")
    
    if df.empty:
        print("No historical data found.")
        return
        
    print(f"Fetched {len(df)} rows. Analyzing indicators...")
    _, processed_df = analyze_market_data(df)
    processed_df = processed_df.fillna(0)
    
    # Calculate obv_zscore and tsi_slope
    import numpy as np
    processed_df["obv_diff_2"] = processed_df["obv"].diff(2)
    rolling_mean_20 = processed_df["obv_diff_2"].rolling(window=20).mean()
    rolling_std_20 = processed_df["obv_diff_2"].rolling(window=20).std(ddof=0)
    safe_std = rolling_std_20.replace(0, np.nan)
    processed_df["obv_zscore"] = (processed_df["obv_diff_2"] - rolling_mean_20) / safe_std
    processed_df["obv_zscore"] = processed_df["obv_zscore"].fillna(0.0)
    processed_df["tsi_slope_2"] = processed_df["tsi"].diff(2)
    processed_df["tsi_crossed_above"] = (
        (processed_df["tsi"].shift(1) <= processed_df["tsi_signal"].shift(1)) &
        (processed_df["tsi"] > processed_df["tsi_signal"])
    )
    
    bench_ticker = get_benchmark_ticker(ticker)
    bench_df = fetch_history(bench_ticker, start_date, end_date, interval="10minute")
    
    validator = SignalValidator(benchmark_ticker=bench_ticker)
    
    # Normalize timestamps
    processed_df["timestamp_parsed"] = pd.to_datetime(processed_df["timestamp"], utc=True)
    if not bench_df.empty:
        bench_df["timestamp_parsed"] = pd.to_datetime(bench_df["timestamp"], utc=True)
        
    breakouts = []
    
    for idx_i, (_, row) in enumerate(processed_df.iterrows()):
        # Filter for today (August 12, 2026)
        row_time = row["timestamp_parsed"]
        if row_time.date() != datetime(2026, 8, 12).date():
            continue
            
        obv_cond = float(row.get("obv_zscore", 0.0)) > 2.0
        tsi_cond = (float(row.get("tsi_slope_2", 0.0)) > 2.5) or bool(row.get("tsi_crossed_above", False))
        
        is_breakout = False
        if obv_cond and tsi_cond:
            if idx_i >= 9:
                ticker_slice = processed_df.iloc[:idx_i+1]
                if not bench_df.empty:
                    bench_slice = bench_df[bench_df["timestamp_parsed"] <= row_time]
                else:
                    bench_slice = None
                    
                signal_payload = {
                    "ticker": ticker,
                    "price": float(row["close"])
                }
                
                is_valid, reason, confidence_score = validator.validate_signal(
                    signal_payload, ticker_slice, bench_slice
                )
                is_breakout = is_valid
                
        if is_breakout:
            breakouts.append({
                "time": row["timestamp"],
                "price": row["close"],
                "obv_zscore": row["obv_zscore"],
                "tsi_slope": row["tsi_slope_2"],
                "reason": reason if 'reason' in locals() else "N/A"
            })
            
    print(f"\nFound {len(breakouts)} real breakouts for {ticker} today:")
    for b in breakouts:
        print(f"Timestamp: {b['time']} | Price: ₹{b['price']:.2f} | OBV Z-Score: {b['obv_zscore']:.2f} | TSI Slope: {b['tsi_slope']:.2f}")

if __name__ == "__main__":
    main()
