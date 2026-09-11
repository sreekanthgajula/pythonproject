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
  Trash2,
  Trophy
} from 'lucide-react';
import StockAlertRaceChart from './components/StockAlertRaceChart';

const API_BASE_URL = '/api';

export default function App() {
  const [activeTab, setActiveTab] = useState('monthly'); // 'monthly' | 'weekly' | 'daily' | 'active_gtts' | 'race'
  const [stocksData, setStocksData] = useState([]);
  const [gttsData, setGttsData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [runningPipeline, setRunningPipeline] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [wsStatus, setWsStatus] = useState({ running: false, monitored_tokens_count: 0 });
  const [tabCounts, setTabCounts] = useState({ monthly: 0, weekly: 0, daily: 0, active_gtts: 0, race: 0 });
  const [selectedSymbols, setSelectedSymbols] = useState([]);

  // Sorting state: default sort by 'rating' descending
  const [sortKey, setSortKey] = useState('rating'); // 'rating' | 'updated_at' | 'alert_count' | 'symbol' | 'recent_high' | 'alert_trigger_price'
  const [sortOrder, setSortOrder] = useState('desc'); // 'desc' | 'asc'

  // Fetch stocks data for the active timeframe
  const fetchTimeframeRatings = async (timeframe) => {
    if (timeframe === 'race') return;
    if (timeframe === 'active_gtts' || timeframe === 'gtts') {
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

  // Fetch all active & triggered GTT alerts (Zerodha GTTs + DB triggered alerts)
  const fetchZerodhaGtts = async () => {
    setLoading(true);
    try {
      let combinedGtts = [];
      const seenSymbols = new Set();

      // 1. Fetch Zerodha GTTs (includes ACTIVE, TRIGGERED, DISABLED, etc.)
      const res = await fetch(`${API_BASE_URL}/zerodha/gtts`);
      if (res.ok) {
        const json = await res.json();
        const items = json.gtts || [];
        for (const g of items) {
          combinedGtts.push(g);
          if (g.symbol) seenSymbols.add(g.symbol.toUpperCase());
        }
      }

      // 2. Fetch DB stocks across monthly, weekly, daily that have alert_count > 0 or triggered alert status
      for (const tf of ['monthly', 'weekly', 'daily']) {
        try {
          const dbRes = await fetch(`${API_BASE_URL}/ratings/${tf}`);
          if (dbRes.ok) {
            const json = await dbRes.json();
            const dbItems = json.data || [];
            const triggeredInTf = dbItems.filter(i => (i.alert_count && i.alert_count > 0) || (i.alert_status && i.alert_status.toUpperCase().includes('TRIGGER')));
            for (const item of triggeredInTf) {
              const symUpper = (item.symbol || '').toUpperCase();
              if (symUpper && !seenSymbols.has(symUpper)) {
                seenSymbols.add(symUpper);
                combinedGtts.push({
                  id: item.gtt_id || `ALERT-${symUpper}`,
                  symbol: symUpper,
                  status: item.alert_status || 'TRIGGERED',
                  trigger_price: item.alert_trigger_price || (item.recent_high * 1.01),
                  last_price: item.recent_high || 0.0,
                  transaction_type: 'BUY',
                  quantity: 1,
                  price: item.alert_trigger_price || (item.recent_high * 1.01),
                  order_type: 'LIMIT',
                  created_at: item.updated_at || new Date().toISOString(),
                  is_db_alert: true
                });
              }
            }
          }
        } catch (e) {
          console.error(`Error fetching DB alerts for ${tf}:`, e);
        }
      }

      setGttsData(combinedGtts);
      setTabCounts(prev => ({
        ...prev,
        active_gtts: combinedGtts.length
      }));
    } catch (err) {
      console.error('Error fetching GTTs:', err);
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

    try {
      const gttRes = await fetch(`${API_BASE_URL}/zerodha/gtts`);
      let gttCount = 0;
      const seenSymbols = new Set();
      if (gttRes.ok) {
        const json = await gttRes.json();
        const allGtts = json.gtts || [];
        gttCount += allGtts.length;
        for (const g of allGtts) {
          if (g.symbol) seenSymbols.add(g.symbol.toUpperCase());
        }
      }

      for (const tf of ['monthly', 'weekly', 'daily']) {
        try {
          const dbRes = await fetch(`${API_BASE_URL}/ratings/${tf}`);
          if (dbRes.ok) {
            const json = await dbRes.json();
            const dbItems = json.data || [];
            const triggeredInTf = dbItems.filter(i => (i.alert_count && i.alert_count > 0) || (i.alert_status && i.alert_status.toUpperCase().includes('TRIGGER')));
            for (const item of triggeredInTf) {
              const symUpper = (item.symbol || '').toUpperCase();
              if (symUpper && !seenSymbols.has(symUpper)) {
                seenSymbols.add(symUpper);
                gttCount += 1;
              }
            }
          }
        } catch (e) {}
      }

      setTabCounts(prev => ({ ...prev, active_gtts: gttCount }));
    } catch (err) {
      console.error('Error fetching GTT count:', err);
    }

    try {
      const raceRes = await fetch(`${API_BASE_URL}/race/daily`);
      if (raceRes.ok) {
        const json = await raceRes.json();
        setTabCounts(prev => ({ ...prev, race: json.count || 0 }));
      }
    } catch (err) {
      console.error('Error fetching race tab count:', err);
    }
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

  // Zerodha API Connection & TOTP Login State
  const [zerodhaStatus, setZerodhaStatus] = useState({ configured: false, status: 'checking', connected: false });
  const [totpCode, setTotpCode] = useState('');
  const [connectingZerodha, setConnectingZerodha] = useState(false);
  const [zerodhaMsg, setZerodhaMsg] = useState('');

  // Fetch Zerodha API Connection status
  const fetchZerodhaStatus = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/zerodha/status`);
      if (res.ok) {
        const json = await res.json();
        const isConnected = json.status === 'valid';
        setZerodhaStatus({ ...json, connected: isConnected });
      }
    } catch (err) {
      console.error('Error fetching Zerodha status:', err);
    }
  };

  // Submit TOTP Code to Connect to Zerodha API
  const handleConnectZerodha = async (e) => {
    if (e) e.preventDefault();
    const cleanTotp = totpCode.trim();
    if (!cleanTotp || cleanTotp.length !== 6) {
      alert('Please enter a valid 6-digit Zerodha TOTP code.');
      return;
    }
    setConnectingZerodha(true);
    setZerodhaMsg('');
    try {
      const res = await fetch(`${API_BASE_URL}/zerodha/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ totp: cleanTotp })
      });
      const json = await res.json();
      if (res.ok && json.status === 'success') {
        setZerodhaMsg('✅ Zerodha API Connected Successfully! Access Token Active.');
        setTotpCode('');
        fetchZerodhaStatus();
        fetchZerodhaGtts();
        fetchWsStatus();
      } else {
        const errMsg = json.detail || json.message || 'Zerodha authentication failed.';
        setZerodhaMsg(`❌ Connection Failed: ${errMsg}`);
        alert(`Zerodha Connection Failed: ${errMsg}`);
      }
    } catch (err) {
      setZerodhaMsg(`❌ Error: ${err}`);
      alert(`Zerodha Connection Error: ${err}`);
    } finally {
      setConnectingZerodha(false);
    }
  };

  useEffect(() => {
    setSelectedSymbols([]);
    fetchTimeframeRatings(activeTab);
    fetchAllTabCounts();
    fetchWsStatus();
    fetchZerodhaStatus();

    // Auto refresh every 10 seconds
    const intervalId = setInterval(() => {
      fetchTimeframeRatings(activeTab);
      fetchWsStatus();
      fetchZerodhaStatus();
    }, 10000);

    return () => clearInterval(intervalId);
  }, [activeTab]);

  // Trigger Chartink -> Grok -> DB -> Alert pipeline run
  const handleRunPipeline = async (isForce = false) => {
    if (isForce) {
      const confirmed = window.confirm(
        '⚡ FORCE RUN GROK AI EVALUATION?\n\nThis will BYPASS the daily guard limit and force live Grok AI re-evaluation for all Chartink candidates.'
      );
      if (!confirmed) return;
    }

    setRunningPipeline(true);
    try {
      const res = await fetch(`${API_BASE_URL}/pipeline/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ top_n: 20, force: isForce })
      });
      if (res.ok) {
        const modeText = isForce ? 'FORCE MODE ON (Daily Guard Bypassed)' : 'STANDARD MODE (Daily Guard Active)';
        alert(`Chartink -> Grok AI Pipeline started in background! [${modeText}]\n\nData will update automatically as Grok evaluates each timeframe.`);
        [3000, 8000, 15000, 25000].forEach(delay => {
          setTimeout(() => {
            fetchTimeframeRatings(activeTab);
            fetchAllTabCounts();
          }, delay);
        });
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
            onClick={() => handleRunPipeline(false)}
            disabled={runningPipeline}
            title="Run pipeline with Daily Guard active (preserves API credits if already run today)"
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
            className="btn-force-run"
            onClick={() => handleRunPipeline(true)}
            disabled={runningPipeline}
            title="Force re-evaluate all Chartink candidate stocks with live Grok API calls (Bypasses Daily Guard Limit)"
          >
            {runningPipeline ? (
              <>
                <div className="loading-spinner"></div>
                <span>Force Running...</span>
              </>
            ) : (
              <>
                <Flame size={16} />
                <span>⚡ Force Run (Bypass Limit)</span>
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

      {/* Zerodha API Connection Panel */}
      <div className="zerodha-connect-card">
        <div className="zerodha-status-info">
          <div className="zerodha-status-header">
            <ShieldCheck size={20} color={zerodhaStatus.connected ? "#10b981" : "#f43f5e"} />
            <span className="zerodha-status-title">Zerodha Kite API Connection</span>
          </div>
          <div className="zerodha-status-pill-container">
            <span className={`zerodha-status-badge ${zerodhaStatus.connected ? 'active' : 'disconnected'}`}>
              <span className={`pulse-dot ${zerodhaStatus.connected ? 'online' : 'offline'}`}></span>
              {zerodhaStatus.connected ? 'API Connection Active & Authenticated' : 'Disconnected (6-Digit TOTP Required)'}
            </span>
          </div>
        </div>

        <form onSubmit={handleConnectZerodha} className="zerodha-connect-form">
          <div className="totp-input-wrapper">
            <input
              type="text"
              maxLength="6"
              placeholder="Enter 6-digit TOTP Code"
              value={totpCode}
              onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ''))}
              className="totp-input"
            />
          </div>
          <button
            type="submit"
            className={`btn-zerodha-connect ${zerodhaStatus.connected ? 'connected' : ''}`}
            disabled={connectingZerodha}
          >
            {connectingZerodha ? (
              <>
                <div className="loading-spinner"></div>
                <span>Connecting...</span>
              </>
            ) : (
              <>
                <CheckCircle2 size={16} />
                <span>{zerodhaStatus.connected ? 'Re-Connect Zerodha' : 'Connect to Zerodha API'}</span>
              </>
            )}
          </button>
        </form>
        {zerodhaMsg && <div className="zerodha-msg-feedback">{zerodhaMsg}</div>}
      </div>

      {/* Summary Stats Overview Cards */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-header">
            <span className="stat-title">Active Timeframe Stocks</span>
            <Layers className="stat-icon" color="#38bdf8" />
          </div>
          <div className="stat-value">{activeTab === 'active_gtts' ? gttsData.length : stocksData.length}</div>
          <div className="stat-desc">{activeTab === 'active_gtts' ? 'Zerodha & Triggered GTT Alerts' : `DB records in ${activeTab.toUpperCase()} table`}</div>
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
            <span className="stat-title">Active & Triggered GTTs</span>
            <ShieldCheck className="stat-icon" color="#10b981" />
          </div>
          <div className="stat-value">{tabCounts.active_gtts || 0}</div>
          <div className="stat-desc">Zerodha & Triggered GTT Alerts</div>
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

          {/* ⚡ TAB 4: ACTIVE & TRIGGERED ZERODHA GTTS */}
          <button
            className={`tab-btn ${activeTab === 'active_gtts' || activeTab === 'gtts' ? 'active' : ''}`}
            onClick={() => setActiveTab('active_gtts')}
            style={{ borderLeft: '1px solid rgba(255, 255, 255, 0.1)' }}
          >
            <ShieldCheck size={16} color="#10b981" />
            <span>⚡ Active GTTs</span>
            <span className="tab-badge" style={{ background: '#10b981', color: '#fff' }}>{tabCounts.active_gtts || 0}</span>
          </button>

          {/* 🏎️ TAB 5: DAILY STOCK ALERT RACE */}
          <button
            className={`tab-btn ${activeTab === 'race' ? 'active' : ''}`}
            onClick={() => setActiveTab('race')}
            style={{ borderLeft: '1px solid rgba(255, 255, 255, 0.1)' }}
          >
            <Trophy size={16} color="#f59e0b" />
            <span>🏎️ Race</span>
            <span className="tab-badge" style={{ background: '#f59e0b', color: '#fff' }}>{tabCounts.race || 0}</span>
          </button>
        </nav>

        {/* Quick Sorting Pills & Delete All Button (Hidden on Active GTTS & Race tabs) */}
        {activeTab !== 'active_gtts' && activeTab !== 'gtts' && activeTab !== 'race' && (
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

        {activeTab !== 'race' && (
          <div className="search-box">
            <Search className="search-icon" size={16} />
            <input
              type="text"
              className="search-input"
              placeholder={activeTab === 'active_gtts' || activeTab === 'gtts' ? "Search GTT ID or ticker..." : "Search ticker or pattern..."}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        )}
      </div>

      {activeTab === 'race' ? (
        /* 🏎️ DAILY STOCK ALERT RACE VIEW */
        <StockAlertRaceChart />
      ) : (
        /* Main Database Table Container */
        <div className="table-card">
          <div className="table-responsive">
          {activeTab === 'active_gtts' || activeTab === 'gtts' ? (
            /* ACTIVE & TRIGGERED ZERODHA GTTS TABLE */
            <table className="data-table">
              <thead>
                <tr>
                  <th>GTT Trigger ID</th>
                  <th>Stock Symbol</th>
                  <th>Last Traded Price</th>
                  <th>+1% Breakout Trigger Price</th>
                  <th>Order Type & Qty</th>
                  <th>Zerodha / Alert Status</th>
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
                        <h3>Fetching Active & Triggered GTT Alerts...</h3>
                      </div>
                    </td>
                  </tr>
                ) : filteredGtts.length === 0 ? (
                  <tr>
                    <td colSpan={8}>
                      <div className="empty-state">
                        <div className="empty-icon">⚡</div>
                        <h3>No Active or Triggered GTT Alerts Found</h3>
                        <p>GTT triggers and alert notifications will appear here as soon as they are placed.</p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  filteredGtts.map((gtt, idx) => {
                    const statusStr = (gtt.status || 'ACTIVE').toUpperCase();
                    const isTriggered = statusStr.includes('TRIGGER');
                    const isDisabled = statusStr.includes('DISABLE') || statusStr.includes('CANCEL');
                    const isActive = statusStr.includes('ACTIVE');

                    let pillClass = 'gtt-active';
                    if (isTriggered) pillClass = 'gtt-triggered';
                    else if (isDisabled) pillClass = 'gtt-disabled';

                    return (
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
                            {gtt.transaction_type || 'BUY'} {gtt.quantity || 1} @ ₹{(gtt.price || 0.0).toFixed(2)} ({gtt.order_type || 'LIMIT'})
                          </span>
                        </td>

                        {/* Status */}
                        <td>
                          <span className={`status-pill ${pillClass}`}>
                            {isTriggered ? (
                              <Flame size={13} style={{ marginRight: '0.3rem', verticalAlign: 'middle' }} />
                            ) : (
                              <CheckCircle2 size={13} style={{ marginRight: '0.3rem', verticalAlign: 'middle' }} />
                            )}
                            {gtt.is_db_alert ? gtt.status : `ZERODHA ${gtt.status || 'ACTIVE'}`}
                          </span>
                        </td>

                        {/* Created At */}
                        <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                          {formatDate(gtt.created_at)}
                        </td>

                        {/* Actions Column: Cancel Zerodha GTT */}
                        <td style={{ textAlign: 'center' }}>
                          {!gtt.is_db_alert && isActive && (
                            <button
                              className="btn-icon-danger"
                              onClick={() => handleCancelZerodhaGtt(gtt.id, gtt.symbol)}
                              title={`Cancel Zerodha GTT #${gtt.id}`}
                            >
                              <Trash2 size={15} />
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })
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
                            {item.timeframe && (
                              <span className="exchange-tag" style={{ background: '#8b5cf6', color: '#fff', marginLeft: '0.3rem' }}>
                                {item.timeframe.toUpperCase()}
                              </span>
                            )}
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
      )}
    </div>
  );
}
