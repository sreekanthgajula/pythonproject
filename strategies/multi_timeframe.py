import pandas as pd
from typing import Optional
from datetime import datetime
from strategies.base import BaseStrategy, Signal


class MultiTimeframeStrategy(BaseStrategy):
    """
    Multi-Timeframe Trend Confirmation Strategy.
    Ensures that the primary macro trend (from monthly, weekly, daily, or manual watchlists
    or a 100-period baseline SMA) is bullish before executing short-term 10-minute pullback buys.
    """
    def __init__(self, strategy_id: str = "multi_tf_10", params: dict = None, data_manager=None):
        default_params = {
            "macro_ma_period": 100,    # 100-period baseline SMA on 10-min candles
            "short_ema_fast": 10,
            "short_ema_slow": 20,
            "stop_loss_pct": 0.015,    # 1.5% stop loss
            "target_reward_ratio": 2.0,# 2:1 Reward to Risk
            "max_holding_bars": 25,    # Max 25 bars holding
            "target_timeframes": ["monthly", "weekly", "daily", "manual"]
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="Multi-Timeframe Trend Confirmation",
            description="Confirms macro trend (Monthly/Weekly/Daily/Manual watchlists & 100-SMA) before entering 10m momentum pullbacks.",
            params=default_params
        )
        self.data_manager = data_manager

    def evaluate(self, candle: dict, rolling_df: pd.DataFrame, ticker_state=None) -> Optional[Signal]:
        min_len = self.params["macro_ma_period"] + 5
        if rolling_df is None or len(rolling_df) < min_len:
            return None

        closes = pd.to_numeric(rolling_df["close"], errors="coerce")
        macro_ma = float(closes.rolling(window=self.params["macro_ma_period"]).mean().iloc[-1])
        current_close = float(candle["close"])

        # 1. Check macro trend filter (100-period baseline SMA)
        if current_close < macro_ma:
            return None

        # 2. Check watchlist filter if data_manager and symbol are available
        symbol = candle.get("symbol")
        timeframe_found = None
        if self.data_manager and symbol:
            for tf in self.params["target_timeframes"]:
                try:
                    records = self.data_manager.get_stock_ratings(table_name=tf, symbol=symbol)
                    if records:
                        timeframe_found = tf
                        break
                except Exception:
                    pass

        # 3. Short-term 10m momentum confirmation (10 EMA crossing above 20 EMA)
        ema_fast = closes.ewm(span=self.params["short_ema_fast"], adjust=False).mean()
        ema_slow = closes.ewm(span=self.params["short_ema_slow"], adjust=False).mean()

        curr_fast = float(ema_fast.iloc[-1])
        prev_fast = float(ema_fast.iloc[-2])
        curr_slow = float(ema_slow.iloc[-1])
        prev_slow = float(ema_slow.iloc[-2])

        is_short_crossover = (prev_fast <= prev_slow) and (curr_fast > curr_slow)

        if is_short_crossover:
            sl = round(current_close * (1.0 - self.params["stop_loss_pct"]), 2)
            risk = current_close - sl
            tp = round(current_close + (risk * self.params["target_reward_ratio"]), 2)

            tf_info = f" (Watchlist: {timeframe_found.upper()})" if timeframe_found else ""
            return Signal(
                strategy_id=self.strategy_id,
                action="BUY",
                instrument_token=candle.get("instrument_token", 0),
                price=current_close,
                timestamp=candle.get("timestamp", datetime.utcnow()),
                stop_loss=sl,
                target_price=tp,
                max_holding_bars=self.params["max_holding_bars"],
                reason=f"Multi-Timeframe Bullish Alignment{tf_info}: Close {current_close:.2f} > 100-SMA ({macro_ma:.2f}) & 10/20 EMA Cross",
                metadata={"macro_ma": macro_ma, "watchlist": timeframe_found, "fast_ema": curr_fast, "slow_ema": curr_slow}
            )

        return None
