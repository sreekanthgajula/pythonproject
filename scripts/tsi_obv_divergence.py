import numpy as np
import pandas as pd

def calculate_tsi(df, long_len=25, short_len=13, signal_len=13):
    """
    Calculate the True Strength Index (TSI) and its Signal Line.
    
    TSI = 100 * (Double Smoothed PC / Double Smoothed Absolute PC)
    where PC = Price Change (Close_t - Close_t-1)
    """
    close = df['close']
    pc = close.diff()
    abs_pc = pc.abs()
    
    # Double smoothing of Price Change
    double_smoothed_pc = pc.ewm(span=long_len, adjust=False).mean().ewm(span=short_len, adjust=False).mean()
    # Double smoothing of Absolute Price Change
    double_smoothed_abs_pc = abs_pc.ewm(span=long_len, adjust=False).mean().ewm(span=short_len, adjust=False).mean()
    
    # Avoid division by zero
    tsi = 100 * (double_smoothed_pc / double_smoothed_abs_pc.replace(0, np.nan))
    tsi = tsi.fillna(0)
    
    # Signal Line (EMA of TSI)
    signal = tsi.ewm(span=signal_len, adjust=False).mean()
    
    df['tsi'] = tsi
    df['tsi_signal'] = signal
    return df

def calculate_obv(df, sma_len=9):
    """
    Calculate On-Balance Volume (OBV) and its Simple Moving Average (SMA).
    """
    close = df['close']
    volume = df['volume']
    
    # Calculate daily OBV changes
    direction = np.sign(close.diff())
    direction.iloc[0] = 0 # first value has no diff
    
    obv_change = direction * volume
    obv = obv_change.cumsum()
    
    # Calculate SMA of OBV
    obv_sma = obv.rolling(window=sma_len).mean()
    
    df['obv'] = obv
    df['obv_sma'] = obv_sma
    return df

def detect_toad_pattern(df, check_window=10, price_consolidation_pct=0.03):
    """
    Detect the TSI-OBV Accumulation Divergence (TOAD) pattern.
    
    Conditions for a bullish entry signal before price breakout:
    1. Price Consolidation: The price range over the check_window is narrow (within price_consolidation_pct).
    2. Volume Confirmation: Average volume in the last few bars is higher than the 20-period Volume SMA.
    3. TSI Turnaround: TSI is negative (oversold/consolidation) and crosses above its Signal Line.
    4. OBV Divergence: OBV crosses above its 9-period SMA and shows a strong upward slope.
    """
    # Calculate required indicators
    df = calculate_tsi(df)
    df = calculate_obv(df)
    df['vol_sma20'] = df['volume'].rolling(window=20).mean()
    
    signals = []
    
    # Start loop after indicators have warmed up (e.g., 30 periods)
    for i in range(30, len(df)):
        # 1. Price Consolidation Check
        window_prices = df['close'].iloc[i - check_window + 1 : i + 1]
        price_min = window_prices.min()
        price_max = window_prices.max()
        price_range_pct = (price_max - price_min) / window_prices.mean()
        is_consolidating = price_range_pct <= price_consolidation_pct
        
        # 2. TSI Bullish Crossover and Slope Check
        tsi_curr = df['tsi'].iloc[i]
        tsi_prev = df['tsi'].iloc[i-1]
        sig_curr = df['tsi_signal'].iloc[i]
        sig_prev = df['tsi_signal'].iloc[i-1]
        
        # We look for a recent crossover or just crossed (within last 3 bars)
        # and TSI should be relatively low (e.g., below 10 or negative, showing room to run)
        tsi_low = tsi_curr < 10
        tsi_crossover = (tsi_prev <= sig_prev and tsi_curr > sig_curr) or \
                        (df['tsi'].iloc[i-2] <= df['tsi_signal'].iloc[i-2] and df['tsi'].iloc[i-1] > df['tsi_signal'].iloc[i-1])
        
        # TSI slope is positive
        tsi_slope_positive = (tsi_curr > df['tsi'].iloc[i-3])
        
        # 3. OBV Accumulation Check
        obv_curr = df['obv'].iloc[i]
        df['obv'].iloc[i-1]
        obv_sma_curr = df['obv_sma'].iloc[i]
        df['obv_sma'].iloc[i-1]
        
        # OBV is above SMA and rising
        obv_above_sma = obv_curr > obv_sma_curr
        obv_rising = obv_curr > df['obv'].iloc[i-3]
        
        # 4. Volume Spike / Presence Check
        # Volume is above its 20-period SMA
        vol_curr = df['volume'].iloc[i]
        vol_sma = df['vol_sma20'].iloc[i]
        volume_strong = vol_curr > vol_sma * 1.2
        
        # Trigger signal if all conditions are met
        if is_consolidating and tsi_low and tsi_crossover and tsi_slope_positive and obv_above_sma and obv_rising and volume_strong:
            signals.append({
                'index': i,
                'time': df.index[i],
                'price': df['close'].iloc[i],
                'tsi': tsi_curr,
                'obv_diff': obv_curr - obv_sma_curr
            })
            
    return df, pd.DataFrame(signals)

# --- Test / Simulation ---
if __name__ == "__main__":
    print("Simulating market data to test TOAD pattern detection...")
    
    # Create 100 periods of synthetic data
    np.random.seed(42)
    dates = pd.date_range(start="2026-07-28 09:30", periods=100, freq="5min")
    
    # Start price at 100
    prices = [100.0]
    volumes = []
    
    # Phase 1: Mild drift down with low volume (0 to 40)
    for _ in range(40):
        prices.append(prices[-1] + np.random.normal(-0.1, 0.2))
        volumes.append(int(np.random.normal(50000, 10000)))
        
    # Phase 2: Consolidation with rising volume and OBV, price remains flat (40 to 60)
    # This is the exact pattern we want to identify!
    for i in range(20):
        prices.append(prices[-1] + np.random.normal(0.02, 0.05)) # very tight price range
        # Volume starts increasing dramatically (accumulation)
        volumes.append(int(np.random.normal(150000 + i * 8000, 20000)))
        
    # Phase 3: Major breakout rise (60 to 80)
    for _ in range(20):
        prices.append(prices[-1] + np.random.normal(1.5, 0.5))
        volumes.append(int(np.random.normal(250000, 50000)))
        
    # Phase 4: Distribution / plateau (80 to 100)
    for _ in range(20):
        prices.append(prices[-1] + np.random.normal(0.0, 0.3))
        volumes.append(int(np.random.normal(100000, 20000)))
        
    # Create DataFrame
    df = pd.DataFrame({
        'close': prices[1:], # match lengths
        'volume': volumes
    }, index=dates)
    
    # Run Detector
    df_result, signals = detect_toad_pattern(df)
    
    print("\n--- Detection Results ---")
    if not signals.empty:
        for idx, row in signals.iterrows():
            print(f"SIGNAL TRIGGERED at {row['time']}: Price={row['price']:.2f}, TSI={row['tsi']:.2f}, OBV Diff={row['obv_diff']:.0f}")
            print(f"Price 10 bars later: {df_result['close'].iloc[int(row['index'])+10]:.2f} (Change: {((df_result['close'].iloc[int(row['index'])+10] / row['price']) - 1)*100:.2f}%)")
    else:
        print("No signals detected.")
