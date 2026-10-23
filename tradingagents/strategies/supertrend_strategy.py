"""
===============================================================================
ADVANCED SUPERTREND TRADING STRATEGY (NSE EQUITIES)
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
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List, Union

import numpy as np
import pandas as pd


# =============================================================================
# 1. PURE PANDAS & NUMPY INDICATOR FUNCTIONS
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

        # -------------------------------------------------------------
        # 4. COMPUTE INSTITUTIONAL METRICS
        # -------------------------------------------------------------
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

        # Sharpe Ratio (annualized based on daily equity returns)
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
        prev_dir = int(prev_row["supertrend_direction"])
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
                reason_parts.append(f"Volume > 1.2x SMA20")
            if self.use_mtf:
                reason_parts.append(f"HTF Supertrend Bullish")
        elif raw_sig == -1:
            action = "SELL_SHORT"
            reason_parts.append("Supertrend Flipped RED")
            reason_parts.append(f"Close (₹{curr_close:,.2f}) < EMA50 (₹{curr_ema:,.2f})")
            if self.use_volume_filter:
                reason_parts.append(f"Volume > 1.2x SMA20")
            if self.use_mtf:
                reason_parts.append(f"HTF Supertrend Bearish")
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
