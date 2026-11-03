import React, { useState, useEffect } from 'react';
import {
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  RefreshCw,
  Zap,
  CheckCircle2,
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
  Search,
  Wrench,
  Terminal,
  Layers,
  Flame
} from 'lucide-react';
import './IntegrityManager.css';

const API_BASE_URL = '/api';

export default function IntegrityManager() {
  const [auditData, setAuditData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [probing, setProbing] = useState(false);
  const [healingSubsystems, setHealingSubsystems] = useState({});
  const [healingAll, setHealingAll] = useState(false);
  const [autoRefreshSecs, setAutoRefreshSecs] = useState(15);
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
        return <Server size={18} color="#10b981" />;
      case 'websocket_stream':
        return <Radio size={18} color="#38bdf8" />;
      case 'gtt_ladder':
        return <Sliders size={18} color="#818cf8" />;
      case 'swarm_debate_gate':
        return <Cpu size={18} color="#c084fc" />;
      case 'race_returns_cache':
        return <BarChart2 size={18} color="#fbbf24" />;
      case 'derivatives_engine':
        return <Activity size={18} color="#fb7185" />;
      case 'morning_short_engine':
        return <Flame size={18} color="#f97316" />;
      case 'evening_pro_engine':
        return <Sparkles size={18} color="#facc15" />;
      case 'paper_trading':
        return <Layers size={18} color="#60a5fa" />;
      case 'mongodb_persistence':
        return <Database size={18} color="#34d399" />;
      case 'telegram_alerts':
        return <Send size={18} color="#38bdf8" />;
      default:
        return <ShieldCheck size={18} color="#94a3b8" />;
    }
  };

  return (
    <div className="integrity-container">
      {/* ACTION NOTICE TOAST */}
      {actionNotice && (
        <div className={`integrity-notice ${actionNotice.type === 'success' ? 'notice-success' : 'notice-error'}`}>
          <div className="notice-content">
            {actionNotice.type === 'success' ? (
              <CheckCircle2 size={18} color="#34d399" />
            ) : (
              <AlertTriangle size={18} color="#fb7185" />
            )}
            <span>{actionNotice.text}</span>
          </div>
          <button className="notice-dismiss-btn" onClick={() => setActionNotice(null)}>
            Dismiss
          </button>
        </div>
      )}

      {/* TOP HERO METRICS & CONTROL BAR */}
      <div className="integrity-hero-grid">
        {/* CARD 1: OVERALL HEALTH GAUGE */}
        <div className="integrity-hero-card">
          <div className="card-header-row">
            <div className="card-title-group">
              <ShieldCheck size={20} color="#34d399" />
              <span>Platform Integrity Score</span>
            </div>
            <span className={`integrity-status-pill status-${overallStatus.toLowerCase()}`}>
              <span className={`pulse-dot dot-${overallStatus.toLowerCase()}`} />
              <span>{overallStatus === 'HEALTHY' ? 'All Systems Go' : overallStatus}</span>
            </span>
          </div>

          <div className="gauge-content-row">
            {/* BIG SCORE CIRCLE */}
            <div className={`gauge-circle score-${overallScore >= 90 ? 'high' : overallScore >= 75 ? 'med' : 'low'}`}>
              <span className={`gauge-score-value val-${overallStatus.toLowerCase()}`}>{overallScore}%</span>
              <span className="gauge-score-label">Health</span>
            </div>

            {/* BREAKDOWN PILLS */}
            <div className="gauge-stats-list">
              <div className="stat-item">
                <span>
                  <span className="stat-dot dot-healthy" />
                  Healthy Engines
                </span>
                <strong>
                  {auditData?.healthy_count || 0} / {auditData?.total_subsystems || 11}
                </strong>
              </div>
              <div className="stat-item">
                <span>
                  <span className="stat-dot dot-warning" />
                  Warnings / Standby
                </span>
                <strong style={{ color: '#fbbf24' }}>{auditData?.warning_count || 0}</strong>
              </div>
              <div className="stat-item">
                <span>
                  <span className="stat-dot dot-degraded" />
                  Degraded Engines
                </span>
                <strong style={{ color: '#fb7185' }}>{auditData?.degraded_count || 0}</strong>
              </div>

              {/* Progress Bar */}
              <div className="progress-track">
                <div
                  className="progress-segment seg-healthy"
                  style={{
                    width: `${((auditData?.healthy_count || 0) / (auditData?.total_subsystems || 11)) * 100}%`
                  }}
                />
                <div
                  className="progress-segment seg-warning"
                  style={{
                    width: `${((auditData?.warning_count || 0) / (auditData?.total_subsystems || 11)) * 100}%`
                  }}
                />
                <div
                  className="progress-segment seg-degraded"
                  style={{
                    width: `${((auditData?.degraded_count || 0) / (auditData?.total_subsystems || 11)) * 100}%`
                  }}
                />
              </div>
            </div>
          </div>

          <div className="card-footer-meta">
            <span>Latency: {auditData?.audit_latency_ms || 0}ms</span>
            <span>Last Audit: {auditData?.dual_time || 'Just now'}</span>
          </div>
        </div>

        {/* CARD 2: DUAL TIMEZONE & MARKET MONITOR */}
        <div className="integrity-hero-card">
          <div className="card-title-group small">
            <Clock size={14} color="#38bdf8" />
            <span>Dual Sync Clocks</span>
          </div>

          <div className="clock-box-list">
            <div className="clock-item">
              <div>
                <div className="clock-meta-label">India (IST)</div>
                <div className="clock-digits ist">{liveDualClock.ist || 'Loading...'}</div>
              </div>
              <span className="clock-tag ist-tag">NSE Window</span>
            </div>

            <div className="clock-item">
              <div>
                <div className="clock-meta-label">Sydney (AEDT)</div>
                <div className="clock-digits syd">{liveDualClock.syd || 'Loading...'}</div>
              </div>
              <span className="clock-tag syd-tag">+5.5 hrs</span>
            </div>
          </div>

          <div className="card-footer-meta">
            <span>Market Session:</span>
            <strong style={{ color: '#e2e8f0' }}>9:15 AM - 3:30 PM IST</strong>
          </div>
        </div>

        {/* CARD 3: MISSION CONTROL ACTIONS */}
        <div className="integrity-hero-card">
          <div className="card-header-row">
            <div className="card-title-group small">
              <Zap size={14} color="#f59e0b" />
              <span>Integrity Actions</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <span style={{ fontSize: '0.72rem', color: '#64748b' }}>Auto:</span>
              <select
                className="auto-refresh-select"
                value={autoRefreshSecs}
                onChange={e => setAutoRefreshSecs(Number(e.target.value))}
              >
                <option value={0}>Off</option>
                <option value={10}>10s</option>
                <option value={15}>15s</option>
                <option value={30}>30s</option>
              </select>
            </div>
          </div>

          <div className="action-buttons-group">
            {/* DEEP PROBE BUTTON */}
            <button
              className="btn-integrity-primary"
              onClick={handleDeepProbe}
              disabled={probing || loading}
            >
              <RefreshCw size={15} className={probing ? 'animate-spin' : ''} />
              <span>{probing ? 'Probing 11 Subsystems...' : 'Deep Probe All Subsystems'}</span>
            </button>

            {/* AUTO-HEAL ALL BUTTON */}
            <button
              className="btn-integrity-heal-all"
              onClick={handleHealAll}
              disabled={healingAll || ((auditData?.warning_count || 0) + (auditData?.degraded_count || 0) === 0)}
            >
              <Wrench size={15} className={healingAll ? 'animate-spin' : ''} />
              <span>
                {healingAll
                  ? 'Healing Warnings...'
                  : `One-Click Auto-Heal (${(auditData?.warning_count || 0) + (auditData?.degraded_count || 0)} Warnings)`}
              </span>
            </button>
          </div>

          <div className="card-footer-meta">
            <span>Regression Watcher:</span>
            <span style={{ color: '#34d399', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '5px' }}>
              <span className="pulse-dot dot-healthy" />
              <span>Active 60s Loop</span>
            </span>
          </div>
        </div>
      </div>

      {/* FILTER TABS & SEARCH BAR */}
      <div className="integrity-toolbar">
        {/* Category Pill Filters */}
        <div className="category-tabs-row">
          {categories.map(cat => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`category-tab-btn ${selectedCategory === cat ? 'active' : ''}`}
            >
              {cat === 'ALL' ? `All Engines (${subsystems.length})` : cat}
            </button>
          ))}
        </div>

        {/* Search Filter */}
        <div className="search-input-box">
          <Search size={14} className="search-icon-svg" />
          <input
            type="text"
            className="search-field"
            value={searchFilter}
            onChange={e => setSearchFilter(e.target.value)}
            placeholder="Search engine, metric, or status..."
          />
          {searchFilter && (
            <button className="search-clear-btn" onClick={() => setSearchFilter('')}>
              ✕
            </button>
          )}
        </div>
      </div>

      {/* SUBSYSTEM CARDS GRID (11 ENGINES) */}
      <div className="subsystems-grid">
        {filteredSubsystems.map(sub => {
          const isHealing = Boolean(healingSubsystems[sub.id]);
          const status = sub.status || 'UNKNOWN';

          return (
            <div key={sub.id} className={`subsystem-card card-${status.toLowerCase()}`}>
              {/* Card Header */}
              <div>
                <div className="subsystem-top-row">
                  <div className="subsystem-info-group">
                    <div className="subsystem-icon-wrapper">
                      {getSubsystemIcon(sub.id, sub.category)}
                    </div>
                    <div>
                      <div className="subsystem-name-label">{sub.name}</div>
                      <div className="subsystem-category-tag">{sub.category}</div>
                    </div>
                  </div>

                  {/* Status Badge */}
                  <span className={`integrity-status-pill status-${status.toLowerCase()}`}>
                    <span className={`pulse-dot dot-${status.toLowerCase()}`} />
                    <span>{status}</span>
                  </span>
                </div>

                {/* Heartbeat & Latency Badges */}
                <div className="subsystem-kpi-row">
                  <span className="kpi-chip kpi-heartbeat">{sub.heartbeat}</span>
                  <span className="kpi-chip kpi-latency">⏱️ {sub.latency_ms}ms</span>
                </div>

                {/* Diagnostic Message */}
                <div className="subsystem-desc-box">{sub.message}</div>

                {/* Extra metrics badges */}
                {sub.metrics && Object.keys(sub.metrics).length > 0 && (
                  <div className="subsystem-metrics-pills">
                    {Object.entries(sub.metrics).slice(0, 4).map(([k, v]) => (
                      <span key={k} className="metric-pill">
                        <span>{k}:</span> <strong>{String(v)}</strong>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Card Footer / Self-Healing Button */}
              <div className="subsystem-card-footer">
                <span className="subsystem-id-label">ID: {sub.id}</span>
                {sub.can_heal ? (
                  <button
                    onClick={() => handleHealSubsystem(sub.id, sub.name)}
                    disabled={isHealing}
                    className={`btn-card-heal ${status === 'HEALTHY' ? 'heal-healthy' : 'heal-warning'}`}
                  >
                    <Wrench size={12} className={isHealing ? 'animate-spin' : ''} />
                    <span>{isHealing ? 'Healing...' : status === 'HEALTHY' ? 'Test Self-Heal' : 'Heal Now'}</span>
                  </button>
                ) : (
                  <span className="auto-checked-label">Continuous Auto-Check</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* DIAGNOSTIC EVENT LOG & REGRESSION FEED */}
      <div className="integrity-events-card">
        <div className="card-header-row">
          <div className="card-title-group">
            <Terminal size={18} color="#38bdf8" />
            <span>Regression Watcher & Diagnostic Audit Stream</span>
          </div>
          <span style={{ fontSize: '0.72rem', color: '#64748b' }}>Live Circular Log (Last 20 Events)</span>
        </div>

        {eventLogs.length === 0 ? (
          <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b', fontSize: '0.8rem' }}>
            No integrity events or regressions recorded yet. Run a Deep Probe to generate logs.
          </div>
        ) : (
          <div className="events-list-container">
            {eventLogs.map((evt, idx) => {
              const level = (evt.level || 'info').toLowerCase();
              return (
                <div key={evt.id || idx} className={`event-row row-${level}`}>
                  <span className={`event-level-badge badge-${level}`}>{evt.level}</span>
                  <div className="event-body">
                    <div className="event-header-line">
                      <span className="event-engine-id">[{evt.engine_id}]</span>
                      <span>{evt.dual_time || evt.timestamp}</span>
                    </div>
                    <div className="event-message-text">{evt.message}</div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
