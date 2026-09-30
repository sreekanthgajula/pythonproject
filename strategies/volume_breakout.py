import pandas as pd
from typing import Optional
from datetime import datetime
from strategies.base import BaseStrategy, Signal


class VolumeBreakoutStrategy(BaseStrategy):
    """
    Volume Surge Price Breakout Strategy.
    Enters when price breaks out to a 20-period high supported by institutional
    volume expansion (> 1.8x average volume) with strong candle body closing near the high.
    """
    def __init__(self, strategy_id: str = "volume_breakout_05", params: dict = None):
        default_params = {
            "lookback_period": 20,
            "volume_multiplier": 1.8,
            "min_candle_pct": 0.003,    # Minimum 0.3% green candle
            "risk_reward": 2.0,
            "max_holding_bars": 20
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="Volume Surge Breakout",
            description="Trades breakouts to 20-period highs backed by heavy institutional volume.",
            params=default_params
        )

    def evaluate(self, candle: dict, rolling_df: pd.DataFrame, ticker_state=None) -> Optional[Signal]:
        n = self.params["lookback_period"]
        if rolling_df is None or len(rolling_df) < n + 1:
            return None

        # Lookback slice (excluding current candle)
        prior_window = rolling_df.iloc[-(n + 1): -1]
        prior_high = float(prior_window["high"].max())
        prior_low = float(prior_window["low"].min())
        avg_vol = float(prior_window["volume"].mean())

        current_close = float(candle["close"])
        current_open = float(candle["open"])
        current_high = float(candle["high"])
        current_low = float(candle["low"])
        current_volume = float(candle.get("volume", 0))

        # Check conditions
        candle_range = current_high - current_low
        is_breakout = current_close > prior_high
        is_bullish = current_close > current_open and (current_close - current_open) / current_open >= self.params["min_candle_pct"]
        is_vol_surge = avg_vol > 0 and current_volume >= (avg_vol * self.params["volume_multiplier"])
        closes_near_high = (candle_range == 0) or ((current_high - current_close) / candle_range <= 0.35)

        if is_breakout and is_bullish and is_vol_surge and closes_near_high:
            risk = current_close - prior_low
            if risk <= 0:
                risk = current_close * 0.015

            sl = round(max(prior_low, current_close * 0.98), 2)
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
                reason=f"Volume breakout: Close {current_close:.2f} > 20-High {prior_high:.2f} with {current_volume:,} vol",
                metadata={"prior_high": prior_high, "avg_volume": avg_vol, "volume": current_volume}
            )

        return None
