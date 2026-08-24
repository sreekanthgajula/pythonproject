import asyncio
import time
import numpy as np

# A state dictionary to hold the sliding window of data for each ticker.
# This prevents reloading the entire database on every new candle.
# For 20 tickers, keeping the last 50 candles in memory uses virtually 0 MB of RAM.
TICKER_DATA = {}
MAX_WINDOW = 50 

class TickerState:
    def __init__(self, ticker):
        self.ticker = ticker
        self.closes = []
        self.volumes = []
        self.obv = 0.0
        self.obv_history = []
        
        # State variables to calculate EMAs incrementally (Stateful EMA)
        self.ema1_pc = 0.0
        self.ema2_pc = 0.0
        self.ema1_abs_pc = 0.0
        self.ema2_abs_pc = 0.0
        self.tsi = 0.0
        self.tsi_signal = 0.0

    def update(self, new_close, new_volume):
        """
        Incremental state update. Takes O(1) time and minimal CPU.
        """
        if not self.closes:
            self.closes.append(new_close)
            self.volumes.append(new_volume)
            self.obv_history.append(0.0)
            return False # Need at least two data points for change
        
        prev_close = self.closes[-1]
        pc = new_close - prev_close
        abs_pc = abs(pc)
        
        # 1. Update OBV incrementally
        if new_close > prev_close:
            self.obv += new_volume
        elif new_close < prev_close:
            self.obv -= new_volume
            
        self.obv_history.append(self.obv)
        self.closes.append(new_close)
        self.volumes.append(new_volume)
        
        # Maintain sliding window sizes to prevent memory leaks
        if len(self.closes) > MAX_WINDOW:
            self.closes.pop(0)
            self.volumes.pop(0)
            self.obv_history.pop(0)
            
        # 2. Stateful EMA Calculations (TSI)
        # Smoothing factors: alpha = 2 / (span + 1)
        a_long = 2.0 / (25 + 1)
        a_short = 2.0 / (13 + 1)
        a_sig = 2.0 / (13 + 1)
        
        # First smoothing
        self.ema1_pc = (pc * a_long) + (self.ema1_pc * (1.0 - a_long))
        self.ema1_abs_pc = (abs_pc * a_long) + (self.ema1_abs_pc * (1.0 - a_long))
        
        # Second smoothing
        self.ema2_pc = (self.ema1_pc * a_short) + (self.ema2_pc * (1.0 - a_short))
        self.ema2_abs_pc = (self.ema1_abs_pc * a_short) + (self.ema2_abs_pc * (1.0 - a_short))
        
        # TSI & Signal
        if self.ema2_abs_pc != 0:
            self.tsi = 100.0 * (self.ema2_pc / self.ema2_abs_pc)
        else:
            self.tsi = 0.0
            
        self.tsi_signal = (self.tsi * a_sig) + (self.tsi_signal * (1.0 - a_sig))
        
        # Check warmup complete
        return len(self.closes) >= 30

    def check_pattern(self):
        """
        Efficient Short-Circuit Logic.
        We check the cheapest conditions first to exit as early as possible.
        """
        # 1. Cheap Check: Volume check (Requires only basic arithmetic)
        avg_vol = sum(self.volumes[-20:]) / 20.0
        if self.volumes[-1] < avg_vol * 1.2:
            return False  # Exit early
            
        # 2. Cheap Check: Price Consolidation (Basic min/max on small list)
        window = self.closes[-10:]
        p_min, p_max = min(window), max(window)
        p_mean = sum(window) / 10.0
        if (p_max - p_min) / p_mean > 0.03:
            return False  # Exit early
            
        # 3. Momentum Check: TSI Crossover
        # Since TSI is calculated statefully above, this is O(1)
        if self.tsi >= 10:
            return False
            
        # 4. OBV Check: OBV above its 9-period SMA
        obv_sma = sum(self.obv_history[-9:]) / 9.0
        if self.obv < obv_sma:
            return False
            
        return True

async def on_candle_close(ticker, close, volume):
    """
    Called when a new candle closes. 
    Processes 1 ticker at a time asynchronously.
    """
    if ticker not in TICKER_DATA:
        TICKER_DATA[ticker] = TickerState(ticker)
        
    state = TICKER_DATA[ticker]
    warmup_complete = state.update(close, volume)
    
    if warmup_complete and state.check_pattern():
        print(f"[ALERT] PATTERN DETECTED for {ticker}! Price: {close:.2f}, TSI: {state.tsi:.2f}, OBV: {state.obv:.0f}")

async def mock_websocket_stream():
    """
    Simulates a real-time WebSocket connection receiving 5-minute candle close updates 
    for 20 tickers simultaneously.
    """
    tickers = [f"TICKER_{i}" for i in range(1, 21)]
    print(f"Starting real-time scanner for {len(tickers)} tickers...")
    
    # Pre-warm state with mock historical data
    for ticker in tickers:
        state = TickerState(ticker)
        TICKER_DATA[ticker] = state
        curr_price = 100.0
        for _ in range(40):
            curr_price += np.random.normal(0, 0.1)
            state.update(curr_price, int(np.random.normal(50000, 5000)))
            
    print("Warmup complete. Monitoring incoming live closes...")
    
    # Simulate receiving a live bar close every 2 seconds for demonstration
    for bar_idx in range(5):
        await asyncio.sleep(2)
        print(f"\n--- New Candle Close Received (Bar {bar_idx+1}) ---")
        
        # Process all 20 tickers
        tasks = []
        for ticker in tickers:
            # Simulate a consolidation with volume spike on a random ticker to trigger signal
            if ticker == "TICKER_7" and bar_idx == 2:
                # Force trigger setup
                close = TICKER_DATA[ticker].closes[-1] + 0.01
                vol = 150000 # Spike
            else:
                close = TICKER_DATA[ticker].closes[-1] + np.random.normal(0, 0.05)
                vol = int(np.random.normal(50000, 10000))
                
            tasks.append(on_candle_close(ticker, close, vol))
            
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(mock_websocket_stream())
