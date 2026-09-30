from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any


@dataclass
class Position:
    """
    Represents an active paper trading position held by a virtual portfolio.
    """
    strategy_id: str
    instrument_token: int
    entry_price: float
    quantity: int
    entry_time: datetime
    stop_loss: float
    target_price: float
    max_holding_bars: int = 20
    bars_held: int = 0
    current_price: float = 0.0

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.entry_price) * self.quantity


@dataclass
class TradeRecord:
    """
    Represents a closed trade with realized performance metadata.
    """
    strategy_id: str
    instrument_token: int
    entry_price: float
    exit_price: float
    quantity: int
    entry_time: datetime
    exit_time: datetime
    realized_pnl: float
    return_pct: float
    exit_reason: str
    bars_held: int


class VirtualPortfolio:
    """
    Virtual portfolio ledger for an isolated trading strategy.
    Tracks virtual cash balance, active open positions, and closed trades history.
    """
    def __init__(self, strategy_id: str, initial_capital: float = 100000.0):
        self.strategy_id = strategy_id
        self.initial_capital = float(initial_capital)
        self.cash = float(initial_capital)
        self.positions: Dict[int, Position] = {}  # instrument_token -> Position
        self.closed_trades: List[TradeRecord] = []

    @property
    def invested_capital(self) -> float:
        return sum(pos.entry_price * pos.quantity for pos in self.positions.values())

    @property
    def current_market_value(self) -> float:
        return sum(pos.current_price * pos.quantity for pos in self.positions.values())

    @property
    def total_equity(self) -> float:
        return self.cash + self.current_market_value

    @property
    def realized_pnl(self) -> float:
        return sum(trade.realized_pnl for trade in self.closed_trades)

    @property
    def unrealized_pnl(self) -> float:
        return sum(pos.unrealized_pnl for pos in self.positions.values())

    @property
    def win_rate(self) -> float:
        if not self.closed_trades:
            return 0.0
        winning_trades = sum(1 for t in self.closed_trades if t.realized_pnl > 0)
        return (winning_trades / len(self.closed_trades)) * 100.0

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.realized_pnl for t in self.closed_trades if t.realized_pnl > 0)
        gross_loss = abs(sum(t.realized_pnl for t in self.closed_trades if t.realized_pnl < 0))
        if gross_loss == 0:
            return gross_profit if gross_profit > 0 else 1.0
        return gross_profit / gross_loss

    def can_open_position(self, allocation_pct: float = 0.20) -> bool:
        """Determines if sufficient unallocated virtual cash is available for a new trade."""
        required_cash = self.total_equity * allocation_pct
        return self.cash >= required_cash and required_cash > 0

    def open_position(
        self,
        instrument_token: int,
        price: float,
        timestamp: datetime,
        stop_loss: float,
        target_price: float,
        max_holding_bars: int = 20,
        allocation_pct: float = 0.20
    ) -> Optional[Position]:
        """Executes a virtual buy order and records an open position."""
        if instrument_token in self.positions:
            return None  # Already holding position in this instrument

        capital_to_allocate = self.total_equity * allocation_pct
        if capital_to_allocate > self.cash:
            capital_to_allocate = self.cash

        quantity = int(capital_to_allocate // price)
        if quantity <= 0:
            return None

        cost = price * quantity
        self.cash -= cost

        pos = Position(
            strategy_id=self.strategy_id,
            instrument_token=instrument_token,
            entry_price=price,
            quantity=quantity,
            entry_time=timestamp,
            stop_loss=stop_loss,
            target_price=target_price,
            max_holding_bars=max_holding_bars,
            bars_held=0,
            current_price=price
        )

        self.positions[instrument_token] = pos
        return pos

    def close_position(
        self,
        instrument_token: int,
        exit_price: float,
        timestamp: datetime,
        reason: str
    ) -> Optional[TradeRecord]:
        """Closes an open position and updates portfolio cash balance & trade metrics."""
        pos = self.positions.pop(instrument_token, None)
        if not pos:
            return None

        proceeds = exit_price * pos.quantity
        self.cash += proceeds
        pnl = proceeds - (pos.entry_price * pos.quantity)
        ret_pct = ((exit_price - pos.entry_price) / pos.entry_price) * 100.0

        record = TradeRecord(
            strategy_id=self.strategy_id,
            instrument_token=instrument_token,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            quantity=pos.quantity,
            entry_time=pos.entry_time,
            exit_time=timestamp,
            realized_pnl=pnl,
            return_pct=ret_pct,
            exit_reason=reason,
            bars_held=pos.bars_held
        )

        self.closed_trades.append(record)
        return record
