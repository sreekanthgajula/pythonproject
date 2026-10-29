"""
===============================================================================
ADVANCED SUPERTREND TRADING STRATEGY & EVENING PRO BUYING SCANNER (NSE EQUITIES)
===============================================================================
A production-ready, quantitative trading strategy utilizing:
  1. Primary Supertrend (ATR 10, Multiplier 3.0) with state-machine band tracking
  2. EMA 50 Trend Filter (Long when Close > EMA50, Short when Close < EMA50)
  3. Supertrend Line Trailing Stop Loss Exit
  4. Optional Multi-Timeframe Confirmation (Higher Timeframe Supertrend alignment)
  5. Optional Volume Expansion Filter (Volume > 1.2x 20-period Volume SMA)
  6. Dynamic ATR / Supertrend-based Position Sizing (% Capital at Risk)
  7. Multi-Mode Execution: Long-Only, Long-Short, or Short-Only
  8. Full Backtesting Engine with Trade Log, Equity Curve & Institutional Metrics

Technical Architecture: Pure Pandas & NumPy (No external TA-Lib dependencies).
===============================================================================
"""

import math
import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List, Union

import numpy as np
import pandas as pd
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from tradingagents.dataflows.symbol_utils import normalize_symbol
from data_manager import DataManager

load_dotenv(dotenv_path=project_root / ".env")
logger = logging.getLogger(__name__)


# =============================================================================
# 1. PURE PANDAS & NUMPY TECHNICAL INDICATOR FUNCTIONS
# =============================================================================

def ema(series: pd.Series, period: int = 50) -> pd.Series:
    """
    Exponential Moving Average (EMA) calculated using pure pandas.
    Uses adjust=False to match standard TradingView and exchange implementations.
    """
    if not isinstance(series, pd.Series):
        series = pd.Series(series)
    return series.ewm(span=period, adjust=False).mean()


def calculate_atr(df: pd.DataFrame, period: int = 10) -> pd.Series:
    """
    Average True Range (ATR) calculated using Wilder's smoothing.
    Wilder's Smoothing is equivalent to exponential moving average with alpha = 1 / period.
    """
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)

    tr0 = high - low
    tr1 = (high - close_prev).abs()
    tr2 = (low - close_prev).abs()
    tr = pd.concat([tr0, tr1, tr2], axis=1).max(axis=1)

    # Wilder's Smoothing: ewm with alpha=1/period, adjust=False
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return atr


def supertrend(
    df: pd.DataFrame,
    period: int = 10,
    multiplier: float = 3.0
) -> Tuple[pd.Series, pd.Series]:
    """
    Calculates the canonical Supertrend indicator using pure pandas and numpy.

    Formula:
      - Basic Upper Band = (High + Low) / 2 + (Multiplier * ATR)
      - Basic Lower Band = (High + Low) / 2 - (Multiplier * ATR)
      - Final Upper Band = Basic Upper if (Basic Upper < Prev Final Upper or Prev Close > Prev Final Upper) else Prev Final Upper
      - Final Lower Band = Basic Lower if (Basic Lower > Prev Final Lower or Prev Close < Prev Final Lower) else Prev Final Lower
      - Trend Direction = +1 (Bullish/Green) or -1 (Bearish/Red)
      - Supertrend Line = Final Lower Band (if Bullish) else Final Upper Band (if Bearish)

    Returns:
        Tuple[pd.Series, pd.Series]: (supertrend_line, supertrend_direction)
        direction: +1 for Bullish (Green), -1 for Bearish (Red)
    """
    n = len(df)
    if n == 0:
        empty_s = pd.Series(dtype=float)
        return empty_s, pd.Series(dtype=int)

    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    close = df["close"].values.astype(float)

    atr = calculate_atr(df, period=period).values.astype(float)
    hl2 = (high + low) / 2.0

    basic_upper = hl2 + (multiplier * atr)
    basic_lower = hl2 - (multiplier * atr)

    final_upper = np.zeros(n, dtype=float)
    final_lower = np.zeros(n, dtype=float)
    st_line = np.zeros(n, dtype=float)
    direction = np.zeros(n, dtype=int)

    for i in range(n):
        if i == 0:
            final_upper[i] = basic_upper[i]
            final_lower[i] = basic_lower[i]
            direction[i] = 1 if close[i] >= basic_lower[i] else -1
            st_line[i] = final_lower[i] if direction[i] == 1 else final_upper[i]
            continue

        # Final Upper Band logic
        if basic_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i - 1]

        # Final Lower Band logic
        if basic_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = final_lower[i - 1]

        # Trend Direction transition
        prev_dir = direction[i - 1]
        if prev_dir == 1:
            if close[i] < final_lower[i]:
                direction[i] = -1
                st_line[i] = final_upper[i]
            else:
                direction[i] = 1
                st_line[i] = final_lower[i]
        else:
            if close[i] > final_upper[i]:
                direction[i] = 1
                st_line[i] = final_lower[i]
            else:
                direction[i] = -1
                st_line[i] = final_upper[i]

    st_series = pd.Series(st_line, index=df.index, name="supertrend")
    dir_series = pd.Series(direction, index=df.index, name="supertrend_direction")
    return st_series, dir_series


# =============================================================================
# 2. ADVANCED SUPERTREND STRATEGY CLASS
# =============================================================================

