import React, { useState, useEffect } from 'react';
import {
  TrendingDown,
  Zap,
  RefreshCw,
  AlertTriangle,
  ShieldAlert,
  Clock,
  Sparkles,
  Flame,
  ArrowDownRight,
  Search,
  X,
  Filter,
  Layers,
  Send,
  Target,
  CheckCircle2,
  Crosshair,
  Activity
} from 'lucide-react';

const API_BASE_URL = '/api';

export default function MorningShortScanner() {
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [filterScore, setFilterScore] = useState(40);
  const [selectedStage, setSelectedStage] = useState('ALL'); // 'ALL', 'STAGE 1', 'STAGE 2'
  const [searchQuery, setSearchQuery] = useState('');
  const [alertingSymbols, setAlertingSymbols] = useState({});
  const [alertSuccess, setAlertSuccess] = useState({});
  const [timing, setTiming] = useState(null);

  const fetchShortCandidates = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/short-candidates`);
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'success') {
          setCandidates(data.data || data.candidates || []);
          setLastUpdated(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
        } else {
          setError(data.detail || 'Failed to load short candidates');
        }
      } else {
        setError(`Server returned status ${res.status}`);
      }
    } catch (err) {
      setError(err.message || 'Network error fetching short candidates');
    } finally {
      setLoading(false);
    }
  };

  const handleTriggerScan = async () => {
    setScanning(true);
    try {
      const res = await fetch(`${API_BASE_URL}/scan-short-candidates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      if (res.ok) {
        setTimeout(() => {
          fetchShortCandidates();
          setScanning(false);
        }, 3000);
      } else {
        setScanning(false);
      }
    } catch (err) {
      console.error('Failed to trigger short scan:', err);
      setScanning(false);
    }
  };

  const handleSendTelegramAlert = async (symbol) => {
    if (!symbol) return;
    setAlertingSymbols(prev => ({ ...prev, [symbol]: true }));
    try {
      const res = await fetch(`${API_BASE_URL}/short-candidates/${symbol}/alert`, {
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
    fetchShortCandidates();
    fetchMarketTiming();
    const interval = setInterval(fetchMarketTiming, 60000);
    return () => clearInterval(interval);
  }, []);

  const filteredCandidates = candidates
    .filter((c) => {
      if (selectedStage === 'STAGE 1') return c.stage === 'STAGE 1';
      if (selectedStage === 'STAGE 2') return c.stage === 'STAGE 2';
      return true;
    })
    .filter((c) => (c.short_probability_score || 0) >= filterScore)
    .filter((c) => (c.symbol || '').toLowerCase().includes(searchQuery.toLowerCase().trim()))
    .sort((a, b) => (b.short_probability_score || 0) - (a.short_probability_score || 0));

  const stage1Count = candidates.filter(c => c.stage === 'STAGE 1').length;
  const stage2Count = candidates.filter(c => c.stage === 'STAGE 2').length;

  return (
    <div className="morning-short-container">
      {/* Premium Hero Header */}
      <div className="morning-short-hero">
        <div className="morning-short-hero-content">
          <div>
            <div className="morning-short-badges">
              <span className="badge-setup-time">
                <Clock size={13} />
                09:15 AM – 11:30 AM IST (2:45 PM – 5:00 PM Sydney)
              </span>
              {timing && (
                <span
                  className="badge-zerodha-live"
                  style={{
                    background: timing?.morning_short_scanner?.is_active_now
                      ? 'rgba(34, 197, 94, 0.18)'
                      : 'rgba(148, 163, 184, 0.12)',
                    borderColor: timing?.morning_short_scanner?.is_active_now
                      ? 'rgba(34, 197, 94, 0.45)'
                      : 'rgba(148, 163, 184, 0.25)',
                    color: timing?.morning_short_scanner?.is_active_now ? '#22c55e' : '#94a3b8'
                  }}
                  title={timing?.morning_short_scanner?.status_message}
                >
                  <Activity size={12} />
                  {timing?.morning_short_scanner?.is_active_now
                    ? '🟢 Active 5m Morning Window'
                    : '⏸️ Scheduled: 2:45 PM - 5:00 PM Sydney'}
                </span>
              )}
              <span className="badge-zerodha-live">
                <Zap size={13} />
                Zerodha 5m Live Engine
              </span>
              <span className="badge-zerodha-live" style={{ background: 'rgba(56, 189, 248, 0.15)', borderColor: 'rgba(56, 189, 248, 0.3)', color: '#38bdf8' }}>
                <Send size={12} />
                Telegram Chart Alerts
              </span>
              {lastUpdated && (
                <span className="badge-sync-time">
                  <Clock size={13} />
                  Synced {lastUpdated}
                </span>
              )}
            </div>

            <h1 className="morning-short-title">
              <span className="morning-short-title-text">Morning Exhaustion & VWAP Reversion</span>
              <span className="morning-short-title-icon">
                <TrendingDown size={22} />
              </span>
            </h1>
            <p className="morning-short-desc">
              Low-noise, institutional 5-minute scanner detecting <strong>Stage 1 Sniper Reversion</strong> (+2 SD VWAP exhaustion) and <strong>Stage 2 VWAP Breakdown</strong> with Volume, OBV & TSI confirmation.
            </p>
          </div>

          <div className="morning-short-hero-actions">
            <button
              onClick={handleTriggerScan}
              disabled={scanning}
              className="btn-run-short-scan"
            >
              <RefreshCw size={15} className={scanning ? 'spin' : ''} />
              <span>{scanning ? 'Scanning 5m Market...' : 'Run 5m Live Scan ⚡'}</span>
            </button>
            <button
              onClick={fetchShortCandidates}
              disabled={loading}
              className="btn-refresh-short-scan"
              title="Refresh Candidates List"
            >
              <RefreshCw size={15} className={loading ? 'spin' : ''} />
            </button>
          </div>
        </div>
      </div>

      {/* Control Toolbar: Stage Filter Tabs & Search Box */}
      <div className="morning-short-toolbar">
        {/* Left: Stage Selection & Score Filters */}
        <div className="filter-pills-group">
          <div className="filter-label">
            <Filter size={14} />
            <span>Setup Stage:</span>
          </div>

          <button
            onClick={() => setSelectedStage('ALL')}
            className={`pill-btn ${selectedStage === 'ALL' ? 'active' : ''}`}
          >
            <span>All Setups ({candidates.length})</span>
          </button>

          <button
            onClick={() => setSelectedStage('STAGE 1')}
            className={`pill-btn ${selectedStage === 'STAGE 1' ? 'active' : ''}`}
            style={selectedStage === 'STAGE 1' ? { background: 'linear-gradient(135deg, #e11d48, #be123c)' } : {}}
          >
            <Target size={13} />
            <span>Stage 1: Sniper Reversion ({stage1Count})</span>
          </button>

          <button
            onClick={() => setSelectedStage('STAGE 2')}
            className={`pill-btn ${selectedStage === 'STAGE 2' ? 'active' : ''}`}
            style={selectedStage === 'STAGE 2' ? { background: 'linear-gradient(135deg, #f59e0b, #d97706)' } : {}}
          >
            <Zap size={13} />
            <span>Stage 2: VWAP Breakdown ({stage2Count})</span>
          </button>

          <div className="filter-label" style={{ marginLeft: '0.75rem' }}>
            <span>Min Score:</span>
          </div>
          {[40, 50, 65, 75].map((score) => {
            const isActive = filterScore === score;
            return (
              <button
                key={score}
                onClick={() => setFilterScore(score)}
                className={`pill-btn ${isActive ? 'active' : ''}`}
              >
                {score >= 75 && <Flame size={12} />}
                <span>&ge; {score}</span>
              </button>
            );
          })}
        </div>

        {/* Right: Search Box + Match Counter */}
        <div className="short-search-wrapper">
          <div className="short-search-input-box">
            <Search size={15} className="short-search-icon" />
            <input
              type="text"
              placeholder="Search symbol (e.g. RELIANCE)..."
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
            <span><strong>{filteredCandidates.length}</strong> {filteredCandidates.length === 1 ? 'candidate' : 'candidates'}</span>
          </div>
        </div>
      </div>

      {/* Main Table Content */}
      {loading && candidates.length === 0 ? (
        <div className="short-table-card" style={{ padding: '4rem 2rem', textAlign: 'center' }}>
          <RefreshCw size={36} className="spin" style={{ color: 'var(--danger-rose)', margin: '0 auto 1rem' }} />
          <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#ffffff' }}>Scanning 5-minute intraday VWAP rejection setups via Zerodha API...</h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>Evaluating +2SD upper band exhaustion, OBV floor breakdowns, and TSI bearish crossovers</p>
        </div>
      ) : error ? (
        <div className="short-table-card" style={{ padding: '2rem', display: 'flex', alignItems: 'center', gap: '1rem', background: 'rgba(244, 63, 94, 0.1)', borderColor: 'rgba(244, 63, 94, 0.3)' }}>
          <AlertTriangle size={28} style={{ color: '#fb7185', flexShrink: 0 }} />
          <div>
            <div style={{ fontWeight: 700, fontSize: '1rem', color: '#ffffff' }}>Error Loading Short Candidates</div>
            <div style={{ fontSize: '0.8rem', color: '#fda4af', marginTop: '0.2rem' }}>{error}</div>
          </div>
        </div>
      ) : filteredCandidates.length === 0 ? (
        <div className="short-table-card" style={{ padding: '4rem 2rem', textAlign: 'center' }}>
          <ShieldAlert size={44} style={{ color: 'var(--text-dim)', margin: '0 auto 0.75rem' }} />
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#ffffff' }}>No candidates match active filters</h3>
          <p style={{ fontSize: '0.825rem', color: 'var(--text-muted)', marginTop: '0.4rem', maxWidth: '420px', marginInline: 'auto' }}>
            {searchQuery
              ? `No stock symbol matching "${searchQuery}" with conviction ≥ ${filterScore} Pts.`
              : `Try selecting "All Setups" or click "Run 5m Live Scan ⚡" to evaluate the current market.`}
          </p>
          {(searchQuery || selectedStage !== 'ALL') && (
            <button
              onClick={() => { setSearchQuery(''); setSelectedStage('ALL'); }}
              className="pill-btn"
              style={{ marginTop: '1rem', padding: '0.5rem 1rem' }}
            >
              Reset Filters
            </button>
          )}
        </div>
      ) : (
        <div className="short-table-card">
          <table className="short-data-table">
            <thead>
              <tr>
                <th style={{ width: '22%' }}>Stock & Setup Stage</th>
                <th style={{ width: '20%' }}>Price, VWAP & Ext.</th>
                <th style={{ width: '22%' }}>Trade Levels (R:R)</th>
                <th style={{ width: '24%' }}>Structural Triggers</th>
                <th style={{ width: '12%', textAlign: 'center' }}>Telegram Alert</th>
              </tr>
            </thead>
            <tbody>
              {filteredCandidates.map((c, idx) => {
                const stockName = c.symbol || '';
                const score = c.short_probability_score || 0;
                const stage = c.stage;
                const isAlerting = alertingSymbols[stockName];
                const isAlertSent = alertSuccess[stockName];

                return (
                  <tr key={stockName || idx}>
                    {/* COLUMN 1: STOCK & SETUP STAGE */}
                    <td>
                      <div className="stock-cell-info">
                        <div className="rank-pill">
                          #{idx + 1}
                        </div>
                        <div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                            <span className="stock-symbol-title">{stockName}</span>
                            {stage === 'STAGE 1' ? (
                              <span className="badge-stage-1">
                                <Target size={11} /> Stage 1 Sniper
                              </span>
                            ) : stage === 'STAGE 2' ? (
                              <span className="badge-stage-2">
                                <Zap size={11} /> Stage 2 VWAP
                              </span>
                            ) : (
                              <span className="badge-stage-watch">
                                Watchlist
                              </span>
                            )}
                          </div>
                          <div className="score-subtitle">
                            Conviction: <strong>{score.toFixed(1)} / 100</strong>
                            {c.morning_runup_pct > 0 && (
                              <span style={{ color: '#fda4af', marginLeft: '0.5rem' }}>
                                (Peak: +{c.morning_runup_pct}%)
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* COLUMN 2: PRICE, VWAP & EXTENSION */}
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                          <span style={{ color: '#ffffff', fontWeight: 700, fontSize: '0.95rem' }}>
                            ₹{c.close_price?.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </span>
                          {c.room_to_vwap_pct !== undefined && c.room_to_vwap_pct > 0 && (
                            <span className="reason-pct-tag" style={{ padding: '0.1rem 0.4rem', fontSize: '0.7rem' }}>
                              +{c.room_to_vwap_pct}% to VWAP
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                          VWAP: <strong style={{ color: '#fde047' }}>₹{c.vwap?.toFixed(2)}</strong>
                          {c.upper_band_2sd > 0 && (
                            <span style={{ marginLeft: '0.5rem', color: '#f472b6' }}>
                              (+2SD: ₹{c.upper_band_2sd?.toFixed(2)})
                            </span>
                          )}
                        </div>
                      </div>
                    </td>

                    {/* COLUMN 3: EXECUTION LEVELS (ENTRY / SL / TARGET) */}
                    <td>
                      <div className="levels-grid">
                        <div className="level-row">
                          <span className="level-lbl">Entry:</span>
                          <span className="level-val">₹{c.suggested_entry?.toFixed(2)}</span>
                        </div>
                        <div className="level-row">
                          <span className="level-lbl">R : R:</span>
                          <span className="level-val" style={{ color: '#38bdf8' }}>{c.risk_reward || '1 : 2.0'}</span>
                        </div>
                        <div className="level-row">
                          <span className="level-lbl">Stop Loss:</span>
                          <span className="level-val sl">₹{c.stop_loss?.toFixed(2)}</span>
                        </div>
                        <div className="level-row">
                          <span className="level-lbl">Target:</span>
                          <span className="level-val tgt">₹{c.target_price?.toFixed(2)}</span>
                        </div>
                      </div>
                    </td>

                    {/* COLUMN 4: STRUCTURAL TRIGGERS */}
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                        <div style={{ fontSize: '0.825rem', fontWeight: 600, color: 'var(--text-main)', lineHeight: 1.4 }}>
                          {c.reason || 'Developing short structure'}
                        </div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem' }}>
                          {c.failed_push_type && c.failed_push_type !== 'None' && (
                            <span className="trigger-tag-pill" style={{ color: '#fda4af', borderColor: 'rgba(244, 63, 94, 0.3)' }}>
                              <ArrowDownRight size={11} /> {c.failed_push_type}
                            </span>
                          )}
                          {c.tsi_confirmed_roll && (
                            <span className="trigger-tag-pill" style={{ color: '#38bdf8', borderColor: 'rgba(56, 189, 248, 0.3)' }}>
                              <Activity size={11} /> TSI Bearish Roll
                            </span>
                          )}
                          {c.obv_breakdown && (
                            <span className="trigger-tag-pill" style={{ color: '#c084fc', borderColor: 'rgba(192, 132, 252, 0.3)' }}>
                              OBV Breakdown
                            </span>
                          )}
                          {c.vol_climax && (
                            <span className="trigger-tag-pill" style={{ color: '#fde047', borderColor: 'rgba(253, 224, 71, 0.3)' }}>
                              <Flame size={11} /> Vol Climax
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
                        title="Dispatch in-memory 5m chart & alert to Telegram"
                      >
                        {isAlerting ? (
                          <>
                            <RefreshCw size={13} className="spin" />
                            <span>Sending...</span>
                          </>
                        ) : isAlertSent ? (
                          <>
                            <CheckCircle2 size={13} style={{ color: '#4ade80' }} />
                            <span style={{ color: '#4ade80' }}>Sent!</span>
                          </>
                        ) : (
                          <>
                            <Send size={13} />
                            <span>Alert 📢</span>
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
