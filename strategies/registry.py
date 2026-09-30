import logging
from typing import List, Dict, Optional
from strategies.base import BaseStrategy
from strategies.darvas_box import DarvasBoxStrategy
from strategies.tsi_obv_trend import TSIOBVTrendStrategy
from strategies.rsi_pullback import RSIPullbackStrategy
from strategies.ema_atr_trend import EMAATRTrendStrategy
from strategies.volume_breakout import VolumeBreakoutStrategy
from strategies.bollinger_squeeze import BollingerSqueezeStrategy
from strategies.macd_zero_cross import MACDZeroCrossStrategy
from strategies.donchian_breakout import DonchianBreakoutStrategy
from strategies.stochastic_pullback import StochasticPullbackStrategy
from strategies.multi_timeframe import MultiTimeframeStrategy

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """
    Registry that instantiates, manages, and exposes all 10 automated trading strategies.
    Supports enable/disable toggling and dynamic strategy retrieval.
    """
    def __init__(self, data_manager=None):
        self.data_manager = data_manager
        self.strategies: Dict[str, BaseStrategy] = {}
        self._initialize_strategies()

    def _initialize_strategies(self):
        """Instantiates all 10 low-frequency strategies."""
        all_strats = [
            DarvasBoxStrategy(strategy_id="darvas_box_01"),
            TSIOBVTrendStrategy(strategy_id="tsi_obv_02"),
            RSIPullbackStrategy(strategy_id="rsi_pullback_03"),
            EMAATRTrendStrategy(strategy_id="ema_atr_04"),
            VolumeBreakoutStrategy(strategy_id="volume_breakout_05"),
            BollingerSqueezeStrategy(strategy_id="bb_squeeze_06"),
            MACDZeroCrossStrategy(strategy_id="macd_zero_07"),
            DonchianBreakoutStrategy(strategy_id="donchian_08"),
            StochasticPullbackStrategy(strategy_id="stoch_pullback_09"),
            MultiTimeframeStrategy(strategy_id="multi_tf_10", data_manager=self.data_manager),
        ]

        for s in all_strats:
            self.strategies[s.strategy_id] = s
            logger.info(f"Registered Strategy: [{s.strategy_id}] {s.name}")

    def get_all_strategies(self) -> List[BaseStrategy]:
        """Returns all registered strategies."""
        return list(self.strategies.values())

    def get_enabled_strategies(self) -> List[BaseStrategy]:
        """Returns only enabled strategies."""
        return [s for s in self.strategies.values() if s.enabled]

    def get_strategy(self, strategy_id: str) -> Optional[BaseStrategy]:
        """Retrieves a specific strategy by ID."""
        return self.strategies.get(strategy_id)

    def set_strategy_enabled(self, strategy_id: str, enabled: bool) -> bool:
        """Enables or disables a specific strategy."""
        strat = self.get_strategy(strategy_id)
        if strat:
            strat.enabled = enabled
            logger.info(f"Strategy [{strategy_id}] enabled set to: {enabled}")
            return True
        return False
