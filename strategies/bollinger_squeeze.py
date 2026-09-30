import pandas as pd
import numpy as np
from typing import Optional
from datetime import datetime
from strategies.base import BaseStrategy, Signal


class BollingerSqueezeStrategy(BaseStrategy):
    """
    Bollinger Band Volatility Squeeze Breakout.
    Enters when Bollinger Bands compress to historically tight levels (indicating low volatility)
    and then price breaks through the Upper Band as volatility expands.
    """
    def __init__(self, strategy_id: str = "bb_squeeze_06", params: dict = None):
        default_params = {
            "period": 20,
            "num_std": 2.0,
            "squeeze_lookback": 20,
            "max_holding_bars": 20,
            "risk_reward": 2.0
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="Bollinger Band Squeeze",
            description="Trades directional breakouts following volatility compression.",
            params=default_params
        )

    def evaluate(self, candle: dict, rolling_df: pd.DataFrame, ticker_state=None) -> Optional[Signal]:
        n = self.params["period"]
        if rolling_df is None or len(rolling_df) < n + self.params["squeeze_lookback"]:
            return None

        closes = pd.to_numeric(rolling_df["close"], errors="coerce")
        sma = closes.rolling(window=n).mean()
        std = closes.rolling(window=n).std()

        upper_band = sma + (std * self.params["num_std"])
        lower_band = sma - (std * self.params["num_std"])
        bandwidth = (upper_band - lower_band) / sma

        # Was bandwidth squeezed to near its recent lows?
        min_bw = bandwidth.iloc[-self.params["squeeze_lookback"]: -1].min()
        recent_squeeze = bandwidth.iloc[-2] <= min_bw * 1.15

        current_close = float(candle["close"])
        curr_upper = float(upper_band.iloc[-1])
        curr_mid = float(sma.iloc[-1])

        # Breakout above upper band following squeeze
        if recent_squeeze and current_close > curr_upper:
            risk = current_close - curr_mid
            sl = round(curr_mid, 2)
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
                reason=f"BB Squeeze breakout: Close {current_close:.2f} > Upper {curr_upper:.2f} (BandWidth: {bandwidth.iloc[-1]:.4f})",
                metadata={"bandwidth": bandwidth.iloc[-1], "upper": curr_upper, "mid": curr_mid}
            )

        return None
