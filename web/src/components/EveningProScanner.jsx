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
  Layers
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

  useEffect(() => {
    fetchEveningCandidates();
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
                2:30 PM – 3:30 PM BTST Setup
              </span>
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
              <span className="evening-pro-title-text">Evening Pro Buying (BTST)</span>
              <span className="evening-pro-title-icon">
                <TrendingUp size={22} />
              </span>
            </h1>
            <p className="morning-short-desc">
              Identifies late-afternoon institutional accumulation and BTST buying setups based on day-end closing power and volume expansion.
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
                <th style={{ width: '35%' }}>Stock Name & Conviction</th>
                <th style={{ width: '65%' }}>Professional Accumulation Reason</th>
              </tr>
            </thead>
            <tbody>
              {filteredCandidates.map((c, idx) => {
                const stockName = c.symbol || '';
                const score = c.pro_buying_score || 0;
                const formattedReason = formatReason(c.reason, c.close_position_pct);

                return (
                  <tr key={stockName || idx}>
                    {/* COLUMN 1: STOCK NAME & CONVICTION BADGE */}
                    <td>
                      <div className="stock-cell-info">
                        <div className="rank-pill">
                          #{idx + 1}
                        </div>
                        <div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <span className="stock-symbol-title">{stockName}</span>
                            {score >= 75 && (
                              <span className="badge-high-pro-conviction">
                                <Flame size={10} /> High Accumulation
                              </span>
                            )}
                          </div>
                          {score > 0 && (
                            <div className="score-subtitle">
                              Pro Score: <strong>{score.toFixed(1)} / 100</strong>
                            </div>
                          )}
                        </div>
                      </div>
                    </td>

                    {/* COLUMN 2: REASON */}
                    <td>
                      <div className="reason-cell-flex">
                        <div className="reason-arrow-green-icon">
                          <ArrowUpRight size={18} />
                        </div>
                        <div className="reason-text-group">
                          <span className="reason-main-title">{formattedReason.main}</span>
                          <span className="reason-green-pct-tag">(Closed at {formattedReason.pct} of day's range)</span>
                        </div>
                      </div>
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
