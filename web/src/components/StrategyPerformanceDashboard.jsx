import React, { useState, useEffect } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Activity,
  Award,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  Clock,
  Filter,
  RefreshCw,
  Zap,
  DollarSign,
  BarChart2,
  ToggleLeft,
  ToggleRight,
  Layers,
  ArrowUpRight,
  ArrowDownRight
} from 'lucide-react';

const API_BASE_URL = '/api';

export default function StrategyPerformanceDashboard() {
  const [strategies, setStrategies] = useState([]);
  const [trades, setTrades] = useState([]);
  const [selectedStrategyId, setSelectedStrategyId] = useState('all');
  const [loading, setLoading] = useState(false);
  const [togglingId, setTogglingId] = useState(null);

  // Summary Metrics
  const [totalEquity, setTotalEquity] = useState(0);
  const [totalRealizedPnl, setTotalRealizedPnl] = useState(0);
  const [totalTradesCount, setTotalTradesCount] = useState(0);
  const [overallWinRate, setOverallWinRate] = useState(0);

  const fetchStrategies = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/paper/strategies`);
      if (res.ok) {
        const json = await res.json();
        const strats = json.strategies || [];
        setStrategies(strats);

        // Compute overall metrics across all 10 strategies
        let equitySum = 0;
        let pnlSum = 0;
        let tradesSum = 0;
        let winningTradesCount = 0;

        strats.forEach(s => {
          equitySum += s.total_equity || 100000;
          pnlSum += s.realized_pnl || 0;
          tradesSum += s.total_trades_count || 0;
        });

        setTotalEquity(equitySum);
        setTotalRealizedPnl(pnlSum);
        setTotalTradesCount(tradesSum);
      }
    } catch (err) {
      console.error('Error fetching paper strategies:', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchTrades = async (stratId = 'all') => {
    try {
      const url = `${API_BASE_URL}/paper/trades${stratId !== 'all' ? `?strategy_id=${stratId}` : ''}`;
      const res = await fetch(url);
      if (res.ok) {
        const json = await res.json();
        const tradeList = json.trades || [];
        setTrades(tradeList);

        if (tradeList.length > 0) {
          const wins = tradeList.filter(t => t.realized_pnl > 0).length;
          setOverallWinRate(((wins / tradeList.length) * 100).toFixed(1));
        } else {
          setOverallWinRate(0);
        }
      }
    } catch (err) {
      console.error('Error fetching paper trades:', err);
    }
  };

  useEffect(() => {
    fetchStrategies();
    fetchTrades('all');
  }, []);

  const handleToggleStrategy = async (strategyId, currentEnabled) => {
    setTogglingId(strategyId);
    try {
      const res = await fetch(`${API_BASE_URL}/paper/toggle-strategy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy_id: strategyId, enabled: !currentEnabled })
      });
      if (res.ok) {
        setStrategies(prev =>
          prev.map(s => (s.strategy_id === strategyId ? { ...s, enabled: !currentEnabled } : s))
        );
      }
    } catch (err) {
      console.error(`Failed to toggle strategy ${strategyId}:`, err);
    } finally {
      setTogglingId(null);
    }
  };

  const handleStrategyFilterChange = (stratId) => {
    setSelectedStrategyId(stratId);
    fetchTrades(stratId);
  };

  const initialTotalCapital = strategies.length * 100000;

  return (
    <div className="strategy-dashboard-container" style={{ padding: '24px', color: '#f8fafc' }}>
      {/* 1. Header & Live Refresh */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '28px', fontWeight: '800', background: 'linear-gradient(90deg, #38bdf8, #818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Zap size={28} color="#38bdf8" /> Multi-Strategy Paper Trading Engine
          </h1>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '14px' }}>
            Real-time performance metrics, portfolio progress & profit/loss audit for all 10 automated strategies
          </p>
        </div>
        <button
          onClick={() => { fetchStrategies(); fetchTrades(selectedStrategyId); }}
          disabled={loading}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '10px 18px',
            backgroundColor: '#1e293b',
            color: '#38bdf8',
            border: '1px solid #334155',
            borderRadius: '10px',
            cursor: 'pointer',
            fontWeight: '600',
            transition: 'all 0.2s ease'
          }}
        >
          <RefreshCw size={16} className={loading ? 'spin-anim' : ''} />
          Refresh Stats
        </button>
      </div>

      {/* 2. Key Performance Metrics Summary Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px', marginBottom: '28px' }}>
        {/* Total Equity */}
        <div style={{ background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.9), rgba(30, 41, 59, 0.7))', padding: '20px', borderRadius: '16px', border: '1px solid #334155', boxShadow: '0 4px 20px rgba(0,0,0,0.3)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#94a3b8', fontSize: '13px', fontWeight: '600' }}>
            TOTAL PORTFOLIO EQUITY
            <BarChart2 size={18} color="#38bdf8" />
          </div>
          <div style={{ fontSize: '26px', fontWeight: '800', margin: '8px 0 4px 0', color: '#f8fafc' }}>
            ₹{totalEquity.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
          </div>
          <div style={{ fontSize: '12px', color: totalEquity >= initialTotalCapital ? '#4ade80' : '#f87171', fontWeight: '600' }}>
            {totalEquity >= initialTotalCapital ? '▲' : '▼'} ₹{(totalEquity - initialTotalCapital).toLocaleString('en-IN', { maximumFractionDigits: 2 })} from ₹{initialTotalCapital.toLocaleString('en-IN')} capital
          </div>
        </div>

        {/* Realized P&L */}
        <div style={{ background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.9), rgba(30, 41, 59, 0.7))', padding: '20px', borderRadius: '16px', border: '1px solid #334155', boxShadow: '0 4px 20px rgba(0,0,0,0.3)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#94a3b8', fontSize: '13px', fontWeight: '600' }}>
            NET REALIZED P&L
            {totalRealizedPnl >= 0 ? <TrendingUp size={18} color="#4ade80" /> : <TrendingDown size={18} color="#f87171" />}
          </div>
          <div style={{ fontSize: '26px', fontWeight: '800', margin: '8px 0 4px 0', color: totalRealizedPnl >= 0 ? '#4ade80' : '#f87171' }}>
            {totalRealizedPnl >= 0 ? '+' : ''}₹{totalRealizedPnl.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
          </div>
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>
            Across all completed trades
          </div>
        </div>

        {/* Win Rate */}
        <div style={{ background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.9), rgba(30, 41, 59, 0.7))', padding: '20px', borderRadius: '16px', border: '1px solid #334155', boxShadow: '0 4px 20px rgba(0,0,0,0.3)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#94a3b8', fontSize: '13px', fontWeight: '600' }}>
            OVERALL WIN RATE
            <Award size={18} color="#fbbf24" />
          </div>
          <div style={{ fontSize: '26px', fontWeight: '800', margin: '8px 0 4px 0', color: '#fbbf24' }}>
            {overallWinRate}%
          </div>
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>
            Percentage of profitable trades
          </div>
        </div>

        {/* Total Trades */}
        <div style={{ background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.9), rgba(30, 41, 59, 0.7))', padding: '20px', borderRadius: '16px', border: '1px solid #334155', boxShadow: '0 4px 20px rgba(0,0,0,0.3)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#94a3b8', fontSize: '13px', fontWeight: '600' }}>
            TOTAL TRADES EXECUTED
            <Activity size={18} color="#a78bfa" />
          </div>
          <div style={{ fontSize: '26px', fontWeight: '800', margin: '8px 0 4px 0', color: '#a78bfa' }}>
            {totalTradesCount}
          </div>
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>
            Closed positions logged to DB
          </div>
        </div>
      </div>

      {/* 3. All 10 Strategies Leaderboard Table */}
      <div style={{ background: '#0f172a', borderRadius: '16px', border: '1px solid #334155', padding: '20px', marginBottom: '32px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ fontSize: '18px', fontWeight: '700', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Layers size={20} color="#38bdf8" /> All Strategies Performance Leaderboard
          </h2>
          <span style={{ fontSize: '13px', color: '#64748b' }}>10 Automated Sub-Portfolios (₹100,000 Virtual Balance Each)</span>
        </div>

        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '14px' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #334155', color: '#94a3b8', fontSize: '12px', textTransform: 'uppercase' }}>
                <th style={{ padding: '12px' }}>Status</th>
                <th style={{ padding: '12px' }}>Strategy Name & ID</th>
                <th style={{ padding: '12px' }}>Description</th>
                <th style={{ padding: '12px' }}>Total Equity</th>
                <th style={{ padding: '12px' }}>Realized P&L</th>
                <th style={{ padding: '12px' }}>Win Rate</th>
                <th style={{ padding: '12px' }}>Trades</th>
                <th style={{ padding: '12px' }}>Filter Trades</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((strat) => {
                const isSelected = selectedStrategyId === strat.strategy_id;
                const pnl = strat.realized_pnl || 0;
                return (
                  <tr
                    key={strat.strategy_id}
                    style={{
                      borderBottom: '1px solid #1e293b',
                      backgroundColor: isSelected ? 'rgba(56, 189, 248, 0.08)' : 'transparent',
                      transition: 'background-color 0.2s ease'
                    }}
                  >
                    <td style={{ padding: '14px 12px' }}>
                      <button
                        onClick={() => handleToggleStrategy(strat.strategy_id, strat.enabled)}
                        disabled={togglingId === strat.strategy_id}
                        title={strat.enabled ? 'Click to Disable Strategy' : 'Click to Enable Strategy'}
                        style={{
                          background: 'none',
                          border: 'none',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          color: strat.enabled ? '#4ade80' : '#64748b',
                          fontWeight: '600'
                        }}
                      >
                        {strat.enabled ? <ToggleRight size={26} color="#4ade80" /> : <ToggleLeft size={26} color="#64748b" />}
                        <span style={{ fontSize: '12px' }}>{strat.enabled ? 'ACTIVE' : 'OFF'}</span>
                      </button>
                    </td>

                    <td style={{ padding: '14px 12px' }}>
                      <div style={{ fontWeight: '700', color: '#f8fafc' }}>{strat.name}</div>
                      <div style={{ fontSize: '12px', color: '#38bdf8', fontFamily: 'monospace' }}>{strat.strategy_id}</div>
                    </td>

                    <td style={{ padding: '14px 12px', color: '#94a3b8', fontSize: '13px', maxWidth: '300px' }}>
                      {strat.description}
                    </td>

                    <td style={{ padding: '14px 12px', fontWeight: '700', color: '#f8fafc' }}>
                      ₹{(strat.total_equity || 100000).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                    </td>

                    <td style={{ padding: '14px 12px', fontWeight: '700', color: pnl >= 0 ? '#4ade80' : '#f87171' }}>
                      {pnl >= 0 ? '+' : ''}₹{pnl.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                    </td>

                    <td style={{ padding: '14px 12px' }}>
                      <span style={{ backgroundColor: '#1e293b', padding: '4px 10px', borderRadius: '6px', fontSize: '12px', fontWeight: '600', color: '#fbbf24' }}>
                        {(strat.win_rate || 0).toFixed(1)}%
                      </span>
                    </td>

                    <td style={{ padding: '14px 12px', color: '#cbd5e1' }}>
                      {strat.total_trades_count || 0}
                    </td>

                    <td style={{ padding: '14px 12px' }}>
                      <button
                        onClick={() => handleStrategyFilterChange(isSelected ? 'all' : strat.strategy_id)}
                        style={{
                          padding: '6px 12px',
                          backgroundColor: isSelected ? '#38bdf8' : '#1e293b',
                          color: isSelected ? '#0f172a' : '#94a3b8',
                          border: '1px solid #334155',
                          borderRadius: '8px',
                          cursor: 'pointer',
                          fontSize: '12px',
                          fontWeight: '600'
                        }}
                      >
                        {isSelected ? 'Viewing Trades' : 'View Trades'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 4. Trades Executed (Profit or Loss Detail Table) */}
      <div style={{ background: '#0f172a', borderRadius: '16px', border: '1px solid #334155', padding: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h2 style={{ fontSize: '18px', fontWeight: '700', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Clock size={20} color="#38bdf8" /> Executed Trades History (Profit / Loss Audit)
            </h2>
            <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '13px' }}>
              Showing {trades.length} completed trade records logged in MongoDB `paper_trades`
            </p>
          </div>

          {/* Strategy Filter Dropdown */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Filter size={16} color="#94a3b8" />
            <select
              value={selectedStrategyId}
              onChange={(e) => handleStrategyFilterChange(e.target.value)}
              style={{
                backgroundColor: '#1e293b',
                color: '#f8fafc',
                border: '1px solid #334155',
                borderRadius: '8px',
                padding: '8px 14px',
                fontSize: '13px',
                outline: 'none',
                cursor: 'pointer'
              }}
            >
              <option value="all">All Strategies</option>
              {strategies.map((s) => (
                <option key={s.strategy_id} value={s.strategy_id}>
                  {s.name} ({s.strategy_id})
                </option>
              ))}
            </select>
          </div>
        </div>

        {trades.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px', color: '#64748b' }}>
            <Activity size={40} style={{ marginBottom: '12px', opacity: 0.5 }} />
            <div>No completed paper trades found for this filter.</div>
            <div style={{ fontSize: '12px', marginTop: '4px' }}>Trades will automatically populate as 10-minute candles trigger entry & exit signals.</div>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #334155', color: '#94a3b8', fontSize: '12px', textTransform: 'uppercase' }}>
                  <th style={{ padding: '12px' }}>Exit Time</th>
                  <th style={{ padding: '12px' }}>Strategy ID</th>
                  <th style={{ padding: '12px' }}>Instrument</th>
                  <th style={{ padding: '12px' }}>Action</th>
                  <th style={{ padding: '12px' }}>Entry Price</th>
                  <th style={{ padding: '12px' }}>Exit Price</th>
                  <th style={{ padding: '12px' }}>Qty</th>
                  <th style={{ padding: '12px' }}>Realized P&L</th>
                  <th style={{ padding: '12px' }}>Return %</th>
                  <th style={{ padding: '12px' }}>Exit Reason</th>
                  <th style={{ padding: '12px' }}>Bars Held</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, idx) => {
                  const isProfit = t.realized_pnl >= 0;
                  return (
                    <tr key={idx} style={{ borderBottom: '1px solid #1e293b' }}>
                      <td style={{ padding: '12px', color: '#cbd5e1' }}>
                        {t.exit_time ? new Date(t.exit_time).toLocaleString() : 'N/A'}
                      </td>
                      <td style={{ padding: '12px', fontWeight: '600', color: '#38bdf8' }}>
                        {t.strategy_id}
                      </td>
                      <td style={{ padding: '12px', fontWeight: '700', color: '#f8fafc' }}>
                        {t.symbol || `Token #${t.instrument_token}`}
                      </td>
                      <td style={{ padding: '12px' }}>
                        <span style={{ backgroundColor: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', padding: '3px 8px', borderRadius: '4px', fontWeight: '700', fontSize: '11px' }}>
                          BUY
                        </span>
                      </td>
                      <td style={{ padding: '12px', color: '#cbd5e1' }}>₹{t.entry_price?.toFixed(2)}</td>
                      <td style={{ padding: '12px', color: '#cbd5e1' }}>₹{t.exit_price?.toFixed(2)}</td>
                      <td style={{ padding: '12px', color: '#cbd5e1' }}>{t.quantity}</td>
                      <td style={{ padding: '12px', fontWeight: '800', color: isProfit ? '#4ade80' : '#f87171' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          {isProfit ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}
                          {isProfit ? '+' : ''}₹{t.realized_pnl?.toFixed(2)}
                        </div>
                      </td>
                      <td style={{ padding: '12px', fontWeight: '700' }}>
                        <span style={{
                          backgroundColor: isProfit ? 'rgba(74, 222, 128, 0.15)' : 'rgba(248, 113, 113, 0.15)',
                          color: isProfit ? '#4ade80' : '#f87171',
                          padding: '4px 8px',
                          borderRadius: '6px',
                          fontSize: '12px'
                        }}>
                          {isProfit ? '+' : ''}{t.return_pct?.toFixed(2)}%
                        </span>
                      </td>
                      <td style={{ padding: '12px', color: '#94a3b8', fontSize: '12px', maxWidth: '240px' }}>
                        {t.exit_reason}
                      </td>
                      <td style={{ padding: '12px', color: '#cbd5e1' }}>{t.bars_held} bars</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
