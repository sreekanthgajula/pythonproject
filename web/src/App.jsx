import React, { useState, useEffect } from 'react';
import {
  TrendingUp,
  Flame,
  RefreshCw,
  Search,
  Zap,
  Star,
  Activity,
  Layers,
  Calendar,
  Clock,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Bell,
  ShieldCheck,
  CheckCircle2,
  Trash2
} from 'lucide-react';

const API_BASE_URL = '/api';

export default function App() {
  const [activeTab, setActiveTab] = useState('monthly'); // 'monthly' | 'weekly' | 'daily' | 'gtts'
  const [stocksData, setStocksData] = useState([]);
  const [gttsData, setGttsData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [runningPipeline, setRunningPipeline] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [wsStatus, setWsStatus] = useState({ running: false, monitored_tokens_count: 0 });
  const [tabCounts, setTabCounts] = useState({ monthly: 0, weekly: 0, daily: 0, gtts: 0 });

  // Sorting state: default sort by 'rating' descending
  const [sortKey, setSortKey] = useState('rating'); // 'rating' | 'updated_at' | 'alert_count' | 'symbol' | 'recent_high' | 'alert_trigger_price'
  const [sortOrder, setSortOrder] = useState('desc'); // 'desc' | 'asc'

  // Fetch stocks data for the active timeframe
  const fetchTimeframeRatings = async (timeframe) => {
    if (timeframe === 'gtts') {
      fetchZerodhaGtts();
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/ratings/${timeframe}`);
      if (res.ok) {
        const json = await res.json();
        setStocksData(json.data || []);
        setTabCounts(prev => ({ ...prev, [timeframe]: json.count || 0 }));
      }
    } catch (err) {
      console.error(`Error fetching ${timeframe} ratings:`, err);
    } finally {
      setLoading(false);
    }
  };

  // Fetch active GTT alerts straight from Zerodha API
  const fetchZerodhaGtts = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/zerodha/gtts`);
      if (res.ok) {
        const json = await res.json();
        const items = json.gtts || [];
        setGttsData(items);
        setTabCounts(prev => ({ ...prev, gtts: json.count || items.length }));
      }
    } catch (err) {
      console.error('Error fetching Zerodha GTTs:', err);
    } finally {
      setLoading(false);
    }
  };

  // Fetch counts for all timeframes for tab badges
  const fetchAllTabCounts = async () => {
    for (const tf of ['monthly', 'weekly', 'daily']) {
      try {
        const res = await fetch(`${API_BASE_URL}/ratings/${tf}`);
        if (res.ok) {
          const json = await res.json();
          setTabCounts(prev => ({ ...prev, [tf]: json.count || 0 }));
        }
      } catch (err) {
        console.error(`Error fetching tab count for ${tf}:`, err);
      }
    }
    fetchZerodhaGtts();
  };

  // Fetch WebSocket live status
  const fetchWsStatus = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/zerodha/websocket/status`);
      if (res.ok) {
        const json = await res.json();
        setWsStatus(json);
      }
    } catch (err) {
      console.error('Error fetching WebSocket status:', err);
    }
  };

  // Batch selection state for individual/multi-select deletion
  const [selectedSymbols, setSelectedSymbols] = useState([]);

  useEffect(() => {
    setSelectedSymbols([]);
    fetchTimeframeRatings(activeTab);
    fetchAllTabCounts();
    fetchWsStatus();

    // Auto refresh every 10 seconds
    const intervalId = setInterval(() => {
      fetchTimeframeRatings(activeTab);
      fetchWsStatus();
    }, 10000);

    return () => clearInterval(intervalId);
  }, [activeTab]);

  // Trigger Chartink -> Grok -> DB -> Alert pipeline run
  const handleRunPipeline = async () => {
    setRunningPipeline(true);
    try {
      const res = await fetch(`${API_BASE_URL}/pipeline/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ top_n: 20 })
      });
      if (res.ok) {
        alert('Chartink -> Grok AI -> DB Pipeline started in background! Data will update automatically.');
        setTimeout(() => {
          fetchTimeframeRatings(activeTab);
          fetchAllTabCounts();
        }, 5000);
      }
    } catch (err) {
      alert(`Pipeline launch failed: ${err}`);
    } finally {
      setRunningPipeline(false);
    }
  };

  // Handle deleting all stocks in the active timeframe collection
  const handleDeleteAllTimeframeStocks = async () => {
    if (activeTab === 'gtts') return;
    const confirmed = window.confirm(
      `⚠️ ARE YOU SURE?\n\nThis will PERMANENTLY DELETE ALL stocks from the ${activeTab.toUpperCase()} database table!`
    );
    if (!confirmed) return;

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/ratings/${activeTab}`, {
        method: 'DELETE'
      });
      const json = await res.json();
      if (res.ok && json.status === 'success') {
        alert(`Successfully deleted ${json.deleted_count} stocks from ${activeTab.toUpperCase()} table.`);
        fetchTimeframeRatings(activeTab);
        fetchAllTabCounts();
      } else {
        alert(`Failed to delete: ${json.detail || json.message || 'Unknown error'}`);
      }
    } catch (err) {
      alert(`Error deleting all ${activeTab} stocks: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  // Handle deleting an individual stock from the active timeframe collection
  const handleDeleteSingleStock = async (symbol) => {
    if (activeTab === 'gtts') return;
    const confirmed = window.confirm(
      `Remove ${symbol} from the ${activeTab.toUpperCase()} database table?`
    );
    if (!confirmed) return;

    try {
      const res = await fetch(`${API_BASE_URL}/ratings/${activeTab}/${encodeURIComponent(symbol)}`, {
        method: 'DELETE'
      });
      const json = await res.json();
      if (res.ok && json.status === 'success') {
        fetchTimeframeRatings(activeTab);
        fetchAllTabCounts();
      } else {
        alert(`Failed to delete ${symbol}: ${json.detail || json.message || 'Unknown error'}`);
      }
    } catch (err) {
      alert(`Error deleting stock ${symbol}: ${err}`);
    }
  };

  // Handle cancelling a Zerodha GTT alert trigger directly via Zerodha API
  const handleCancelZerodhaGtt = async (triggerId, symbol) => {
    const confirmed = window.confirm(
      `Cancel Zerodha GTT alert trigger #${triggerId} for ${symbol || ''} directly on Zerodha API?`
    );
    if (!confirmed) return;

    try {
      const res = await fetch(`${API_BASE_URL}/zerodha/gtts/${triggerId}`, {
        method: 'DELETE'
      });
      const json = await res.json();
      if (res.ok && json.status === 'success') {
        fetchZerodhaGtts();
        fetchAllTabCounts();
      } else {
        alert(`Failed to cancel GTT: ${json.detail || json.message || 'Unknown error'}`);
      }
    } catch (err) {
      alert(`Error cancelling GTT #${triggerId}: ${err}`);
    }
  };

  // Toggle selection of a single stock symbol
  const handleToggleSelectSymbol = (symbol) => {
    setSelectedSymbols(prev => 
      prev.includes(symbol) ? prev.filter(s => s !== symbol) : [...prev, symbol]
    );
  };

  // Toggle select all visible stocks in current active timeframe
  const handleSelectAllToggle = () => {
    const visibleSymbols = processedStocks.map(s => s.symbol);
    const isAllSelected = visibleSymbols.length > 0 && visibleSymbols.every(s => selectedSymbols.includes(s));
    if (isAllSelected) {
      setSelectedSymbols(prev => prev.filter(s => !visibleSymbols.includes(s)));
    } else {
      setSelectedSymbols(prev => Array.from(new Set([...prev, ...visibleSymbols])));
    }
  };

  // Handle batch deletion of selected stocks
  const handleDeleteSelectedStocks = async () => {
    if (selectedSymbols.length === 0 || activeTab === 'gtts') return;
    const confirmed = window.confirm(
      `Delete ${selectedSymbols.length} selected stocks from the ${activeTab.toUpperCase()} database table?`
    );
    if (!confirmed) return;

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/ratings/${activeTab}/delete-batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: selectedSymbols })
      });
      const json = await res.json();
      if (res.ok && json.status === 'success') {
        alert(`Successfully deleted ${json.deleted_count} selected stocks from ${activeTab.toUpperCase()} table.`);
        setSelectedSymbols([]);
        fetchTimeframeRatings(activeTab);
        fetchAllTabCounts();
      } else {
        alert(`Failed to delete selected stocks: ${json.detail || json.message || 'Unknown error'}`);
      }
    } catch (err) {
      alert(`Error deleting selected stocks: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  // Handle interactive column sort header click
  const handleSort = (key) => {
    if (sortKey === key) {
      setSortOrder(prev => (prev === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(key);
      setSortOrder('desc');
    }
  };

  // Filter and sort stocks
  const processedStocks = stocksData
    .filter(item => {
      const sym = item.symbol || '';
      const reason = item.reason || '';
      const query = searchQuery.toLowerCase().trim();
      return sym.toLowerCase().includes(query) || reason.toLowerCase().includes(query);
    })
    .sort((a, b) => {
      let valA = a[sortKey];
      let valB = b[sortKey];

      if (sortKey === 'rating') {
        valA = a.rating || 0;
        valB = b.rating || 0;
      } else if (sortKey === 'updated_at') {
        valA = a.updated_at ? new Date(a.updated_at).getTime() : 0;
        valB = b.updated_at ? new Date(b.updated_at).getTime() : 0;
      } else if (sortKey === 'alert_count') {
        valA = a.alert_count || 0;
        valB = b.alert_count || 0;
      } else if (sortKey === 'recent_high') {
        valA = a.recent_high || 0;
        valB = b.recent_high || 0;
      } else if (sortKey === 'alert_trigger_price') {
        valA = a.alert_trigger_price || 0;
        valB = b.alert_trigger_price || 0;
      } else if (sortKey === 'symbol') {
        valA = (a.symbol || '').toLowerCase();
        valB = (b.symbol || '').toLowerCase();
        return sortOrder === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
      }

      if (valA === valB) {
        const timeA = a.updated_at ? new Date(a.updated_at).getTime() : 0;
        const timeB = b.updated_at ? new Date(b.updated_at).getTime() : 0;
        return timeB - timeA;
      }

      return sortOrder === 'asc' ? valA - valB : valB - valA;
    });

  // Filter GTTs based on search query
  const filteredGtts = gttsData.filter(g => {
    const sym = g.symbol || '';
    const idStr = String(g.id || '');
    const query = searchQuery.toLowerCase().trim();
    return sym.toLowerCase().includes(query) || idStr.toLowerCase().includes(query);
  });

  // Calculate summary stats
  const totalScreened = (tabCounts.monthly || 0) + (tabCounts.weekly || 0) + (tabCounts.daily || 0);
  const highConvictionCount = stocksData.filter(s => (s.rating || 0) >= 4.0).length;
  const totalAlertTriggers = stocksData.reduce((acc, curr) => acc + (curr.alert_count || 0), 0);

  const formatDate = (dateStr) => {
    if (!dateStr) return 'N/A';
    try {
      const d = new Date(dateStr);
      return d.toLocaleString('en-IN', {
        timeZone: 'Asia/Kolkata',
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true
      }) + ' IST';
    } catch {
      return dateStr;
    }
  };

  const renderSortIcon = (key) => {
    if (sortKey !== key) {
      return <ArrowUpDown size={13} className="sort-icon-dim" />;
    }
    return sortOrder === 'desc' ? (
      <ArrowDown size={14} className="sort-icon-active" />
    ) : (
      <ArrowUp size={14} className="sort-icon-active" />
    );
  };

  return (
    <div className="app-container">
      {/* Header Bar */}
      <header className="app-header">
        <div className="brand-title">
          <div className="brand-icon">
            <TrendingUp size={24} color="#ffffff" />
          </div>
          <div className="brand-text">
            <h1>TradingAgents AI</h1>
            <p>Grok AI Chartink Screener & 1% Breakout Trigger Alerts</p>
          </div>
        </div>

        <div className="header-actions">
          {/* WebSocket Status Indicator */}
          <div className="status-badge">
            <span className={`pulse-dot ${wsStatus.running ? 'online' : ''}`}></span>
            <span>{wsStatus.running ? `KiteTicker Live (${wsStatus.monitored_tokens_count} Tokens)` : 'WebSocket Standby'}</span>
          </div>

          <button
            className="btn-primary"
            onClick={handleRunPipeline}
            disabled={runningPipeline}
          >
            {runningPipeline ? (
              <>
                <div className="loading-spinner"></div>
                <span>Executing Grok...</span>
              </>
            ) : (
              <>
                <Zap size={16} />
                <span>Run Grok Pipeline</span>
              </>
            )}
          </button>

          <button
            className="btn-icon-secondary"
            onClick={() => fetchTimeframeRatings(activeTab)}
            title="Refresh Data"
          >
            <RefreshCw size={18} className={loading ? 'spin-anim' : ''} />
          </button>
        </div>
      </header>

      {/* Summary Stats Overview Cards */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-header">
            <span className="stat-title">Active Timeframe Stocks</span>
            <Layers className="stat-icon" color="#38bdf8" />
          </div>
          <div className="stat-value">{activeTab === 'gtts' ? gttsData.length : stocksData.length}</div>
          <div className="stat-desc">{activeTab === 'gtts' ? 'Zerodha GTT Triggers Active' : `DB records in ${activeTab.toUpperCase()} table`}</div>
        </div>

        <div className="stat-card">
          <div className="stat-header">
            <span className="stat-title">High Conviction (⭐ &ge; 4.0)</span>
            <Star className="stat-icon" color="#10b981" />
          </div>
          <div className="stat-value">{highConvictionCount}</div>
          <div className="stat-desc">Filtered by Grok AI analysis</div>
        </div>

        <div className="stat-card">
          <div className="stat-header">
            <span className="stat-title">Alert Triggers Count</span>
            <Flame className="stat-icon" color="#f43f5e" />
          </div>
          <div className="stat-value">{totalAlertTriggers}</div>
          <div className="stat-desc">Total times 1% alerts triggered</div>
        </div>

        <div className="stat-card">
          <div className="stat-header">
            <span className="stat-title">Active Zerodha GTTs</span>
            <Bell className="stat-icon" color="#a855f7" />
          </div>
          <div className="stat-value">{tabCounts.gtts || 0}</div>
          <div className="stat-desc">Live on Zerodha account</div>
        </div>
      </div>

      {/* Prominent Tabs Navigation */}
      <div className="tabs-header-container">
        <nav className="tabs-nav">
          <button
            className={`tab-btn ${activeTab === 'monthly' ? 'active' : ''}`}
            onClick={() => setActiveTab('monthly')}
          >
            <Calendar size={16} />
            <span>Monthly Tab</span>
            <span className="tab-badge">{tabCounts.monthly || 0}</span>
          </button>

          <button
            className={`tab-btn ${activeTab === 'weekly' ? 'active' : ''}`}
            onClick={() => setActiveTab('weekly')}
          >
            <Clock size={16} />
            <span>Weekly Tab</span>
            <span className="tab-badge">{tabCounts.weekly || 0}</span>
          </button>

          <button
            className={`tab-btn ${activeTab === 'daily' ? 'active' : ''}`}
            onClick={() => setActiveTab('daily')}
          >
            <Zap size={16} />
            <span>Daily Tab</span>
            <span className="tab-badge">{tabCounts.daily || 0}</span>
          </button>

          {/* ⚡ NEW TAB: ACTIVE ZERODHA GTTS */}
          <button
            className={`tab-btn ${activeTab === 'gtts' ? 'active' : ''}`}
            onClick={() => setActiveTab('gtts')}
            style={{ borderLeft: '1px solid rgba(255, 255, 255, 0.1)' }}
          >
            <Bell size={16} color="#a855f7" />
            <span>⚡ Active Zerodha GTTs</span>
            <span className="tab-badge" style={{ background: '#a855f7', color: '#fff' }}>{tabCounts.gtts || 0}</span>
          </button>
        </nav>

        {/* Quick Sorting Pills & Delete All Button (Hidden on GTTS tab) */}
        {activeTab !== 'gtts' && (
          <div className="sort-controls">
            <span className="sort-label">Sort By:</span>
            <button
              className={`sort-pill ${sortKey === 'rating' ? 'active' : ''}`}
              onClick={() => handleSort('rating')}
            >
              <Star size={13} />
              <span>Grok Rating {sortKey === 'rating' ? (sortOrder === 'desc' ? '▼' : '▲') : ''}</span>
            </button>

            <button
              className={`sort-pill ${sortKey === 'updated_at' ? 'active' : ''}`}
              onClick={() => handleSort('updated_at')}
            >
              <Clock size={13} />
              <span>Last Updated {sortKey === 'updated_at' ? (sortOrder === 'desc' ? '▼' : '▲') : ''}</span>
            </button>

            <button
              className={`sort-pill ${sortKey === 'alert_count' ? 'active' : ''}`}
              onClick={() => handleSort('alert_count')}
            >
              <Flame size={13} />
              <span>Alert Count {sortKey === 'alert_count' ? (sortOrder === 'desc' ? '▼' : '▲') : ''}</span>
            </button>

            {selectedSymbols.length > 0 && (
              <button
                className="btn-danger-solid"
                onClick={handleDeleteSelectedStocks}
                title={`Delete ${selectedSymbols.length} selected stocks from ${activeTab} DB`}
              >
                <Trash2 size={14} />
                <span>Delete Selected ({selectedSymbols.length})</span>
              </button>
            )}

            <button
              className="btn-danger-outline"
              onClick={handleDeleteAllTimeframeStocks}
              title={`Delete all ${activeTab} stocks from database`}
              disabled={stocksData.length === 0}
            >
              <Trash2 size={14} />
              <span>Delete All {activeTab.toUpperCase()} Stocks</span>
            </button>
          </div>
        )}

        <div className="search-box">
          <Search className="search-icon" size={16} />
          <input
            type="text"
            className="search-input"
            placeholder={activeTab === 'gtts' ? "Search GTT ID or ticker..." : "Search ticker or pattern..."}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      {/* Main Database Table Container */}
      <div className="table-card">
        <div className="table-responsive">
          {activeTab === 'gtts' ? (
            /* ACTIVE ZERODHA GTTS TABLE */
            <table className="data-table">
              <thead>
                <tr>
                  <th>GTT Trigger ID</th>
                  <th>Stock Symbol</th>
                  <th>Last Traded Price</th>
                  <th>+1% Breakout Trigger Price</th>
                  <th>Order Type & Qty</th>
                  <th>Zerodha Status</th>
                  <th>Created Date</th>
                  <th style={{ textAlign: 'center' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={8}>
                      <div className="empty-state">
                        <div className="loading-spinner" style={{ margin: '0 auto 1rem' }}></div>
                        <h3>Fetching Active GTT Alerts from Zerodha Account...</h3>
                      </div>
                    </td>
                  </tr>
                ) : filteredGtts.length === 0 ? (
                  <tr>
                    <td colSpan={8}>
                      <div className="empty-state">
                        <div className="empty-icon">⚡</div>
                        <h3>No Active GTT Alerts Found on Zerodha Account</h3>
                        <p>Zerodha GTT triggers will appear here as soon as they are placed.</p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  filteredGtts.map((gtt, idx) => (
                    <tr key={gtt.id || idx}>
                      {/* GTT ID */}
                      <td>
                        <span className="ticker-symbol" style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}>
                          #{gtt.id}
                        </span>
                      </td>

                      {/* Stock Symbol */}
                      <td>
                        <div className="ticker-cell">
                          <span className="ticker-symbol">{gtt.symbol}</span>
                          <span className="exchange-tag">NSE</span>
                        </div>
                      </td>

                      {/* Last Traded Price */}
                      <td>
                        <span className="price-val">₹{(gtt.last_price || 0.0).toFixed(2)}</span>
                      </td>

                      {/* +1% Trigger Price */}
                      <td>
                        <span className="trigger-val">₹{(gtt.trigger_price || 0.0).toFixed(2)}</span>
                      </td>

                      {/* Order Type & Quantity */}
                      <td>
                        <span style={{ fontSize: '0.85rem', color: 'var(--text-main)', fontWeight: 600 }}>
                          {gtt.transaction_type} {gtt.quantity} @ ₹{(gtt.price || 0.0).toFixed(2)} ({gtt.order_type})
                        </span>
                      </td>

                      {/* Zerodha Status */}
                      <td>
                        <span className="status-pill gtt-active">
                          <CheckCircle2 size={13} style={{ marginRight: '0.3rem', verticalAlign: 'middle' }} />
                          ZERODHA {gtt.status || 'ACTIVE'}
                        </span>
                      </td>

                      {/* Created At */}
                      <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                        {formatDate(gtt.created_at)}
                      </td>

                      {/* Actions Column: Cancel Zerodha GTT */}
                      <td style={{ textAlign: 'center' }}>
                        <button
                          className="btn-icon-danger"
                          onClick={() => handleCancelZerodhaGtt(gtt.id, gtt.symbol)}
                          title={`Cancel Zerodha GTT #${gtt.id}`}
                        >
                          <Trash2 size={15} />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          ) : (
            /* MONTHLY / WEEKLY / DAILY STOCKS TABLE */
            <table className="data-table">
              <thead>
                <tr>
                  {/* Select All Checkbox */}
                  <th style={{ width: '40px', textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      className="custom-checkbox"
                      checked={processedStocks.length > 0 && processedStocks.every(s => selectedSymbols.includes(s.symbol))}
                      onChange={handleSelectAllToggle}
                      title="Select / Deselect All Visible Stocks"
                    />
                  </th>

                  <th className="sortable-th" onClick={() => handleSort('symbol')}>
                    <div className="th-content">
                      <span>Stock Symbol</span>
                      {renderSortIcon('symbol')}
                    </div>
                  </th>

                  <th className="sortable-th" onClick={() => handleSort('rating')}>
                    <div className="th-content">
                      <span>Grok Rating</span>
                      {renderSortIcon('rating')}
                    </div>
                  </th>

                  <th>Breakout Reason & Context</th>

                  <th className="sortable-th" onClick={() => handleSort('recent_high')}>
                    <div className="th-content">
                      <span>Recent High</span>
                      {renderSortIcon('recent_high')}
                    </div>
                  </th>

                  <th className="sortable-th" onClick={() => handleSort('alert_trigger_price')}>
                    <div className="th-content">
                      <span>+1% Alert Price</span>
                      {renderSortIcon('alert_trigger_price')}
                    </div>
                  </th>

                  <th>Alert Status</th>

                  <th className="sortable-th" onClick={() => handleSort('alert_count')}>
                    <div className="th-content">
                      <span>🔥 Alert Count</span>
                      {renderSortIcon('alert_count')}
                    </div>
                  </th>

                  <th className="sortable-th" onClick={() => handleSort('updated_at')}>
                    <div className="th-content">
                      <span>Last Updated</span>
                      {renderSortIcon('updated_at')}
                    </div>
                  </th>

                  <th style={{ textAlign: 'center' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading && processedStocks.length === 0 ? (
                  <tr>
                    <td colSpan={10}>
                      <div className="empty-state">
                        <div className="loading-spinner" style={{ margin: '0 auto 1rem' }}></div>
                        <h3>Loading {activeTab.toUpperCase()} Database Records...</h3>
                      </div>
                    </td>
                  </tr>
                ) : processedStocks.length === 0 ? (
                  <tr>
                    <td colSpan={10}>
                      <div className="empty-state">
                        <div className="empty-icon">📊</div>
                        <h3>No Stocks Found in {activeTab.toUpperCase()} Table</h3>
                        <p>Run the Grok pipeline to fetch and evaluate top stocks from Chartink.</p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  processedStocks.map((item, idx) => {
                    const alertCount = item.alert_count || 0;
                    const recentHigh = item.recent_high || 0.0;
                    const triggerPrice = item.alert_trigger_price || (recentHigh * 1.01);
                    const statusStr = item.alert_status || 'LOCAL_ALERT_SET';
                    const isGtt = statusStr.includes('GTT');
                    const isSelected = selectedSymbols.includes(item.symbol);

                    return (
                      <tr key={item._id || item.symbol || idx} className={isSelected ? 'row-selected' : ''}>
                        {/* Select Checkbox */}
                        <td style={{ textAlign: 'center' }}>
                          <input
                            type="checkbox"
                            className="custom-checkbox"
                            checked={isSelected}
                            onChange={() => handleToggleSelectSymbol(item.symbol)}
                          />
                        </td>

                        {/* Stock Symbol */}
                        <td>
                          <div className="ticker-cell">
                            <span className="ticker-symbol">{item.symbol}</span>
                            <span className="exchange-tag">NSE</span>
                          </div>
                        </td>

                        {/* Grok Conviction Rating */}
                        <td>
                          <div className="rating-pill">
                            <Star size={14} fill="#10b981" color="#10b981" />
                            <span>{(item.rating || 4.0).toFixed(1)}</span>
                          </div>
                        </td>

                        {/* Analysis Reason */}
                        <td>
                          <div className="reason-text">
                            {item.reason || 'Strong TSI & volume breakout setup.'}
                          </div>
                        </td>

                        {/* Recent High */}
                        <td>
                          <span className="price-val">₹{recentHigh.toFixed(2)}</span>
                        </td>

                        {/* +1% Alert Trigger Price */}
                        <td>
                          <span className="trigger-val">₹{triggerPrice.toFixed(2)}</span>
                        </td>

                        {/* Alert Status */}
                        <td>
                          <span className={`status-pill ${isGtt ? 'gtt-active' : 'local-set'}`}>
                            {isGtt ? 'ZERODHA GTT ACTIVE' : 'LOCAL ALERT SET'}
                          </span>
                        </td>

                        {/* 🔥 ALERT COUNT COLUMN */}
                        <td>
                          <div className={`alert-count-badge ${alertCount > 0 ? 'has-alerts' : 'no-alerts'}`}>
                            <Flame className="flame-icon" size={15} />
                            <span>{alertCount} Triggered</span>
                          </div>
                        </td>

                        {/* Last Updated */}
                        <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                          {formatDate(item.updated_at)}
                        </td>

                        {/* Actions Column: Delete Individual Stock */}
                        <td style={{ textAlign: 'center' }}>
                          <button
                            className="btn-icon-danger"
                            onClick={() => handleDeleteSingleStock(item.symbol)}
                            title={`Delete ${item.symbol} from ${activeTab.toUpperCase()} DB`}
                          >
                            <Trash2 size={15} />
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
