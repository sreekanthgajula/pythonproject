import logging
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd

from strategies.registry import StrategyRegistry
from paper_trading.portfolio import VirtualPortfolio, Position
from paper_trading.persistence import save_paper_trade, save_portfolio_snapshot

logger = logging.getLogger(__name__)


class PaperTradingEngine:
    """
    Automated Multi-Strategy Paper Trading Engine.
    Executes and evaluates 10 low-frequency strategies side-by-side in isolated virtual sub-portfolios.
    """
    def __init__(self, data_manager=None, initial_capital: float = 100000.0):
        self.data_manager = data_manager
        self.initial_capital = initial_capital
        self.registry = StrategyRegistry(data_manager=self.data_manager)
        self.portfolios: Dict[str, VirtualPortfolio] = {}

        # Instantiate an isolated virtual portfolio for each registered strategy
        for strat in self.registry.get_all_strategies():
            self.portfolios[strat.strategy_id] = VirtualPortfolio(
                strategy_id=strat.strategy_id,
                initial_capital=initial_capital
            )

    def on_candle(self, candle: dict, rolling_df: pd.DataFrame, ticker_state=None):
        """
        Callback triggered whenever a 10-minute candle closes.
        1. Updates open positions for all strategies and checks exit triggers.
        2. Evaluates signals for enabled strategies and executes buys.
        3. Saves snapshots to database if available.
        """
        token = candle.get("instrument_token", 0)
        close_p = float(candle["close"])
        high_p = float(candle["high"])
        low_p = float(candle["low"])
        ts = candle.get("timestamp", datetime.utcnow())

        # Step 1: Position Monitoring & Exit Evaluation across all portfolios
        for strat_id, portfolio in self.portfolios.items():
            if token in portfolio.positions:
                pos: Position = portfolio.positions[token]
                pos.bars_held += 1
                pos.current_price = close_p

                exit_triggered = False
                exit_price = close_p
                reason = ""

                # Check Stop Loss (Low breached SL)
                if low_p <= pos.stop_loss:
                    exit_triggered = True
                    exit_price = pos.stop_loss
                    reason = f"Stop Loss Hit ({low_p:.2f} <= SL {pos.stop_loss:.2f})"
                # Check Profit Target (High reached Target)
                elif high_p >= pos.target_price:
                    exit_triggered = True
                    exit_price = pos.target_price
                    reason = f"Target Price Hit ({high_p:.2f} >= TP {pos.target_price:.2f})"
                # Check Max Holding Period
                elif pos.bars_held >= pos.max_holding_bars:
                    exit_triggered = True
                    exit_price = close_p
                    reason = f"Max Holding Bars Expired ({pos.bars_held} >= {pos.max_holding_bars})"

                if exit_triggered:
                    trade = portfolio.close_position(token, exit_price, ts, reason)
                    if trade:
                        logger.info(
                            f" ❌ [PAPER EXIT] [{strat_id}] Closed Token {token} at {exit_price:.2f} | "
                            f"PnL: ₹{trade.realized_pnl:,.2f} ({trade.return_pct:+.2f}%) | Reason: {reason}"
                        )
                        if self.data_manager:
                            save_paper_trade(self.data_manager.db, trade)
                            save_portfolio_snapshot(self.data_manager.db, portfolio)

        # Step 2: Signal Evaluation & Order Execution for enabled strategies
        for strat in self.registry.get_enabled_strategies():
            portfolio = self.portfolios[strat.strategy_id]
            
            # Skip if already holding a position in this instrument
            if token in portfolio.positions:
                continue

            try:
                signal = strat.evaluate(candle, rolling_df, ticker_state)
                if signal and signal.action == "BUY":
                    pos = portfolio.open_position(
                        instrument_token=token,
                        price=signal.price,
                        timestamp=signal.timestamp,
                        stop_loss=signal.stop_loss or (signal.price * 0.98),
                        target_price=signal.target_price or (signal.price * 1.04),
                        max_holding_bars=signal.max_holding_bars or 20
                    )
                    if pos:
                        logger.info(
                            f" 🚀 [PAPER ENTRY] [{strat.strategy_id}] BOUGHT {pos.quantity} units of Token {token} "
                            f"at ₹{pos.entry_price:.2f} | SL: ₹{pos.stop_loss:.2f} | TP: ₹{pos.target_price:.2f} | "
                            f"Reason: {signal.reason}"
                        )
                        if self.data_manager:
                            save_portfolio_snapshot(self.data_manager.db, portfolio)
            except Exception as e:
                logger.error(f"Error evaluating strategy [{strat.strategy_id}]: {e}")

    def get_performance_summary(self) -> List[dict]:
        """Returns structured performance comparison data across all 10 strategies."""
        summary = []
        for strat in self.registry.get_all_strategies():
            portfolio = self.portfolios[strat.strategy_id]
            summary.append({
                "strategy_id": strat.strategy_id,
                "name": strat.name,
                "total_equity": portfolio.total_equity,
                "realized_pnl": portfolio.realized_pnl,
                "unrealized_pnl": portfolio.unrealized_pnl,
                "win_rate": portfolio.win_rate,
                "profit_factor": portfolio.profit_factor,
                "open_positions": len(portfolio.positions),
                "total_trades": len(portfolio.closed_trades)
            })

        # Sort leaderboard by Total Equity descending
        summary.sort(key=lambda x: x["total_equity"], reverse=True)
        return summary

    def print_summary(self):
        """Prints an ASCII Leaderboard comparing all 10 strategy sub-portfolios."""
        summary = self.get_performance_summary()
        header = (
            "\n" + "=" * 95 + "\n"
            f"{'RANK':<5} | {'STRATEGY ID':<16} | {'NAME':<28} | {'EQUITY (₹)':<12} | {'PNL (₹)':<10} | {'WIN %':<7} | {'TRADES':<6}\n"
            + "-" * 95
        )
        lines = [header]
        for rank, s in enumerate(summary, start=1):
            line = (
                f"{rank:<5} | {s['strategy_id']:<16} | {s['name']:<28} | "
                f"₹{s['total_equity']:>10,.2f} | ₹{s['realized_pnl']:>8,.2f} | "
                f"{s['win_rate']:>5.1f}% | {s['total_trades']:>6}"
            )
            lines.append(line)
        lines.append("=" * 95 + "\n")
        logger.info("\n".join(lines))