class AdvancedSupertrendStrategy:
    """
    Advanced Multi-Timeframe Supertrend Strategy with EMA-50 and Volume Filters
    tailored for Indian Equities (NSE).
    """

    def __init__(
        self,
        atr_period: int = 10,
        multiplier: float = 3.0,
        ema_period: int = 50,
        risk_per_trade: float = 0.01,
        mode: str = "long_only",
        use_mtf: bool = False,
        htf_atr_period: int = 10,
        htf_multiplier: float = 3.0,
        use_volume_filter: bool = False,
        volume_sma_period: int = 20,
        volume_multiplier: float = 1.2,
        stop_type: str = "supertrend",
        atr_stop_multiplier: float = 1.5,
    ):
        """
        Initializes the Advanced Supertrend Strategy parameters.

        Args:
            atr_period (int): Lookback period for ATR (default 10).
            multiplier (float): Supertrend ATR band multiplier (default 3.0).
            ema_period (int): EMA trend filter period (default 50).
            risk_per_trade (float): Capital percentage risked per trade (default 0.01 = 1%).
            mode (str): Execution mode ('long_only', 'long_short', 'short_only').
            use_mtf (bool): Enable higher timeframe Supertrend confirmation.
            htf_atr_period (int): ATR period for higher timeframe.
            htf_multiplier (float): Multiplier for higher timeframe Supertrend.
            use_volume_filter (bool): Enable volume expansion confirmation.
            volume_sma_period (int): Period for volume moving average (default 20).
            volume_multiplier (float): Factor required above volume SMA (default 1.2x).
            stop_type (str): Stop loss distance basis: 'supertrend' or 'atr'.
            atr_stop_multiplier (float): Stop distance multiplier if stop_type='atr'.
        """
        self.atr_period = atr_period
        self.multiplier = multiplier
        self.ema_period = ema_period
        self.risk_per_trade = risk_per_trade

        valid_modes = {"long_only", "long_short", "short_only"}
        if mode.lower() not in valid_modes:
            raise ValueError(f"Invalid mode '{mode}'. Must be one of {valid_modes}")
        self.mode = mode.lower()

        self.use_mtf = use_mtf
        self.htf_atr_period = htf_atr_period
        self.htf_multiplier = htf_multiplier

        self.use_volume_filter = use_volume_filter
        self.volume_sma_period = volume_sma_period
        self.volume_multiplier = volume_multiplier

        valid_stops = {"supertrend", "atr"}
        if stop_type.lower() not in valid_stops:
            raise ValueError(f"Invalid stop_type '{stop_type}'. Must be one of {valid_stops}")
        self.stop_type = stop_type.lower()
        self.atr_stop_multiplier = atr_stop_multiplier

    def _normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensures DataFrame has standardized column names and sorted datetime index."""
        if df is None or df.empty:
            return pd.DataFrame()

        norm = df.copy()
        col_map = {c: c.strip().lower() for c in norm.columns}
        norm = norm.rename(columns=col_map)

        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(norm.columns):
            missing = required - set(norm.columns)
            raise ValueError(f"Input DataFrame is missing required columns: {missing}")

        # Ensure date column exists or index is datetime
        if "date" in norm.columns:
            if not pd.api.types.is_datetime64_any_dtype(norm["date"]):
                norm["date"] = pd.to_datetime(norm["date"])
            norm = norm.sort_values("date").reset_index(drop=True)
        elif isinstance(norm.index, pd.DatetimeIndex):
            norm["date"] = norm.index
            norm = norm.reset_index(drop=True)

        return norm

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates all technical indicators: ATR, Supertrend, EMA 50, and Volume SMA.
        """
        df_norm = self._normalize_dataframe(df)
        if len(df_norm) < max(self.atr_period, self.ema_period):
            return df_norm

        # 1. ATR & Supertrend
        df_norm["atr"] = calculate_atr(df_norm, period=self.atr_period)
        st_line, st_dir = supertrend(df_norm, period=self.atr_period, multiplier=self.multiplier)
        df_norm["supertrend"] = st_line
        df_norm["supertrend_direction"] = st_dir

        # Supertrend Flip detection (+1 = green flip, -1 = red flip, 0 = continuation)
        prev_dir = df_norm["supertrend_direction"].shift(1).fillna(0).astype(int)
        curr_dir = df_norm["supertrend_direction"].astype(int)
        df_norm["st_flip_green"] = (prev_dir == -1) & (curr_dir == 1)
        df_norm["st_flip_red"] = (prev_dir == 1) & (curr_dir == -1)

        # 2. Trend Filter: EMA 50
        df_norm["ema_50"] = ema(df_norm["close"], period=self.ema_period)
        df_norm["close_above_ema50"] = df_norm["close"] > df_norm["ema_50"]
        df_norm["close_below_ema50"] = df_norm["close"] < df_norm["ema_50"]

        # 3. Volume Filter: Volume SMA 20
        df_norm["vol_sma"] = df_norm["volume"].rolling(self.volume_sma_period).mean()
        df_norm["volume_surge"] = df_norm["volume"] > (df_norm["vol_sma"] * self.volume_multiplier)

        return df_norm

    def _resolve_htf_direction(
        self,
        main_df: pd.DataFrame,
        higher_tf_df: Optional[pd.DataFrame] = None
    ) -> pd.Series:
        """Computes or aligns higher-timeframe Supertrend direction."""
        n = len(main_df)
        if not self.use_mtf:
            return pd.Series(np.ones(n, dtype=int), index=main_df.index)

        # 1. External higher timeframe provided
        if higher_tf_df is not None and not higher_tf_df.empty:
            htf_norm = self._normalize_dataframe(higher_tf_df)
            _, htf_dir = supertrend(htf_norm, period=self.htf_atr_period, multiplier=self.htf_multiplier)
            htf_norm["htf_dir"] = htf_dir

            if "date" in main_df.columns and "date" in htf_norm.columns:
                merged = pd.merge_asof(
                    main_df[["date"]],
                    htf_norm[["date", "htf_dir"]],
                    on="date",
                    direction="backward"
                )
                return merged["htf_dir"].fillna(1).astype(int)

        # 2. Resample from main DataFrame if date is available
        if "date" in main_df.columns and pd.api.types.is_datetime64_any_dtype(main_df["date"]):
            try:
                temp = main_df.copy().set_index("date")
                resampled = temp.resample("1D").agg({
                    "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
                }).dropna()
                if len(resampled) >= self.htf_atr_period:
                    _, h_dir = supertrend(resampled, period=self.htf_atr_period, multiplier=self.htf_multiplier)
                    resampled["htf_dir"] = h_dir
                    resampled = resampled.reset_index()
                    merged = pd.merge_asof(
                        main_df[["date"]],
                        resampled[["date", "htf_dir"]],
                        on="date",
                        direction="backward"
                    )
                    return merged["htf_dir"].fillna(1).astype(int)
            except Exception:
                pass

        # Fallback if higher timeframe cannot be resolved
        return pd.Series(np.ones(n, dtype=int), index=main_df.index)

    def generate_signals(
        self,
        df: pd.DataFrame,
        higher_tf_df: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """
        Generates trading signals and triggers based on core rules and optional filters.

        Signal encoding:
          +1 = LONG ENTRY (Supertrend flips Red -> Green AND Close > EMA50)
          -1 = SHORT ENTRY (Supertrend flips Green -> Red AND Close < EMA50)
           0 = HOLD / NO NEW ENTRY
        """
        ind_df = self.calculate_indicators(df)
        if ind_df.empty or "supertrend" not in ind_df.columns:
            return ind_df

        # Resolve Higher Timeframe Direction
        htf_dir = self._resolve_htf_direction(ind_df, higher_tf_df)
        ind_df["htf_supertrend_dir"] = htf_dir

        # Volume condition
        if self.use_volume_filter:
            vol_ok = ind_df["volume_surge"].fillna(False)
        else:
            vol_ok = pd.Series(True, index=ind_df.index)

        # MTF condition
        if self.use_mtf:
            htf_long_ok = (ind_df["htf_supertrend_dir"] == 1)
            htf_short_ok = (ind_df["htf_supertrend_dir"] == -1)
        else:
            htf_long_ok = pd.Series(True, index=ind_df.index)
            htf_short_ok = pd.Series(True, index=ind_df.index)

        # Long Entry Trigger
        long_trigger = (
            ind_df["st_flip_green"] &
            ind_df["close_above_ema50"] &
            vol_ok &
            htf_long_ok
        )

        # Short Entry Trigger
        short_trigger = (
            ind_df["st_flip_red"] &
            ind_df["close_below_ema50"] &
            vol_ok &
            htf_short_ok
        )

        # Apply execution mode restrictions
        signals = pd.Series(0, index=ind_df.index)
        if self.mode in ("long_only", "long_short"):
            signals[long_trigger] = 1
        if self.mode in ("short_only", "long_short"):
            signals[short_trigger] = -1

        ind_df["signal"] = signals
        return ind_df

    def calculate_position_size(
        self,
        capital: float,
        entry_price: float,
        st_level: float,
        atr_val: float
    ) -> Tuple[int, float, float]:
        """
        Calculates position size and stop loss based on selected stop_type.

        Returns:
            Tuple[shares: int, stop_loss: float, stop_distance: float]
        """
        if entry_price <= 0 or capital <= 0:
            return 0, 0.0, 0.0

        if self.stop_type == "supertrend":
            stop_dist = abs(entry_price - st_level)
            stop_loss = st_level
        else:
            # Pure ATR-based stop
            stop_dist = self.atr_stop_multiplier * max(0.01, atr_val)
            stop_loss = entry_price - stop_dist if entry_price >= st_level else entry_price + stop_dist

        # Safety clamp on stop distance (min 0.2% of price)
        min_dist = entry_price * 0.002
        stop_dist = max(min_dist, stop_dist)

        risk_amount = capital * self.risk_per_trade
        shares = int(risk_amount / stop_dist)

        # Capital ceiling (cannot buy more shares than 100% portfolio capital)
        max_shares = int(capital / entry_price)
        shares = max(0, min(shares, max_shares))

        return shares, round(stop_loss, 2), round(stop_dist, 2)

    def backtest(
        self,
        df: pd.DataFrame,
        initial_capital: float = 100000.0,
        higher_tf_df: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        """
        Executes a backtest over the provided OHLCV historical dataset.

        Returns a dictionary containing:
          - 'trade_log': list of all executed trades with entries, exits, PnL
          - 'equity_curve': pd.DataFrame tracking daily portfolio equity and drawdowns
          - 'metrics': comprehensive summary metrics (Win rate, Return %, Profit Factor, etc.)
        """
        sig_df = self.generate_signals(df, higher_tf_df=higher_tf_df)
        if sig_df.empty or len(sig_df) < max(self.atr_period, self.ema_period):
            return {
                "status": "error",
                "message": "Insufficient historical data for backtest",
                "trade_log": [],
                "metrics": {},
                "equity_curve": pd.DataFrame()
            }

        capital = float(initial_capital)
        trades: List[Dict[str, Any]] = []
        equity_records: List[Dict[str, Any]] = []

        active_trade: Optional[Dict[str, Any]] = None
        peak_equity = capital

        dates = sig_df["date"].values if "date" in sig_df.columns else sig_df.index.values
        opens = sig_df["open"].values
        highs = sig_df["high"].values
        lows = sig_df["low"].values
        closes = sig_df["close"].values
        signals = sig_df["signal"].values
        st_lines = sig_df["supertrend"].values
        st_dirs = sig_df["supertrend_direction"].values
        atrs = sig_df["atr"].values
        n = len(sig_df)

        for i in range(n):
            dt = str(dates[i])
            curr_open = float(opens[i])
            curr_high = float(highs[i])
            curr_low = float(lows[i])
            curr_close = float(closes[i])
            curr_st = float(st_lines[i])
            curr_dir = int(st_dirs[i])
            curr_atr = float(atrs[i]) if not np.isnan(atrs[i]) else 0.0

            # -------------------------------------------------------------
            # 1. EVALUATE EXITS ON ACTIVE POSITION
            # -------------------------------------------------------------
            if active_trade is not None:
                pos_type = active_trade["type"]
                entry_p = active_trade["entry_price"]
                shares = active_trade["shares"]
                trailing_stop = active_trade["trailing_stop"]

                exit_triggered = False
                exit_price = 0.0
                exit_reason = ""

                if pos_type == "LONG":
                    # Update trailing stop (use Supertrend line as trailing stop)
                    if self.stop_type == "supertrend":
                        trailing_stop = max(trailing_stop, curr_st)
                    active_trade["trailing_stop"] = trailing_stop

                    # Condition A: Trailing Stop Hit intraday
                    if curr_low <= trailing_stop:
                        exit_triggered = True
                        exit_price = min(curr_open, trailing_stop) if curr_open < trailing_stop else trailing_stop
                        exit_reason = "Trailing Stop Loss Hit"
                    # Condition B: Supertrend flipped to opposite color (Red / -1)
                    elif curr_dir == -1:
                        exit_triggered = True
                        exit_price = curr_close
                        exit_reason = "Supertrend Flipped Red"

                elif pos_type == "SHORT":
                    # Update trailing stop
                    if self.stop_type == "supertrend":
                        trailing_stop = min(trailing_stop, curr_st)
                    active_trade["trailing_stop"] = trailing_stop

                    # Condition A: Trailing Stop Hit intraday
                    if curr_high >= trailing_stop:
                        exit_triggered = True
                        exit_price = max(curr_open, trailing_stop) if curr_open > trailing_stop else trailing_stop
                        exit_reason = "Trailing Stop Loss Hit"
                    # Condition B: Supertrend flipped to opposite color (Green / +1)
                    elif curr_dir == 1:
                        exit_triggered = True
                        exit_price = curr_close
                        exit_reason = "Supertrend Flipped Green"

                if exit_triggered:
                    if pos_type == "LONG":
                        pnl = (exit_price - entry_p) * shares
                        pnl_pct = ((exit_price - entry_p) / entry_p) * 100.0
                    else:
                        pnl = (entry_p - exit_price) * shares
                        pnl_pct = ((entry_p - exit_price) / entry_p) * 100.0

                    capital += pnl
                    active_trade.update({
                        "exit_date": dt,
                        "exit_price": round(exit_price, 2),
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "exit_reason": exit_reason,
                        "capital_after": round(capital, 2),
                        "bars_held": i - active_trade["entry_bar"]
                    })
                    trades.append(active_trade)
                    active_trade = None

            # -------------------------------------------------------------
            # 2. EVALUATE NEW ENTRIES
            # -------------------------------------------------------------
            if active_trade is None and signals[i] != 0:
                sig = signals[i]
                trade_type = "LONG" if sig == 1 else "SHORT"
                entry_price = curr_close

                shares, stop_loss, stop_dist = self.calculate_position_size(
                    capital=capital,
                    entry_price=entry_price,
                    st_level=curr_st,
                    atr_val=curr_atr
                )

                if shares > 0:
                    active_trade = {
                        "trade_id": len(trades) + 1,
                        "type": trade_type,
                        "entry_date": dt,
                        "entry_bar": i,
                        "entry_price": round(entry_price, 2),
                        "shares": shares,
                        "initial_stop": round(stop_loss, 2),
                        "trailing_stop": round(stop_loss, 2),
                        "capital_at_risk": round(shares * stop_dist, 2),
                        "position_value": round(shares * entry_price, 2)
                    }

            # -------------------------------------------------------------
            # 3. TRACK EQUITY CURVE & DRAWDOWNS
            # -------------------------------------------------------------
            unrealized_pnl = 0.0
            if active_trade is not None:
                if active_trade["type"] == "LONG":
                    unrealized_pnl = (curr_close - active_trade["entry_price"]) * active_trade["shares"]
                else:
                    unrealized_pnl = (active_trade["entry_price"] - curr_close) * active_trade["shares"]

            current_equity = capital + unrealized_pnl
            peak_equity = max(peak_equity, current_equity)
            drawdown_pct = ((peak_equity - current_equity) / peak_equity) * 100.0 if peak_equity > 0 else 0.0

            equity_records.append({
                "date": dt,
                "equity": round(current_equity, 2),
                "cash": round(capital, 2),
                "drawdown_pct": round(drawdown_pct, 2),
                "in_position": active_trade is not None
            })

        # Close open position at end of backtest if still active
        if active_trade is not None:
            last_close = float(closes[-1])
            pos_type = active_trade["type"]
            entry_p = active_trade["entry_price"]
            shares = active_trade["shares"]
            pnl = (last_close - entry_p) * shares if pos_type == "LONG" else (entry_p - last_close) * shares
            pnl_pct = (pnl / (entry_p * shares)) * 100.0
            capital += pnl
            active_trade.update({
                "exit_date": str(dates[-1]),
                "exit_price": round(last_close, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "exit_reason": "End of Dataset Force Close",
                "capital_after": round(capital, 2),
                "bars_held": n - 1 - active_trade["entry_bar"]
            })
            trades.append(active_trade)

        equity_df = pd.DataFrame(equity_records)
        metrics = self._calculate_metrics(initial_capital, capital, trades, equity_df)

        return {
            "status": "success",
            "initial_capital": initial_capital,
            "final_capital": round(capital, 2),
            "trade_log": trades,
            "metrics": metrics,
            "equity_curve": equity_df
        }

    def _calculate_metrics(
        self,
        initial_capital: float,
        final_capital: float,
        trades: List[Dict[str, Any]],
        equity_df: pd.DataFrame
    ) -> Dict[str, Any]:
        """Calculates performance statistics and risk-adjusted metrics."""
        total_trades = len(trades)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "total_return_pct": 0.0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_pct": 0.0,
                "avg_trade_pct": 0.0,
                "avg_trade_amount": 0.0,
                "sharpe_ratio": 0.0
            }

        pnls = [t["pnl"] for t in trades]
        pnl_pcts = [t["pnl_pct"] for t in trades]

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_trades) * 100.0

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf")

        total_return_pct = round(((final_capital - initial_capital) / initial_capital) * 100.0, 2)
        avg_trade_pnl = round(float(np.mean(pnls)), 2)
        avg_trade_pct = round(float(np.mean(pnl_pcts)), 2)

        max_dd = float(equity_df["drawdown_pct"].max()) if not equity_df.empty else 0.0

        sharpe = 0.0
        if not equity_df.empty and len(equity_df) >= 10:
            eq_series = equity_df["equity"]
            daily_returns = eq_series.pct_change().dropna()
            std_ret = daily_returns.std()
            if std_ret > 0:
                sharpe = round(float((daily_returns.mean() / std_ret) * math.sqrt(252)), 2)

        return {
            "total_trades": total_trades,
            "winning_trades": win_count,
            "losing_trades": loss_count,
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": profit_factor,
            "total_return_pct": total_return_pct,
            "max_drawdown_pct": round(max_dd, 2),
            "avg_trade_amount": avg_trade_pnl,
            "avg_trade_pct": avg_trade_pct,
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "sharpe_ratio": sharpe
        }

    def get_latest_signal(
        self,
        df: pd.DataFrame,
        higher_tf_df: Optional[pd.DataFrame] = None,
        capital: float = 100000.0,
        symbol: str = "TICKER"
    ) -> Dict[str, Any]:
        """
        Evaluates the latest bar of the dataset and returns live trade setup,
        actionable signal, position sizing, stop loss, and market state.
        """
        sig_df = self.generate_signals(df, higher_tf_df=higher_tf_df)
        if sig_df.empty or len(sig_df) < max(self.atr_period, self.ema_period):
            return {
                "symbol": symbol,
                "signal": "INSUFFICIENT_DATA",
                "reason": "Not enough historical candles to compute indicators"
            }

        last_row = sig_df.iloc[-1]
        prev_row = sig_df.iloc[-2] if len(sig_df) >= 2 else last_row

        curr_close = float(last_row["close"])
        curr_open = float(last_row["open"])
        curr_high = float(last_row["high"])
        curr_low = float(last_row["low"])
        curr_vol = float(last_row["volume"])
        curr_st = float(last_row["supertrend"])
        curr_dir = int(last_row["supertrend_direction"])
        curr_ema = float(last_row["ema_50"])
        curr_atr = float(last_row["atr"]) if not np.isnan(last_row["atr"]) else 0.0

        st_flipped_green = bool(last_row["st_flip_green"])
        st_flipped_red = bool(last_row["st_flip_red"])
        above_ema50 = bool(last_row["close_above_ema50"])
        below_ema50 = bool(last_row["close_below_ema50"])
        vol_passed = bool(last_row["volume_surge"]) if self.use_volume_filter else True
        htf_dir = int(last_row.get("htf_supertrend_dir", 1))

        raw_sig = int(last_row["signal"])

        # Determine actionable signal
        action = "HOLD"
        reason_parts = []

        if raw_sig == 1:
            action = "BUY"
            reason_parts.append("Supertrend Flipped GREEN")
            reason_parts.append(f"Close (₹{curr_close:,.2f}) > EMA50 (₹{curr_ema:,.2f})")
            if self.use_volume_filter:
                reason_parts.append("Volume > 1.2x SMA20")
            if self.use_mtf:
                reason_parts.append("HTF Supertrend Bullish")
        elif raw_sig == -1:
            action = "SELL_SHORT"
            reason_parts.append("Supertrend Flipped RED")
            reason_parts.append(f"Close (₹{curr_close:,.2f}) < EMA50 (₹{curr_ema:,.2f})")
            if self.use_volume_filter:
                reason_parts.append("Volume > 1.2x SMA20")
            if self.use_mtf:
                reason_parts.append("HTF Supertrend Bearish")
        else:
            if curr_dir == 1:
                action = "HOLD_LONG" if above_ema50 else "WATCH_LONG"
                reason_parts.append("Supertrend is GREEN (Bullish Trend in progress)")
            else:
                action = "HOLD_SHORT" if below_ema50 else "WATCH_SHORT"
                reason_parts.append("Supertrend is RED (Bearish Trend in progress)")

        # Position sizing and risk levels
        shares, stop_loss, stop_dist = self.calculate_position_size(
            capital=capital,
            entry_price=curr_close,
            st_level=curr_st,
            atr_val=curr_atr
        )

        stop_dist_pct = round((stop_dist / curr_close) * 100.0, 2) if curr_close > 0 else 0.0
        target_price = round(curr_close + (stop_dist * 2.0), 2) if curr_dir == 1 else round(curr_close - (stop_dist * 2.0), 2)

        return {
            "symbol": symbol,
            "timestamp": str(last_row["date"]) if "date" in last_row else datetime.now().isoformat(),
            "close_price": curr_close,
            "open_price": curr_open,
            "high_price": curr_high,
            "low_price": curr_low,
            "volume": curr_vol,
            "signal": action,
            "supertrend": round(curr_st, 2),
            "supertrend_direction": "BULLISH (GREEN)" if curr_dir == 1 else "BEARISH (RED)",
            "supertrend_flipped_green": st_flipped_green,
            "supertrend_flipped_red": st_flipped_red,
            "ema50": round(curr_ema, 2),
            "above_ema50": above_ema50,
            "below_ema50": below_ema50,
            "volume_filter_passed": vol_passed,
            "htf_confirmed": (htf_dir == 1 if curr_dir == 1 else htf_dir == -1) if self.use_mtf else True,
            "suggested_entry": curr_close,
            "stop_loss": stop_loss,
            "stop_distance": stop_dist,
            "stop_distance_pct": stop_dist_pct,
            "target_price": target_price,
            "position_size_shares": shares,
            "position_capital_allocated": round(shares * curr_close, 2),
            "capital_at_risk": round(shares * stop_dist, 2),
            "mode": self.mode,
            "reason": " | ".join(reason_parts)
        }


# =============================================================================
# 3. ZERODHA HISTORICAL DATA INTEGRATION & WATCHLIST SCANNER
# =============================================================================

def fetch_historical_daily_data(symbol: str, period_days: int = 365) -> pd.DataFrame:
    """Fetches daily OHLCV historical data for a given ticker exclusively via Zerodha API."""
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("-EQ", "")

    try:
        from tradingagents.dataflows.zerodha import get_zerodha_stock_df
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=period_days)
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")

        df_z = get_zerodha_stock_df(clean_sym, start_str, end_str, interval="day")
        if df_z is not None and not df_z.empty:
            df_z = df_z.rename(columns={
                "Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"
            })
            if {"date", "open", "high", "low", "close", "volume"}.issubset(df_z.columns):
                res_df = df_z[["date", "open", "high", "low", "close", "volume"]].dropna()
                if len(res_df) >= 30:
                    return res_df
    except Exception as e:
        logger.error(f"Zerodha data fetch for {clean_sym} failed: {e}")

    return pd.DataFrame()


