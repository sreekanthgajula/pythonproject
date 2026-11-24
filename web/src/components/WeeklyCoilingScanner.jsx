import React, { useState, useEffect } from 'react';
import {
  Zap,
  RefreshCw,
  Search,
  Filter,
  Layers,
  Activity,
  Send,
  Target,
  ShieldCheck,
  CheckCircle2,
  TrendingUp,
  Flame,
  Award,
  Sparkles
} from 'lucide-react';

const API_BASE_URL = '/api';

export default function WeeklyCoilingScanner() {
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [filterMode, setFilterMode] = useState('ALL'); // 'ALL' | 'READY' | 'FORMING'
  const [searchQuery, setSearchQuery] = useState('');
  const [alertingSymbols, setAlertingSymbols] = useState({});
  const [alertSuccess, setAlertSuccess] = useState({});
  const [checkingIgnitions, setCheckingIgnitions] = useState(false);
  const [ignitionResult, setIgnitionResult] = useState(null);

  const fetchCoilingCandidates = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/coiling-candidates`);
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setCandidates(data.candidates || []);
        setLastUpdated(new Date().toLocaleTimeString());
      } else {
        setError(data.detail || 'Failed to fetch weekly coiling candidates');
      }
    } catch (err) {
      setError(`Network error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleTriggerScan = async () => {
    setScanning(true);
    try {
      const res = await fetch(`${API_BASE_URL}/scan-coiling-candidates`, { method: 'POST' });
      if (res.ok) {
        // Poll for fresh results after 5s
        setTimeout(() => {
          fetchCoilingCandidates();
          setScanning(false);
        }, 5000);
      } else {
        setScanning(false);
      }
    } catch (err) {
      setScanning(false);
    }
  };

  const handleSendTelegramAlert = async (symbol) => {
    if (!symbol) return;
    setAlertingSymbols(prev => ({ ...prev, [symbol]: true }));
    try {
      const res = await fetch(`${API_BASE_URL}/coiling-candidates/${symbol}/alert`, { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setAlertSuccess(prev => ({ ...prev, [symbol]: true }));
        setTimeout(() => {
          setAlertSuccess(prev => ({ ...prev, [symbol]: false }));
        }, 4000);
      } else {
        alert(`Dispatch failed: ${data.detail || 'Unknown error'}`);
      }
    } catch (err) {
      alert(`Network error: ${err.message}`);
    } finally {
      setAlertingSymbols(prev => ({ ...prev, [symbol]: false }));
    }
  };

  const handleCheckIgnitions = async () => {
    setCheckingIgnitions(true);
    setIgnitionResult(null);
    try {
      const res = await fetch(`${API_BASE_URL}/coiling-candidates/check-ignitions`, { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setIgnitionResult(data);
        fetchCoilingCandidates();
      } else {
        alert(`Ignition check failed: ${data.detail || data.message || 'Unknown error'}`);
      }
    } catch (err) {
      alert(`Network error: ${err.message}`);
    } finally {
      setCheckingIgnitions(false);
    }
  };

  useEffect(() => {
    fetchCoilingCandidates();
  }, []);

  const readyCount = candidates.filter(c => c.status === 'COILING_READY').length;
  const formingCount = candidates.filter(c => c.status === 'COILING_FORMING').length;

  const filteredCandidates = candidates.filter(c => {
    if (filterMode === 'READY' && c.status !== 'COILING_READY') return false;
    if (filterMode === 'FORMING' && c.status !== 'COILING_FORMING') return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      return (c.symbol || '').toLowerCase().includes(q);
    }
    return true;
  });

  return (
    <div className="coiling-scanner-container" style={{ padding: '1rem', color: '#f8fafc' }}>
      {/* Header Banner */}
      <div className="race-header-card" style={{ marginBottom: '1.25rem' }}>
        <div className="race-header-main" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div className="race-title-group" style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <div className="race-icon-box" style={{ background: 'rgba(56, 189, 248, 0.15)', padding: '12px', borderRadius: '12px' }}>
              <Zap size={28} color="#38bdf8" />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 700, color: '#f8fafc' }}>
                ⚡ Weekly Coiling & Pre-Breakout Scanner
              </h2>
              <p style={{ margin: '4px 0 0 0', fontSize: '0.85rem', color: '#94a3b8' }}>
                True Strength Index (TSI) Coiling + OBV Stealth Accumulation + Volatility Contraction Shelves (Inspired by SPECTRUM July 2026)
                {lastUpdated && <span style={{ marginLeft: '10px', opacity: 0.7 }}>• Updated: {lastUpdated}</span>}
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            <button
              className="btn-refresh-derivatives"
              onClick={handleCheckIgnitions}
              disabled={checkingIgnitions || loading}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 14px',
                background: '#10b981',
                color: '#fff',
                border: 'none',
                borderRadius: '8px',
                fontWeight: 600,
                cursor: 'pointer'
              }}
              title="Poll Zerodha live quotes for breakout tests of shelf ceiling"
            >
              <Zap size={14} className={checkingIgnitions ? 'spin' : ''} />
              <span>{checkingIgnitions ? 'Checking Live Ignitions...' : 'Check Intraday Ignitions'}</span>
            </button>
            <button
              className="btn-refresh-derivatives"
              onClick={handleTriggerScan}
              disabled={scanning || loading}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 14px',
                background: '#0284c7',
                color: '#fff',
                border: 'none',
                borderRadius: '8px',
                fontWeight: 600,
                cursor: 'pointer'
              }}
            >
              <RefreshCw size={14} className={scanning ? 'spin' : ''} />
              <span>{scanning ? 'Scanning All Stocks...' : 'Run Weekly Scan'}</span>
            </button>
            <button
              className="btn-icon-secondary"
              onClick={fetchCoilingCandidates}
              disabled={loading}
              title="Refresh list from MongoDB"
            >
              <RefreshCw size={16} className={loading ? 'spin-anim' : ''} />
            </button>
          </div>
        </div>

        {/* Metric Overview Cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginTop: '1.25rem' }}>
          <div style={{ background: 'rgba(15, 23, 42, 0.65)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '10px', padding: '12px 16px' }}>
            <span style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Total Coiling Setups</span>
            <div style={{ fontSize: '1.6rem', fontWeight: 800, color: '#38bdf8', marginTop: '4px' }}>{candidates.length}</div>
          </div>
          <div style={{ background: 'rgba(15, 23, 42, 0.65)', border: '1px solid rgba(16, 185, 129, 0.3)', borderRadius: '10px', padding: '12px 16px' }}>
            <span style={{ fontSize: '0.75rem', color: '#10b981', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Ready for Breakout (Score ≥ 75)</span>
            <div style={{ fontSize: '1.6rem', fontWeight: 800, color: '#10b981', marginTop: '4px' }}>{readyCount}</div>
          </div>
          <div style={{ background: 'rgba(15, 23, 42, 0.65)', border: '1px solid rgba(245, 158, 11, 0.3)', borderRadius: '10px', padding: '12px 16px' }}>
            <span style={{ fontSize: '0.75rem', color: '#f59e0b', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Forming Bases (Score 50-74)</span>
            <div style={{ fontSize: '1.6rem', fontWeight: 800, color: '#f59e0b', marginTop: '4px' }}>{formingCount}</div>
          </div>
        </div>

        {/* Filter Pills and Search */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '1.25rem', gap: '1rem', flexWrap: 'wrap' }}>
          <div className="race-mode-selector" style={{ display: 'flex', gap: '6px' }}>
            <button
              className={`race-mode-pill ${filterMode === 'ALL' ? 'active' : ''}`}
              onClick={() => setFilterMode('ALL')}
            >
              All Setups ({candidates.length})
            </button>
            <button
              className={`race-mode-pill ${filterMode === 'READY' ? 'active' : ''}`}
              onClick={() => setFilterMode('READY')}
            >
              <Zap size={12} color="#10b981" />
              <span>Breakout Ready ({readyCount})</span>
            </button>
            <button
              className={`race-mode-pill ${filterMode === 'FORMING' ? 'active' : ''}`}
              onClick={() => setFilterMode('FORMING')}
            >
              <span>Base Forming ({formingCount})</span>
            </button>
          </div>

          <div className="race-search-bar" style={{ minWidth: '240px' }}>
            <Search className="search-icon" size={15} />
            <input
              type="text"
              className="search-input"
              placeholder="Search coiling symbol..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Candidates Table */}
      <div className="table-card" style={{ background: '#0f172a', borderRadius: '12px', border: '1px solid rgba(255, 255, 255, 0.08)', overflow: 'hidden' }}>
        {loading && candidates.length === 0 ? (
          <div className="empty-state" style={{ padding: '3rem', textAlign: 'center' }}>
            <div className="loading-spinner" style={{ margin: '0 auto 1rem' }}></div>
            <h3>Scanning Weekly Charts for Coiling Springs...</h3>
          </div>
        ) : filteredCandidates.length === 0 ? (
          <div className="empty-state" style={{ padding: '3rem', textAlign: 'center' }}>
            <div className="empty-icon" style={{ fontSize: '2.5rem' }}>📦</div>
            <h3>No Coiling Candidates Found</h3>
            <p style={{ color: '#94a3b8' }}>Click "Run Weekly Scan" to evaluate all tracked stocks with Zerodha weekly data.</p>
          </div>
        ) : (
          <div className="table-responsive">
            <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.86rem' }}>
              <thead>
                <tr style={{ background: 'rgba(30, 41, 59, 0.7)', borderBottom: '1px solid rgba(255, 255, 255, 0.08)' }}>
                  <th style={{ padding: '12px 14px' }}>Rank & Symbol</th>
                  <th>Coiling Score</th>
                  <th>LTP & 3M Return</th>
                  <th>Weekly Consolidation Shelf</th>
                  <th>GTT Trigger (+1%)</th>
                  <th>Stop-Loss & Risk</th>
                  <th>Weekly TSI / OBV Pillars</th>
                  <th style={{ textAlign: 'center' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredCandidates.map((c, idx) => {
                  const isReady = c.status === 'COILING_READY';
                  const isAlerting = alertingSymbols[c.symbol];
                  const hasAlerted = alertSuccess[c.symbol];

                  return (
                    <tr
                      key={c.symbol}
                      style={{
                        borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
                        background: isReady ? 'rgba(16, 185, 129, 0.03)' : 'transparent'
                      }}
                    >
                      {/* Symbol */}
                      <td style={{ padding: '12px 14px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{ fontWeight: 800, color: '#38bdf8', fontSize: '0.95rem' }}>#{idx + 1}</span>
                          <div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <span style={{ fontWeight: 700, fontSize: '0.95rem', color: '#f8fafc' }}>{c.symbol}</span>
                              {c.has_spring && (
                                <span style={{
                                  padding: '1px 5px',
                                  borderRadius: '4px',
                                  fontSize: '0.65rem',
                                  fontWeight: 700,
                                  background: 'rgba(236, 72, 153, 0.25)',
                                  color: '#f472b6',
                                  border: '1px solid rgba(236, 72, 153, 0.4)'
                                }} title={`Wyckoff Spring Shakeout: ${c.spring_shadow_pct}% lower wick absorption`}>
                                  ⚡ Spring
                                </span>
                              )}
                              {c.base_age_weeks >= 6 && (
                                <span style={{
                                  padding: '1px 5px',
                                  borderRadius: '4px',
                                  fontSize: '0.65rem',
                                  fontWeight: 700,
                                  background: c.base_age_weeks >= 8 ? 'rgba(168, 85, 247, 0.25)' : 'rgba(56, 189, 248, 0.2)',
                                  color: c.base_age_weeks >= 8 ? '#c084fc' : '#38bdf8',
                                  border: `1px solid ${c.base_age_weeks >= 8 ? 'rgba(168, 85, 247, 0.4)' : 'rgba(56, 189, 248, 0.4)'}`
                                }}>
                                  {c.base_age_weeks >= 8 ? `Apex (${c.base_age_weeks}W)` : `${c.base_age_weeks}W Base`}
                                </span>
                              )}
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginTop: '2px' }}>
                              <span style={{
                                display: 'inline-block',
                                padding: '2px 6px',
                                borderRadius: '4px',
                                fontSize: '0.68rem',
                                fontWeight: 700,
                                background: isReady ? 'rgba(16, 185, 129, 0.2)' : 'rgba(245, 158, 11, 0.2)',
                                color: isReady ? '#34d399' : '#fbbf24'
                              }}>
                                {c.status}
                              </span>
                              {c.ignition_state && (
                                <span style={{
                                  display: 'inline-block',
                                  padding: '2px 6px',
                                  borderRadius: '4px',
                                  fontSize: '0.68rem',
                                  fontWeight: 800,
                                  background: 'rgba(239, 68, 68, 0.25)',
                                  color: '#f87171',
                                  border: '1px solid rgba(239, 68, 68, 0.4)'
                                }}>
                                  🔥 {c.ignition_state}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>

                      {/* Score */}
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span style={{
                            fontSize: '1.1rem',
                            fontWeight: 800,
                            color: isReady ? '#10b981' : '#f59e0b'
                          }}>
                            {c.coiling_score}
                          </span>
                          <span style={{ fontSize: '0.75rem', color: '#64748b' }}>/ 100</span>
                        </div>
                      </td>

                      {/* LTP & 3M Return */}
                      <td>
                        <div style={{ fontWeight: 700, color: '#f8fafc' }}>₹{c.ltp.toLocaleString()}</div>
                        <div style={{ fontSize: '0.75rem', color: c.prior_3m_return >= 0 ? '#10b981' : '#f43f5e' }}>
                          3M: {c.prior_3m_return > 0 ? `+${c.prior_3m_return}%` : `${c.prior_3m_return}%`}
                        </div>
                      </td>

                      {/* Shelf Box */}
                      <td>
                        <div style={{ fontWeight: 600 }}>₹{c.shelf_low} - ₹{c.shelf_high}</div>
                        <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                          4W Base: <strong style={{ color: c.shelf_spread_pct <= 15 ? '#10b981' : '#fbbf24' }}>{c.shelf_spread_pct}%</strong>
                          {c.pivot_spread_pct && (
                            <span style={{ marginLeft: '6px' }}>
                              • 2W Pivot: <strong style={{ color: c.pivot_spread_pct <= 8 ? '#10b981' : '#38bdf8' }}>{c.pivot_spread_pct}%</strong>
                            </span>
                          )}
                        </div>
                      </td>

                      {/* GTT Trigger & R-Multiples */}
                      <td>
                        <div style={{ fontWeight: 700, color: '#38bdf8' }}>
                          ₹{c.gtt_trigger_price}
                        </div>
                        {c.target_1r ? (
                          <div style={{ fontSize: '0.72rem', color: '#10b981', marginTop: '2px' }}>
                            +1R: ₹{c.target_1r} • +2R: ₹{c.target_2r}
                          </div>
                        ) : (
                          <div style={{ fontSize: '0.72rem', color: '#64748b' }}>+1% above shelf ceiling</div>
                        )}
                      </td>

                      {/* Stop-Loss */}
                      <td>
                        <div style={{ fontWeight: 600, color: '#ef4444' }}>₹{c.gtt_stoploss_price}</div>
                        <div style={{ fontSize: '0.72rem', color: '#94a3b8' }}>Risk: {c.risk_pct}%</div>
                      </td>

                      {/* Pillars & Technicals */}
                      <td style={{ maxWidth: '300px' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                          <span style={{ fontSize: '0.75rem', color: '#38bdf8' }}>
                            TSI: <strong>{c.weekly_tsi}</strong> (Sig: {c.weekly_tsi_signal})
                          </span>
                          <span style={{ fontSize: '0.75rem', color: '#10b981' }}>
                            OBV: <strong>{c.weekly_obv > 0 ? `+${(c.weekly_obv/1000).toFixed(0)}k` : `${(c.weekly_obv/1000).toFixed(0)}k`}</strong> (Vol: {c.vol_ratio}x)
                          </span>
                        </div>
                      </td>

                      {/* Actions */}
                      <td style={{ textAlign: 'center', padding: '12px' }}>
                        <button
                          onClick={() => handleSendTelegramAlert(c.symbol)}
                          disabled={isAlerting}
                          title="Dispatch GTT & Coiling Alert to Telegram"
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            padding: '6px 10px',
                            background: hasAlerted ? '#059669' : '#1e293b',
                            border: '1px solid rgba(255, 255, 255, 0.1)',
                            borderRadius: '6px',
                            color: hasAlerted ? '#fff' : '#38bdf8',
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            cursor: 'pointer'
                          }}
                        >
                          {hasAlerted ? (
                            <>
                              <CheckCircle2 size={13} />
                              <span>Sent!</span>
                            </>
                          ) : (
                            <>
                              <Send size={13} className={isAlerting ? 'spin' : ''} />
                              <span>{isAlerting ? 'Sending...' : 'Alert'}</span>
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
    </div>
  );
}
