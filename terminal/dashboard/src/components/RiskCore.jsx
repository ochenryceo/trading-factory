export default function RiskCore({ data }) {
  const intel = data?.intelligence || {};
  const anomalies = intel.anomalies || [];
  const failure = intel.failure_mode || {};
  const pressure = intel.edge_pressure || {};

  const riskLevel = pressure.level === 'CRITICAL' ? 'HIGH' : pressure.level === 'HIGH' ? 'MODERATE' : 'LOW';
  const riskColor = riskLevel === 'HIGH' ? '#ef4444' : riskLevel === 'MODERATE' ? '#f59e0b' : '#22c55e';
  const riskEmoji = riskLevel === 'HIGH' ? '🔴' : riskLevel === 'MODERATE' ? '🟡' : '🟢';

  return (
    <div className="glass-card" style={{ padding: '16px 14px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontSize: '0.5rem', color: '#475569', fontWeight: 700, letterSpacing: '0.15em', marginBottom: '10px' }}>
        RISK CORE
      </div>

      {/* Risk level */}
      <div style={{ textAlign: 'center', marginBottom: '14px' }}>
        <div style={{ fontSize: '1.6rem', fontWeight: 800, color: riskColor }}>
          {riskEmoji} {riskLevel}
        </div>
        <div style={{ fontSize: '0.6rem', color: '#475569', marginTop: '2px' }}>SYSTEM RISK</div>
      </div>

      {/* Risk breakdown */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '12px' }}>
        <RiskLine label="Execution" value="NONE" color="#22c55e" />
        <RiskLine label="Data" value="NONE" color="#22c55e" />
        <RiskLine label="Anomaly" value={anomalies.length === 0 ? 'CLEAR' : `${anomalies.length} DETECTED`} color={anomalies.length === 0 ? '#22c55e' : '#ef4444'} />
      </div>

      {/* Failure mode */}
      <div style={{
        padding: '10px 12px', borderRadius: '8px',
        background: failure.mode === 'NONE' ? 'rgba(34,197,94,0.05)' : 'rgba(245,158,11,0.06)',
        border: `1px solid ${failure.mode === 'NONE' ? 'rgba(34,197,94,0.1)' : 'rgba(245,158,11,0.12)'}`,
      }}>
        <div style={{ fontSize: '0.45rem', color: '#475569', fontWeight: 700, letterSpacing: '0.12em', marginBottom: '3px' }}>FAILURE MODE</div>
        <div style={{
          fontSize: '0.75rem', fontWeight: 700,
          color: failure.mode === 'NONE' ? '#22c55e' : '#f59e0b',
          marginBottom: '3px',
        }}>
          {failure.mode || 'NONE'}
        </div>
        {failure.severity && failure.mode !== 'NONE' && (
          <div style={{ fontSize: '0.6rem', color: '#22c55e' }}>Severity: {failure.severity}</div>
        )}
        <div style={{ fontSize: '0.6rem', color: '#64748b', marginTop: '4px', lineHeight: 1.4 }}>
          {failure.explanation || 'System nominal'}
        </div>
      </div>

      {/* Anomalies */}
      {anomalies.length > 0 && (
        <div style={{ marginTop: '8px' }}>
          {anomalies.slice(0, 3).map((a, i) => (
            <div key={i} style={{
              fontSize: '0.6rem', padding: '4px 6px', borderRadius: '4px', marginBottom: '3px',
              background: 'rgba(239,68,68,0.06)', color: '#ef4444',
            }}>
              ⚠️ {a.detail}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RiskLine({ label, value, color }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <span style={{ fontSize: '0.6rem', color: '#475569' }}>{label}</span>
      <span style={{ fontSize: '0.6rem', fontWeight: 700, color }}>{value}</span>
    </div>
  );
}
