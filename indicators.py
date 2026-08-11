import pandas as pd
from ta.momentum import TSIIndicator
from ta.volume import OnBalanceVolumeIndicator

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