def run_supertrend_btst_agents_debate(
    symbol: str,
    btst_playbook: Optional[str],
    is_bullish_st: bool,
    flipped_green: bool,
    above_ema50: bool,
    swing_5d_breakout: bool,
    close_pos_pct: float,
    is_green_candle: bool,
    vol_ratio: float,
    obv_bullish: bool,
    tsi_bullish: bool,
    stop_dist_pct: float,
) -> Dict[str, Any]:
    """
    Runs a 6-Agent Pre-BTST Quantitative Debate (100% Zerodha Data, $0 AI Cost)
    to evaluate how strong the Supertrend Pro Buying (BTST) setup is out of 10:
      1. Supertrend & Trend Structure Analyst (ST 10,3 flip/trend, EMA 50, 5D Swing Breakout)
      2. BTST Closing Power & Price Action Analyst (Day range close % & green body strength)
      3. Institutional Volume, OBV & TSI Flow Analyst (Volume surge, OBV > EMA20, TSI > Signal)
      4. BTST Bull Researcher (Synthesizes overnight gap-up & continuation thesis)
      5. Overnight Gap-Risk Researcher (Penalizes weak closes < 65%, red bars, or wide stops)
      6. Chief Risk & Portfolio Judge (Produces final `agents_debate_rating` out of 10)
    """
    # Agent 1: Supertrend & Trend Structure Analyst (0-10)
    st_score = 4.0
    if is_bullish_st:
        st_score += 2.2
    if flipped_green:
        st_score += 2.2
    elif swing_5d_breakout:
        st_score += 1.8
    if above_ema50:
        st_score += 1.6
    st_score = round(min(10.0, max(1.5, st_score)), 1)

    # Agent 2: BTST Closing Power & Price Action Analyst (0-10)
    if not is_green_candle or close_pos_pct < 50.0:
        close_score = round(max(1.5, (close_pos_pct / 100.0) * 5.0), 1)
    else:
        close_score = round(min(10.0, 5.5 + ((close_pos_pct - 50.0) / 50.0) * 4.5), 1)

    # Agent 3: Institutional Volume, OBV & TSI Flow Analyst (0-10)
    flow_score = 4.2
    if vol_ratio >= 1.2:
        flow_score += min(2.4, 1.2 + (vol_ratio - 1.2) * 1.1)
    elif vol_ratio >= 1.0:
        flow_score += 0.6
    if obv_bullish:
        flow_score += 1.7
    if tsi_bullish:
        flow_score += 1.7
    flow_score = round(min(10.0, max(2.0, flow_score)), 1)

    # Agent 4: BTST Bull Lead Researcher
    bull_thesis_score = round((st_score * 0.36) + (close_score * 0.34) + (flow_score * 0.30), 1)

    # Agent 5: Overnight Gap-Risk Researcher (Counter-Thesis Penalty 0.0 - 4.5)
    risk_penalty = 0.0
    risk_reasons = []
    if not is_green_candle:
        risk_penalty += 2.2
        risk_reasons.append("Red distribution candle")
    if close_pos_pct < 65.0:
        risk_penalty += 1.5
        risk_reasons.append(f"Weak close ({close_pos_pct:.0f}% of range)")
    if not above_ema50:
        risk_penalty += 1.0
        risk_reasons.append("Below EMA50")
    if not obv_bullish:
        risk_penalty += 0.5
        risk_reasons.append("OBV lag")
    if not tsi_bullish:
        risk_penalty += 0.4
        risk_reasons.append("TSI soft")
    if stop_dist_pct > 4.0:
        risk_penalty += 0.5
        risk_reasons.append(f"Wide stop ({stop_dist_pct:.1f}%)")
    risk_penalty = round(min(4.5, risk_penalty), 1)

    # Agent 6: Chief Risk & Portfolio Judge
    playbook_bonus = 0.5 if btst_playbook in ("STAGE 1: ST Flip Breakout", "STAGE 2: 5D Swing Breakout") else (0.3 if btst_playbook else 0.0)
    final_rating = round(min(10.0, max(1.0, bull_thesis_score + playbook_bonus - risk_penalty)), 1)

    if final_rating >= 8.5:
        verdict = "STRONG BTST CONSENSUS 🔥"
    elif final_rating >= 7.2:
        verdict = "DEBATE APPROVED ✅"
    elif final_rating >= 6.2:
        verdict = "MODERATE BTST ⚡"
    else:
        verdict = "REJECTED / WEAK CLOSE ⚠️"

    filled = int(round(final_rating))
    bar = "█" * filled + "░" * (10 - filled)
    risk_note = "Strong Closing Demand" if not risk_reasons else ", ".join(risk_reasons[:2])
    summary = (
        f"ST/Trend {st_score}/10 • ClosePower {close_score}/10 • "
        f"OBV/TSI {flow_score}/10 | Risk: {risk_note}"
    )

    return {
        "agents_debate_rating": final_rating,
        "agents_debate_verdict": verdict,
        "agents_debate_bar": bar,
        "agents_debate_summary": summary,
        "st_agent_score": st_score,
        "closing_power_agent_score": close_score,
        "flow_agent_score": flow_score,
        "bull_thesis_score": bull_thesis_score,
        "risk_penalty": risk_penalty,
        "risk_reasons": risk_reasons,
    }


