import React from 'react';
import { Activity, RefreshCw, Sparkles, AlertTriangle, ShieldOff, Zap } from 'lucide-react';

const DerivativesSpeedometer = ({
  data,
  loading,
  loadingGrokNews,
  onRefresh,
  onUpdateGrok,
  onFocusConnect
}) => {
  const isConnected = data && data.zerodha_connected !== false;

  if (!isConnected) {
    return (
      <div className="derivatives-analyst-card disconnected-card">
        <div className="derivatives-card-header">
          <div className="derivatives-title">
            <Activity size={18} className="title-icon" />
            <span>NSE Derivatives Analyst Speedometer</span>
            <span className="badge-grok-ai rule-based disconnected-badge">
              <ShieldOff size={12} /> Zerodha API Disconnected
            </span>
          </div>
        </div>

        <div className="zerodha-disconnected-overlay">
          <div className="disconnected-icon-wrap">
            <AlertTriangle size={36} className="warning-icon" />
          </div>
          <h3 className="disconnected-heading">Zerodha API Not Connected</h3>
          <p className="disconnected-text">
            Live options chain analysis, PCR ratios, and the market speedometer require an active Zerodha session.
            Please connect your Zerodha account via 6-digit TOTP login.
          </p>
          <button 
            className="btn-zerodha-connect-prompt"
            onClick={onFocusConnect}
          >
            <Zap size={15} />
            <span>Connect to Zerodha API</span>
          </button>
        </div>
      </div>
    );
  }

  const sentimentScore = data.sentiment_score ?? 0;
  const needleAngle = data.needle_angle ?? 0; // -90deg to +90deg
  const dayVerdict = data.day_verdict || "NEUTRAL DAY ⚖️";
  
  let verdictClass = "neutral";
  if (sentimentScore >= 25) verdictClass = "bull";
  else if (sentimentScore <= -25) verdictClass = "bear";

  return (
    <div className="derivatives-analyst-card">
      {/* Header Bar */}
      <div className="derivatives-card-header">
        <div className="derivatives-title">
          <Activity size={18} className="title-icon" />
          <span>NSE Derivatives Analyst</span>
          <span className="live-zerodha-indicator" title="Connected to Zerodha API • Refreshing every 5 mins (Low Server Pressure)">
            <span className="pulse-dot"></span> Live Zerodha (5m Auto Sync)
          </span>
          {data?.used_grok && data?.grok_cached && (
            <span className="badge-grok-ai cached" title="Using cached Grok AI news & analysis. Click 'Update News via Grok AI' to refresh.">
              Grok AI (Cached {data.last_updated_time || ''})
            </span>
          )}
          {data?.used_grok && !data?.grok_cached && (
            <span className="badge-grok-ai live" title="Fresh Grok AI news & directional analysis fetched!">
              Grok AI (Live {data.last_updated_time || ''})
            </span>
          )}
          {!data?.used_grok && (
            <span className="badge-grok-ai rule-based" title="Fast rule-based bias used. Grok API not called to preserve tokens.">
              Rule-Based (0 Grok Tokens Used)
            </span>
          )}
        </div>

        <div className="derivatives-actions">
          <button 
            className="btn-refresh-derivatives" 
            onClick={() => onRefresh(false)}
            disabled={loading || loadingGrokNews}
            title="Refreshes live Zerodha spot, GIFT Nifty, PCR, VIX, and strikes without calling Grok AI (0 tokens)"
          >
            <RefreshCw size={14} className={loading ? "spin" : ""} />
            <span>{loading ? "Refreshing..." : "Refresh Live Data"}</span>
          </button>
          <button 
            className="btn-update-grok-news" 
            onClick={() => onUpdateGrok(true)}
            disabled={loading || loadingGrokNews}
            title="Manually query Grok AI to fetch latest news & re-evaluate directional bias (Uses Grok Tokens)"
          >
            <Sparkles size={14} className={loadingGrokNews ? "spin" : ""} />
            <span>{loadingGrokNews ? "Asking Grok AI..." : "Update News via Grok AI"}</span>
          </button>
        </div>
      </div>

      {/* Speedometer Gauge Body */}
      <div className="speedometer-gauge-wrapper">
        <div className="speedometer-svg-container">
          <svg viewBox="0 0 200 120" className="speedometer-svg">
            <defs>
              <linearGradient id="bearGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#f43f5e" />
                <stop offset="100%" stopColor="#e11d48" />
              </linearGradient>
              <linearGradient id="neutralGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#f59e0b" />
                <stop offset="100%" stopColor="#d97706" />
              </linearGradient>
              <linearGradient id="bullGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#10b981" />
                <stop offset="100%" stopColor="#059669" />
              </linearGradient>
            </defs>

            {/* Bear Zone Arc (-90deg to -22.5deg) */}
            <path
              d="M 20 100 A 80 80 0 0 1 43.4 43.4"
              fill="none"
              stroke="url(#bearGrad)"
              strokeWidth="16"
              strokeLinecap="round"
            />
            {/* Neutral Zone Arc (-22.5deg to +22.5deg) */}
            <path
              d="M 43.4 43.4 A 80 80 0 0 1 156.6 43.4"
              fill="none"
              stroke="url(#neutralGrad)"
              strokeWidth="16"
            />
            {/* Bull Zone Arc (+22.5deg to +90deg) */}
            <path
              d="M 156.6 43.4 A 80 80 0 0 1 180 100"
              fill="none"
              stroke="url(#bullGrad)"
              strokeWidth="16"
              strokeLinecap="round"
            />

            {/* Scale Labels */}
            <text x="18" y="116" className="gauge-label bear-label">BEAR</text>
            <text x="100" y="24" className="gauge-label neutral-label" textAnchor="middle">NEUTRAL</text>
            <text x="182" y="116" className="gauge-label bull-label" textAnchor="end">BULL</text>

            {/* Rotating Dial Needle */}
            <g transform={`translate(100, 100) rotate(${needleAngle})`} className="needle-group">
              <polygon points="-3,-5 0,-78 3,-5" fill="#f8fafc" />
              <polygon points="-1.5,-5 0,-78 1.5,-5" fill="#38bdf8" />
              <circle cx="0" cy="0" r="8" fill="#38bdf8" />
              <circle cx="0" cy="0" r="4" fill="#0f172a" />
            </g>
          </svg>
        </div>

        {/* Verdict Display */}
        <div className={`speedometer-verdict-box ${verdictClass}`}>
          <div className="verdict-tag font-bold">DAY PREDICTION</div>
          <div className="verdict-title">{dayVerdict}</div>
          <div className="sentiment-score-badge">
            Score: <span className="score-val">{sentimentScore > 0 ? `+${sentimentScore}` : sentimentScore}</span> / 100
          </div>
        </div>
      </div>

      {/* Metrics Bar */}
      <div className="derivatives-metrics-bar">
        <div className="metric-pill">
          <span className="label">Nifty Spot</span>
          <span className="val">{data.nifty_spot?.toLocaleString()}</span>
        </div>
        <div className="metric-pill">
          <span className="label">GIFT Nifty</span>
          <span className="val">{data.gift_nifty?.toLocaleString()}</span>
        </div>
        <div className="metric-pill">
          <span className="label">Put-Call Ratio (PCR)</span>
          <span className="val">{data.pcr}</span>
        </div>
        <div className="metric-pill">
          <span className="label">India VIX</span>
          <span className="val">{data.india_vix}</span>
        </div>
        <div className="metric-pill">
          <span className="label">Max Call Strike (Resistance)</span>
          <span className="val text-danger">{data.max_call_strike?.toLocaleString()}</span>
        </div>
        <div className="metric-pill">
          <span className="label">Max Put Strike (Support)</span>
          <span className="val text-success">{data.max_put_strike?.toLocaleString()}</span>
        </div>
      </div>

      {/* Commentary Box */}
      {data.analysis_output && (
        <div className="derivatives-output-box">
          <pre className="derivatives-output-text">{data.analysis_output}</pre>
        </div>
      )}
    </div>
  );
};

export default DerivativesSpeedometer;
