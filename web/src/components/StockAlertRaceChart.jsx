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

export default function StockAlertRaceChart({ todayOnly = false }) {
  const [raceData, setRaceData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [todayDate, setTodayDate] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [lastUpdated, setLastUpdated] = useState('');

  const fetchRaceLeaderboard = async () => {
    setLoading(true);
    try {
      const endpoint = todayOnly ? `${API_BASE_URL}/race/daily?today_only=true` : `${API_BASE_URL}/race/daily?today_only=false`;
      const res = await fetch(endpoint);
      if (res.ok) {
        const json = await res.json();
        setRaceData(json.leaderboard || []);
        setTodayDate(json.date || new Date().toISOString().slice(0, 10));
        setLastUpdated(json.timestamp_ist || new Date().toLocaleTimeString());
      }
    } catch (err) {
      console.error('Error fetching race leaderboard:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRaceLeaderboard();
    const interval = setInterval(fetchRaceLeaderboard, 10000);
    return () => clearInterval(interval);
  }, [todayOnly]);

  const filteredRace = raceData.filter(item => {
    const sym = item.symbol || '';
    const reason = item.reason || '';
    const query = searchQuery.toLowerCase().trim();
    return sym.toLowerCase().includes(query) || reason.toLowerCase().includes(query);
  });

  const top1 = raceData[0];
  const top2 = raceData[1];
  const top3 = raceData[2];

  const maxAlerts = Math.max(...raceData.map(d => d.alert_count || 1), 1);

  const formatDate = (dateStr) => {
    if (!dateStr) return 'N/A';
    try {
      const d = new Date(dateStr);
      return d.toLocaleTimeString('en-IN', {
        timeZone: 'Asia/Kolkata',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true
      }) + ' IST';
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="race-container">
      {/* Race Header Banner */}
      <div className="race-header-card">
        <div className="race-header-main">
          <div className="race-title-group">
            <div className="race-icon-box">
              <Trophy size={28} color="#f59e0b" />
            </div>
            <div>
              <h2>{todayOnly ? "🏎️ Today's Stock Alert Grand Prix" : "🏆 All-Time Stock Alert Grand Prix"}</h2>
              <p>
                {todayOnly
                  ? "Live Race for 1% Breakout Alerts Triggered Today (Past Days & Un-triggered Stocks Discarded)"
                  : "Overall Standings Across All Tracked Candidates & Historical Triggers"}
              </p>
            </div>
          </div>
          <div className="race-actions">
            <div className="daily-reset-badge" title="Leaderboard automatically resets every day at midnight (00:00 IST)">
              <Clock size={14} color="#38bdf8" />
              <span>{todayOnly ? `Current Day Triggers [${todayDate || 'Today'}]` : `Resets Daily at 00:00 IST [${todayDate || 'Today'}]`}</span>
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
              </div>
              <div className="podium-flame-box silver-flame">
                <Flame size={18} />
                <span>{top2.alert_count} Alerts Today</span>
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
              </div>
              <div className="podium-flame-box gold-flame">
                <Flame size={22} />
                <span>{top1.alert_count} Alerts Today</span>
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
              </div>
              <div className="podium-flame-box bronze-flame">
                <Flame size={18} />
                <span>{top3.alert_count} Alerts Today</span>
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
          <h3>{todayOnly ? "🏎️ Today's Breakout Alert Race Standings" : "🏆 All-Time Alert Race Standings"}</h3>
          <span className="race-count-tag">{filteredRace.length} Contenders</span>
        </div>

        {loading && filteredRace.length === 0 ? (
          <div className="empty-state">
            <div className="loading-spinner" style={{ margin: '0 auto 1rem' }}></div>
            <h3>Calculating Live Stock Alert Race...</h3>
          </div>
        ) : filteredRace.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">🏎️</div>
            <h3>{todayOnly ? "No 1% Breakout Alerts Triggered Today Yet" : "No Candidate Stocks Found"}</h3>
            <p>
              {todayOnly
                ? "Stocks triggered on previous days and un-triggered candidates are discarded from Today's Race."
                : "Candidate stocks across all timeframes will appear here."}
            </p>
          </div>
        ) : (
          <div className="race-bar-list">
            {filteredRace.map((stock) => {
              const alertCount = stock.alert_count || 0;
              const barPercent = Math.max(8, Math.min(100, (alertCount / maxAlerts) * 100));
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
                          {alertCount > 0 ? `${alertCount} Triggers` : '0 Alerts'}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="race-flame-cell">
                    <div className={`race-flame-badge ${alertCount > 0 ? 'active-flame' : 'idle-flame'}`}>
                      <Flame size={16} />
                      <span>{alertCount}</span>
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
