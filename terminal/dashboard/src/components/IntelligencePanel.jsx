export default function IntelligencePanel({ data }) {
  const intel = data?.intelligence || {};
  const blockers = intel.blockers || {};
  const pressure = intel.edge_pressure || {};
  const expectation = intel.expectation_match || {};
  const anomalies = intel.anomalies || [];
  const intent = intel.intent || {};
  const failure = intel.failure_mode || {};

  const pressureEmoji = { CRITICAL: '🔴', HIGH: '🔥', MODERATE: '🟡', LOW: '🟢' }[pressure.level] || '⚪';
  const pressureColor = { CRITICAL: '#ef4444', HIGH: '#f97316', MODERATE: '#f59e0b', LOW: '#22c55e' }[pressure.level] || '#64748b';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

      {/* Row 1: Blockers + Edge Pressure + System Intent */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>

        {/* BLOCKERS */}
        <div className="glass-card" style={{ padding: '16px 18px' }}>
          <Label>WHY NOT WINNING YET</Label>
          <div style={{ fontSize: '0.8rem', color: '#e2e8f0', fontWeight: 600, marginBottom: '8px' }}>
            {blockers.primary_constraint || 'Unknown'}
          </div>
          {(blockers.breakdown || []).slice(0, 4).map((b, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: '#64748b', marginBottom: '3px' }}>
              <span>{b.reason?.replace(/_/g, ' ')}</span>
              <span style={{ color: '#8892a8', fontWeight: 600 }}>{b.pct}%</span>
            </div>
          ))}
        </div>

        {/* EDGE PRESSURE */}
        <div className="glass-card" style={{ padding: '16px 18px' }}>
          <Label>EDGE PRESSURE</Label>
          <div style={{ fontSize: '1.3rem', fontWeight: 800, color: pressureColor, marginBottom: '8px' }}>
            {pressureEmoji} {pressure.level || '?'}
          </div>
          {(pressure.signals || []).map((s, i) => (
            <div key={i} style={{ fontSize: '0.7rem', color: '#64748b', marginBottom: '3px' }}>• {s}</div>
          ))}
          <div style={{ fontSize: '0.65rem', color: '#475569', marginTop: '6px', fontStyle: 'italic' }}>
            {pressure.level === 'CRITICAL' ? 'System compressing toward phase transition' :
             pressure.level === 'HIGH' ? 'Pressure building — expansion approaching' :
             'Normal exploration pressure'}
          </div>
        </div>

        {/* SYSTEM INTENT */}
        <div className="glass-card" style={{ padding: '16px 18px' }}>
          <Label>SYSTEM INTENT</Label>
          <div style={{ marginBottom: '6px' }}>
            <MiniLabel color="#6366f1">GOAL</MiniLabel>
            <div style={{ fontSize: '0.8rem', color: '#e2e8f0', fontWeight: 600 }}>{intent.goal || '?'}</div>
          </div>
          <div style={{ marginBottom: '6px' }}>
            <MiniLabel color="#06b6d4">STRATEGY</MiniLabel>
            <div style={{ fontSize: '0.72rem', color: '#8892a8' }}>{intent.strategy || '?'}</div>
          </div>
          <div>
            <MiniLabel color="#22c55e">NEXT OBJECTIVE</MiniLabel>
            <div style={{ fontSize: '0.72rem', color: '#8892a8' }}>{intent.next_objective || '?'}</div>
          </div>
        </div>
      </div>

      {/* Row 2: Expectation Match + Anomalies + Failure Mode */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>

        {/* EXPECTATION VS ACTUAL */}
        <div className="glass-card" style={{ padding: '16px 18px' }}>
          <Label>EXPECTATION VS REALITY</Label>
          <div style={{
            fontSize: '0.85rem', fontWeight: 700, marginBottom: '8px',
            color: expectation.all_match ? '#22c55e' : '#ef4444',
          }}>
            {expectation.all_match ? '✅ ALL MATCH' : '⚠️ MISMATCH DETECTED'}
          </div>
          {(expectation.expectations || []).map((e, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.7rem', marginBottom: '4px' }}>
              <span style={{ color: e.match ? '#22c55e' : '#ef4444', fontWeight: 700 }}>
                {e.match ? '✅' : '❌'}
              </span>
              <span style={{ color: '#8892a8' }}>{e.metric}:</span>
              <span style={{ color: '#64748b' }}>expected {e.expected}</span>
              <span style={{ color: '#475569' }}>→</span>
              <span style={{ color: e.match ? '#22c55e' : '#ef4444', fontWeight: 600 }}>{e.actual}</span>
            </div>
          ))}
        </div>

        {/* ANOMALY DETECTION */}
        <div className="glass-card" style={{ padding: '16px 18px' }}>
          <Label>ANOMALY DETECTION</Label>
          {anomalies.length === 0 ? (
            <div style={{ fontSize: '0.85rem', color: '#22c55e', fontWeight: 600 }}>
              ✅ None detected
            </div>
          ) : (
            anomalies.slice(0, 5).map((a, i) => (
              <div key={i} style={{
                fontSize: '0.7rem', marginBottom: '4px', padding: '4px 8px', borderRadius: '6px',
                background: a.severity === 'critical' ? 'rgba(239,68,68,0.08)' : 'rgba(245,158,11,0.06)',
                color: a.severity === 'critical' ? '#ef4444' : '#f59e0b',
              }}>
                ⚠️ {a.detail}
              </div>
            ))
          )}
          <div style={{ fontSize: '0.6rem', color: '#334155', marginTop: '6px', fontStyle: 'italic' }}>
            Monitors: impossible WR, extreme Sharpe, stale state, strategy clustering
          </div>
        </div>

        {/* FAILURE MODE */}
        <div className="glass-card" style={{ padding: '16px 18px' }}>
          <Label>FAILURE MODE</Label>
          <div style={{
            fontSize: '0.95rem', fontWeight: 700, marginBottom: '4px',
            color: failure.mode === 'NONE' ? '#22c55e' : '#f59e0b',
          }}>
            {failure.mode || 'UNKNOWN'}
          </div>
          <div style={{ display: 'flex', gap: '12px', marginBottom: '6px' }}>
            <div>
              <MiniLabel color="#64748b">TYPE</MiniLabel>
              <div style={{ fontSize: '0.7rem', color: '#8892a8' }}>{failure.type || '?'}</div>
            </div>
            <div>
              <MiniLabel color="#64748b">SEVERITY</MiniLabel>
              <div style={{ fontSize: '0.7rem', color: failure.severity === 'Expected' ? '#22c55e' : '#f59e0b' }}>
                {failure.severity || '?'}
              </div>
            </div>
          </div>
          <div style={{ fontSize: '0.7rem', color: '#64748b', lineHeight: 1.5 }}>
            {failure.explanation || ''}
          </div>
        </div>
      </div>
    </div>
  );
}

function Label({ children }) {
  return (
    <div style={{
      fontSize: '0.55rem', color: '#475569', fontWeight: 700,
      letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '8px',
    }}>
      {children}
    </div>
  );
}

function MiniLabel({ children, color = '#475569' }) {
  return (
    <div style={{
      fontSize: '0.5rem', color, fontWeight: 700,
      letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: '2px',
    }}>
      {children}
    </div>
  );
}
