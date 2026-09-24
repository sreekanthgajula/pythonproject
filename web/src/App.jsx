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
  Trophy,
  Sparkles
} from 'lucide-react';
import StockAlertRaceChart from './components/StockAlertRaceChart';
import DerivativesSpeedometer from './components/DerivativesSpeedometer';

const API_BASE_URL = '/api';

export default function App() {
  const [activeTab, setActiveTab] = useState('monthly'); // 'monthly' | 'weekly' | 'daily' | 'manual' | 'darvas' | 'active_gtts' | 'todays_race' | 'race'
  const [stocksData, setStocksData] = useState([]);
  const [gttsData, setGttsData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [runningPipeline, setRunningPipeline] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [wsStatus, setWsStatus] = useState({ running: false, monitored_tokens_count: 0 });
  const [tabCounts, setTabCounts] = useState({ monthly: 0, weekly: 0, daily: 0, manual: 0, darvas: 0, active_gtts: 0, todays_race: 0, race: 0 });
  const [selectedSymbols, setSelectedSymbols] = useState([]);

  // Manual Stock Modal State
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [resettingGttSymbol, setResettingGttSymbol] = useState(null);
  const [resettingAllGtts, setResettingAllGtts] = useState(false);
  const [syncingGtts, setSyncingGtts] = useState(false);
  const [scanningDarvas, setScanningDarvas] = useState(false);
  const [manualSymbol, setManualSymbol] = useState('');
  const [manualReason, setManualReason] = useState('');
  const [addingManualStock, setAddingManualStock] = useState(false);
  const [manualError, setManualError] = useState('');

  const handleScanDarvas = async () => {
    setScanningDarvas(true);
    try {
      const res = await fetch(`${API_BASE_URL}/darvas/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        fetchAllTabCounts();
        if (activeTab === 'darvas') {
          fetchTimeframeRatings('darvas');
        }
        const scanned = data.scanned_count ?? (data.data ? data.data.length : 0);
        const qualified = data.qualified_count ?? (data.data ? data.data.length : 0);
        alert(`⚡ Darvas Box Scan Complete!\nScanned ${scanned} watchlist stocks.\nFound ${qualified} qualified Darvas Box setups!`);
      } else {
        alert(`Darvas Scan error: ${data.detail || data.message || 'Scan failed'}`);
      }
    } catch (err) {
      alert(`Error triggering Darvas scan: ${err.message}`);
    } finally {
      setScanningDarvas(false);
    }
  };

  // NSE Derivatives Analyst State
  const [derivativesData, setDerivativesData] = useState(null);
  const [loadingDerivatives, setLoadingDerivatives] = useState(false);
  const [loadingGrokNews, setLoadingGrokNews] = useState(false);

  const fetchDerivativesAnalysis = async (forceGrok = false) => {
    if (forceGrok) {
      setLoadingGrokNews(true);
    } else {
      setLoadingDerivatives(true);
    }
    try {
      const res = await fetch(`${API_BASE_URL}/derivatives/analysis?force_grok=${forceGrok}`);
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'success') {
          setDerivativesData(data);
        }
      }
    } catch (err) {
      console.error('Failed to fetch derivatives analysis:', err);
    } finally {
      setLoadingDerivatives(false);
      setLoadingGrokNews(false);
    }
  };


  // Sorting state: default sort by 'rating' descending
  const [sortKey, setSortKey] = useState('rating'); // 'rating' | 'updated_at' | 'alert_count' | 'symbol' | 'recent_high' | 'alert_trigger_price'
  const [sortOrder, setSortOrder] = useState('desc'); // 'desc' | 'asc'

  // Fetch stocks data for the active timeframe
  const fetchTimeframeRatings = async (timeframe) => {
    if (timeframe === 'race' || timeframe === 'todays_race') return;
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

      // 2. Fetch DB stocks across monthly, weekly, daily, manual that have alert_count > 0 or triggered alert status
      for (const tf of ['monthly', 'weekly', 'daily', 'manual']) {
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

      const activeOnlyCount = combinedGtts.filter(g => (g.status || '').toUpperCase().includes('ACTIVE')).length;
      setGttsData(combinedGtts);
      setTabCounts(prev => ({
        ...prev,
        active_gtts: activeOnlyCount
      }));
    } catch (err) {
      console.error('Error fetching GTTs:', err);
    } finally {
      setLoading(false);
    }
  };

  // Add stock manually endpoint handler
  const handleAddManualStock = async (e) => {
    if (e) e.preventDefault();
    const cleanSym = manualSymbol.trim().toUpperCase();
    if (!cleanSym) {
      setManualError('Please enter a valid stock symbol.');
      return;
    }
    setAddingManualStock(true);
    setManualError('');
    try {
      const res = await fetch(`${API_BASE_URL}/manual/add-stock`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: cleanSym, reason: manualReason.trim() || 'Manually added high potency stock' })
      });
      const json = await res.json();
      if (res.ok && json.status === 'success') {
        alert(`✅ Stock '${json.symbol}' added successfully to Manual table with 1% Zerodha GTT Alert!`);
        setIsAddModalOpen(false);
        setManualSymbol('');
        setManualReason('');
        setActiveTab('manual');
        fetchTimeframeRatings('manual');
        fetchAllTabCounts();
      } else {
        const errMsg = json.detail || json.message || 'Failed to add stock manually.';
        setManualError(errMsg);
      }
    } catch (err) {
      setManualError(`Error adding stock: ${err.message || err}`);
    } finally {
      setAddingManualStock(false);
    }
  };

  // Fetch counts for all timeframes for tab badges
  const fetchAllTabCounts = async () => {
    for (const tf of ['monthly', 'weekly', 'daily', 'manual', 'darvas']) {
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

      for (const tf of ['monthly', 'weekly', 'daily', 'manual']) {
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
      const todaysRaceRes = await fetch(`${API_BASE_URL}/race/daily?today_only=true`);
      if (todaysRaceRes.ok) {
        const json = await todaysRaceRes.json();
        setTabCounts(prev => ({ ...prev, todays_race: json.count || 0 }));
      }
    } catch (err) {
      console.error('Error fetching todays_race tab count:', err);
    }

    try {
      const pastWeekRaceRes = await fetch(`${API_BASE_URL}/race/daily?past_week_only=true`);
      if (pastWeekRaceRes.ok) {
        const json = await pastWeekRaceRes.json();
        setTabCounts(prev => ({ ...prev, past_week_race: json.count || 0 }));
      }
    } catch (err) {
      console.error('Error fetching past_week_race tab count:', err);
    }

    try {
      const raceRes = await fetch(`${API_BASE_URL}/race/daily?today_only=false`);
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
    fetchDerivativesAnalysis();

    // Fast status auto refresh every 10 seconds
    const intervalId = setInterval(() => {
      fetchTimeframeRatings(activeTab);
      fetchAllTabCounts();
      fetchWsStatus();
      fetchZerodhaStatus();
    }, 10000);

    // Derivatives OI & Speedometer auto refresh every 5 minutes (300,000 ms) - Low Server Pressure
    const derivativesIntervalId = setInterval(() => {
      fetchDerivativesAnalysis(false);
    }, 300000);

    return () => {
      clearInterval(intervalId);
      clearInterval(derivativesIntervalId);
    };
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


  // Reset 1% GTT alert from live current trading price for a single stock
  const handleResetSingleGtt = async (symbol) => {
    setResettingGttSymbol(symbol);
    try {
      const res = await fetch(`${API_BASE_URL}/stocks/${encodeURIComponent(symbol)}/reset-gtt?timeframe=${activeTab}`, {
        method: 'POST'
      });
      const json = await res.json();
      if (res.ok && json.status === 'success') {
        alert(`⚡ 1% GTT RESET COMPLETE FOR ${symbol}!\n\n${json.message}`);
        fetchTimeframeRatings(activeTab);
        fetchZerodhaGtts();
      } else {
        alert(`❌ Failed to reset GTT for ${symbol}: ${json.detail || json.message || 'Unknown error'}`);
      }
    } catch (err) {
      alert(`❌ Error resetting GTT for ${symbol}: ${err}`);
    } finally {
      setResettingGttSymbol(null);
    }
  };

  // Reset 1% GTT alerts from live current trading prices for ALL stocks in active tab
  const handleResetAllGtts = async (tf) => {
    const tabName = tf === 'manual' ? 'MANUAL' : tf.toUpperCase();
    const confirmed = window.confirm(
      `⚡ RESET ALL 1% GTT ALERTS FOR ${tabName} STOCKS?\n\nThis will cancel all previous GTT alerts on Zerodha for ${tabName} stocks and place NEW 1% GTT breakout alerts based on their LIVE CURRENT TRADING PRICES.`
    );
    if (!confirmed) return;

    setResettingAllGtts(true);
    try {
      const res = await fetch(`${API_BASE_URL}/stocks/reset-all-gtts?timeframe=${tf}`, {
        method: 'POST'
      });
      const json = await res.json();
      if (res.ok && json.status === 'success') {
        alert(`⚡ BATCH 1% GTT RESET COMPLETE!\n\n${json.message}`);
        fetchTimeframeRatings(activeTab);
        fetchZerodhaGtts();
      } else {
        alert(`❌ Failed to batch reset GTT alerts: ${json.detail || json.message || 'Unknown error'}`);
      }
    } catch (err) {
      alert(`❌ Error resetting GTT alerts: ${err}`);
    } finally {
      setResettingAllGtts(false);
    }
  };

  // Synchronize & deduplicate GTT orders on Zerodha account with DB watchlist
  const handleSyncGtts = async () => {
    setSyncingGtts(true);
    try {
      const res = await fetch(`${API_BASE_URL}/zerodha/sync-gtts`, {
        method: 'POST'
      });
      const json = await res.json();
      if (res.ok && json.status === 'success') {
        alert(`🔄 ZERODHA GTT SYNC COMPLETE!\n\n${json.message}`);
        fetchZerodhaGtts();
        fetchAllTabCounts();
        if (activeTab === 'active_gtts' || activeTab === 'gtts') {
          fetchTimeframeRatings('gtts');
        }
      } else {
        alert(`❌ Zerodha GTT sync failed: ${json.detail || json.message || 'Unknown error'}`);
      }
    } catch (err) {
      alert(`❌ Error syncing GTTs: ${err}`);
    } finally {
      setSyncingGtts(false);
    }
  };

  // Handle deleting all stocks in the active timeframe collection
  const handleDeleteAllTimeframeStocks = async () => {
    if (activeTab === 'gtts' || activeTab === 'race' || activeTab === 'todays_race') return;
    const isManual = activeTab === 'manual';
    const tabName = isManual ? 'MANUAL' : activeTab.toUpperCase();
    const confirmed = window.confirm(
      `⚠️ ARE YOU SURE YOU WANT TO DELETE ALL ${tabName} STOCKS?\n\nThis will PERMANENTLY DELETE ALL stock records from the ${tabName} database collection and CANCEL their active Zerodha GTT breakout alerts!`
    );
    if (!confirmed) return;

    setLoading(true);
    try {
      const endpoint = isManual ? `${API_BASE_URL}/manual/clear-all` : `${API_BASE_URL}/ratings/${activeTab}`;
      const res = await fetch(endpoint, {
        method: 'DELETE'
      });
      const json = await res.json();
      if (res.ok && json.status === 'success') {
        alert(`✅ Successfully deleted ${json.deleted_count} stock records from ${tabName} table and cancelled associated Zerodha GTT alerts.`);
        fetchTimeframeRatings(activeTab);
        fetchAllTabCounts();
        fetchZerodhaGtts();
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
      } else if (sortKey === 'close_strength_pct') {
        valA = a.close_strength_pct || 0;
        valB = b.close_strength_pct || 0;
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
            className="btn-sync-gtts"
            onClick={handleSyncGtts}
            disabled={syncingGtts}
            title="Deduplicate & sync active GTT orders on Zerodha with DB watchlist (Removes duplicates & orphans)"
          >
            {syncingGtts ? (
              <>
                <div className="loading-spinner"></div>
                <span>Syncing GTTs...</span>
              </>
            ) : (
              <>
                <RefreshCw size={16} />
                <span>Sync GTTs</span>
              </>
            )}
          </button>

          <button
            className="btn-primary"
            onClick={handleScanDarvas}
            disabled={scanningDarvas}
            style={{ background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)', border: 'none' }}
            title="Scan all watchlist stocks against Darvas Box rules & purge consolidated setups"
          >
            {scanningDarvas ? (
              <>
                <div className="loading-spinner"></div>
                <span>Scanning Darvas...</span>
              </>
            ) : (
              <>
                <Flame size={16} color="#fbbf24" />
                <span>⚡ Scan Darvas</span>
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


      {/* NSE Derivatives Analyst Speedometer Card */}
      <DerivativesSpeedometer
        data={derivativesData}
        loading={loadingDerivatives}
        loadingGrokNews={loadingGrokNews}
        onRefresh={fetchDerivativesAnalysis}
        onUpdateGrok={fetchDerivativesAnalysis}
        onFocusConnect={() => {
          const totpInput = document.querySelector('.zerodha-totp-input');
          if (totpInput) {
            totpInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
            totpInput.focus();
          }
        }}
      />

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

          {/* 🌟 TAB 4: MANUAL HIGH POTENCY TAB */}
          <button
            className={`tab-btn ${activeTab === 'manual' ? 'active' : ''}`}
            onClick={() => setActiveTab('manual')}
          >
            <Sparkles size={16} color="#ec4899" />
            <span>Manual 🌟</span>
            <span className="tab-badge" style={{ background: '#ec4899', color: '#fff' }}>{tabCounts.manual || 0}</span>
          </button>

          {/* ⚡ TAB 5: TRUE DARVAS BOX BREAKOUTS */}
          <button
            className={`tab-btn ${activeTab === 'darvas' ? 'active' : ''}`}
            onClick={() => setActiveTab('darvas')}
            style={{ borderLeft: '1px solid rgba(255, 255, 255, 0.1)' }}
          >
            <Flame size={16} color="#3b82f6" />
            <span>⚡ Darvas Box</span>
            <span className="tab-badge" style={{ background: '#3b82f6', color: '#fff' }}>{tabCounts.darvas || 0}</span>
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

          {/* 🏎️ TAB 5: STOCK ALERT RACE (Features Today's Race / Past Week Gainers / All-Time Mode Switcher) */}
          <button
            className={`tab-btn ${activeTab === 'race' || activeTab === 'todays_race' || activeTab === 'past_week_race' ? 'active' : ''}`}
            onClick={() => setActiveTab('todays_race')}
            style={{ borderLeft: '1px solid rgba(255, 255, 255, 0.1)' }}
          >
            <Trophy size={16} color="#f59e0b" />
            <span>🏎️ Stock Alert Race</span>
            <span className="tab-badge" style={{ background: '#f59e0b', color: '#fff' }}>{tabCounts.todays_race || tabCounts.race || 0}</span>
          </button>
        </nav>

        {/* Quick Sorting Pills & Delete All Button (Hidden on Active GTTS & Race tabs) */}
        {activeTab !== 'active_gtts' && activeTab !== 'gtts' && activeTab !== 'race' && activeTab !== 'todays_race' && activeTab !== 'past_week_race' && (
          <div className="sort-controls">
            {activeTab === 'manual' && (
              <button
                className="btn-add-manual-stock"
                onClick={() => {
                  setManualError('');
                  setIsAddModalOpen(true);
                }}
                title="Manually add a high potency stock to track and set 1% GTT alert"
                style={{ marginRight: '0.5rem' }}
              >
                <Sparkles size={16} />
                <span>+ Add Stock Manually</span>
              </button>
            )}

            <span className="sort-label">Sort By:</span>
            <button
              className={`sort-pill ${sortKey === 'rating' ? 'active' : ''}`}
              onClick={() => handleSort('rating')}
            >
              <Star size={13} />
              <span>Grok Rating {sortKey === 'rating' ? (sortOrder === 'desc' ? '▼' : '▲') : ''}</span>
            </button>

            {activeTab === 'darvas' && (
              <button
                className={`sort-pill ${sortKey === 'close_strength_pct' ? 'active' : ''}`}
                onClick={() => handleSort('close_strength_pct')}
              >
                <Zap size={13} color="#fbbf24" />
                <span>Close Strength {sortKey === 'close_strength_pct' ? (sortOrder === 'desc' ? '▼' : '▲') : ''}</span>
              </button>
            )}

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

            <button
              className="btn-gtt-reset-all"
              onClick={() => handleResetAllGtts(activeTab)}
              disabled={loading || stocksData.length === 0 || resettingAllGtts}
              title={`Cancel old GTTs and set new 1% GTT breakout alerts from current trading prices for all ${activeTab.toUpperCase()} stocks`}
            >
              {resettingAllGtts ? (
                <>
                  <div className="loading-spinner" style={{ width: '13px', height: '13px' }}></div>
                  <span>Resetting GTTs...</span>
                </>
              ) : (
                <>
                  <Zap size={14} color="#f59e0b" />
                  <span>⚡ Reset 1% GTTs (Current Price)</span>
                </>
              )}
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

        {(activeTab === 'active_gtts' || activeTab === 'gtts') && (
          <div className="sort-controls" style={{ marginLeft: 'auto' }}>
            <button
              className="btn-sync-gtts"
              onClick={handleSyncGtts}
              disabled={syncingGtts}
              title="Deduplicate & sync active GTT orders on Zerodha with DB watchlist"
            >
              {syncingGtts ? (
                <>
                  <div className="loading-spinner" style={{ width: '13px', height: '13px' }}></div>
                  <span>Syncing GTTs...</span>
                </>
              ) : (
                <>
                  <RefreshCw size={14} />
                  <span>Sync GTTs (Clean Duplicates)</span>
                </>
              )}
            </button>
          </div>
        )}

        {activeTab !== 'race' && activeTab !== 'todays_race' && activeTab !== 'past_week_race' && (
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

      {activeTab === 'todays_race' ? (
        /* 🏎️ TODAY'S STOCK ALERT RACE VIEW (Current Day Only) */
        <StockAlertRaceChart todayOnly={true} pastWeekOnly={false} />
      ) : activeTab === 'past_week_race' ? (
        /* 📈 PAST WEEK GAINERS STOCK ALERT RACE VIEW */
        <StockAlertRaceChart todayOnly={false} pastWeekOnly={true} />
      ) : activeTab === 'race' ? (
        /* 🏆 ALL-TIME STOCK ALERT RACE VIEW */
        <StockAlertRaceChart todayOnly={false} pastWeekOnly={false} />
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

                  {activeTab === 'darvas' && (
                    <th className="sortable-th" onClick={() => handleSort('close_strength_pct')}>
                      <div className="th-content">
                        <span>Close Strength %</span>
                        {renderSortIcon('close_strength_pct')}
                      </div>
                    </th>
                  )}

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
                        <div className="empty-icon">{activeTab === 'manual' ? '🌟' : '📊'}</div>
                        <h3>No Stocks Found in {activeTab.toUpperCase()} Table</h3>
                        <p>
                          {activeTab === 'manual'
                            ? 'Add high potency stocks manually to track and set 1% Zerodha GTT alerts.'
                            : 'Run the Grok pipeline to fetch and evaluate top stocks from Chartink.'}
                        </p>
                        {activeTab === 'manual' && (
                          <button
                            className="btn-add-manual-stock"
                            onClick={() => {
                              setManualError('');
                              setIsAddModalOpen(true);
                            }}
                            style={{ marginTop: '1rem' }}
                          >
                            <Sparkles size={16} />
                            <span>+ Add Stock Manually</span>
                          </button>
                        )}
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
                            <span>{(item.rating || 5.0).toFixed(1)}</span>
                          </div>
                        </td>

                        {/* Close Strength % (Darvas Tab) */}
                        {activeTab === 'darvas' && (
                          <td>
                            <div className="close-strength-pill" style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                              background: (item.close_strength_pct || 0) >= 75 ? 'rgba(245, 158, 11, 0.2)' : 'rgba(107, 114, 128, 0.2)',
                              color: (item.close_strength_pct || 0) >= 75 ? '#fbbf24' : '#9ca3af',
                              border: (item.close_strength_pct || 0) >= 75 ? '1px solid rgba(245, 158, 11, 0.4)' : '1px solid rgba(107, 114, 128, 0.4)',
                              borderRadius: '6px',
                              padding: '4px 8px',
                              fontSize: '0.82rem',
                              fontWeight: 600
                            }}>
                              <Zap size={13} color={(item.close_strength_pct || 0) >= 75 ? '#fbbf24' : '#9ca3af'} />
                              <span>{(item.close_strength_pct || 0).toFixed(1)}%</span>
                            </div>
                          </td>
                        )}

                        {/* Analysis Reason & Darvas Metrics */}
                        <td>
                          <div className="reason-text">
                            {activeTab === 'darvas' ? (
                              <div>
                                <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginBottom: '0.3rem' }}>
                                  <span style={{ background: 'rgba(59, 130, 246, 0.2)', color: '#60a5fa', border: '1px solid rgba(59, 130, 246, 0.4)', borderRadius: '4px', padding: '2px 6px', fontSize: '0.75rem', fontWeight: 600 }}>
                                    Box Top: ₹{item.box_top || recentHigh}
                                  </span>
                                  {item.box_bottom > 0 && (
                                    <span style={{ background: 'rgba(107, 114, 128, 0.2)', color: '#9ca3af', border: '1px solid rgba(107, 114, 128, 0.4)', borderRadius: '4px', padding: '2px 6px', fontSize: '0.75rem', fontWeight: 600 }}>
                                      Box Bottom: ₹{item.box_bottom}
                                    </span>
                                  )}
                                  {item.volume_surge_ratio > 0 && (
                                    <span style={{ background: 'rgba(16, 185, 129, 0.2)', color: '#34d399', border: '1px solid rgba(16, 185, 129, 0.4)', borderRadius: '4px', padding: '2px 6px', fontSize: '0.75rem', fontWeight: 600 }}>
                                      🔥 Vol Ratio: {item.volume_surge_ratio}x Avg
                                    </span>
                                  )}
                                  {item.close_strength_pct > 0 && (
                                    <span style={{ background: 'rgba(245, 158, 11, 0.2)', color: '#fbbf24', border: '1px solid rgba(245, 158, 11, 0.4)', borderRadius: '4px', padding: '2px 6px', fontSize: '0.75rem', fontWeight: 600 }}>
                                      💪 Close Strength: {item.close_strength_pct}%
                                    </span>
                                  )}
                                </div>
                                <div style={{ fontSize: '0.8rem', color: '#cbd5e1' }}>{item.reason}</div>
                              </div>
                            ) : (
                              item.reason || 'Strong TSI & volume breakout setup.'
                            )}
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

                        {/* Actions Column: GTT Alert Reset & Delete */}
                        <td style={{ textAlign: 'center' }}>
                          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
                            <button
                              className="btn-action-gtt"
                              onClick={() => handleResetSingleGtt(item.symbol)}
                              disabled={resettingGttSymbol === item.symbol}
                              title={`Set new 1% GTT alert for ${item.symbol} from its current trading price & cancel old GTT`}
                            >
                              {resettingGttSymbol === item.symbol ? (
                                <div className="loading-spinner" style={{ width: '12px', height: '12px' }}></div>
                              ) : (
                                <>
                                  <Zap size={13} />
                                  <span>GTT</span>
                                </>
                              )}
                            </button>

                            <button
                              className="btn-icon-danger"
                              onClick={() => handleDeleteSingleStock(item.symbol)}
                              title={`Delete ${item.symbol} from ${activeTab.toUpperCase()} DB`}
                            >
                              <Trash2 size={15} />
                            </button>
                          </div>
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

      {/* Modal for Adding Manual Stock */}
      {isAddModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsAddModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Add Stock Manually (High Potency)</h3>
              <button className="modal-close-btn" onClick={() => setIsAddModalOpen(false)}>×</button>
            </div>
            <form onSubmit={handleAddManualStock} className="modal-body">
              <div className="form-group">
                <label>Stock Symbol (e.g., RELIANCE, TATAMOTORS, INFY):</label>
                <input
                  type="text"
                  required
                  placeholder="Enter Stock Symbol"
                  value={manualSymbol}
                  onChange={(e) => {
                    setManualSymbol(e.target.value.toUpperCase());
                    setManualError('');
                  }}
                  className="modal-input"
                  autoFocus
                />
              </div>
              <div className="form-group">
                <label>Potency Reason / Thesis:</label>
                <textarea
                  placeholder="Why do you feel this stock has high potency?"
                  value={manualReason}
                  onChange={(e) => setManualReason(e.target.value)}
                  className="modal-textarea"
                  rows={3}
                />
              </div>

              {manualError && (
                <div className="modal-error-alert">
                  <strong>⚠️ Cannot Add Stock:</strong> {manualError}
                </div>
              )}

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn-cancel"
                  onClick={() => setIsAddModalOpen(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn-submit-manual"
                  disabled={addingManualStock}
                >
                  {addingManualStock ? (
                    <>
                      <div className="loading-spinner"></div>
                      <span>Adding & Setting GTT Alert...</span>
                    </>
                  ) : (
                    <span>Add Stock & Set 1% GTT Alert</span>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
