import pandas as pd
import numpy as np
from typing import Optional
from datetime import datetime
from strategies.base import BaseStrategy, Signal


def compute_rsi(series: pd.Series, period: int = 2) -> pd.Series:
    """Computes RSI using exponential / wilder smoothing."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


class RSIPullbackStrategy(BaseStrategy):
    """
    Connors-Style RSI Mean Reversion in an Uptrend.
    Takes high-probability pullbacks when a stock in a strong secular trend
    experiences a brief, sharp sell-off.
    """
    def __init__(self, strategy_id: str = "rsi_pullback_03", params: dict = None):
        default_params = {
            "trend_ma_period": 50,     # Trend filter: price must be above 50 MA
            "rsi_period": 2,           # Fast 2-period RSI
            "rsi_oversold": 15.0,      # Extreme oversold threshold
            "exit_ma_period": 5,       # Fast exit moving average
            "stop_loss_pct": 0.02,     # 2.0% safety stop
            "max_holding_bars": 8      # Maximum 8 bars to hold
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="Connors RSI Pullback",
            description="Buys short-term oversold dips (RSI-2 < 15) when the primary trend is bullish (above 50 MA).",
            params=default_params
        )

    def evaluate(self, candle: dict, rolling_df: pd.DataFrame, ticker_state=None) -> Optional[Signal]:
        min_required = max(self.params["trend_ma_period"], 20) + 2
        if rolling_df is None or len(rolling_df) < min_required:
            return None

        closes = pd.to_numeric(rolling_df["close"], errors="coerce")
        current_close = float(candle["close"])

        # 1. Trend Filter: Price must be above 50-period SMA
        trend_ma = closes.rolling(window=self.params["trend_ma_period"]).mean().iloc[-1]
        if pd.isna(trend_ma) or current_close < trend_ma:
            return None

        # 2. Fast 2-period RSI
        rsi_series = compute_rsi(closes, period=self.params["rsi_period"])
        curr_rsi = float(rsi_series.iloc[-1])

        # 3. Check Oversold Condition
        if curr_rsi < self.params["rsi_oversold"]:
            # Exit MA for reference
            exit_ma = float(closes.rolling(window=self.params["exit_ma_period"]).mean().iloc[-1])
            sl = round(current_close * (1.0 - self.params["stop_loss_pct"]), 2)
            # Target is at least the 5-period SMA or a modest gain
            tp = round(max(exit_ma, current_close * 1.025), 2)

            return Signal(
                strategy_id=self.strategy_id,
                action="BUY",
                instrument_token=candle.get("instrument_token", 0),
                price=current_close,
                timestamp=candle.get("timestamp", datetime.utcnow()),
                stop_loss=sl,
                target_price=tp,
                max_holding_bars=self.params["max_holding_bars"],
                reason=f"RSI-2 oversold ({curr_rsi:.1f} < {self.params['rsi_oversold']}) above 50-MA ({trend_ma:.2f})",
                metadata={"rsi_2": curr_rsi, "trend_ma": trend_ma, "exit_ma": exit_ma}
            )

        return None
