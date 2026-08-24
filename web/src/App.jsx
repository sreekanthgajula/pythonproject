import React, { useState, useEffect } from 'react';
import TradingChart from './components/TradingChart';

const API_BASE_URL = 'http://localhost:8000/api';

// Poll interval of 30 seconds for live updates
const LIVE_POLL_INTERVAL = 30000;

// Helper to format ISO timestamps into simple Indian Time (IST) e.g. 9:15 AM or 12 Aug, 2:30 PM
const formatSimpleTime = (tsStr) => {
  if (!tsStr) return '';
  try {
    const d = new Date(tsStr);
    if (isNaN(d.getTime())) return tsStr;
    const timeStr = d.toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true
    }).toUpperCase();
    
    const dateStr = d.toLocaleDateString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: 'numeric',
      month: 'short'
    });
    const todayStr = new Date().toLocaleDateString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: 'numeric',
      month: 'short'
    });
    
    if (dateStr === todayStr) {
      return timeStr;
    } else {
      return `${dateStr}, ${timeStr}`;
    }
  } catch (e) {
    return tsStr;
  }
};

function App() {
  // Default to RELIANCE.NS, but allow users to query any ticker
  const [ticker, setTicker] = useState('RELIANCE.NS');
  const [searchVal, setSearchVal] = useState('RELIANCE.NS');
  const [timeframe, setTimeframe] = useState('10m');
  
  const [chartData, setChartData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [lastUpdated, setLastUpdated] = useState(null);

  const [watchlist, setWatchlist] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [currentTimeIST, setCurrentTimeIST] = useState('');

  // Handle fetching older historical candles when user scrolls left on chart
  const handleLoadMoreHistorical = async (earliestTime) => {
    if (loadingMore || !earliestTime) return;
    try {
      setLoadingMore(true);
      let earliestDate;
      if (typeof earliestTime === 'number') {
        earliestDate = new Date(earliestTime * 1000);
      } else {
        earliestDate = new Date(earliestTime);
      }
      if (isNaN(earliestDate.getTime())) return;

      const endDateStr = earliestDate.toISOString().split('T')[0];
      const cleanTicker = encodeURIComponent(ticker.trim().toUpperCase());
      const res = await fetch(`${API_BASE_URL}/chart/${cleanTicker}?interval=${timeframe}&end_date=${endDateStr}`);
      
      if (res.ok) {
        const historicalData = await res.json();
        if (historicalData && historicalData.length > 0) {
          setChartData(prev => {
            const existingTimes = new Set(prev.map(d => d.time));
            const newCandles = historicalData.filter(d => !existingTimes.has(d.time));
            return [...newCandles, ...prev].sort((a, b) => (a.time > b.time ? 1 : -1));
          });
        }
      }
    } catch (err) {
      console.error('Error fetching historical chart data:', err);
    } finally {
      setLoadingMore(false);
    }
  };

  // Live IST Clock
  useEffect(() => {
    const updateClock = () => {
      const now = new Date();
      const formatted = now.toLocaleTimeString('en-IN', {
        timeZone: 'Asia/Kolkata',
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
        hour12: true
      }).toUpperCase();
      setCurrentTimeIST(formatted);
    };
    updateClock();
    const clockTimer = setInterval(updateClock, 1000);
    return () => clearInterval(clockTimer);
  }, []);

  // Fetch chart data for a specific ticker and timeframe
  useEffect(() => {
    let isMounted = true;
    let intervalId;

    const fetchChart = async (isSilent = false) => {
      try {
        if (!isSilent) {
          setLoading(true);
          setErrorMsg('');
        }
        
        const cleanTicker = encodeURIComponent(ticker.trim().toUpperCase());
        const res = await fetch(`${API_BASE_URL}/chart/${cleanTicker}?interval=${timeframe}`);
        
        if (res.ok) {
          const data = await res.json();
          if (isMounted) {
            setChartData(data);
            setLastUpdated(new Date().toLocaleTimeString());
          }
        } else {
          if (!isSilent) {
            setErrorMsg(`Failed to load chart data for ticker "${ticker.toUpperCase()}". Make sure it is a valid Yahoo Finance / Zerodha ticker.`);
          }
          console.warn(`Failed to fetch updates for ${ticker}.`);
        }
      } catch (err) {
        console.error('Error fetching chart data:', err);
        if (!isSilent) {
          setErrorMsg(`Network error while fetching data for "${ticker.toUpperCase()}".`);
        }
      } finally {
        if (isMounted && !isSilent) {
          setLoading(false);
        }
      }
    };

    // Initial load for this ticker and timeframe
    fetchChart(false);

    // Setup background interval for live updates
    intervalId = setInterval(() => {
      fetchChart(true);
    }, LIVE_POLL_INTERVAL);

    return () => {
      isMounted = false;
      clearInterval(intervalId);
    };
  }, [ticker, timeframe]);

  // Fetch watchlist and active alerts periodically
  useEffect(() => {
    const fetchWatchlistAndAlerts = async () => {
      try {
        const [wRes, aRes] = await Promise.all([
          fetch(`${API_BASE_URL}/watchlist`),
          fetch(`${API_BASE_URL}/alerts`)
        ]);
        
        if (wRes.ok) {
          const wData = await wRes.json();
          setWatchlist(wData.watchlist || []);
        }
        
        if (aRes.ok) {
          const aData = await aRes.json();
          setAlerts(aData.alerts || []);
        }
      } catch (err) {
        console.error('Error fetching watchlist/alerts:', err);
      }
    };
    
    fetchWatchlistAndAlerts();
    const intervalId = setInterval(fetchWatchlistAndAlerts, LIVE_POLL_INTERVAL);
    return () => clearInterval(intervalId);
  }, []);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    if (searchVal.trim()) {
      setTicker(searchVal.trim());
    }
  };

  const toggleWatchlist = async (symbolToToggle) => {
    const cleanSymbol = symbolToToggle.trim().toUpperCase();
    const isWatched = watchlist.includes(cleanSymbol);
    const method = isWatched ? 'DELETE' : 'POST';
    
    try {
      const res = await fetch(`${API_BASE_URL}/watchlist/${cleanSymbol}`, { method });
      if (res.ok) {
        const data = await res.json();
        setWatchlist(data.watchlist || []);
      }
    } catch (err) {
      console.error('Error toggling watchlist:', err);
    }
  };

  const handleClearAlerts = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/alerts`, { method: 'DELETE' });
      if (res.ok) {
        setAlerts([]);
      }
    } catch (err) {
      console.error('Error clearing alerts:', err);
    }
  };

  const isCurrentTickerWatched = watchlist.includes(ticker.toUpperCase());

  const timeframeLabels = {
    '10m': '10 Min',
    '1h': '1 Hour',
    '1d': '1 Day',
    '1w': '1 Week',
    '1M': '1 Month'
  };

  return (
    <div className="container">
      <div className="header">
        <h1>TradingAgents Terminal</h1>
        <p>Multi-Timeframe Breakout & Momentum Monitor (OBV & TSI)</p>
        
        <form onSubmit={handleSearchSubmit} className="search-container">
          <input
            type="text"
            className="search-input"
            placeholder="Enter ticker (e.g. PYRAMID.NS, AAPL)..."
            value={searchVal}
            onChange={(e) => setSearchVal(e.target.value)}
          />
          <select 
            value={timeframe} 
            onChange={(e) => setTimeframe(e.target.value)}
            className="timeframe-select-header"
          >
            <option value="10m">⏱ 10 Min</option>
            <option value="1h">⏰ 1 Hour</option>
            <option value="1d">📅 1 Day</option>
            <option value="1w">📊 1 Week</option>
            <option value="1M">🗓 1 Month</option>
          </select>
          <button type="submit" className="search-btn">Search</button>
        </form>
      </div>

      <div className="dashboard-grid">
        {/* Main Panel */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {loading && (
            <div className="glass-panel loading-container">
              <div className="spinner"></div>
              <h3>Fetching {timeframeLabels[timeframe]} market data for {ticker.toUpperCase()}...</h3>
            </div>
          )}

          {errorMsg && (
            <div className="glass-panel" style={{borderColor: 'var(--danger)'}}>
              <h3 style={{color: 'var(--danger)', marginBottom: '10px'}}>Error</h3>
              <p>{errorMsg}</p>
            </div>
          )}

          {!loading && !errorMsg && chartData.length > 0 && (
            <div className="glass-panel">
              <div className="live-indicator-container">
                <div style={{ display: 'flex', alignItems: 'center', gap: '15px', flexWrap: 'wrap' }}>
                  <h2 style={{color: '#2563eb', margin: 0}}>{ticker.toUpperCase()}</h2>
                  
                  {/* Timeframe Pill Selector */}
                  <div className="timeframe-pills">
                    {['10m', '1h', '1d', '1w', '1M'].map(tf => (
                      <button
                        key={tf}
                        className={`tf-pill ${timeframe === tf ? 'active' : ''}`}
                        onClick={() => setTimeframe(tf)}
                      >
                        {timeframeLabels[tf]}
                      </button>
                    ))}
                  </div>

                  <button 
                    onClick={() => toggleWatchlist(ticker)}
                    className={`watch-toggle-btn ${isCurrentTickerWatched ? 'watching' : ''}`}
                  >
                    {isCurrentTickerWatched ? '✓ Watching' : '+ Watch'}
                  </button>
                </div>
                <div style={{display: 'flex', alignItems: 'center', gap: '15px'}}>
                  {lastUpdated && (
                    <span className="last-updated-text">Last updated: {lastUpdated}</span>
                  )}
                  <span className="live-indicator">
                    <span className="live-dot"></span>
                    LIVE
                  </span>
                </div>
              </div>
              <p style={{color: 'var(--text-muted)', marginBottom: '15px'}}>
                {timeframeLabels[timeframe]} price candles with OBV Capital Flow (OBV Z-Score) and TSI Momentum
              </p>
              <TradingChart data={chartData} onLoadMore={handleLoadMoreHistorical} isLoadingMore={loadingMore} />
            </div>
          )}
        </div>

        {/* Sidebar Panel */}
        <div className="sidebar-panel">
          {/* Watchlist Panel */}
          <div className="glass-panel" style={{ padding: '20px' }}>
            <h3 style={{ marginBottom: '15px', fontSize: '1.1rem', color: 'var(--text-main)' }}>Watchlist</h3>
            <div className="watchlist-container">
              {watchlist.length === 0 ? (
                <div className="empty-placeholder">No stocks in watchlist</div>
              ) : (
                watchlist.map((symbol) => (
                  <div key={symbol} className="watchlist-card">
                    <span className="ticker-badge" style={{ cursor: 'pointer' }} onClick={() => { setTicker(symbol); setSearchVal(symbol); }}>
                      {symbol}
                    </span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span className="status-badge">
                        <span className="live-dot" style={{ width: '6px', height: '6px' }}></span>
                        LIVE
                      </span>
                      <button className="btn-remove-watchlist" onClick={() => toggleWatchlist(symbol)}>✕</button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Active Alerts Panel */}
          <div className="glass-panel" style={{ padding: '20px', flex: 1 }}>
            <h3 style={{ marginBottom: '15px', fontSize: '1.1rem', color: 'var(--text-main)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span>Breakout Alerts</span>
                {currentTimeIST && (
                  <span style={{ fontSize: '0.8rem', padding: '2px 8px', borderRadius: '4px', backgroundColor: 'rgba(255,255,255,0.06)', color: 'var(--accent, #3b82f6)', fontWeight: 500 }}>
                    IST {currentTimeIST}
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                {alerts.length > 0 && (
                  <button 
                    onClick={handleClearAlerts}
                    style={{
                      background: 'rgba(239, 68, 68, 0.15)',
                      color: '#ef4444',
                      border: '1px solid rgba(239, 68, 68, 0.3)',
                      borderRadius: '4px',
                      padding: '2px 10px',
                      fontSize: '0.75rem',
                      cursor: 'pointer',
                      fontWeight: 600,
                      transition: 'all 0.2s ease'
                    }}
                    title="Clear all breakout alerts"
                  >
                    Clear
                  </button>
                )}
                {alerts.length > 0 && <span className="live-dot" style={{ backgroundColor: 'var(--danger)', boxShadow: '0 0 8px var(--danger)' }}></span>}
              </div>
            </h3>
            <div className="alerts-list">
              {alerts.length === 0 ? (
                <div className="empty-placeholder">No breakout alerts triggered yet</div>
              ) : (
                [...alerts].reverse().map((alert) => (
                  <div key={alert.id} className="alert-item">
                    <div className="alert-header">
                      <span className="alert-ticker">{alert.ticker}</span>
                      <span className="alert-conviction">{(alert.confidence * 100).toFixed(0)}% Conviction</span>
                    </div>
                    <div className="alert-meta">
                      ₹{alert.price.toFixed(2)} • {formatSimpleTime(alert.timestamp)}
                    </div>
                    <div className="alert-reason">
                      {alert.reason}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
