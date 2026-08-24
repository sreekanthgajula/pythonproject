import pandas as pd
from ta.momentum import TSIIndicator
from ta.volume import OnBalanceVolumeIndicator

MAX_WINDOW = 50

class TickerState:
    """
    Incremental state dictionary for sliding window indicator calculation (O(1) time & RAM).
    Follows the approach from scripts/realtime_scanner.py.
    """
    def __init__(self, ticker, max_window: int = MAX_WINDOW):
        self.ticker = ticker
        self.max_window = max_window
        self.closes = []
        self.volumes = []
        self.timestamps = []
        self.obv = 0.0
        self.obv_history = []
        
        # State variables to calculate EMAs incrementally (Stateful EMA for TSI)
        self.ema1_pc = 0.0
        self.ema2_pc = 0.0
        self.ema1_abs_pc = 0.0
        self.ema2_abs_pc = 0.0
        self.tsi = 0.0
        self.tsi_signal = 0.0
        self.tsi_history = []
        self.tsi_signal_history = []

    def update(self, new_close: float, new_volume: float, timestamp=None) -> bool:
        """
        Incremental state update. Takes O(1) time and minimal CPU.
        Returns True when minimum warmup candles (>= 30) have been ingested.
        """
        new_close = float(new_close)
        new_volume = float(new_volume)

        if not self.closes:
            self.closes.append(new_close)
            self.volumes.append(new_volume)
            if timestamp is not None:
                self.timestamps.append(timestamp)
            self.obv_history.append(0.0)
            self.tsi_history.append(0.0)
            self.tsi_signal_history.append(0.0)
            return False

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
        if timestamp is not None:
            self.timestamps.append(timestamp)

        # Maintain sliding window sizes to prevent memory leaks
        if len(self.closes) > self.max_window:
            self.closes.pop(0)
            self.volumes.pop(0)
            if self.timestamps:
                self.timestamps.pop(0)
            self.obv_history.pop(0)
            if len(self.tsi_history) > self.max_window:
                self.tsi_history.pop(0)
                self.tsi_signal_history.pop(0)

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

        # TSI & Signal calculation
        if self.ema2_abs_pc != 0:
            self.tsi = 100.0 * (self.ema2_pc / self.ema2_abs_pc)
        else:
            self.tsi = 0.0

        self.tsi_signal = (self.tsi * a_sig) + (self.tsi_signal * (1.0 - a_sig))
        self.tsi_history.append(self.tsi)
        self.tsi_signal_history.append(self.tsi_signal)

        # Warmup threshold check
        return len(self.closes) >= 30

    def check_pattern(self) -> bool:
        """
        Efficient Short-Circuit Logic from realtime_scanner.py.
        Checks cheapest conditions first to exit as early as possible.
        """
        if len(self.closes) < 20 or len(self.volumes) < 20:
            return False

        # 1. Cheap Check: Volume check (Requires only basic arithmetic)
        avg_vol = sum(self.volumes[-20:]) / 20.0
        if avg_vol > 0 and self.volumes[-1] < avg_vol * 1.2:
            return False  # Exit early

        # 2. Cheap Check: Price Consolidation (Basic min/max on small window)
        if len(self.closes) < 10:
            return False
        window = self.closes[-10:]
        p_min, p_max = min(window), max(window)
        p_mean = sum(window) / 10.0
        if p_mean > 0 and (p_max - p_min) / p_mean > 0.03:
            return False  # Exit early

        # 3. Momentum Check: TSI Condition
        if self.tsi >= 10:
            return False

        # 4. OBV Check: OBV above its 9-period SMA
        if len(self.obv_history) < 9:
            return False
        obv_sma = sum(self.obv_history[-9:]) / 9.0
        if self.obv < obv_sma:
            return False

        return True

def calculate_tsi(df: pd.DataFrame, window_slow: int = 25, window_fast: int = 13) -> pd.Series:
    """
    Calculates the True Strength Index (TSI) for a given DataFrame.
    
    Args:
        df (pd.DataFrame): DataFrame containing at least a 'close' column.
        window_slow (int): Slow window size. Defaults to 25.
        window_fast (int): Fast window size. Defaults to 13.
        
    Returns:
        pd.Series: TSI values.
    """
    # Ensure 'close' column is numeric
    close_series = pd.to_numeric(df['close'], errors='coerce')
    
    tsi_indicator = TSIIndicator(
        close=close_series,
        window_slow=window_slow,
        window_fast=window_fast,
        fillna=False
    )
    return tsi_indicator.tsi()

def calculate_obv(df: pd.DataFrame) -> pd.Series:
    """
    Calculates the On-Balance Volume (OBV) for a given DataFrame.
    
    Args:
        df (pd.DataFrame): DataFrame containing 'close' and 'volume' columns.
        
    Returns:
        pd.Series: OBV values.
    """
    # Ensure 'close' and 'volume' columns are numeric
    close_series = pd.to_numeric(df['close'], errors='coerce')
    volume_series = pd.to_numeric(df['volume'], errors='coerce')
    
    obv_indicator = OnBalanceVolumeIndicator(
        close=close_series,
        volume=volume_series,
        fillna=False
    )
    return obv_indicator.on_balance_volume()

def append_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates TSI and OBV, appending them as new columns 'tsi' and 'obv'
    to the provided DataFrame (modifies in place).
    
    Args:
        df (pd.DataFrame): Input DataFrame with 'close' and 'volume' columns.
        
    Returns:
        pd.DataFrame: DataFrame with the calculated indicator columns.
    """
    df['tsi'] = calculate_tsi(df)
    df['obv'] = calculate_obv(df)
    return df

