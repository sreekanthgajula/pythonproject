import pandas as pd
from typing import Optional
from datetime import datetime
from strategies.base import BaseStrategy, Signal


class DonchianBreakoutStrategy(BaseStrategy):
    """
    Donchian Channel Turtle Breakout Strategy.
    Enters on a 20-period upper channel breakout and sets stop-loss at 10-period channel low.
    """
    def __init__(self, strategy_id: str = "donchian_08", params: dict = None):
        default_params = {
            "entry_period": 20,
            "exit_period": 10,
            "max_holding_bars": 30,
            "risk_reward": 2.0
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="Donchian Channel Turtle",
            description="Trades 20-period high breakouts with 10-period low exits.",
            params=default_params
        )

    def evaluate(self, candle: dict, rolling_df: pd.DataFrame, ticker_state=None) -> Optional[Signal]:
        n_entry = self.params["entry_period"]
        n_exit = self.params["exit_period"]
        if rolling_df is None or len(rolling_df) < max(n_entry, n_exit) + 1:
            return None

        # Prior window excluding current candle
        window = rolling_df.iloc[-(n_entry + 1): -1]
        donchian_high = float(window["high"].max())
        exit_low = float(rolling_df.iloc[-(n_exit + 1): -1]["low"].min())

        current_close = float(candle["close"])

        if current_close > donchian_high:
            sl = round(exit_low, 2)
            if sl >= current_close:
                sl = round(current_close * 0.98, 2)
            risk = current_close - sl
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
                reason=f"Donchian breakout: Close {current_close:.2f} > 20-Bar High {donchian_high:.2f}",
                metadata={"donchian_high": donchian_high, "exit_low": exit_low}
            )

        return None
