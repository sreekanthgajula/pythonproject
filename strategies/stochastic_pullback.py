import pandas as pd
from typing import Optional
from datetime import datetime
from strategies.base import BaseStrategy, Signal


def compute_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3):
    """Calculates Stochastic Oscillator %K and %D lines."""
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")

    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()

    denom = (highest_high - lowest_low).replace(0, 1e-5)
    k_line = 100.0 * ((close - lowest_low) / denom)
    d_line = k_line.rolling(window=d_period).mean()
    return k_line, d_line


class StochasticPullbackStrategy(BaseStrategy):
    """
    Stochastic Dip in Trend Strategy.
    Filters for primary uptrends (Close > 50 EMA) and buys when %K crosses above %D from oversold (< 20).
    """
    def __init__(self, strategy_id: str = "stoch_pullback_09", params: dict = None):
        default_params = {
            "trend_ema": 50,
            "k_period": 14,
            "d_period": 3,
            "oversold_threshold": 20.0,
            "stop_loss_pct": 0.015,
            "take_profit_pct": 0.030,
            "max_holding_bars": 15
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="Stochastic Dip in Trend",
            description="Buys %K > %D crossover below 20 oversold level when price is above 50-EMA.",
            params=default_params
        )

    def evaluate(self, candle: dict, rolling_df: pd.DataFrame, ticker_state=None) -> Optional[Signal]:
        min_len = max(self.params["trend_ema"], self.params["k_period"] + self.params["d_period"]) + 2
        if rolling_df is None or len(rolling_df) < min_len:
            return None

        closes = pd.to_numeric(rolling_df["close"], errors="coerce")
        ema_50 = closes.ewm(span=self.params["trend_ema"], adjust=False).mean().iloc[-1]
        current_close = float(candle["close"])

        # Trend filter
        if current_close < ema_50:
            return None

        k_line, d_line = compute_stochastic(
            rolling_df,
            k_period=self.params["k_period"],
            d_period=self.params["d_period"]
        )

        curr_k = float(k_line.iloc[-1])
        prev_k = float(k_line.iloc[-2])
        curr_d = float(d_line.iloc[-1])
        prev_d = float(d_line.iloc[-2])

        # Crossover from oversold area (< 20)
        is_oversold = prev_k <= self.params["oversold_threshold"] or prev_d <= self.params["oversold_threshold"]
        is_cross = (prev_k <= prev_d) and (curr_k > curr_d)

        if is_oversold and is_cross:
            sl = round(current_close * (1.0 - self.params["stop_loss_pct"]), 2)
            tp = round(current_close * (1.0 + self.params["take_profit_pct"]), 2)

            return Signal(
                strategy_id=self.strategy_id,
                action="BUY",
                instrument_token=candle.get("instrument_token", 0),
                price=current_close,
                timestamp=candle.get("timestamp", datetime.utcnow()),
                stop_loss=sl,
                target_price=tp,
                max_holding_bars=self.params["max_holding_bars"],
                reason=f"Stochastic oversold cross: %K ({curr_k:.1f}) crossed %D ({curr_d:.1f}) above 50-EMA ({ema_50:.2f})",
                metadata={"stoch_k": curr_k, "stoch_d": curr_d, "ema_50": ema_50}
            )

        return None
