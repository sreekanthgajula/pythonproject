from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
import pandas as pd


@dataclass
class Signal:
    """
    Standardized trading signal emitted by a strategy.
    """
    strategy_id: str
    action: str  # "BUY", "SELL", "CLOSE", "HOLD"
    instrument_token: int
    price: float
    timestamp: datetime
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    max_holding_bars: Optional[int] = None
    confidence: float = 1.0
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """
    Abstract base class for all low-frequency trading strategies.
    Every strategy encapsulates its own parameters, indicator requirements,
    and entry/exit evaluation logic.
    """
    def __init__(self, strategy_id: str, name: str, description: str = "", params: Optional[Dict[str, Any]] = None):
        self.strategy_id = strategy_id
        self.name = name
        self.description = description
        self.params = params or {}
        self.enabled = True

    @abstractmethod
    def evaluate(self, candle: dict, rolling_df: pd.DataFrame, ticker_state=None) -> Optional[Signal]:
        """
        Evaluates the current candle and rolling price/indicator data.
        
        Args:
            candle (dict): Closed candle document with OHLCV data.
            rolling_df (pd.DataFrame): In-memory rolling window of recent candles with indicators.
            ticker_state: Optional incremental state object (e.g. indicators.TickerState).
            
        Returns:
            Optional[Signal]: A Signal instance if entry/exit triggered, otherwise None.
        """
        pass

    def __repr__(self):
        return f"<Strategy [{self.strategy_id}] {self.name} (enabled={self.enabled})>"