def analyze_evening_pro_candidate(symbol: str, df: pd.DataFrame = None) -> dict:
    """
    Analyzes a stock using the Advanced Supertrend Strategy v2.0 (ATR 10, Multiplier 3, EMA 50)
    combined with 3 Institutional BTST Playbooks (ST Flip Breakout, 5D Swing Breakout,
    and Late-Day Closing Accumulation), OBV + TSI flow confirmation, ATR-bounded BTST stop loss,
    and a 6-Agent Pre-BTST Quantitative Debate Rating out of 10.
    """
    clean_sym = symbol.strip().upper().replace(".NS", "").replace("-EQ", "")

    if df is None or df.empty or len(df) < 30:
        df = fetch_historical_daily_data(clean_sym, period_days=365)

    if df is None or df.empty or len(df) < 30:
        return {
            "symbol": clean_sym,
            "pro_buying_score": 0.0,
            "agents_debate_rating": 0.0,
            "is_pro_buying": False,
            "reason": "Insufficient OHLCV data"
        }

    strategy = AdvancedSupertrendStrategy(
        atr_period=10,
        multiplier=3.0,
        ema_period=50,
        risk_per_trade=0.01,
        mode="long_only",
        use_volume_filter=True,
        volume_multiplier=1.2,
        stop_type="supertrend"
    )

    sig_info = strategy.get_latest_signal(df, symbol=clean_sym)
    ind_df = strategy.calculate_indicators(df)

    curr_close = float(sig_info.get("close_price", 0.0))
    curr_open = float(sig_info.get("open_price", 0.0))
    curr_low = float(sig_info.get("low_price", 0.0))
    curr_high = float(sig_info.get("high_price", 0.0))
    curr_vol = float(sig_info.get("volume", 0.0))
    day_range = curr_high - curr_low
    close_pos_pct = round(((curr_close - curr_low) / day_range) * 100.0, 1) if day_range > 0 else 50.0
    is_green_candle = (curr_close >= curr_open)

    # Compute OBV, TSI(13,25,13), 5-Day Swing High, and Volume Ratio on ind_df
    vol_sma20 = float(ind_df["vol_sma"].iloc[-1]) if "vol_sma" in ind_df.columns and not np.isnan(ind_df["vol_sma"].iloc[-1]) else max(1.0, curr_vol)
    vol_ratio = round(curr_vol / max(1.0, vol_sma20), 2)
    curr_atr = float(ind_df["atr"].iloc[-1]) if "atr" in ind_df.columns and not np.isnan(ind_df["atr"].iloc[-1]) else (curr_close * 0.015)

    close_diff = ind_df["close"].diff()
    obv_dir = np.where(close_diff > 0, 1, np.where(close_diff < 0, -1, 0))
    obv_dir[0] = 0
    obv_series = (obv_dir * ind_df["volume"]).cumsum()
    obv_ema20 = obv_series.ewm(span=20, adjust=False).mean()
    obv_bullish = bool(obv_series.iloc[-1] > obv_ema20.iloc[-1])

    abs_pc = close_diff.abs()
    pc_fast = close_diff.ewm(span=25, adjust=False).mean().ewm(span=13, adjust=False).mean()
    abs_fast = abs_pc.ewm(span=25, adjust=False).mean().ewm(span=13, adjust=False).mean().replace(0, np.nan)
    tsi_series = (100.0 * (pc_fast / abs_fast)).fillna(0.0)
    tsi_sig_series = tsi_series.ewm(span=13, adjust=False).mean().fillna(0.0)
    curr_tsi = round(float(tsi_series.iloc[-1]), 2)
    curr_tsi_sig = round(float(tsi_sig_series.iloc[-1]), 2)
    tsi_bullish = bool(curr_tsi > curr_tsi_sig)

    prev_5d_high = float(ind_df["high"].iloc[-6:-1].max()) if len(ind_df) >= 6 else curr_high
    swing_5d_breakout = bool(curr_close > prev_5d_high and is_green_candle)

    is_bullish = sig_info.get("supertrend_direction") == "BULLISH (GREEN)"
    flipped_green = bool(sig_info.get("supertrend_flipped_green", False))
    above_ema50 = bool(sig_info.get("above_ema50", False))
    vol_passed = bool(vol_ratio >= 1.2 and is_green_candle)

    # Evaluate the 3 Institutional BTST Playbooks (strictly requires green candle & strong closing range!)
    btst_playbook = None
    action = sig_info.get("signal", "HOLD")
    score = 20.0

    if is_bullish and is_green_candle and close_pos_pct >= 65.0:
        if flipped_green and above_ema50:
            btst_playbook = "STAGE 1: ST Flip Breakout"
            action = "BUY"
            score = 92.0 + min(7.0, (close_pos_pct - 65.0) * 0.2 + (2.0 if vol_passed else 0.0))
        elif above_ema50 and swing_5d_breakout and (vol_ratio >= 1.15 or obv_bullish):
            btst_playbook = "STAGE 2: 5D Swing Breakout"
            action = "BUY"
            score = 86.0 + min(10.0, (close_pos_pct - 65.0) * 0.22 + min(3.0, (vol_ratio - 1.0) * 2.0))
        elif above_ema50 and close_pos_pct >= 75.0 and obv_bullish and tsi_bullish and vol_ratio >= 1.1:
            btst_playbook = "STAGE 3: Closing Accumulation"
            action = "BUY"
            score = 78.0 + min(10.0, (close_pos_pct - 75.0) * 0.3 + min(3.0, (vol_ratio - 1.0) * 2.0))
        elif flipped_green:
            btst_playbook = "WATCH: ST Flip (Below EMA50)"
            action = "WATCH_LONG"
            score = 68.0
        elif above_ema50 and (obv_bullish or tsi_bullish):
            btst_playbook = "WATCH: Bullish Trend"
            action = "HOLD_LONG"
            score = 62.0
        else:
            score = 50.0
    elif is_bullish and not is_green_candle:
        # Red candle inside Supertrend -> penalize heavily so sell-off days never rank as BTST buys!
        action = "HOLD_LONG"
        score = max(15.0, min(38.0, close_pos_pct * 0.5))

    score = round(min(99.5, score), 1)

    # Tight ATR-bounded BTST Stop Loss (caps stop distance at min(ST distance, 1.5x ATR, 3.2% max))
    raw_st = float(sig_info.get("supertrend", curr_close * 0.97))
    atr_stop = curr_close - (1.5 * curr_atr)
    low_stop = curr_low * 0.996
    tight_stop = max(raw_st, atr_stop, low_stop, curr_close * 0.968)
    if tight_stop >= curr_close:
        tight_stop = round(curr_close * 0.982, 2)
    else:
        tight_stop = round(tight_stop, 2)

    stop_dist = round(max(curr_close * 0.005, curr_close - tight_stop), 2)
    stop_dist_pct = round((stop_dist / curr_close) * 100.0, 2) if curr_close > 0 else 1.5
    target_price = round(curr_close + (stop_dist * 2.0), 2)
    shares = max(1, min(int(100000.0 / curr_close), int(1000.0 / stop_dist))) if curr_close > 0 else 0

    # Run 6-Agent Pre-BTST Quantitative Debate
    debate_info = run_supertrend_btst_agents_debate(
        symbol=clean_sym,
        btst_playbook=btst_playbook,
        is_bullish_st=is_bullish,
        flipped_green=flipped_green,
        above_ema50=above_ema50,
        swing_5d_breakout=swing_5d_breakout,
        close_pos_pct=close_pos_pct,
        is_green_candle=is_green_candle,
        vol_ratio=vol_ratio,
        obv_bullish=obv_bullish,
        tsi_bullish=tsi_bullish,
        stop_dist_pct=stop_dist_pct,
    )

    is_pro_buying = bool(
        is_bullish
        and is_green_candle
        and close_pos_pct >= 65.0
        and score >= 68.0
        and debate_info["agents_debate_rating"] >= 6.8
    )

    reason_tags = []
    if btst_playbook:
        reason_tags.append(btst_playbook)
    reason_tags.append(f"Closed at {close_pos_pct:.1f}% of day range")
    reason_tags.append(f"Vol {vol_ratio:.2f}x SMA20")
    if obv_bullish and tsi_bullish:
        reason_tags.append("OBV & TSI Bullish")

    return {
        "symbol": clean_sym,
        "btst_playbook": btst_playbook,
        "pro_buying_score": score,
        "agents_debate_rating": debate_info["agents_debate_rating"],
        "agents_debate_verdict": debate_info["agents_debate_verdict"],
        "agents_debate_bar": debate_info["agents_debate_bar"],
        "agents_debate_summary": debate_info["agents_debate_summary"],
        "agents_debate": debate_info,
        "is_pro_buying": is_pro_buying,
        "signal": action,
        "close_price": curr_close,
        "open_price": curr_open,
        "high_price": curr_high,
        "low_price": curr_low,
        "volume": curr_vol,
        "volume_ratio": vol_ratio,
        "close_position_pct": close_pos_pct,
        "is_green_candle": is_green_candle,
        "swing_5d_breakout": swing_5d_breakout,
        "obv_bullish": obv_bullish,
        "tsi_bullish": tsi_bullish,
        "tsi_val": curr_tsi,
        "tsi_signal": curr_tsi_sig,
        "supertrend": sig_info.get("supertrend", 0.0),
        "supertrend_direction": sig_info.get("supertrend_direction", "UNKNOWN"),
        "supertrend_flipped_green": flipped_green,
        "supertrend_flipped_red": sig_info.get("supertrend_flipped_red", False),
        "ema50": sig_info.get("ema50", 0.0),
        "above_ema50": above_ema50,
        "volume_filter_passed": vol_passed,
        "suggested_entry": curr_close,
        "stop_loss": tight_stop,
        "stop_distance": stop_dist,
        "stop_distance_pct": stop_dist_pct,
        "target_price": target_price,
        "risk_reward": "1 : 2.0",
        "position_size_shares": shares,
        "reason": " | ".join(reason_tags)
    }


