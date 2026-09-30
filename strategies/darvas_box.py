import pandas as pd
from typing import Optional
from datetime import datetime
from strategies.base import BaseStrategy, Signal


class DarvasBoxStrategy(BaseStrategy):
    """
    Darvas Box Breakout Strategy.
    Identifies consolidation boxes (high-low ranges) and buys when price
    breaks above the box top on above-average volume.
    """
    def __init__(self, strategy_id: str = "darvas_box_01", params: dict = None):
        default_params = {
            "box_period": 15,          # Lookback window to define the box
            "volume_factor": 1.25,     # Volume must exceed average by this factor
            "risk_reward_ratio": 2.0,  # Target is 2x the box height
            "max_holding_bars": 25,    # Maximum bars to hold
            "box_threshold_pct": 0.04  # Box height must be under 4% to ensure consolidation
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="Darvas Box Breakout",
            description="Trades breakouts from tight consolidation boxes with volume confirmation.",
            params=default_params
        )

    def evaluate(self, candle: dict, rolling_df: pd.DataFrame, ticker_state=None) -> Optional[Signal]:
        box_len = self.params["box_period"]
        if rolling_df is None or len(rolling_df) < box_len + 1:
            return None

        # Take the lookback slice preceding the current candle
        window = rolling_df.iloc[-(box_len + 1): -1]
        box_high = float(window["high"].max())
        box_low = float(window["low"].min())
        avg_volume = float(window["volume"].mean())

        current_close = float(candle["close"])
        current_volume = float(candle.get("volume", 0))

        # Check if the preceding range was a tight consolidation
        box_height = box_high - box_low
        if box_low <= 0 or (box_height / box_low) > self.params["box_threshold_pct"]:
            return None

        # Breakout condition: Close breaks above box_high with volume surge
        if current_close > box_high and current_volume >= (avg_volume * self.params["volume_factor"]):
            stop_loss = round(box_low, 2)
            target = round(current_close + (box_height * self.params["risk_reward_ratio"]), 2)

            return Signal(
                strategy_id=self.strategy_id,
                action="BUY",
                instrument_token=candle.get("instrument_token", 0),
                price=current_close,
                timestamp=candle.get("timestamp", datetime.utcnow()),
                stop_loss=stop_loss,
                target_price=target,
                max_holding_bars=self.params["max_holding_bars"],
                reason=f"Darvas Box breakout: Close {current_close:.2f} > BoxHigh {box_high:.2f} (Vol: {current_volume:,} vs Avg: {avg_volume:,.0f})",
                metadata={"box_high": box_high, "box_low": box_low, "box_height": box_height}
            )

        return None
