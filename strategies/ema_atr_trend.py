import pandas as pd
import numpy as np
from typing import Optional
from datetime import datetime
from strategies.base import BaseStrategy, Signal


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculates Average True Range (ATR)."""
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean().bfill()


class EMAATRTrendStrategy(BaseStrategy):
    """
    Dual EMA Trend Following with ATR Volatility Protection.
    Catches major trend transitions when fast EMA (20) crosses slow EMA (50),
    using ATR to adapt stop-loss distances to current market volatility.
    """
    def __init__(self, strategy_id: str = "ema_atr_04", params: dict = None):
        default_params = {
            "fast_ema": 20,
            "slow_ema": 50,
            "atr_period": 14,
            "atr_multiplier": 2.5,
            "risk_reward": 2.0,
            "max_holding_bars": 35
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="Dual EMA & ATR Trend",
            description="Trades medium-term trends on 20/50 EMA crosses with volatility-adjusted ATR stops.",
            params=default_params
        )

    def evaluate(self, candle: dict, rolling_df: pd.DataFrame, ticker_state=None) -> Optional[Signal]:
        min_required = self.params["slow_ema"] + 5
        if rolling_df is None or len(rolling_df) < min_required:
            return None

        closes = pd.to_numeric(rolling_df["close"], errors="coerce")
        fast_ema = closes.ewm(span=self.params["fast_ema"], adjust=False).mean()
        slow_ema = closes.ewm(span=self.params["slow_ema"], adjust=False).mean()

        curr_fast = fast_ema.iloc[-1]
        prev_fast = fast_ema.iloc[-2]
        curr_slow = slow_ema.iloc[-1]
        prev_slow = slow_ema.iloc[-2]

        # Bullish Golden Cross
        is_cross = (prev_fast <= prev_slow) and (curr_fast > curr_slow)
        current_close = float(candle["close"])

        if is_cross:
            atr_series = compute_atr(rolling_df, period=self.params["atr_period"])
            curr_atr = float(atr_series.iloc[-1])
            if np.isnan(curr_atr) or curr_atr <= 0:
                curr_atr = current_close * 0.01

            risk = curr_atr * self.params["atr_multiplier"]
            sl = round(current_close - risk, 2)
            tp = round(current_close + (risk * self.params["risk_reward"]), 2)

            return Signal(
                strategy_id=self.strategy_id,
                action="BUY",
                instrument_token=candle.get("instrument_token", 0),
                price=current_close,
                timestamp=candle.get("timestamp", datetime.utcnow()),
                stop_loss=sl,
                target_price=tp,
                max_holding_bars=self.params["max_holding_bars"],
                reason=f"EMA {self.params['fast_ema']} crossed above EMA {self.params['slow_ema']} (ATR: {curr_atr:.2f})",
                metadata={"fast_ema": curr_fast, "slow_ema": curr_slow, "atr": curr_atr}
            )

        return None