# Anti-spam cache in memory
_SENT_ALERTS_TODAY = {}


def format_evening_pro_telegram_alert(c: dict) -> str:
    """Formats detailed HTML Telegram alert message for Supertrend Pro Buying (BTST) setups with Agents Debate Rating."""
    sym = c.get("symbol", "").upper()
    playbook = c.get("btst_playbook") or "SUPERTREND BTST ACCUMULATION"
    score = c.get("pro_buying_score", 0.0)
    debate_rating = c.get("agents_debate_rating") or round(min(10.0, max(1.0, score / 10.0)), 1)
    debate_verdict = c.get("agents_debate_verdict") or "STRONG BTST CONSENSUS 🔥"
    debate_summary = c.get("agents_debate_summary") or ""
    entry = c.get("suggested_entry", c.get("close_price", 0.0))
    sl = c.get("stop_loss", 0.0)
    tgt = c.get("target_price", 0.0)
    stop_pct = c.get("stop_distance_pct", 1.5)
    st_val = c.get("supertrend", 0.0)
    ema50 = c.get("ema50", 0.0)
    close_pct = c.get("close_position_pct", 75.0)
    vol_ratio = c.get("volume_ratio", 1.2)
    shares = c.get("position_size_shares", 1)
    now_str = datetime.now().strftime("%I:%M %p")
    summary_line = f"🗣️ <i>{debate_summary}</i>\n" if debate_summary else ""

    msg = (
        f"🚀 <b>SUPERTREND PRO BUYING (BTST) ALERT</b> 🚀\n"
        f"⚡ <b>Playbook</b>: <b>{playbook}</b>\n"
        f"📌 <b>Symbol</b>: <b>#{sym}</b>  •  🕒 <b>{now_str} IST</b>\n"
        f"⭐️ <b>Conviction Score</b>: <b>{score:.1f} / 100</b>\n"
        f"🤖 <b>Agents Debate Rating:</b> <b>{debate_rating} / 10</b> ({debate_verdict})\n"
        f"{summary_line}\n"
        f"📈 <b>BTST EXECUTION LEVELS (1 : 2.0 R:R)</b>:\n"
        f"   • <b>Suggested Entry</b>: ₹{entry:,.2f}\n"
        f"   • <b>ATR/ST Stop Loss</b>: ₹{sl:,.2f} (Risk: {stop_pct:.2f}%)\n"
        f"   • <b>BTST Target (1:2)</b>: ₹{tgt:,.2f}\n"
        f"   • <b>Position Size (1% Risk)</b>: {shares} shares\n\n"
        f"📊 <b>SUPERTREND & FLOW CONFIRMATION</b>:\n"
        f"   • <b>Supertrend (10,3)</b>: ₹{st_val:,.2f} (BULLISH GREEN)\n"
        f"   • <b>EMA 50 Filter</b>: ₹{ema50:,.2f} (Close Above EMA50 ✓)\n"
        f"   • <b>Closing Power</b>: Closed at <b>{close_pct:.1f}%</b> of Day's Range\n"
        f"   • <b>Volume Surge</b>: <b>{vol_ratio:.2f}x</b> 20-Day SMA\n\n"
        f"📸 <i>5m Chart Attached: Candlestick + Volume + OBV + TSI</i>\n"
        f"⚡ <i>Zerodha Live Supertrend BTST Engine</i>"
    )
    return msg


