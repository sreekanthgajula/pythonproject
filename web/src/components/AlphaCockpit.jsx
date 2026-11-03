import React, { useState, useEffect } from 'react';
import {
  Sparkles,
  TrendingUp,
  TrendingDown,
  Flame,
  Clock,
  ShieldCheck,
  RefreshCw,
  Zap,
  Activity,
  ArrowRight,
  Sliders,
  Layers,
  Award,
  ChevronRight,
  ExternalLink
} from 'lucide-react';
import './AlphaCockpit.css';

const API_BASE_URL = '/api';

export default function AlphaCockpit({ onNavigateTab }) {
  const [cockpitData, setCockpitData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState('');

  const fetchCockpitData = async (showLoading = false) => {
    if (showLoading) setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/alpha-cockpit`);
      if (res.ok) {
        const data = await res.json();
        setCockpitData(data);
        setLastRefreshed(new Date().toLocaleTimeString());
      }
    } catch (err) {
      console.error('Failed to load Alpha Cockpit:', err);
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  useEffect(() => {
    fetchCockpitData(true);
    const interval = setInterval(() => fetchCockpitData(false), 15000);
    return () => clearInterval(interval);
  }, []);

  const darvasList = cockpitData?.darvas_breakouts || [];
  const btstList = cockpitData?.evening_btst || [];
  const shortList = cockpitData?.morning_shorts || [];
  const raceList = cockpitData?.race_leaders || [];
  const derivatives = cockpitData?.derivatives || {};
  const integrity = cockpitData?.integrity || { score: 96.4, healthy: 10, total: 11 };

  return (
    <div className="alpha-cockpit-container">
      {/* MACRO BANNER */}
      <div className="cockpit-macro-banner">
        <div className="macro-left-group">
          <div className="cockpit-title-block">
            <div className="cockpit-icon-badge">
              <Sparkles size={22} color="#38bdf8" />
            </div>
            <div>
              <div className="cockpit-main-title">Alpha Command Cockpit</div>
              <div className="cockpit-subtitle">Live Multi-Strategy Market Radar (NSE)</div>
            </div>
          </div>

          <div className="macro-kpi-chip">
            <span className="macro-kpi-label">Nifty 50 Spot</span>
            <span className="macro-kpi-val spot">
              ₹{derivatives.nifty_spot ? derivatives.nifty_spot.toLocaleString('en-IN') : '24,200.00'}
            </span>
          </div>

          <div className="macro-kpi-chip">
            <span className="macro-kpi-label">Macro PCR</span>
            <span className="macro-kpi-val pcr">{derivatives.pcr || '1.05'}</span>
          </div>

          <div className="macro-kpi-chip">
            <span className="macro-kpi-label">Market Bias</span>
            <span className="macro-kpi-val bias">{derivatives.sentiment || 'NEUTRAL_BULLISH'}</span>
          </div>
        </div>

        <div className="macro-right-group">
          <div className="cockpit-dual-clock-box">
            <Clock size={14} color="#38bdf8" />
            <div className="clock-sub-item">
              <span>{cockpitData?.dual_time || 'Loading time...'}</span>
            </div>
          </div>

          <button
            className="btn-cockpit-refresh"
            onClick={() => fetchCockpitData(true)}
            disabled={loading}
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            <span>{loading ? 'Refreshing...' : 'Refresh'}</span>
          </button>
        </div>
      </div>

      {/* 4-QUADRANT ALPHA GRID */}
      <div className="cockpit-quadrant-grid">
        {/* QUADRANT 1: TOP DARVAS BOX BREAKOUTS */}
        <div className="cockpit-card card-darvas">
          <div>
            <div className="cockpit-card-header">
              <div className="cockpit-card-title">
                <Sliders size={18} color="#38bdf8" />
                <span>Top Darvas Box Breakouts</span>
              </div>
              <span className="cockpit-card-badge badge-darvas">Accumulation Bases</span>
            </div>

            {darvasList.length === 0 ? (
              <div className="cockpit-empty-state">No Darvas breakout candidates currently active.</div>
            ) : (
              <div className="setup-items-list">
                {darvasList.map((item, idx) => (
                  <div key={item.symbol || idx} className="setup-item-row">
                    <div className="setup-left-info">
                      <span className="setup-rank-num">#{idx + 1}</span>
                      <div>
                        <div className="setup-symbol-title">{item.symbol}</div>
                        <div className="setup-tag-line">
                          Roof: ₹{item.box_roof || item.recent_high || 0} | Rating: {item.rating || 4.2}/5
                        </div>
                      </div>
                    </div>

                    <div className="setup-metrics-cluster">
                      <div className="setup-metric-box">
                        <span className="setup-metric-lbl">Pillar Score</span>
                        <span className="setup-metric-val val-cyan">
                          {item.darvas_score ? Math.round(item.darvas_score) : 100}
                        </span>
                      </div>
                      <div className="setup-metric-box">
                        <span className="setup-metric-lbl">+1% Trigger</span>
                        <span className="setup-metric-val val-green">
                          ₹{item.alert_trigger_price || item.recent_high || 0}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="cockpit-card-footer">
            <span>Tight consolidation bases ready to explode</span>
            {onNavigateTab && (
              <button
                className="btn-setup-action"
                onClick={() => onNavigateTab('darvas')}
              >
                <span>View Darvas Table</span>
                <ChevronRight size={13} />
              </button>
            )}
          </div>
        </div>

        {/* QUADRANT 2: TOP EVENING PRO BTST PICKS */}
        <div className="cockpit-card card-btst">
          <div>
            <div className="cockpit-card-header">
              <div className="cockpit-card-title">
                <TrendingUp size={18} color="#10b981" />
                <span>Top Supertrend Pro (BTST)</span>
              </div>
              <span className="cockpit-card-badge badge-btst">3:15 PM Institutional Surge</span>
            </div>

            {btstList.length === 0 ? (
              <div className="cockpit-empty-state">No evening institutional surges recorded yet today.</div>
            ) : (
              <div className="setup-items-list">
                {btstList.map((item, idx) => (
                  <div key={item.symbol || idx} className="setup-item-row">
                    <div className="setup-left-info">
                      <span className="setup-rank-num">#{idx + 1}</span>
                      <div>
                        <div className="setup-symbol-title">{item.symbol}</div>
                        <div className="setup-tag-line">
                          Closing @ High: {item.day_range_close_pct || 95}% | Surge: {item.volume_surge || 2.1}x
                        </div>
                      </div>
                    </div>

                    <div className="setup-metrics-cluster">
                      <div className="setup-metric-box">
                        <span className="setup-metric-lbl">BTST Score</span>
                        <span className="setup-metric-val val-green">{item.pro_buying_score || 99}%</span>
                      </div>
                      <div className="setup-metric-box">
                        <span className="setup-metric-lbl">LTP</span>
                        <span className="setup-metric-val val-cyan">₹{item.close || 0}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="cockpit-card-footer">
            <span>High closing strength with overnight gap-up bias</span>
            {onNavigateTab && (
              <button
                className="btn-setup-action"
                onClick={() => onNavigateTab('evening_pro')}
              >
                <span>View BTST Scanner</span>
                <ChevronRight size={13} />
              </button>
            )}
          </div>
        </div>

        {/* QUADRANT 3: TOP MORNING SHORT SETUPS */}
        <div className="cockpit-card card-short">
          <div>
            <div className="cockpit-card-header">
              <div className="cockpit-card-title">
                <TrendingDown size={18} color="#f43f5e" />
                <span>Top Morning Short Candidates</span>
              </div>
              <span className="cockpit-card-badge badge-short">VWAP Reversion</span>
            </div>

            {shortList.length === 0 ? (
              <div className="cockpit-empty-state">No extended morning short candidates active right now.</div>
            ) : (
              <div className="setup-items-list">
                {shortList.map((item, idx) => (
                  <div key={item.symbol || idx} className="setup-item-row">
                    <div className="setup-left-info">
                      <span className="setup-rank-num">#{idx + 1}</span>
                      <div>
                        <div className="setup-symbol-title">{item.symbol}</div>
                        <div className="setup-tag-line">
                          VWAP: ₹{item.vwap || 0} | Dist: {item.vwap_dist_pct || 3.5}%
                        </div>
                      </div>
                    </div>

                    <div className="setup-metrics-cluster">
                      <div className="setup-metric-box">
                        <span className="setup-metric-lbl">Short Score</span>
                        <span className="setup-metric-val val-red">{item.short_score || 85}</span>
                      </div>
                      <div className="setup-metric-box">
                        <span className="setup-metric-lbl">Day High</span>
                        <span className="setup-metric-val val-amber">₹{item.day_high || item.close || 0}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="cockpit-card-footer">
            <span>Fade exhaustions after gap-ups (09:15-10:30 IST)</span>
            {onNavigateTab && (
              <button
                className="btn-setup-action"
                onClick={() => onNavigateTab('morning_short')}
              >
                <span>View Short Scanner</span>
                <ChevronRight size={13} />
              </button>
            )}
          </div>
        </div>

        {/* QUADRANT 4: TODAY'S RACE LEADERS */}
        <div className="cockpit-card card-race">
          <div>
            <div className="cockpit-card-header">
              <div className="cockpit-card-title">
                <Award size={18} color="#f59e0b" />
                <span>Today's Stock Race Podium</span>
              </div>
              <span className="cockpit-card-badge badge-race">Intraday Gainers</span>
            </div>

            {raceList.length === 0 ? (
              <div className="cockpit-empty-state">Race leaderboard sync in progress. Check back shortly.</div>
            ) : (
              <div className="setup-items-list">
                {raceList.map((item, idx) => {
                  const medal = idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : `#${idx + 1}`;
                  return (
                    <div key={item.symbol || idx} className="setup-item-row">
                      <div className="setup-left-info">
                        <span className="setup-rank-num">{medal}</span>
                        <div>
                          <div className="setup-symbol-title">{item.symbol}</div>
                          <div className="setup-tag-line">Prev Close: ₹{item.prev_close || 0}</div>
                        </div>
                      </div>

                      <div className="setup-metrics-cluster">
                        <div className="setup-metric-box">
                          <span className="setup-metric-lbl">Today Gain</span>
                          <span className="setup-metric-val val-green">
                            +{item.daily_change_pct ? item.daily_change_pct.toFixed(2) : '0.00'}%
                          </span>
                        </div>
                        <div className="setup-metric-box">
                          <span className="setup-metric-lbl">Live LTP</span>
                          <span className="setup-metric-val val-cyan">₹{item.ltp || 0}</span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="cockpit-card-footer">
            <span>Real-time returns calculated against Zerodha baseline</span>
            {onNavigateTab && (
              <button
                className="btn-setup-action"
                onClick={() => onNavigateTab('todays_race')}
              >
                <span>View Full Race</span>
                <ChevronRight size={13} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
