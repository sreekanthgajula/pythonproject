import React, { useState, useEffect } from 'react';
import {
  Trophy,
  Flame,
  Award,
  Crown,
  RefreshCw,
  Search,
  Zap,
  TrendingUp,
  Clock,
  CheckCircle2,
  ShieldAlert
} from 'lucide-react';

const API_BASE_URL = '/api';

export default function StockAlertRaceChart({ todayOnly = false, pastWeekOnly = false }) {
  const [activeMode, setActiveMode] = useState(
    pastWeekOnly ? 'past_week' : todayOnly ? 'today' : 'all'
  );
  const [raceData, setRaceData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [todayDate, setTodayDate] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [lastUpdated, setLastUpdated] = useState('');

  const cacheRef = React.useRef({});
  const activeModeRef = React.useRef(activeMode);
  activeModeRef.current = activeMode;

  useEffect(() => {
    if (pastWeekOnly) setActiveMode('past_week');
    else if (todayOnly) setActiveMode('today');
    else setActiveMode('all');
  }, [todayOnly, pastWeekOnly]);

  const fetchRaceLeaderboard = async (targetMode = activeMode) => {
    // If cached result exists, serve immediately for 0ms snappy response
    if (cacheRef.current[targetMode]) {
      const cached = cacheRef.current[targetMode];
      setRaceData(cached.leaderboard || []);
      setTodayDate(cached.date || new Date().toISOString().slice(0, 10));
      setLastUpdated(cached.timestamp_ist || new Date().toLocaleTimeString());
      setLoading(false);
    } else {
      setLoading(true);
    }

    try {
      let endpoint = `${API_BASE_URL}/race/daily?today_only=false`;
      if (targetMode === 'today') {
        endpoint = `${API_BASE_URL}/race/daily?today_only=true`;
      } else if (targetMode === 'past_week') {
        endpoint = `${API_BASE_URL}/race/daily?past_week_only=true`;
      }

      const res = await fetch(endpoint);
      if (res.ok) {
        const json = await res.json();
        // Update cache
        cacheRef.current[targetMode] = json;

        // Only update active state if user is still on targetMode (prevent race conditions)
        if (activeModeRef.current === targetMode) {
          setRaceData(json.leaderboard || []);
          setTodayDate(json.date || new Date().toISOString().slice(0, 10));
          setLastUpdated(json.timestamp_ist || new Date().toLocaleTimeString());
        }
      }
    } catch (err) {
      console.error('Error fetching race leaderboard:', err);
    } finally {
      if (activeModeRef.current === targetMode) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    fetchRaceLeaderboard(activeMode);
    const interval = setInterval(() => fetchRaceLeaderboard(activeModeRef.current), 10000);
    return () => clearInterval(interval);
  }, [activeMode]);

  // Strict defensive mode filtering to guarantee consistent stock subsets per tab
  const modeFilteredRace = raceData.filter(item => {
    if (activeMode === 'today') {
      return item.is_today && (item.alert_count || 0) > 0;
    }
    if (activeMode === 'past_week') {
      return item.weekly_change_pct !== undefined && item.weekly_change_pct > 0;
    }
    return true; // All-Time
  });

  const filteredRace = modeFilteredRace.filter(item => {
    const sym = item.symbol || '';
    const reason = item.reason || '';
    const query = searchQuery.toLowerCase().trim();
    return sym.toLowerCase().includes(query) || reason.toLowerCase().includes(query);
  });

  const top1 = modeFilteredRace[0];
  const top2 = modeFilteredRace[1];
  const top3 = modeFilteredRace[2];

  const maxAlerts = Math.max(...modeFilteredRace.map(d => (activeMode === 'past_week' ? (d.weekly_change_pct || 1) : (d.alert_count || 1))), 1);

  return (
    <div className="race-container">
      {/* Race Header Banner */}
      <div className="race-header-card">
        <div className="race-header-main">
          <div className="race-title-group">
            <div className="race-icon-box">
              {activeMode === 'past_week' ? (
                <TrendingUp size={28} color="#10b981" />
              ) : (
                <Trophy size={28} color="#f59e0b" />
              )}
            </div>
            <div>
              <h2>
                {activeMode === 'today'
                  ? "🏎️ Today's Stock Alert Grand Prix"
                  : activeMode === 'past_week'
                  ? "📈 Week's Stock Alert Grand Prix"
                  : "🏆 All-Time Stock Alert Grand Prix"}
              </h2>
              <p>
                {activeMode === 'today'
                  ? "Live Race for 1% Breakout Alerts Triggered Today (Past Days & Un-triggered Stocks Discarded)"
                  : activeMode === 'past_week'
                  ? "Race Strictly Filtered to Stocks Whose Market Price INCREASED (>0%) Over the Past Week (Past 7 Days)"
                  : "Overall Standings Across All Tracked Candidates & Historical Triggers"}
              </p>
            </div>
          </div>
          <div className="race-actions">
            {/* Mode Switcher Buttons */}
            <div className="race-mode-selector">
              <button
                className={`race-mode-pill ${activeMode === 'today' ? 'active' : ''}`}
                onClick={() => setActiveMode('today')}
              >
                <Clock size={13} />
                <span>Today's</span>
              </button>

              <button
                className={`race-mode-pill ${activeMode === 'past_week' ? 'active' : ''}`}
                onClick={() => setActiveMode('past_week')}
              >
                <TrendingUp size={13} />
                <span>Week's</span>
              </button>

              <button
                className={`race-mode-pill ${activeMode === 'all' ? 'active' : ''}`}
                onClick={() => setActiveMode('all')}
              >
                <Trophy size={13} />
                <span>All-Time</span>
              </button>
            </div>

            <button
              className="btn-icon-secondary"
              onClick={fetchRaceLeaderboard}
              title="Refresh Live Race Standings"
            >
              <RefreshCw size={18} className={loading ? 'spin-anim' : ''} />
            </button>
          </div>
        </div>

        <div className="race-search-bar">
          <Search className="search-icon" size={16} />
          <input
            type="text"
            className="search-input"
            placeholder="Search stock symbol or breakout reason..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      {/* Top 3 Winner Podium Cards */}
      <div className="podium-grid">
        {/* 2ND PLACE PODIUM */}
        <div className={`podium-card silver-podium ${!top2 ? 'empty-podium' : ''}`}>
          <div className="podium-header">
            <span className="rank-badge silver-rank">#2 SILVER 🥈</span>
            <Award size={22} color="#94a3b8" />
          </div>
          {top2 ? (
            <div className="podium-body">
              <div className="podium-symbol-row">
                <span className="podium-symbol">{top2.symbol}</span>
                <span className="exchange-tag">NSE</span>
                {top2.weekly_change_pct !== undefined && top2.weekly_change_pct !== null && (
                  <span className={`weekly-gain-badge ${top2.weekly_change_pct >= 0 ? 'pos' : 'neg'}`}>
                    📈 {top2.weekly_change_pct >= 0 ? `+${top2.weekly_change_pct}%` : `${top2.weekly_change_pct}%`} 7d
                  </span>
                )}
              </div>
              <div className="podium-flame-box silver-flame">
                <Flame size={18} />
                <span>{activeMode === 'past_week' ? `+${top2.weekly_change_pct}% Past Week` : `${top2.alert_count} Alerts`}</span>
              </div>
              <div className="podium-stats">
                <div className="podium-stat">
                  <span>Recent High</span>
                  <strong>₹{(top2.recent_high || 0).toFixed(2)}</strong>
                </div>
                <div className="podium-stat">
                  <span>Trigger (+1%)</span>
                  <strong className="trigger-val">₹{(top2.alert_trigger_price || 0).toFixed(2)}</strong>
                </div>
              </div>
              <div className="podium-reason">{top2.reason}</div>
            </div>
          ) : (
            <div className="podium-empty-text">2nd Place Standing Open</div>
          )}
        </div>

        {/* 1ST PLACE PODIUM - GOLD WINNER */}
        <div className={`podium-card gold-podium ${!top1 ? 'empty-podium' : ''}`}>
          <div className="gold-crown-banner">
            <Crown size={20} color="#fbbf24" fill="#fbbf24" />
            <span>RACE LEADER</span>
          </div>
          <div className="podium-header">
            <span className="rank-badge gold-rank">#1 GOLD 🥇</span>
            <Trophy size={26} color="#fbbf24" />
          </div>
          {top1 ? (
            <div className="podium-body">
              <div className="podium-symbol-row">
                <span className="podium-symbol gold-title">{top1.symbol}</span>
                <span className="exchange-tag gold-tag">LEADER</span>
                {top1.weekly_change_pct !== undefined && top1.weekly_change_pct !== null && (
                  <span className={`weekly-gain-badge ${top1.weekly_change_pct >= 0 ? 'pos' : 'neg'}`}>
                    📈 {top1.weekly_change_pct >= 0 ? `+${top1.weekly_change_pct}%` : `${top1.weekly_change_pct}%`} 7d
                  </span>
                )}
              </div>
              <div className="podium-flame-box gold-flame">
                <Flame size={22} />
                <span>{activeMode === 'past_week' ? `+${top1.weekly_change_pct}% Past Week` : `${top1.alert_count} Alerts`}</span>
              </div>
              <div className="podium-stats">
                <div className="podium-stat">
                  <span>Recent High</span>
                  <strong>₹{(top1.recent_high || 0).toFixed(2)}</strong>
                </div>
                <div className="podium-stat">
                  <span>Trigger (+1%)</span>
                  <strong className="trigger-val">₹{(top1.alert_trigger_price || 0).toFixed(2)}</strong>
                </div>
              </div>
              <div className="podium-reason">{top1.reason}</div>
            </div>
          ) : (
            <div className="podium-empty-text">Race Leader Standing Open</div>
          )}
        </div>

        {/* 3RD PLACE PODIUM */}
        <div className={`podium-card bronze-podium ${!top3 ? 'empty-podium' : ''}`}>
          <div className="podium-header">
            <span className="rank-badge bronze-rank">#3 BRONZE 🥉</span>
            <Award size={22} color="#cd7f32" />
          </div>
          {top3 ? (
            <div className="podium-body">
              <div className="podium-symbol-row">
                <span className="podium-symbol">{top3.symbol}</span>
                <span className="exchange-tag">NSE</span>
                {top3.weekly_change_pct !== undefined && top3.weekly_change_pct !== null && (
                  <span className={`weekly-gain-badge ${top3.weekly_change_pct >= 0 ? 'pos' : 'neg'}`}>
                    📈 {top3.weekly_change_pct >= 0 ? `+${top3.weekly_change_pct}%` : `${top3.weekly_change_pct}%`} 7d
                  </span>
                )}
              </div>
              <div className="podium-flame-box bronze-flame">
                <Flame size={18} />
                <span>{activeMode === 'past_week' ? `+${top3.weekly_change_pct}% Past Week` : `${top3.alert_count} Alerts`}</span>
              </div>
              <div className="podium-stats">
                <div className="podium-stat">
                  <span>Recent High</span>
                  <strong>₹{(top3.recent_high || 0).toFixed(2)}</strong>
                </div>
                <div className="podium-stat">
                  <span>Trigger (+1%)</span>
                  <strong className="trigger-val">₹{(top3.alert_trigger_price || 0).toFixed(2)}</strong>
                </div>
              </div>
              <div className="podium-reason">{top3.reason}</div>
            </div>
          ) : (
            <div className="podium-empty-text">3rd Place Standing Open</div>
          )}
        </div>
      </div>

      {/* Horizontal Bar Chart Race Standings List */}
      <div className="table-card race-list-card">
        <div className="race-list-header">
          <h3>
            {activeMode === 'today'
              ? "🏎️ Today's Breakout Alert Race Standings"
              : activeMode === 'past_week'
              ? "📈 Week's Breakout Alert Race Standings (>0% 7-Day Growth)"
              : "🏆 All-Time Alert Race Standings"}
          </h3>
          <span className="race-count-tag">{filteredRace.length} Contenders</span>
        </div>

        {loading && filteredRace.length === 0 ? (
          <div className="empty-state">
            <div className="loading-spinner" style={{ margin: '0 auto 1rem' }}></div>
            <h3>Calculating Live Stock Alert Race...</h3>
          </div>
        ) : filteredRace.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">📈</div>
            <h3>
              {activeMode === 'today'
                ? "No 1% Breakout Alerts Triggered Today Yet"
                : activeMode === 'past_week'
                ? "No Stocks Increased in Price Over Past Week"
                : "No Candidate Stocks Found"}
            </h3>
            <p>
              {activeMode === 'past_week'
                ? "Stocks that did not increase in price over the past 7 days are filtered out from the Past Week Gainers Race."
                : activeMode === 'today'
                ? "Stocks triggered on previous days and un-triggered candidates are discarded from Today's Race."
                : "Candidate stocks across all timeframes will appear here."}
            </p>
          </div>
        ) : (
          <div className="race-bar-list">
            {filteredRace.map((stock) => {
              const alertCount = stock.alert_count || 0;
              const valForBar = activeMode === 'past_week' ? (stock.weekly_change_pct || 0) : alertCount;
              const barPercent = Math.max(8, Math.min(100, (valForBar / maxAlerts) * 100));
              const isGold = stock.rank === 1;
              const isSilver = stock.rank === 2;
              const isBronze = stock.rank === 3;

              let rankBadgeClass = 'rank-num';
              if (isGold) rankBadgeClass = 'rank-num gold-num';
              else if (isSilver) rankBadgeClass = 'rank-num silver-num';
              else if (isBronze) rankBadgeClass = 'rank-num bronze-num';

              return (
                <div key={stock.symbol} className={`race-bar-row ${isGold ? 'gold-row' : ''}`}>
                  <div className="race-rank-cell">
                    <span className={rankBadgeClass}>#{stock.rank}</span>
                  </div>

                  <div className="race-info-cell">
                    <div className="race-sym-line">
                      <span className="ticker-symbol">{stock.symbol}</span>
                      <span className="timeframe-tag">{stock.timeframe}</span>
                      {stock.weekly_change_pct !== undefined && stock.weekly_change_pct !== null && (
                        <span className={`weekly-gain-badge ${stock.weekly_change_pct >= 0 ? 'pos' : 'neg'}`}>
                          📈 {stock.weekly_change_pct >= 0 ? `+${stock.weekly_change_pct}%` : `${stock.weekly_change_pct}%`} (1-Wk)
                        </span>
                      )}
                      <span className="price-tag">High: ₹{(stock.recent_high || 0).toFixed(2)}</span>
                      <span className="trigger-tag">Trigger: ₹{(stock.alert_trigger_price || 0).toFixed(2)}</span>
                    </div>

                    {/* Progress Bar Race Animation */}
                    <div className="race-bar-track">
                      <div
                        className={`race-bar-fill ${isGold ? 'fill-gold' : isSilver ? 'fill-silver' : isBronze ? 'fill-bronze' : 'fill-standard'}`}
                        style={{ width: `${barPercent}%` }}
                      >
                        <span className="race-bar-text">
                          {activeMode === 'past_week'
                            ? `+${stock.weekly_change_pct}% Past Week Growth`
                            : alertCount > 0
                            ? `${alertCount} Triggers`
                            : '0 Alerts'}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="race-flame-cell">
                    <div className={`race-flame-badge ${alertCount > 0 || (stock.weekly_change_pct && stock.weekly_change_pct > 0) ? 'active-flame' : 'idle-flame'}`}>
                      {activeMode === 'past_week' ? <TrendingUp size={16} /> : <Flame size={16} />}
                      <span>{activeMode === 'past_week' ? `+${stock.weekly_change_pct}%` : alertCount}</span>
                    </div>
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