def send_evening_pro_telegram_alert(
    candidate: dict,
    kite=None,
    force: bool = False
) -> dict:
    """
    Renders 5m candlestick chart (with Volume + OBV + TSI) and dispatches Telegram photo alert for Supertrend setups.
    Enforces anti-spam: Max 1 alert per symbol per day.
    """
    symbol = candidate.get("symbol", "").strip().upper()
    today_str = datetime.now().strftime("%Y-%m-%d")
    dedup_key = f"{today_str}_{symbol}_SUPERTREND"

    if not force and dedup_key in _SENT_ALERTS_TODAY:
        logger.info(f"[DEDUP] Alert already sent today for {symbol}. Skipping.")
        return {"status": "skipped", "reason": "Already alerted today", "symbol": symbol}

    try:
        dm = DataManager()
        hist_col = dm.db["evening_alerts_history"]
        existing = hist_col.find_one({"date": today_str, "symbol": symbol})
        if not force and existing:
            _SENT_ALERTS_TODAY[dedup_key] = existing.get("timestamp", datetime.now().timestamp())
            logger.info(f"[DEDUP-DB] Alert already in DB today for {symbol}. Skipping.")
            return {"status": "skipped", "reason": "Already in DB today", "symbol": symbol}
    except Exception as db_err:
        logger.debug(f"MongoDB deduplication check notice: {db_err}")

    chart_buf = None
    try:
        from scripts.chart_generator import generate_evening_pro_chart_buffer
        debate_r = candidate.get("agents_debate_rating", 8.5)
        chart_buf = generate_evening_pro_chart_buffer(
            symbol=symbol,
            entry_price=candidate.get("suggested_entry"),
            stop_loss=candidate.get("stop_loss"),
            target_price=candidate.get("target_price"),
            pro_score=candidate.get("pro_buying_score", 0.0),
            num_candles=60,
            kite=kite,
            title_suffix=f" • Agents Debate {debate_r}/10"
        )
    except Exception as chart_err:
        logger.error(f"Failed to generate chart for {symbol}: {chart_err}")

    msg_text = format_evening_pro_telegram_alert(candidate)
    from scripts.chart_generator import send_telegram_chart_alert
    res = send_telegram_chart_alert(
        symbol=symbol,
        message_text=msg_text,
        chart_buffer=chart_buf,
        trigger_price=candidate.get("suggested_entry"),
        parse_mode="HTML",
        kite=kite
    )

    if res.get("sent"):
        _SENT_ALERTS_TODAY[dedup_key] = datetime.now().timestamp()
        try:
            dm = DataManager()
            dm.db["evening_alerts_history"].update_one(
                {"date": today_str, "symbol": symbol},
                {"$set": {
                    "date": today_str,
                    "symbol": symbol,
                    "score": candidate.get("pro_buying_score"),
                    "agents_debate_rating": candidate.get("agents_debate_rating"),
                    "entry": candidate.get("suggested_entry"),
                    "stop_loss": candidate.get("stop_loss"),
                    "target": candidate.get("target_price"),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }},
                upsert=True
            )
        except Exception as e:
            logger.debug(f"Could not write to evening_alerts_history: {e}")

    return res


