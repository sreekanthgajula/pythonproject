import pandas as pd
from typing import Optional
from datetime import datetime
from strategies.base import BaseStrategy, Signal


class TSIOBVTrendStrategy(BaseStrategy):
    """
    True Strength Index (TSI) + On-Balance Volume (OBV) Momentum Strategy.
    Capitalizes on institutional volume accumulation when TSI crosses into
    bullish territory while OBV is trending above its moving average.
    """
    def __init__(self, strategy_id: str = "tsi_obv_02", params: dict = None):
        default_params = {
            "tsi_threshold": -5.0,     # TSI crosses upward from below or near zero
            "obv_ma_period": 9,        # OBV moving average window
            "stop_loss_pct": 0.015,    # 1.5% stop loss
            "take_profit_pct": 0.030,  # 3.0% take profit
            "max_holding_bars": 18     # 18 bars (3 hours on 10m candles)
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="TSI & OBV Trend Momentum",
            description="Trades bullish momentum when TSI crosses above zero and OBV confirms accumulation.",
            params=default_params
        )

    def evaluate(self, candle: dict, rolling_df: pd.DataFrame, ticker_state=None) -> Optional[Signal]:
        current_close = float(candle["close"])
        
        # Check if we can evaluate from ticker_state (O(1))
        if ticker_state and len(ticker_state.tsi_history) >= 2 and len(ticker_state.obv_history) >= self.params["obv_ma_period"]:
            tsi_curr = ticker_state.tsi
            tsi_prev = ticker_state.tsi_history[-2]
            obv_curr = ticker_state.obv
            obv_ma = sum(ticker_state.obv_history[-self.params["obv_ma_period"]:]) / float(self.params["obv_ma_period"])

            # Trigger condition: TSI crosses up, OBV > OBV_SMA
            tsi_crossover = (tsi_prev <= self.params["tsi_threshold"] and tsi_curr > self.params["tsi_threshold"])
            obv_bullish = (obv_curr > obv_ma)

            if tsi_crossover and obv_bullish:
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
                    reason=f"TSI bullish cross ({tsi_prev:.2f} -> {tsi_curr:.2f}) with OBV above {self.params['obv_ma_period']}-SMA",
                    metadata={"tsi": tsi_curr, "obv": obv_curr, "obv_ma": obv_ma}
                )

        # Fallback to rolling_df if columns exist
        if rolling_df is not None and len(rolling_df) >= self.params["obv_ma_period"] + 2:
            if "tsi" in rolling_df.columns and "obv" in rolling_df.columns:
                tsi_curr = float(rolling_df["tsi"].iloc[-1])
                tsi_prev = float(rolling_df["tsi"].iloc[-2])
                obv_series = rolling_df["obv"]
                obv_curr = float(obv_series.iloc[-1])
                obv_ma = float(obv_series.iloc[-self.params["obv_ma_period"]:].mean())

                if (tsi_prev <= self.params["tsi_threshold"] and tsi_curr > self.params["tsi_threshold"]) and (obv_curr > obv_ma):
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
                        reason=f"TSI cross ({tsi_prev:.2f} -> {tsi_curr:.2f}) & OBV accumulation",
                        metadata={"tsi": tsi_curr, "obv": obv_curr, "obv_ma": obv_ma}
                    )

        return None
