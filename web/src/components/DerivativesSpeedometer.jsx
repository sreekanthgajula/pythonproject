import React from 'react';
import { Activity, RefreshCw, Sparkles, AlertTriangle, ShieldOff, Zap } from 'lucide-react';

const SpeedometerSingleCard = ({
  title,
  timeframeBadge,
  subtitle,
  sentimentScore = 0,
  needleAngle = 0,
  verdict = "NEUTRAL ⚖️",
  gradientIdPrefix = "gauge",
  pcrLabel = "PCR",
  pcrVal = "1.0",
  resLabel = "Resistance",
  resVal = "N/A",
  supLabel = "Support",
  supVal = "N/A",
  extraBadge = null
}) => {
  let verdictClass = "neutral";
  if (sentimentScore >= 25) verdictClass = "bull";
  else if (sentimentScore <= -25) verdictClass = "bear";

  return (
    <div className="speedometer-single-card">
      <div className="gauge-card-header">
        <span className="gauge-card-title">{title}</span>
        <span className={`gauge-tf-badge ${timeframeBadge.toLowerCase()}`}>{timeframeBadge}</span>
      </div>
      <div className="gauge-card-subtitle">{subtitle}</div>

      <div className="speedometer-svg-container">
        <svg viewBox="0 0 200 120" className="speedometer-svg">
          <defs>
            <linearGradient id={`${gradientIdPrefix}_bearGrad`} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#f43f5e" />
              <stop offset="100%" stopColor="#e11d48" />
            </linearGradient>
            <linearGradient id={`${gradientIdPrefix}_neutralGrad`} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#f59e0b" />
              <stop offset="100%" stopColor="#d97706" />
            </linearGradient>
            <linearGradient id={`${gradientIdPrefix}_bullGrad`} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#10b981" />
              <stop offset="100%" stopColor="#059669" />
            </linearGradient>
          </defs>

          {/* Bear Zone Arc (-90deg to -22.5deg) */}
          <path
            d="M 20 100 A 80 80 0 0 1 43.4 43.4"
            fill="none"
            stroke={`url(#${gradientIdPrefix}_bearGrad)`}
            strokeWidth="16"
            strokeLinecap="round"
          />
          {/* Neutral Zone Arc (-22.5deg to +22.5deg) */}
          <path
            d="M 43.4 43.4 A 80 80 0 0 1 156.6 43.4"
            fill="none"
            stroke={`url(#${gradientIdPrefix}_neutralGrad)`}
            strokeWidth="16"
          />
          {/* Bull Zone Arc (+22.5deg to +90deg) */}
          <path
            d="M 156.6 43.4 A 80 80 0 0 1 180 100"
            fill="none"
            stroke={`url(#${gradientIdPrefix}_bullGrad)`}
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
        <div className="verdict-tag font-bold">{timeframeBadge} PREDICTION</div>
        <div className="verdict-title">{verdict}</div>
        <div className="sentiment-score-badge">
          Score: <span className="score-val">{sentimentScore > 0 ? `+${sentimentScore}` : sentimentScore}</span> / 100
        </div>
        {extraBadge && (
          <div className="predicted-change-badge" style={{ marginTop: '0.35rem', fontSize: '0.82rem', fontWeight: 'bold' }}>
            {extraBadge}
          </div>
        )}
      </div>

      {/* Mini Gauge Metrics */}
      <div className="gauge-mini-metrics">
        <div className="mini-metric">
          <span className="mini-lbl">{pcrLabel}</span>
          <span className="mini-val">{pcrVal}</span>
        </div>
        <div className="mini-metric">
          <span className="mini-lbl">{resLabel}</span>
          <span className="mini-val text-danger">{typeof resVal === 'number' ? resVal.toLocaleString() : resVal}</span>
        </div>
        <div className="mini-metric">
          <span className="mini-lbl">{supLabel}</span>
          <span className="mini-val text-success">{typeof supVal === 'number' ? supVal.toLocaleString() : supVal}</span>
        </div>
      </div>
    </div>
  );
};

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
            Live options chain analysis, PCR ratios, and market speedometers require an active Zerodha session.
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

  // Daily Metrics
  const dailyScore = data?.sentiment_score ?? 0;
  const dailyNeedle = data?.needle_angle ?? 0;
  const dailyVerdict = data?.day_verdict || "NEUTRAL DAY ⚖️";
  const dailyChange = data?.daily?.change_pct ?? data?.day_change_pct;

  // Weekly Metrics (Decoupled 1-Week Trend)
  const weeklyData = data?.weekly || {};
  const weeklyScore = weeklyData.sentiment_score ?? 0;
  const weeklyNeedle = weeklyData.needle_angle ?? 0;
  const weeklyVerdict = weeklyData.verdict || (weeklyScore >= 25 ? "BULL WEEK 🐂" : weeklyScore <= -25 ? "BEAR WEEK 🐻" : "NEUTRAL WEEK ⚖️");
  const weeklyPcr = weeklyData.pcr ?? 1.0;
  const weeklyCall = weeklyData.max_call_strike || "N/A";
  const weeklyPut = weeklyData.max_put_strike || "N/A";
  const weeklyChange = weeklyData.change_pct;
  const above20Ema = weeklyData.above_20_ema ?? (weeklyScore >= 0);

  // Monthly Metrics (Decoupled 1-Month Macro)
  const monthlyData = data?.monthly || {};
  const monthlyScore = monthlyData.sentiment_score ?? 0;
  const monthlyNeedle = monthlyData.needle_angle ?? 0;
  const monthlyVerdict = monthlyData.verdict || (monthlyScore >= 25 ? "BULL MONTH 🐂" : monthlyScore <= -25 ? "BEAR MONTH 🐻" : "NEUTRAL MONTH ⚖️");
  const monthlyPcr = monthlyData.pcr ?? 1.0;
  const monthlyCall = monthlyData.max_call_strike || "N/A";
  const monthlyPut = monthlyData.max_put_strike || "N/A";
  const monthlyChange = monthlyData.change_pct;
  const above50Sma = monthlyData.above_50_sma ?? (monthlyScore >= 0);
  const above200Sma = monthlyData.above_200_sma ?? (monthlyScore >= 0);

  return (
    <div className="derivatives-analyst-card">
      {/* Header Bar */}
      <div className="derivatives-card-header">
        <div className="derivatives-title">
          <Activity size={18} className="title-icon" />
          <span>NSE Market Trend Speedometers</span>
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

      {/* 3-Column Side-by-Side Speedometer Grid */}
      <div className="speedometer-triple-grid">
        {/* Daily Speedometer */}
        <SpeedometerSingleCard
          title="Daily Swing"
          timeframeBadge="Daily"
          subtitle="Intraday & Day Bias"
          sentimentScore={dailyScore}
          needleAngle={dailyNeedle}
          verdict={dailyVerdict}
          gradientIdPrefix="daily"
          pcrLabel="Day PCR"
          pcrVal={data?.pcr || 1.0}
          resLabel="Day Res"
          resVal={data?.max_call_strike || "N/A"}
          supLabel="Day Sup"
          supVal={data?.max_put_strike || "N/A"}
          extraBadge={
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', alignItems: 'center' }}>
              {dailyChange !== undefined && (
                <span>1-D Return: <strong style={{ color: dailyChange >= 0 ? '#10b981' : '#f43f5e' }}>{dailyChange > 0 ? `+${dailyChange}%` : `${dailyChange}%`}</strong></span>
              )}
              {data?.predicted_nifty_change && (
                <span>Pred Move: <strong style={{ color: data.predicted_nifty_change.includes('+') ? '#10b981' : data.predicted_nifty_change.includes('-') ? '#f43f5e' : '#f59e0b' }}>{data.predicted_nifty_change}</strong></span>
              )}
            </div>
          }
        />

        {/* Weekly Speedometer */}
        <SpeedometerSingleCard
          title="Weekly Trend"
          timeframeBadge="Weekly"
          subtitle="1-Week Trend Bias"
          sentimentScore={weeklyScore}
          needleAngle={weeklyNeedle}
          verdict={weeklyVerdict}
          gradientIdPrefix="weekly"
          pcrLabel="Weekly PCR"
          pcrVal={weeklyPcr}
          resLabel="Wk Res"
          resVal={weeklyCall}
          supLabel="Wk Sup"
          supVal={weeklyPut}
          extraBadge={
            <span>
              {weeklyChange !== undefined ? (
                <>1-W Return: <strong style={{ color: weeklyChange >= 0 ? '#10b981' : '#f43f5e' }}>{weeklyChange > 0 ? `+${weeklyChange}%` : `${weeklyChange}%`}</strong> • </>
              ) : null}
              <span style={{ color: above20Ema ? '#10b981' : '#f43f5e' }}>{above20Ema ? 'Above 20 EMA' : 'Below 20 EMA'}</span>
            </span>
          }
        />

        {/* Monthly Speedometer */}
        <SpeedometerSingleCard
          title="Monthly Macro"
          timeframeBadge="Monthly"
          subtitle="1-Month Macro Bias"
          sentimentScore={monthlyScore}
          needleAngle={monthlyNeedle}
          verdict={monthlyVerdict}
          gradientIdPrefix="monthly"
          pcrLabel="Monthly PCR"
          pcrVal={monthlyPcr}
          resLabel="Month Res"
          resVal={monthlyCall}
          supLabel="Month Sup"
          supVal={monthlyPut}
          extraBadge={
            <span>
              {monthlyChange !== undefined ? (
                <>1-M Return: <strong style={{ color: monthlyChange >= 0 ? '#10b981' : '#f43f5e' }}>{monthlyChange > 0 ? `+${monthlyChange}%` : `${monthlyChange}%`}</strong> • </>
              ) : null}
              <span style={{ color: above50Sma ? '#10b981' : '#f43f5e' }}>{above50Sma ? (above200Sma ? 'Above 50d/200d SMA' : 'Above 50d SMA') : 'Below 50d SMA'}</span>
            </span>
          }
        />
      </div>

      {/* Key Market Metrics Bar */}
      <div className="derivatives-metrics-bar">
        <div className="metric-pill">
          <span className="label">Nifty Spot</span>
          <span className="val">{data?.nifty_spot?.toLocaleString() || 'N/A'}</span>
        </div>
        <div className="metric-pill">
          <span className="label">GIFT Nifty</span>
          <span className="val">{data?.gift_nifty?.toLocaleString() || 'N/A'}</span>
        </div>
        {data?.predicted_nifty_change && (
          <div className="metric-pill">
            <span className="label">Predicted % Change</span>
            <span className={`val ${data.predicted_nifty_change.includes('+') ? 'text-success' : data.predicted_nifty_change.includes('-') ? 'text-danger' : ''}`}>
              {data.predicted_nifty_change}
            </span>
          </div>
        )}
        <div className="metric-pill">
          <span className="label">Put-Call Ratio (PCR)</span>
          <span className="val">{data?.pcr || '1.0'}</span>
        </div>
        <div className="metric-pill">
          <span className="label">India VIX</span>
          <span className="val">{data?.india_vix || 'N/A'}</span>
        </div>
        <div className="metric-pill">
          <span className="label">Max Call Strike (Resistance)</span>
          <span className="val text-danger">{data?.max_call_strike?.toLocaleString() || 'N/A'}</span>
        </div>
        <div className="metric-pill">
          <span className="label">Max Put Strike (Support)</span>
          <span className="val text-success">{data?.max_put_strike?.toLocaleString() || 'N/A'}</span>
        </div>
      </div>

      {/* Commentary / Analysis Output Box */}
      {data?.analysis_output && (
        <div className="derivatives-output-box">
          <pre className="derivatives-output-text">{data.analysis_output}</pre>
        </div>
      )}
    </div>
  );
};

export default DerivativesSpeedometer;
