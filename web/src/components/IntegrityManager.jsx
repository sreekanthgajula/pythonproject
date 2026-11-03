import React, { useState, useEffect, useRef } from 'react';
import {
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  RefreshCw,
  Zap,
  CheckCircle2,
  XCircle,
  Activity,
  Server,
  Radio,
  Sliders,
  Database,
  Send,
  Cpu,
  BarChart2,
  Clock,
  Sparkles,
  ArrowRight,
  ChevronRight,
  Filter,
  Search,
  Wrench,
  Terminal,
  Layers,
  Flame,
  Info
} from 'lucide-react';

const API_BASE_URL = '/api';

export default function IntegrityManager() {
  const [auditData, setAuditData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [probing, setProbing] = useState(false);
  const [healingSubsystems, setHealingSubsystems] = useState({});
  const [healingAll, setHealingAll] = useState(false);
  const [autoRefreshSecs, setAutoRefreshSecs] = useState(15); // 0, 10, 15, 30
  const [selectedCategory, setSelectedCategory] = useState('ALL');
  const [searchFilter, setSearchFilter] = useState('');
  const [eventLogs, setEventLogs] = useState([]);
  const [actionNotice, setActionNotice] = useState(null);
  const [liveDualClock, setLiveDualClock] = useState({ ist: '', syd: '' });

  // Update clock every second
  useEffect(() => {
    const updateDualClock = () => {
      const now = new Date();
      const ist = now.toLocaleTimeString('en-US', {
        timeZone: 'Asia/Kolkata',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true
      });
      const syd = now.toLocaleTimeString('en-US', {
        timeZone: 'Australia/Sydney',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true
      });
      setLiveDualClock({ ist, syd });
    };
    updateDualClock();
    const interval = setInterval(updateDualClock, 1000);
    return () => clearInterval(interval);
  }, []);

  // Fetch Integrity Status
  const fetchIntegrityStatus = async (showLoading = false) => {
    if (showLoading) setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/integrity/status`);
      if (res.ok) {
        const data = await res.json();
        setAuditData(data);
        if (data.recent_events) {
          setEventLogs(data.recent_events);
        }
      }
    } catch (err) {
      console.error('Error fetching integrity status:', err);
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  // Initial fetch and auto-refresh loop
  useEffect(() => {
    fetchIntegrityStatus(true);
  }, []);

  useEffect(() => {
    if (autoRefreshSecs <= 0) return;
    const interval = setInterval(() => {
      fetchIntegrityStatus(false);
    }, autoRefreshSecs * 1000);
    return () => clearInterval(interval);
  }, [autoRefreshSecs]);

  // Deep Probe Now
  const handleDeepProbe = async () => {
    setProbing(true);
    try {
      const res = await fetch(`${API_BASE_URL}/integrity/probe`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setAuditData(data);
        if (data.recent_events) {
          setEventLogs(data.recent_events);
        }
        setActionNotice({
          type: 'success',
          text: `Deep Probe complete in ${data.audit_latency_ms || 0}ms! Overall Score: ${data.overall_score}%`
        });
      } else {
        setActionNotice({ type: 'error', text: 'Deep Probe request failed.' });
      }
    } catch (err) {
      setActionNotice({ type: 'error', text: `Deep probe error: ${err.message}` });
    } finally {
      setProbing(false);
      setTimeout(() => setActionNotice(null), 5000);
    }
  };

  // Self-heal a specific subsystem
  const handleHealSubsystem = async (engineId, engineName) => {
    setHealingSubsystems(prev => ({ ...prev, [engineId]: true }));
    try {
      const res = await fetch(`${API_BASE_URL}/integrity/heal/${engineId}`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data.refreshed_status) {
          setAuditData(data.refreshed_status);
          if (data.refreshed_status.recent_events) {
            setEventLogs(data.refreshed_status.recent_events);
          }
        }
        setActionNotice({
          type: 'success',
          text: `Self-Heal executed for ${engineName}: ${data.heal_result?.message || 'Completed'}`
        });
      } else {
        setActionNotice({ type: 'error', text: `Self-heal failed for ${engineName}.` });
      }
    } catch (err) {
      setActionNotice({ type: 'error', text: `Self-heal error: ${err.message}` });
    } finally {
      setHealingSubsystems(prev => ({ ...prev, [engineId]: false }));
      setTimeout(() => setActionNotice(null), 5000);
    }
  };

  // Auto-heal all degraded / warning subsystems
  const handleHealAll = async () => {
    setHealingAll(true);
    try {
      const res = await fetch(`${API_BASE_URL}/integrity/heal-all`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data.refreshed_status) {
          setAuditData(data.refreshed_status);
          if (data.refreshed_status.recent_events) {
            setEventLogs(data.refreshed_status.recent_events);
          }
        }
        setActionNotice({
          type: 'success',
          text: `Auto-Healed ${data.healed_count || 0} subsystem(s)! System Score: ${data.refreshed_status?.overall_score}%`
        });
      } else {
        setActionNotice({ type: 'error', text: 'Auto-heal all request failed.' });
      }
    } catch (err) {
      setActionNotice({ type: 'error', text: `Auto-heal error: ${err.message}` });
    } finally {
      setHealingAll(false);
      setTimeout(() => setActionNotice(null), 5000);
    }
  };

  // Filter Subsystems
  const subsystems = auditData?.subsystems || [];
  const categories = ['ALL', ...Array.from(new Set(subsystems.map(s => s.category)))];

  const filteredSubsystems = subsystems.filter(s => {
    const matchesCategory = selectedCategory === 'ALL' || s.category === selectedCategory;
    const matchesSearch =
      searchFilter === '' ||
      s.name.toLowerCase().includes(searchFilter.toLowerCase()) ||
      s.message.toLowerCase().includes(searchFilter.toLowerCase()) ||
      s.heartbeat.toLowerCase().includes(searchFilter.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  const overallScore = auditData?.overall_score || 0;
  const overallStatus = auditData?.overall_status || 'UNKNOWN';

  // Helper for Category Icon
  const getSubsystemIcon = (id, category) => {
    switch (id) {
      case 'zerodha_auth':
        return <Server className="w-5 h-5 text-emerald-400" />;
      case 'websocket_stream':
        return <Radio className="w-5 h-5 text-cyan-400" />;
      case 'gtt_ladder':
        return <Sliders className="w-5 h-5 text-indigo-400" />;
      case 'swarm_debate_gate':
        return <Cpu className="w-5 h-5 text-purple-400" />;
      case 'race_returns_cache':
        return <BarChart2 className="w-5 h-5 text-amber-400" />;
      case 'derivatives_engine':
        return <Activity className="w-5 h-5 text-rose-400" />;
      case 'morning_short_engine':
        return <Flame className="w-5 h-5 text-orange-400" />;
      case 'evening_pro_engine':
        return <Sparkles className="w-5 h-5 text-yellow-400" />;
      case 'paper_trading':
        return <Layers className="w-5 h-5 text-blue-400" />;
      case 'mongodb_persistence':
        return <Database className="w-5 h-5 text-emerald-300" />;
      case 'telegram_alerts':
        return <Send className="w-5 h-5 text-sky-400" />;
      default:
        return <ShieldCheck className="w-5 h-5 text-gray-400" />;
    }
  };

  return (
    <div className="space-y-6 text-gray-100">
      {/* ACTION NOTICE TOAST */}
      {actionNotice && (
        <div
          className={`flex items-center justify-between p-4 rounded-xl border shadow-xl transition-all ${
            actionNotice.type === 'success'
              ? 'bg-emerald-950/80 border-emerald-500/50 text-emerald-200'
              : 'bg-rose-950/80 border-rose-500/50 text-rose-200'
          }`}
        >
          <div className="flex items-center space-x-3">
            {actionNotice.type === 'success' ? (
              <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
            ) : (
              <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0" />
            )}
            <span className="text-sm font-medium">{actionNotice.text}</span>
          </div>
          <button
            onClick={() => setActionNotice(null)}
            className="text-xs uppercase tracking-wider text-gray-400 hover:text-white"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* TOP HERO METRICS & CONTROL BAR */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* CARD 1: OVERALL HEALTH GAUGE (5 COLS) */}
        <div className="lg:col-span-5 bg-[#121620] border border-gray-800 rounded-2xl p-6 shadow-xl relative overflow-hidden flex flex-col justify-between">
          <div className="absolute top-0 right-0 w-64 h-64 bg-gradient-to-bl from-cyan-500/10 via-emerald-500/5 to-transparent rounded-full blur-2xl pointer-events-none" />

          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-2.5">
              <ShieldCheck className="w-6 h-6 text-emerald-400" />
              <h2 className="text-lg font-bold tracking-wide text-white">Platform Integrity Score</h2>
            </div>
            <span
              className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider flex items-center space-x-1.5 ${
                overallStatus === 'HEALTHY'
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                  : overallStatus === 'WARNING'
                  ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40'
                  : 'bg-rose-500/20 text-rose-400 border border-rose-500/40'
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  overallStatus === 'HEALTHY'
                    ? 'bg-emerald-400 animate-pulse'
                    : overallStatus === 'WARNING'
                    ? 'bg-amber-400 animate-pulse'
                    : 'bg-rose-400 animate-ping'
                }`}
              />
              <span>{overallStatus === 'HEALTHY' ? 'All Systems Go' : overallStatus}</span>
            </span>
          </div>

          <div className="flex items-center space-x-6 my-2">
            {/* BIG SCORE CIRCLE */}
            <div className="relative flex items-center justify-center w-28 h-28 rounded-full border-4 border-gray-800 bg-[#0c0f17]">
              <div
                className={`text-3xl font-extrabold tracking-tight ${
                  overallScore >= 95
                    ? 'text-emerald-400'
                    : overallScore >= 75
                    ? 'text-amber-400'
                    : 'text-rose-400'
                }`}
              >
                {overallScore}%
              </div>
            </div>

            {/* BREAKDOWN PILLS */}
            <div className="flex-1 space-y-2">
              <div className="flex items-center justify-between text-xs text-gray-400">
                <span className="flex items-center space-x-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 inline-block" />
                  <span>Healthy Engines</span>
                </span>
                <span className="font-bold text-white">
                  {auditData?.healthy_count || 0} / {auditData?.total_subsystems || 11}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs text-gray-400">
                <span className="flex items-center space-x-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-400 inline-block" />
                  <span>Warnings / Standby</span>
                </span>
                <span className="font-bold text-amber-400">{auditData?.warning_count || 0}</span>
              </div>
              <div className="flex items-center justify-between text-xs text-gray-400">
                <span className="flex items-center space-x-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-rose-400 inline-block" />
                  <span>Degraded Engines</span>
                </span>
                <span className="font-bold text-rose-400">{auditData?.degraded_count || 0}</span>
              </div>

              {/* Progress Bar */}
              <div className="w-full bg-gray-800 h-2 rounded-full overflow-hidden flex mt-2">
                <div
                  className="bg-emerald-500 h-full transition-all duration-500"
                  style={{
                    width: `${((auditData?.healthy_count || 0) / (auditData?.total_subsystems || 11)) * 100}%`
                  }}
                />
                <div
                  className="bg-amber-500 h-full transition-all duration-500"
                  style={{
                    width: `${((auditData?.warning_count || 0) / (auditData?.total_subsystems || 11)) * 100}%`
                  }}
                />
                <div
                  className="bg-rose-500 h-full transition-all duration-500"
                  style={{
                    width: `${((auditData?.degraded_count || 0) / (auditData?.total_subsystems || 11)) * 100}%`
                  }}
                />
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-gray-800/80 flex items-center justify-between text-xs text-gray-500">
            <span>Latency: {auditData?.audit_latency_ms || 0}ms</span>
            <span>Last Audit: {auditData?.dual_time || 'Just now'}</span>
          </div>
        </div>

        {/* CARD 2: DUAL TIMEZONE & MARKET MONITOR (3 COLS) */}
        <div className="lg:col-span-3 bg-[#121620] border border-gray-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
          <div className="flex items-center space-x-2 text-gray-400 text-xs font-semibold uppercase tracking-wider mb-2">
            <Clock className="w-4 h-4 text-cyan-400" />
            <span>Dual Sync Clocks</span>
          </div>

          <div className="space-y-4 my-auto">
            <div className="bg-[#0b0e14] p-3 rounded-xl border border-gray-800/80 flex items-center justify-between">
              <div>
                <div className="text-[10px] uppercase font-bold text-gray-500">India (IST)</div>
                <div className="text-base font-extrabold text-cyan-400 tracking-wide font-mono">
                  {liveDualClock.ist || 'Loading...'}
                </div>
              </div>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-950/60 text-cyan-300 border border-cyan-800/40">
                NSE Window
              </span>
            </div>

            <div className="bg-[#0b0e14] p-3 rounded-xl border border-gray-800/80 flex items-center justify-between">
              <div>
                <div className="text-[10px] uppercase font-bold text-gray-500">Sydney (AEDT)</div>
                <div className="text-base font-extrabold text-indigo-400 tracking-wide font-mono">
                  {liveDualClock.syd || 'Loading...'}
                </div>
              </div>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-indigo-950/60 text-indigo-300 border border-indigo-800/40">
                +5.5 hrs
              </span>
            </div>
          </div>

          <div className="text-[11px] text-gray-500 pt-2 border-t border-gray-800/80 flex items-center justify-between">
            <span>Market Session:</span>
            <span className="text-gray-300 font-medium">9:15 AM - 3:30 PM IST</span>
          </div>
        </div>

        {/* CARD 3: MISSION CONTROL ACTIONS (4 COLS) */}
        <div className="lg:col-span-4 bg-[#121620] border border-gray-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center space-x-2 text-gray-400 text-xs font-semibold uppercase tracking-wider">
              <Zap className="w-4 h-4 text-amber-400" />
              <span>Integrity Actions</span>
            </div>
            <div className="flex items-center space-x-1.5 text-xs">
              <span className="text-gray-500 text-[11px]">Auto-Refresh:</span>
              <select
                value={autoRefreshSecs}
                onChange={e => setAutoRefreshSecs(Number(e.target.value))}
                className="bg-[#0b0e14] text-gray-300 text-xs border border-gray-700 rounded px-2 py-0.5 focus:outline-none"
              >
                <option value={0}>Off</option>
                <option value={10}>10s</option>
                <option value={15}>15s</option>
                <option value={30}>30s</option>
              </select>
            </div>
          </div>

          <div className="space-y-3 my-auto">
            {/* DEEP PROBE BUTTON */}
            <button
              onClick={handleDeepProbe}
              disabled={probing || loading}
              className="w-full flex items-center justify-center space-x-2 px-4 py-3 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 disabled:opacity-50 text-white rounded-xl font-bold shadow-lg shadow-cyan-900/30 transition-all text-sm"
            >
              <RefreshCw className={`w-4 h-4 ${probing ? 'animate-spin' : ''}`} />
              <span>{probing ? 'Probing All 11 Subsystems...' : 'Deep Probe All Subsystems'}</span>
            </button>

            {/* AUTO-HEAL ALL BUTTON */}
            <button
              onClick={handleHealAll}
              disabled={healingAll || auditData?.warning_count + auditData?.degraded_count === 0}
              className="w-full flex items-center justify-center space-x-2 px-4 py-3 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl font-bold shadow-lg shadow-emerald-900/30 transition-all text-sm"
            >
              <Wrench className={`w-4 h-4 ${healingAll ? 'animate-spin' : ''}`} />
              <span>
                {healingAll
                  ? 'Healing Warnings & Degraded...'
                  : `One-Click Auto-Heal (${(auditData?.warning_count || 0) + (auditData?.degraded_count || 0)} Warnings)`}
              </span>
            </button>
          </div>

          <div className="text-[11px] text-gray-500 pt-2 border-t border-gray-800/80 flex items-center justify-between">
            <span>Regression Watcher:</span>
            <span className="text-emerald-400 font-bold flex items-center space-x-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span>Active in Background</span>
            </span>
          </div>
        </div>
      </div>

      {/* FILTER TABS & SEARCH BAR */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-[#121620] border border-gray-800 p-4 rounded-xl">
        {/* Category Pill Filters */}
        <div className="flex items-center space-x-1.5 overflow-x-auto pb-1 md:pb-0 scrollbar-none">
          {categories.map(cat => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                selectedCategory === cat
                  ? 'bg-cyan-500 text-black shadow-md shadow-cyan-500/20'
                  : 'bg-[#0c0f17] text-gray-400 hover:text-white border border-gray-800'
              }`}
            >
              {cat === 'ALL' ? `All Engines (${subsystems.length})` : cat}
            </button>
          ))}
        </div>

        {/* Search Filter */}
        <div className="relative min-w-[260px]">
          <Search className="w-4 h-4 text-gray-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchFilter}
            onChange={e => setSearchFilter(e.target.value)}
            placeholder="Search engine, metric, or status..."
            className="w-full bg-[#0b0e14] border border-gray-800 rounded-lg pl-9 pr-4 py-1.5 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-cyan-500 transition-colors"
          />
          {searchFilter && (
            <button
              onClick={() => setSearchFilter('')}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white text-xs"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* SUBSYSTEM CARDS GRID (11 ENGINES) */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {filteredSubsystems.map(sub => {
          const isHealing = Boolean(healingSubsystems[sub.id]);
          const status = sub.status || 'UNKNOWN';

          return (
            <div
              key={sub.id}
              className={`bg-[#121620] border rounded-2xl p-5 shadow-lg flex flex-col justify-between transition-all hover:border-gray-700 ${
                status === 'HEALTHY'
                  ? 'border-gray-800/90 hover:shadow-emerald-950/20'
                  : status === 'WARNING'
                  ? 'border-amber-500/40 bg-amber-950/10 hover:shadow-amber-950/20'
                  : 'border-rose-500/50 bg-rose-950/20 hover:shadow-rose-950/30'
              }`}
            >
              {/* Card Header */}
              <div>
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center space-x-3">
                    <div className="p-2.5 rounded-xl bg-[#0c0f17] border border-gray-800">
                      {getSubsystemIcon(sub.id, sub.category)}
                    </div>
                    <div>
                      <h3 className="text-sm font-bold text-white tracking-wide">{sub.name}</h3>
                      <span className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold">
                        {sub.category}
                      </span>
                    </div>
                  </div>

                  {/* Status Badge */}
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider flex items-center space-x-1 border ${
                      status === 'HEALTHY'
                        ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                        : status === 'WARNING'
                        ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                        : 'bg-rose-500/20 text-rose-400 border-rose-500/40'
                    }`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        status === 'HEALTHY'
                          ? 'bg-emerald-400'
                          : status === 'WARNING'
                          ? 'bg-amber-400 animate-pulse'
                          : 'bg-rose-400 animate-ping'
                      }`}
                    />
                    <span>{status}</span>
                  </span>
                </div>

                {/* Heartbeat & Latency Badges */}
                <div className="flex flex-wrap items-center gap-2 my-3">
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-mono font-medium bg-[#0b0e14] text-cyan-300 border border-gray-800">
                    {sub.heartbeat}
                  </span>
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-mono text-gray-400 bg-[#0b0e14] border border-gray-800">
                    ⏱️ {sub.latency_ms}ms
                  </span>
                </div>

                {/* Diagnostic Message */}
                <p className="text-xs text-gray-300 leading-relaxed bg-[#0b0e14]/60 p-3 rounded-xl border border-gray-800/80 my-3 font-normal">
                  {sub.message}
                </p>

                {/* Extra metrics badges */}
                {sub.metrics && Object.keys(sub.metrics).length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mb-4">
                    {Object.entries(sub.metrics).slice(0, 4).map(([k, v]) => (
                      <span
                        key={k}
                        className="text-[10px] px-2 py-0.5 rounded bg-gray-800/60 text-gray-400 border border-gray-700/50"
                      >
                        <span className="text-gray-500 font-mono">{k}:</span>{' '}
                        <span className="text-gray-200 font-bold">{String(v)}</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Card Footer / Self-Healing Button */}
              <div className="pt-3 border-t border-gray-800 flex items-center justify-between mt-2">
                <span className="text-[11px] text-gray-500 font-mono">ID: {sub.id}</span>
                {sub.can_heal ? (
                  <button
                    onClick={() => handleHealSubsystem(sub.id, sub.name)}
                    disabled={isHealing}
                    className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                      status === 'HEALTHY'
                        ? 'bg-[#0b0e14] hover:bg-gray-800 text-gray-300 border border-gray-700'
                        : 'bg-amber-500 hover:bg-amber-400 text-black shadow-md shadow-amber-500/20'
                    }`}
                  >
                    <Wrench className={`w-3.5 h-3.5 ${isHealing ? 'animate-spin' : ''}`} />
                    <span>{isHealing ? 'Healing...' : status === 'HEALTHY' ? 'Test Self-Heal' : 'Heal Now'}</span>
                  </button>
                ) : (
                  <span className="text-[11px] text-gray-500 italic">Continuous Auto-Check</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* DIAGNOSTIC EVENT LOG & REGRESSION FEED */}
      <div className="bg-[#121620] border border-gray-800 rounded-2xl p-6 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-2.5">
            <Terminal className="w-5 h-5 text-cyan-400" />
            <h3 className="text-base font-bold text-white tracking-wide">
              Regression Watcher & Diagnostic Audit Stream
            </h3>
          </div>
          <span className="text-xs text-gray-500">Live Circular Log (Last 20 Events)</span>
        </div>

        {eventLogs.length === 0 ? (
          <div className="p-8 text-center text-gray-500 text-xs">
            No integrity events or regressions recorded yet. Run a Deep Probe to generate logs.
          </div>
        ) : (
          <div className="space-y-2 max-h-[360px] overflow-y-auto pr-2 scrollbar-thin">
            {eventLogs.map((evt, idx) => (
              <div
                key={evt.id || idx}
                className={`p-3 rounded-xl border text-xs font-mono flex items-start space-x-3 transition-colors ${
                  evt.level === 'ERROR'
                    ? 'bg-rose-950/20 border-rose-500/30 text-rose-200'
                    : evt.level === 'WARNING'
                    ? 'bg-amber-950/20 border-amber-500/30 text-amber-200'
                    : evt.level === 'SUCCESS'
                    ? 'bg-emerald-950/20 border-emerald-500/30 text-emerald-200'
                    : 'bg-[#0b0e14] border-gray-800/80 text-gray-300'
                }`}
              >
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase shrink-0 ${
                    evt.level === 'ERROR'
                      ? 'bg-rose-500/20 text-rose-400 border border-rose-500/40'
                      : evt.level === 'WARNING'
                      ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40'
                      : evt.level === 'SUCCESS'
                      ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                      : 'bg-gray-800 text-gray-400'
                  }`}
                >
                  {evt.level}
                </span>

                <div className="flex-1">
                  <div className="flex items-center justify-between text-[11px] text-gray-500 mb-1">
                    <span className="font-semibold text-gray-300">[{evt.engine_id}]</span>
                    <span>{evt.dual_time || evt.timestamp}</span>
                  </div>
                  <div className="text-gray-200 leading-normal">{evt.message}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
