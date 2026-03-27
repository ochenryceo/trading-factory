export default function BlockersPanel({ data }) {
  const blockers = data?.intelligence?.blockers || {};
  const breakdown = blockers.breakdown || [];

  return (
    <div className="glass-card" style={{ padding: '14px 16px' }}>
      <div style={{ fontSize: '0.5rem', color: '#475569', fontWeight: 700, letterSpacing: '0.15em', marginBottom: '8px' }}>
        WHY NOT WINNING YET
      </div>

      <div style={{ fontSize: '0.8rem', color: '#e2e8f0', fontWeight: 600, marginBottom: '10px', lineHeight: 1.4 }}>
        {blockers.primary_constraint || 'Analyzing...'}
      </div>

      {breakdown.map((b, i) => (
        <div key={i} style={{ marginBottom: '6px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px' }}>
            <span style={{ fontSize: '0.65rem', color: '#8892a8' }}>{b.reason?.replace(/_/g, ' ')}</span>
            <span style={{ fontSize: '0.65rem', color: '#94a3b8', fontWeight: 700 }}>{b.pct}%</span>
          </div>
          <div style={{ height: '4px', borderRadius: '2px', background: 'rgba(255,255,255,0.04)', overflow: 'hidden' }}>
            <div style={{
              height: '100%', borderRadius: '2px',
              width: `${Math.min(100, b.pct)}%`,
              background: i === 0 ? '#ef4444' : i === 1 ? '#f59e0b' : '#6366f1',
              transition: 'width 0.5s ease',
            }} />
          </div>
        </div>
      ))}

      <div style={{
        marginTop: '10px', fontSize: '0.6rem', color: '#475569',
        fontStyle: 'italic', borderTop: '1px solid rgba(255,255,255,0.03)',
        paddingTop: '8px', lineHeight: 1.5,
      }}>
        {breakdown.length > 0 && breakdown[0].reason === 'sanity_filter'
          ? 'Strategies exist but hit reality boundaries → expansion needed'
          : 'System evaluating — patterns emerging'
        }
      </div>
    </div>
  );
}
