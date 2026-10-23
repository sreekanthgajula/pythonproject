import React, { useState, useEffect } from 'react';
import {
  TrendingUp,
  Zap,
  RefreshCw,
  AlertTriangle,
  ShieldAlert,
  Clock,
  Sparkles,
  Flame,
  ArrowUpRight,
  Search,
  X,
  Filter,
  Layers,
  Activity,
  CheckCircle2,
  Send,
  Target
} from 'lucide-react';

const API_BASE_URL = '/api';

export default function EveningProScanner() {
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [filterScore, setFilterScore] = useState(50);
  const [searchQuery, setSearchQuery] = useState('');
  const [timing, setTiming] = useState(null);
  const [alertingSymbols, setAlertingSymbols] = useState({});
  const [alertSuccess, setAlertSuccess] = useState({});

  const handleSendTelegramAlert = async (symbol) => {
    if (!symbol) return;
    setAlertingSymbols(prev => ({ ...prev, [symbol]: true }));
    try {
      const res = await fetch(`${API_BASE_URL}/evening-candidates/${symbol}/alert`, {
        method: 'POST'
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setAlertSuccess(prev => ({ ...prev, [symbol]: true }));
        setTimeout(() => {
          setAlertSuccess(prev => ({ ...prev, [symbol]: false }));
        }, 4000);
      } else {
        alert(`Alert dispatch failed: ${data.detail || (data.result && data.result.message) || 'Unknown error'}`);
      }
    } catch (err) {
      alert(`Network error dispatching alert: ${err.message}`);
    } finally {
      setAlertingSymbols(prev => ({ ...prev, [symbol]: false }));
    }
  };

  const fetchEveningCandidates = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/evening-candidates`);
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'success') {
          setCandidates(data.data || data.candidates || []);
          setLastUpdated(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
        } else {
          setError(data.detail || 'Failed to load candidates');
        }
      } else {
        setError(`Server returned status ${res.status}`);
      }
    } catch (err) {
      setError(err.message || 'Network error fetching evening candidates');
    } finally {
      setLoading(false);
    }
  };

  const handleTriggerScan = async () => {
    setScanning(true);
    try {
      const res = await fetch(`${API_BASE_URL}/scan-evening-candidates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      if (res.ok) {
        setTimeout(() => {
          fetchEveningCandidates();
          setScanning(false);
        }, 2500);
      } else {
        setScanning(false);
      }
    } catch (err) {
      console.error('Failed to trigger scan:', err);
      setScanning(false);
    }
  };

  const fetchMarketTiming = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/market-timing`);
      if (res.ok) {
        const data = await res.json();
        setTiming(data);
      }
    } catch (e) {
      // ignore
    }
  };

  useEffect(() => {
    fetchEveningCandidates();
    fetchMarketTiming();
    const interval = setInterval(fetchMarketTiming, 60000);
    return () => clearInterval(interval);
  }, []);

  const filteredCandidates = candidates
    .filter((c) => (c.pro_buying_score || 0) >= filterScore)
    .filter((c) => (c.symbol || '').toLowerCase().includes(searchQuery.toLowerCase().trim()))
    .sort((a, b) => (b.pro_buying_score || 0) - (a.pro_buying_score || 0));

  const formatReason = (rawReason, closePosPct) => {
    const closePct = closePosPct !== undefined && closePosPct !== null ? closePosPct : 0.0;
    if (!rawReason) {
      return { main: "Heavy Professional Buying", pct: `${closePct}%` };
    }
    const parts = rawReason.split('|').map(s => s.trim());
    const mainPart = parts.find(p => p.toLowerCase().includes('professional buying')) || parts[0];
    const cleaned = mainPart.replace(/^[^a-zA-Z]*/, '').trim();
    const match = cleaned.match(/Closed at ([0-9.]+)%/i);
    if (match) {
      return { main: "Heavy Professional Buying", pct: `${match[1]}%` };
    }
    return { main: cleaned || "Heavy Professional Buying", pct: `${closePct}%` };
  };

  return (
    <div className="evening-pro-container">
      {/* Premium Hero Header */}
      <div className="evening-pro-hero">
        <div className="morning-short-hero-content">
          <div>
            <div className="morning-short-badges">
              <span className="badge-evening-setup">
                <Clock size={13} />
                2:30 PM – 3:30 PM IST (8:00 PM – 9:00 PM Sydney) BTST Setup
              </span>
              {timing && (
                <span
                  className="badge-zerodha-live"
                  style={{
                    background: timing?.evening_pro_scanner?.is_active_now
                      ? 'rgba(34, 197, 94, 0.18)'
                      : 'rgba(148, 163, 184, 0.12)',
                    borderColor: timing?.evening_pro_scanner?.is_active_now
                      ? 'rgba(34, 197, 94, 0.45)'
                      : 'rgba(148, 163, 184, 0.25)',
                    color: timing?.evening_pro_scanner?.is_active_now ? '#22c55e' : '#94a3b8'
                  }}
                  title={timing?.evening_pro_scanner?.status_message}
                >
                  <Activity size={12} />
                  {timing?.evening_pro_scanner?.is_active_now
                    ? '🟢 Active BTST Window'
                    : '⏸️ Scheduled: 8:00 PM - 9:00 PM Sydney'}
                </span>
              )}
              <span className="badge-zerodha-live">
                <Zap size={13} />
                Zerodha API Live Engine
              </span>
              {lastUpdated && (
                <span className="badge-sync-time">
                  <Clock size={13} />
                  Synced {lastUpdated}
                </span>
              )}
            </div>

            <h1 className="morning-short-title">
              <span className="evening-pro-title-text">Supertrend Pro Buying (BTST)</span>
              <span className="evening-pro-title-icon">
                <TrendingUp size={22} />
              </span>
            </h1>
            <p className="morning-short-desc">
              Advanced <strong>Supertrend (10, 3)</strong> &amp; <strong>EMA 50</strong> trend-following strategy with volume expansion filter and dynamic ATR position sizing for Indian equities.
            </p>
          </div>

          <div className="morning-short-hero-actions">
            <button
              onClick={handleTriggerScan}
              disabled={scanning}
              className="btn-run-evening-scan"
            >
              <RefreshCw size={15} className={scanning ? 'spin' : ''} />
              <span>{scanning ? 'Scanning Market...' : 'Run Evening Scan ⚡'}</span>
            </button>
            <button
              onClick={fetchEveningCandidates}
              disabled={loading}
              className="btn-refresh-short-scan"
              title="Refresh Candidates List"
            >
              <RefreshCw size={15} className={loading ? 'spin' : ''} />
            </button>
          </div>
        </div>
      </div>

      {/* Control Toolbar */}
      <div className="morning-short-toolbar">
        {/* Left: Score Filter Pills */}
        <div className="filter-pills-group">
          <div className="filter-label">
            <Filter size={14} />
            <span>Min Conviction:</span>
          </div>
          {[40, 50, 65, 75, 85].map((score) => {
            const isActive = filterScore === score;
            return (
              <button
                key={score}
                onClick={() => setFilterScore(score)}
                className={`pill-btn ${isActive ? 'active-emerald' : ''}`}
              >
                {score >= 75 && <Flame size={13} />}
                <span>&ge; {score} Pts</span>
              </button>
            );
          })}
        </div>

        {/* Right: Realigned Search Box + Counter */}
        <div className="short-search-wrapper">
          <div className="short-search-input-box">
            <Search size={15} className="short-search-icon" />
            <input
              type="text"
              placeholder="Search stock symbol..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="short-search-input"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="short-search-clear"
                title="Clear Search"
              >
                <X size={14} />
              </button>
            )}
          </div>

          <div className="short-counter-badge">
            <Layers size={14} />
            <span><strong>{filteredCandidates.length}</strong> {filteredCandidates.length === 1 ? 'stock' : 'stocks'}</span>
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      {loading && candidates.length === 0 ? (
        <div className="short-table-card" style={{ padding: '4rem 2rem', textAlign: 'center' }}>
          <RefreshCw size={36} className="spin" style={{ color: '#10b981', margin: '0 auto 1rem' }} />
          <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#ffffff' }}>Scanning late-day professional accumulation setups via Zerodha API...</h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>Analyzing day-end closing power and volume expansion</p>
        </div>
      ) : error ? (
        <div className="short-table-card" style={{ padding: '2rem', display: 'flex', alignItems: 'center', gap: '1rem', background: 'rgba(16, 185, 129, 0.1)', borderColor: 'rgba(16, 185, 129, 0.3)' }}>
          <AlertTriangle size={28} style={{ color: '#34d399', flexShrink: 0 }} />
          <div>
            <div style={{ fontWeight: 700, fontSize: '1rem', color: '#ffffff' }}>Error Loading Evening Candidates</div>
            <div style={{ fontSize: '0.8rem', color: '#a7f3d0', marginTop: '0.2rem' }}>{error}</div>
          </div>
        </div>
      ) : filteredCandidates.length === 0 ? (
        <div className="short-table-card" style={{ padding: '4rem 2rem', textAlign: 'center' }}>
          <ShieldAlert size={44} style={{ color: 'var(--text-dim)', margin: '0 auto 0.75rem' }} />
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#ffffff' }}>No stocks match current filters</h3>
          <p style={{ fontSize: '0.825rem', color: 'var(--text-muted)', marginTop: '0.4rem', maxWidth: '400px', marginInLine: 'auto' }}>
            {searchQuery
              ? `No stock symbol matching "${searchQuery}" with conviction ≥ ${filterScore} Pts.`
              : `Try lowering the conviction threshold below ${filterScore} Pts or run a live market scan.`}
          </p>
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="pill-btn"
              style={{ marginTop: '1rem', padding: '0.5rem 1rem' }}
            >
              Clear Search Query
            </button>
          )}
        </div>
      ) : (
        <div className="short-table-card">
          <table className="short-data-table">
            <thead>
              <tr>
                <th style={{ width: '22%' }}>Stock & Setup Signal</th>
                <th style={{ width: '20%' }}>LTP, ST (10,3) & EMA50</th>
                <th style={{ width: '22%' }}>Strategy Levels (1:2 R:R)</th>
                <th style={{ width: '24%' }}>Accumulation Conditions</th>
                <th style={{ width: '12%', textAlign: 'center' }}>Telegram Alert</th>
              </tr>
            </thead>
            <tbody>
              {filteredCandidates.map((c, idx) => {
                const stockName = c.symbol || '';
                const score = c.pro_buying_score || 0;
                const isAlerting = alertingSymbols[stockName];
                const isAlertSent = alertSuccess[stockName];
                const formattedReason = formatReason(c.reason, c.close_position_pct);
                const isBuy = c.signal === 'BUY';
                const isFlipped = c.supertrend_flipped_green;
                const isAboveEma = c.above_ema50;
                const isVolPassed = c.volume_filter_passed;

                return (
                  <tr key={stockName || idx}>
                    {/* COLUMN 1: STOCK & SETUP SIGNAL */}
                    <td>
                      <div className="stock-cell-info">
                        <div className="rank-pill" style={{ background: 'rgba(16, 185, 129, 0.2)', color: '#34d399', borderColor: 'rgba(16, 185, 129, 0.4)' }}>
                          #{idx + 1}
                        </div>
                        <div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
                            <span className="stock-symbol-title">{stockName}</span>
                            {isFlipped ? (
                              <span className="badge-stage-1" style={{ background: 'rgba(34, 197, 94, 0.2)', color: '#4ade80', borderColor: 'rgba(34, 197, 94, 0.4)' }}>
                                <Zap size={11} /> ST Flip Green
                              </span>
                            ) : isBuy ? (
                              <span className="badge-stage-1" style={{ background: 'rgba(16, 185, 129, 0.2)', color: '#34d399', borderColor: 'rgba(16, 185, 129, 0.4)' }}>
                                <TrendingUp size={11} /> BUY Signal
                              </span>
                            ) : score >= 75 ? (
                              <span className="badge-high-pro-conviction">
                                <Flame size={11} /> High BTST
                              </span>
                            ) : null}
                          </div>
                          <div className="score-subtitle" style={{ marginTop: '0.25rem' }}>
                            Supertrend Score: <strong style={{ color: score >= 75 ? '#34d399' : '#a7f3d0' }}>{score.toFixed(1)} / 100</strong>
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* COLUMN 2: LTP, ST (10,3) & EMA50 */}
                    <td>
                      <div className="price-stack">
                        <div className="ltp-row">
                          <span className="label-dim">LTP:</span>
                          <span className="val-bright" style={{ color: '#34d399', fontWeight: 700 }}>₹{c.close_price ? c.close_price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '-'}</span>
                        </div>
                        <div className="metric-subrow">
                          <span className="label-dim">ST (10,3):</span>
                          <span style={{ color: c.supertrend_direction?.includes('BULLISH') ? '#4ade80' : '#f87171', fontWeight: 600 }}>
                            ₹{c.supertrend ? c.supertrend.toFixed(2) : '-'}
                          </span>
                        </div>
                        <div className="metric-subrow">
                          <span className="label-dim">EMA 50:</span>
                          <span style={{ color: isAboveEma ? '#38bdf8' : '#94a3b8' }}>
                            ₹{c.ema50 ? c.ema50.toFixed(2) : '-'} {isAboveEma && '✓'}
                          </span>
                        </div>
                      </div>
                    </td>

                    {/* COLUMN 3: STRATEGY LEVELS */}
                    <td>
                      <div className="trade-levels-grid">
                        <div className="level-item entry">
                          <span className="level-label">Entry</span>
                          <span className="level-val" style={{ color: '#38bdf8' }}>₹{c.suggested_entry ? c.suggested_entry.toFixed(2) : '-'}</span>
                        </div>
                        <div className="level-item stop">
                          <span className="level-label">ST Stop</span>
                          <span className="level-val" style={{ color: '#f87171' }}>₹{c.stop_loss ? c.stop_loss.toFixed(2) : '-'}</span>
                        </div>
                        <div className="level-item target">
                          <span className="level-label">1:2 Target</span>
                          <span className="level-val" style={{ color: '#4ade80' }}>₹{c.target_price ? c.target_price.toFixed(2) : '-'}</span>
                        </div>
                      </div>
                      {c.position_size_shares > 0 && (
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                          Size (1% Risk): <strong style={{ color: '#ffffff' }}>{c.position_size_shares} shares</strong> {c.stop_distance_pct ? `(${c.stop_distance_pct}% risk)` : ''}
                        </div>
                      )}
                    </td>

                    {/* COLUMN 4: ACCUMULATION CONDITIONS */}
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem' }}>
                          {isFlipped && (
                            <span className="trigger-tag-pill" style={{ color: '#4ade80', borderColor: 'rgba(34, 197, 94, 0.4)', background: 'rgba(34, 197, 94, 0.1)' }}>
                              <Zap size={11} /> Red ➔ Green Flip
                            </span>
                          )}
                          {isAboveEma && (
                            <span className="trigger-tag-pill" style={{ color: '#38bdf8', borderColor: 'rgba(56, 189, 248, 0.4)', background: 'rgba(56, 189, 248, 0.1)' }}>
                              Close &gt; EMA 50
                            </span>
                          )}
                          {isVolPassed && (
                            <span className="trigger-tag-pill" style={{ color: '#fde047', borderColor: 'rgba(253, 224, 71, 0.4)', background: 'rgba(253, 224, 71, 0.1)' }}>
                              <Flame size={11} /> Vol &gt; 1.2x SMA20
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', lineHeight: '1.25' }}>
                          {formattedReason.main}
                          {formattedReason.pct && (
                            <span style={{ color: '#34d399', marginLeft: '0.25rem' }}>
                              ({formattedReason.pct} of day range)
                            </span>
                          )}
                        </div>
                      </div>
                    </td>

                    {/* COLUMN 5: TELEGRAM ALERT ACTION */}
                    <td style={{ textAlign: 'center' }}>
                      <button
                        onClick={() => handleSendTelegramAlert(stockName)}
                        disabled={isAlerting || isAlertSent}
                        className="btn-send-tg-alert"
                        style={{
                          background: isAlertSent ? 'rgba(34, 197, 94, 0.2)' : 'rgba(16, 185, 129, 0.15)',
                          borderColor: isAlertSent ? '#22c55e' : 'rgba(16, 185, 129, 0.4)',
                          color: isAlertSent ? '#4ade80' : '#34d399'
                        }}
                        title="Dispatch Supertrend chart & BTST alert to Telegram"
                      >
                        {isAlerting ? (
                          <>
                            <RefreshCw size={13} className="spin" />
                            <span>Sending...</span>
                          </>
                        ) : isAlertSent ? (
                          <>
                            <CheckCircle2 size={13} style={{ color: '#4ade80' }} />
                            <span style={{ color: '#4ade80' }}>Alert Sent!</span>
                          </>
                        ) : (
                          <>
                            <Send size={13} />
                            <span>Send Alert 🚀</span>
                          </>
                        )}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