def get_all_watchlist_symbols() -> list:
    """Retrieves all tracked stocks from MongoDB user tables (prioritizing high-closing BTST & Darvas leaders)."""
    priority_syms = []
    other_syms = set()
    try:
        dm = DataManager()
        for doc in dm.db["evening_pro_candidates"].find({}, {"symbol": 1, "close_position_pct": 1}).sort("pro_buying_score", -1):
            s = doc.get("symbol")
            if s and (doc.get("close_position_pct") or 0) >= 65.0:
                norm_s = normalize_symbol(s)
                if norm_s not in priority_syms:
                    priority_syms.append(norm_s)
        for tf in ["darvas", "daily", "weekly", "monthly", "manual"]:
            records = dm.get_stock_ratings(tf)
            for r in records:
                s = r.get("symbol") or r.get("ticker")
                if s:
                    norm_s = normalize_symbol(s)
                    if norm_s not in priority_syms:
                        other_syms.add(norm_s)
    except Exception as e:
        logger.warning(f"Could not load watchlist symbols from DB: {e}")

    combined = priority_syms + sorted(list(other_syms))
    if not combined:
        combined = [
            "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN",
            "TATAMOTORS", "TATASTEEL", "BHARTIARTL", "AXISBANK", "LT",
            "BAJFINANCE", "MARUTI", "SUNPHARMA", "TITAN", "WIPRO", "HCLTECH"
        ]

    return combined


