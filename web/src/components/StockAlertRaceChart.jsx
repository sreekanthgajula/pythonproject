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

  const getStockChangePct = (stock) => {
    if (activeMode === 'today') {
      return stock.daily_change_pct !== undefined ? stock.daily_change_pct : (stock.positive_change_pct || 0);
    } else if (activeMode === 'past_week') {
      return stock.weekly_change_pct !== undefined ? stock.weekly_change_pct : (stock.positive_change_pct || 0);
    } else {
      return stock.monthly_change_pct !== undefined ? stock.monthly_change_pct : (stock.positive_change_pct || stock.weekly_change_pct || 0);
    }
  };

  const getTimeframeLabel = () => {
    if (activeMode === 'today') return 'Daily';
    if (activeMode === 'past_week') return 'Weekly';
    return 'Monthly';
  };

  // Filter & sort race standings strictly based on positive percentage change in selected timeframe
  const modeFilteredRace = raceData
    .map(item => ({
      ...item,
      pctGain: getStockChangePct(item)
    }))
    .filter(item => item.pctGain > 0)
    .sort((a, b) => b.pctGain - a.pctGain)
    .map((item, idx) => ({ ...item, rank: idx + 1 }));

  const filteredRace = modeFilteredRace.filter(item => {
    const sym = item.symbol || '';
    const reason = item.reason || '';
    const query = searchQuery.toLowerCase().trim();
    return sym.toLowerCase().includes(query) || reason.toLowerCase().includes(query);
  });

  const top1 = modeFilteredRace[0];
  const top2 = modeFilteredRace[1];
  const top3 = modeFilteredRace[2];

  const maxGain = Math.max(...modeFilteredRace.map(d => d.pctGain), 1);

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
                  ? "🏎️ Today's Positive % Change Grand Prix"
                  : activeMode === 'past_week'
                  ? "📈 Week's Positive % Change Grand Prix"
                  : "🏆 Monthly Positive % Change Grand Prix"}
              </h2>
              <p>
                {activeMode === 'today'
                  ? "Live Stock Race Ranked Strictly by Today's Positive % Price Gain (>0% Daily Growth)"
                  : activeMode === 'past_week'
                  ? "Live Stock Race Ranked Strictly by Past Week's Positive % Price Gain (>0% 7-Day Growth)"
                  : "Live Stock Race Ranked Strictly by Monthly / Timeframe Positive % Price Gain (>0% Growth)"}
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
                <span>Daily</span>
              </button>

              <button
                className={`race-mode-pill ${activeMode === 'past_week' ? 'active' : ''}`}
                onClick={() => setActiveMode('past_week')}
              >
                <TrendingUp size={13} />
                <span>Weekly</span>
              </button>

              <button
                className={`race-mode-pill ${activeMode === 'all' ? 'active' : ''}`}
                onClick={() => setActiveMode('all')}
              >
                <Trophy size={13} />
                <span>Monthly</span>
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
                <span className="weekly-gain-badge pos">
                  📈 +{top2.pctGain.toFixed(2)}% ({getTimeframeLabel()})
                </span>
              </div>
              <div className="podium-flame-box silver-flame">
                <Flame size={18} />
                <span>+{top2.pctGain.toFixed(2)}% {getTimeframeLabel()} Gain</span>
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
                <span className="weekly-gain-badge pos">
                  📈 +{top1.pctGain.toFixed(2)}% ({getTimeframeLabel()})
                </span>
              </div>
              <div className="podium-flame-box gold-flame">
                <Flame size={22} />
                <span>+{top1.pctGain.toFixed(2)}% {getTimeframeLabel()} Gain</span>
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
                <span className="weekly-gain-badge pos">
                  📈 +{top3.pctGain.toFixed(2)}% ({getTimeframeLabel()})
                </span>
              </div>
              <div className="podium-flame-box bronze-flame">
                <Flame size={18} />
                <span>+{top3.pctGain.toFixed(2)}% {getTimeframeLabel()} Gain</span>
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
            {`🏎️ ${getTimeframeLabel()}'s Stock Race Standings (>0% ${getTimeframeLabel()} Positive Gain)`}
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
              {`No Stocks with Positive % Price Gain in ${getTimeframeLabel()} Timeframe`}
            </h3>
            <p>
              {`Stocks that did not record positive price growth (>0%) in the ${getTimeframeLabel().toLowerCase()} timeframe are excluded from the race.`}
            </p>
          </div>
        ) : (
          <div className="race-bar-list">
            {filteredRace.map((stock) => {
              const barPercent = Math.max(8, Math.min(100, (stock.pctGain / maxGain) * 100));
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
                      <span className="weekly-gain-badge pos">
                        📈 +{stock.pctGain.toFixed(2)}% ({getTimeframeLabel()})
                      </span>
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
                          +{stock.pctGain.toFixed(2)}% {getTimeframeLabel()} Growth
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="race-flame-cell">
                    <div className="race-flame-badge active-flame">
                      <TrendingUp size={16} />
                      <span>+{stock.pctGain.toFixed(2)}%</span>
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
