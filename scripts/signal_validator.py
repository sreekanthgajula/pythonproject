import pandas as pd

class SignalValidator:
    """
    Second-stage filter engine to validate raw alerts and filter out 'fake' signals.
    """
    def __init__(self, benchmark_ticker="NIFTY_50"):
        self.benchmark_ticker = benchmark_ticker

    def validate_signal(self, signal_payload, ticker_history, benchmark_history=None):
        """
        Runs deep validation filters on a triggered alert.
        Returns (is_valid: bool, reason: str, confidence_score: float)
        """
        ticker = signal_payload['ticker']
        price = signal_payload['price']
        
        print(f"\n[VALIDATOR] Reviewing trigger for {ticker} at price {price:.2f}...")
        
        # --- FILTER 1: Options Open Interest (OI) Check (Crucial for Options) ---
        # Rule: Volume without rising Open Interest is retail churn. 
        # Institutional accumulation requires Open Interest to build up.
        if 'open_interest' in ticker_history.columns:
            recent_oi = ticker_history['open_interest'].iloc[-5:]
            oi_change_pct = (recent_oi.iloc[-1] - recent_oi.iloc[0]) / recent_oi.iloc[0]
            
            if oi_change_pct <= 0.02: # Needs at least 2% growth in contract holdings
                return False, "FAKE: High volume but Open Interest is flat/falling (retail day-trading churn)", 0.0
        else:
            # Fallback for stocks/assets without OI data
            oi_change_pct = 0.0

        # --- FILTER 2: Broad Market Regime / Beta Filter ---
        # Rule: Do not buy bullish breakouts if the broader index is in a sharp downtrend.
        if benchmark_history is not None and not benchmark_history.empty:
            # Check if benchmark is trading above its 20-period EMA
            benchmark_close = benchmark_history['close']
            benchmark_ema20 = benchmark_close.ewm(span=20, adjust=False).mean()
            
            # If benchmark is crashing (price far below EMA20), breakouts fail 80% of the time.
            if benchmark_close.iloc[-1] < benchmark_ema20.iloc[-1] * 0.995:
                return False, f"FAKE: Broader market ({self.benchmark_ticker}) is in a downtrend. High breakout failure risk.", 0.1
        
        # --- FILTER 3: Spread-Volume Anomaly (Buying vs Selling Dominance) ---
        # Rule: In consolidation, down-bars should be on dry volume. 
        # If high-volume bars are mostly red, it's distribution, not accumulation.
        recent_bars = ticker_history.iloc[-10:]
        up_volume = recent_bars[recent_bars['close'] > recent_bars['open']]['volume'].sum()
        down_volume = recent_bars[recent_bars['close'] < recent_bars['open']]['volume'].sum()
        
        total_vol = up_volume + down_volume
        if total_vol > 0:
            buying_ratio = up_volume / total_vol
            if buying_ratio < 0.60: # We want at least 60% of volume to be on green bars
                return False, f"FAKE: Volume is high but buying volume ratio is weak ({buying_ratio:.1%}). Might be distribution.", 0.2
        else:
            buying_ratio = 0.5
            
        # --- FILTER 4: Relative Strength (Outperformance) ---
        # Rule: A true accumulation breakout candidate should show relative strength index outperformance
        if benchmark_history is not None:
            stock_perf = (ticker_history['close'].iloc[-1] / ticker_history['close'].iloc[-10]) - 1
            bench_perf = (benchmark_history['close'].iloc[-1] / benchmark_history['close'].iloc[-10]) - 1
            
            if stock_perf < bench_perf:
                return False, "FAKE: Stock is lagging the benchmark index performance over the last 10 periods.", 0.3

        # Calculate a final conviction score if it passes all tests
        confidence = 0.5 + (buying_ratio * 0.3) + (oi_change_pct * 0.2)
        confidence = min(confidence, 1.0)
        
        return True, "TRUE SIGNAL: Strong volume support, rising Open Interest, and broad market tailwinds.", confidence

# --- Demonstration / Testing ---
if __name__ == "__main__":
    validator = SignalValidator()
    
    # 1. Simulate a FAKE signal (high volume, but declining open interest and weak buying ratio)
    fake_history = pd.DataFrame({
        'open':  [100, 101, 100,  99,  98,  99,  98,  97,  98,  97],
        'close': [101, 100,  99,  98,  99,  98,  97,  98,  97,  97.5],
        'volume': [50000, 80000, 100000, 120000, 90000, 140000, 150000, 130000, 160000, 180000],
        'open_interest': [5000, 4950, 4900, 4800, 4850, 4700, 4600, 4650, 4500, 4400] # Falling OI
    })
    
    # 2. Simulate a TRUE signal (high volume, rising open interest, and dominant buying volume)
    true_history = pd.DataFrame({
        'open':  [100, 100.1, 99.9, 100.2, 100.1, 100.3, 100.2, 100.4, 100.3, 100.5],
        'close': [100.2, 100.0, 100.3, 100.1, 100.4, 100.3, 100.5, 100.4, 100.6, 100.8], # upward drift
        'volume': [150000, 120000, 180000, 110000, 210000, 130000, 250000, 140000, 280000, 310000], # high volume on up close
        'open_interest': [5000, 5050, 5150, 5200, 5300, 5350, 5500, 5550, 5700, 5900] # Rising OI
    })
    
    mock_benchmark = pd.DataFrame({
        'close': [15000, 15020, 15010, 15030, 15025, 15040, 15035, 15050, 15045, 15060]
    })
    
    # Run Validations
    payload_fake = {'ticker': 'NIFTY_OPTION_FAKE', 'price': 97.5}
    is_valid, reason, score = validator.validate_signal(payload_fake, fake_history, mock_benchmark)
    print(f"Result -> Valid: {is_valid} | Reason: {reason} | Score: {score}")
    
    payload_true = {'ticker': 'NIFTY_OPTION_TRUE', 'price': 100.8}
    is_valid, reason, score = validator.validate_signal(payload_true, true_history, mock_benchmark)
    print(f"Result -> Valid: {is_valid} | Reason: {reason} | Score: {score}")
