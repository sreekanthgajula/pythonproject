import logging
from datetime import datetime, timezone
from paper_trading.portfolio import TradeRecord, VirtualPortfolio

logger = logging.getLogger(__name__)


def save_paper_trade(db, trade: TradeRecord) -> bool:
    """
    Saves a completed paper trade record to MongoDB collection 'paper_trades'.
    """
    if db is None:
        return False
    try:
        col = db["paper_trades"]
        doc = {
            "strategy_id": trade.strategy_id,
            "instrument_token": trade.instrument_token,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "quantity": trade.quantity,
            "entry_time": trade.entry_time,
            "exit_time": trade.exit_time,
            "realized_pnl": trade.realized_pnl,
            "return_pct": trade.return_pct,
            "exit_reason": trade.exit_reason,
            "bars_held": trade.bars_held,
            "recorded_at": datetime.now(timezone.utc).replace(tzinfo=None)
        }
        col.insert_one(doc)
        logger.info(f"[PAPER PERSIST] Saved trade [{trade.strategy_id}] PnL: ₹{trade.realized_pnl:,.2f}")
        return True
    except Exception as e:
        logger.error(f"[PAPER PERSIST] Error saving paper trade to DB: {e}")
        return False


def save_portfolio_snapshot(db, portfolio: VirtualPortfolio) -> bool:
    """
    Saves or updates a strategy virtual portfolio equity snapshot to MongoDB collection 'paper_portfolios'.
    """
    if db is None:
        return False
    try:
        col = db["paper_portfolios"]
        doc = {
            "strategy_id": portfolio.strategy_id,
            "initial_capital": portfolio.initial_capital,
            "cash": portfolio.cash,
            "total_equity": portfolio.total_equity,
            "realized_pnl": portfolio.realized_pnl,
            "unrealized_pnl": portfolio.unrealized_pnl,
            "win_rate": portfolio.win_rate,
            "profit_factor": portfolio.profit_factor,
            "open_positions_count": len(portfolio.positions),
            "total_trades_count": len(portfolio.closed_trades),
            "updated_at": datetime.now(timezone.utc).replace(tzinfo=None)
        }
        col.update_one({"strategy_id": portfolio.strategy_id}, {"$set": doc}, upsert=True)
        return True
    except Exception as e:
        logger.error(f"[PAPER PERSIST] Error saving portfolio snapshot to DB: {e}")
        return False
