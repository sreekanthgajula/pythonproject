import React, { useState, useEffect } from 'react';
import TradingChart from './components/TradingChart';

const API_BASE_URL = 'http://localhost:8000/api';

// Poll interval of 30 seconds for live updates
const LIVE_POLL_INTERVAL = 30000;

function App() {
  // Default to RELIANCE.NS, but allow users to query any ticker
  const [ticker, setTicker] = useState('RELIANCE.NS');
  const [searchVal, setSearchVal] = useState('RELIANCE.NS');
  
  const [chartData, setChartData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState('');
  const [lastUpdated, setLastUpdated] = useState(null);

  const [watchlist, setWatchlist] = useState([]);
  const [alerts, setAlerts] = useState([]);

  // Fetch chart data for a specific ticker
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
        const res = await fetch(`${API_BASE_URL}/chart/${cleanTicker}`);
        
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

    // Initial load for this ticker
    fetchChart(false);

    // Setup background interval for live updates
    intervalId = setInterval(() => {
      fetchChart(true);
    }, LIVE_POLL_INTERVAL);

    return () => {
      isMounted = false;
      clearInterval(intervalId);
    };
  }, [ticker]);

  // Fetch watchlist and active alerts periodically
  useEffect(() => {
    const fetchWatchlistAndAlerts = async () => {
      try {
        const wlRes = await fetch(`${API_BASE_URL}/watchlist`);
        if (wlRes.ok) {
          const wlData = await wlRes.json();
          setWatchlist(wlData);
        }
        
        const alRes = await fetch(`${API_BASE_URL}/alerts`);
        if (alRes.ok) {
          const alData = await alRes.json();
          setAlerts(alData);
        }
      } catch (err) {
        console.error('Error fetching watchlist or alerts:', err);
      }
    };
    
    fetchWatchlistAndAlerts();
    const interval = setInterval(fetchWatchlistAndAlerts, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    if (searchVal.trim()) {
      setTicker(searchVal.trim());
    }
  };

  const toggleWatchlist = async (t) => {
    const isWatched = watchlist.includes(t.toUpperCase());
    const endpoint = isWatched ? 'remove' : 'add';
    try {
      const res = await fetch(`${API_BASE_URL}/watchlist/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker: t })
      });
      if (res.ok) {
        const data = await res.json();
        setWatchlist(data.watchlist);
      }
    } catch (err) {
      console.error('Error toggling watchlist:', err);
    }
  };

  const isCurrentTickerWatched = watchlist.includes(ticker.toUpperCase());

  return (
    <div className="container">
      <div className="header">
        <h1>TradingAgents Terminal</h1>
        <p>10-Minute Intraday Breakout Monitor (OBV & TSI)</p>
        
        <form onSubmit={handleSearchSubmit} className="search-container">
          <input
            type="text"
            className="search-input"
            placeholder="Enter ticker (e.g. PYRAMID.NS, AAPL)..."
            value={searchVal}
            onChange={(e) => setSearchVal(e.target.value)}
          />
          <button type="submit" className="search-btn">Search</button>
        </form>
      </div>

      <div className="dashboard-grid">
        {/* Main Panel */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {loading && (
            <div className="glass-panel loading-container">
              <div className="spinner"></div>
              <h3>Fetching market data for {ticker.toUpperCase()}...</h3>
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
                <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
                  <h2 style={{color: '#2563eb', margin: 0}}>{ticker.toUpperCase()} (10m)</h2>
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
              <p style={{color: 'var(--text-muted)', marginBottom: '15px'}}>10-minute price candles with OBV Capital Flow (OBV Z-Score) and TSI Momentum</p>
              <TradingChart data={chartData} />
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
              <span>Breakout Alerts</span>
              {alerts.length > 0 && <span className="live-dot" style={{ backgroundColor: 'var(--danger)', boxShadow: '0 0 8px var(--danger)' }}></span>}
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
                      ₹{alert.price.toFixed(2)} • {alert.timestamp}
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