def scan_and_rank_evening_pro_candidates(
    symbols: list = None,
    send_telegram: bool = True
) -> list:
    """
    Scans watchlist stocks using Advanced Supertrend v2.0 + 6-Agent BTST Debate.
    Strictly filters out weak-closing or red-candle distribution stocks so only genuine
    BTST accumulation candidates (`close_position_pct >= 65%`, `is_green_candle == True`,
    `agents_debate_rating >= 6.5`) are saved to MongoDB.
    """
    if symbols is None or len(symbols) == 0:
        symbols = get_all_watchlist_symbols()

    logger.info(f"🔍 Scanning {len(symbols)} stocks for Supertrend Pro Buying (BTST v2.0 + Agents Debate)...")

    qualified_results = []
    for s in symbols:
        try:
            res = analyze_evening_pro_candidate(s)
            if not res:
                continue

            is_pro = bool(res.get("is_pro_buying"))
            debate_rating = float(res.get("agents_debate_rating", 0.0) or 0.0)
            close_pos = float(res.get("close_position_pct", 0.0) or 0.0)
            is_green = bool(res.get("is_green_candle"))

            if is_pro or (is_green and close_pos >= 65.0 and debate_rating >= 6.5 and res.get("pro_buying_score", 0.0) >= 62.0):
                qualified_results.append(res)

                is_buy_triggered = (
                    res.get("signal") == "BUY" and
                    is_pro and
                    debate_rating >= 7.5
                )
                if send_telegram and is_buy_triggered:
                    logger.info(
                        f"🚀 Qualified Supertrend BTST trigger for {s} "
                        f"(Score: {res.get('pro_buying_score')} | Debate: {debate_rating}/10)! Dispatching alert..."
                    )
                    try:
                        send_evening_pro_telegram_alert(res)
                    except Exception as tg_err:
                        logger.error(f"Error dispatching Telegram alert for {s}: {tg_err}")

        except Exception as e:
            logger.error(f"Error scanning {s} for supertrend candidate: {e}")

    # Sort descending by (agents_debate_rating, pro_buying_score)
    sorted_results = sorted(
        qualified_results,
        key=lambda x: (x.get("agents_debate_rating", 0.0), x.get("pro_buying_score", 0.0)),
        reverse=True
    )

    try:
        dm = DataManager()
        col = dm.db["evening_pro_candidates"]
        col.delete_many({})
        if sorted_results:
            docs_to_save = []
            for r in sorted_results:
                doc = dict(r)
                doc["updated_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
                docs_to_save.append(doc)
            if docs_to_save:
                col.insert_many(docs_to_save)
                logger.info(f"✅ Saved {len(docs_to_save)} high-conviction Supertrend BTST candidates to MongoDB 'evening_pro_candidates'.")
    except Exception as e:
        logger.warning(f"Could not save candidates to MongoDB: {e}")

    return sorted_results


# =============================================================================
# 4. COMPLETE USAGE EXAMPLES & CLI
# =============================================================================

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    import argparse
    parser = argparse.ArgumentParser(description="Advanced Supertrend Trading Strategy & Scanner (NSE)")
    parser.add_argument("--demo", action="store_true", help="Run complete strategy demo (Data prep, Backtest, Live Signal)")
    parser.add_argument("--symbol", type=str, default=None, help="Scan a single symbol (e.g. RELIANCE)")
    parser.add_argument("--telegram", action="store_true", help="Send Telegram alerts for triggers")
    parser.add_argument("--limit", type=int, default=20, help="Number of symbols to scan (default 20)")
    args = parser.parse_args()

    # -------------------------------------------------------------------------
    # DEMO WALKTHROUGH
    # -------------------------------------------------------------------------
    if args.demo:
        print("\n" + "=" * 90)
        print(" 🎯 ADVANCED SUPERTREND STRATEGY - FULL PRODUCTION WALKTHROUGH")
        print("=" * 90)

        # 1. How to prepare data
        print("\n[STEP 1] Preparing Sample OHLCV Data (Daily)...")
        np.random.seed(42)
        dates = pd.date_range("2025-01-01", periods=200, freq="B")
        prices = [1000.0]
        for _ in range(199):
            prices.append(prices[-1] * (1 + np.random.normal(0.001, 0.012)))
        close_series = np.array(prices)
        high_series = close_series * (1 + np.abs(np.random.normal(0.004, 0.004, 200)))
        low_series = close_series * (1 - np.abs(np.random.normal(0.004, 0.004, 200)))
        open_series = (high_series + low_series) / 2.0
        volume_series = np.random.randint(200000, 1500000, 200)

        sample_df = pd.DataFrame({
            "date": dates,
            "open": open_series,
            "high": high_series,
            "low": low_series,
            "close": close_series,
            "volume": volume_series
        })
        print(f"Generated {len(sample_df)} sample bars with columns: {list(sample_df.columns)}")

        # 2. Backtest without MTF & Volume filters
        print("\n[STEP 2] Running Backtest (Pure Supertrend 10,3 + EMA 50, Long-Only)...")
        strat_base = AdvancedSupertrendStrategy(
            atr_period=10,
            multiplier=3.0,
            ema_period=50,
            risk_per_trade=0.01,
            mode="long_only",
            use_mtf=False,
            use_volume_filter=False
        )
        res_base = strat_base.backtest(sample_df, initial_capital=100000.0)
        m_base = res_base["metrics"]
        print(f"  • Total Trades:     {m_base['total_trades']}")
        print(f"  • Win Rate:         {m_base['win_rate_pct']}%")
        print(f"  • Total Return:     {m_base['total_return_pct']}%")
        print(f"  • Profit Factor:    {m_base['profit_factor']}")
        print(f"  • Max Drawdown:     {m_base['max_drawdown_pct']}%")
        print(f"  • Sharpe Ratio:     {m_base['sharpe_ratio']}")

        # 3. Backtest with Volume & MTF Filters
        print("\n[STEP 3] Running Backtest with Volume Filter (> 1.2x SMA20) & MTF Confirmation...")
        strat_filtered = AdvancedSupertrendStrategy(
            atr_period=10,
            multiplier=3.0,
            ema_period=50,
            risk_per_trade=0.01,
            mode="long_only",
            use_mtf=True,
            use_volume_filter=True,
            volume_multiplier=1.2
        )
        res_filt = strat_filtered.backtest(sample_df, initial_capital=100000.0)
        m_filt = res_filt["metrics"]
        print(f"  • Total Trades:     {m_filt['total_trades']}")
        print(f"  • Win Rate:         {m_filt['win_rate_pct']}%")
        print(f"  • Total Return:     {m_filt['total_return_pct']}%")
        print(f"  • Profit Factor:    {m_filt['profit_factor']}")
        print(f"  • Max Drawdown:     {m_filt['max_drawdown_pct']}%")

        # 4. Get Latest Live Signal
        print("\n[STEP 4] Fetching Latest Live Signal & Dynamic Position Size...")
        live_signal = strat_filtered.get_latest_signal(sample_df, capital=100000.0, symbol="NIFTY_STOCK")
        for k, v in live_signal.items():
            print(f"  • {k:<25}: {v}")

        print("\n" + "=" * 90)
        sys.exit(0)

    # -------------------------------------------------------------------------
    # SCANNER EXECUTION
    # -------------------------------------------------------------------------
    if args.symbol:
        sym = args.symbol.strip().upper()
        print(f"\nAnalyzing single symbol: {sym} with Advanced Supertrend Strategy...")
        res = analyze_evening_pro_candidate(sym)
        import json
        print(json.dumps(res, indent=2, default=str))
        if args.telegram:
            print("\nDispatching test Telegram alert...")
            send_evening_pro_telegram_alert(res, force=True)
    else:
        all_syms = get_all_watchlist_symbols()
        scan_syms = all_syms[:args.limit]
        print(f"\nScanning {len(scan_syms)} watchlist stocks using Advanced Supertrend BTST v2.0 + Agents Debate...")
        ranked_candidates = scan_and_rank_evening_pro_candidates(symbols=scan_syms, send_telegram=args.telegram)

        print("\n" + "=" * 125)
        print(" 🚀 SUPERTREND PRO BUYING (BTST v2.0) + 6-AGENT DEBATE CANDIDATES (RANKED DESCENDING)")
        print("=" * 125)
        print(f"{'RANK':<5} {'SYMBOL':<12} {'DEBATE':<10} {'SCORE':<10} {'SIGNAL':<10} {'CLOSE':<10} {'CLOSE%':<8} {'PLAYBOOK / REASON':<45}")
        print("-" * 125)

        for i, c in enumerate(ranked_candidates[:15], 1):
            sym = c.get("symbol")
            deb = f"{c.get('agents_debate_rating', 0):.1f}/10"
            score = f"{c.get('pro_buying_score'):.1f}/100"
            sig = c.get("signal", "HOLD")
            close_p = f"₹{c.get('close_price', 0):.2f}"
            cp_pct = f"{c.get('close_position_pct', 0):.0f}%"
            reason = str(c.get("reason", ""))[:45]

            print(f"{i:<5} {sym:<12} {deb:<10} {score:<10} {sig:<10} {close_p:<10} {cp_pct:<8} {reason:<45}")

        print("=" * 125 + "\n")
