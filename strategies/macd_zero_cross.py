import pandas as pd
from typing import Optional
from datetime import datetime
from strategies.base import BaseStrategy, Signal


def compute_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal_period: int = 9):
    """Calculates MACD Line, Signal Line, and Histogram."""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


class MACDZeroCrossStrategy(BaseStrategy):
    """
    MACD Zero-Line Trend Strategy.
    Enters when the MACD line crosses above the zero line with an expanding histogram,
    signaling momentum acceleration into positive territory.
    """
    def __init__(self, strategy_id: str = "macd_zero_07", params: dict = None):
        default_params = {
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9,
            "stop_loss_pct": 0.018,    # 1.8% stop loss
            "take_profit_pct": 0.036,  # 3.6% target price
            "max_holding_bars": 25     # Max 25 bars holding
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="MACD Zero-Line Trend",
            description="Buys when MACD line crosses above 0 line with histogram expansion.",
            params=default_params
        )

    def evaluate(self, candle: dict, rolling_df: pd.DataFrame, ticker_state=None) -> Optional[Signal]:
        min_len = self.params["slow_period"] + self.params["signal_period"] + 2
        if rolling_df is None or len(rolling_df) < min_len:
            return None

        closes = pd.to_numeric(rolling_df["close"], errors="coerce")
        macd_line, signal_line, hist = compute_macd(
            closes,
            fast=self.params["fast_period"],
            slow=self.params["slow_period"],
            signal_period=self.params["signal_period"]
        )

        curr_macd = float(macd_line.iloc[-1])
        prev_macd = float(macd_line.iloc[-2])
        curr_hist = float(hist.iloc[-1])
        prev_hist = float(hist.iloc[-2])

        # Cross above 0 line and expanding histogram
        is_zero_cross = (prev_macd <= 0.0) and (curr_macd > 0.0)
        is_hist_expanding = curr_hist > prev_hist and curr_hist > 0

        current_close = float(candle["close"])

        if is_zero_cross and is_hist_expanding:
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
                reason=f"MACD Zero Cross: {prev_macd:.4f} -> {curr_macd:.4f} with Hist expansion ({curr_hist:.4f})",
                metadata={"macd": curr_macd, "signal": float(signal_line.iloc[-1]), "histogram": curr_hist}
            )

        return None
