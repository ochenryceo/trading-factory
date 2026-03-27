export default function ExpectationBar({ data }) {
  const exp = data?.intelligence?.expectation_match || {};
  const expectations = exp.expectations || [];
  const allMatch = exp.all_match;

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '16px',
      padding: '8px 16px', borderRadius: '8px',
      background: allMatch ? 'rgba(34,197,94,0.04)' : 'rgba(239,68,68,0.06)',
      border: `1px solid ${allMatch ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.15)'}`,
    }}>
      <div style={{ fontSize: '0.5rem', color: '#3f4a5e', fontWeight: 700, letterSpacing: '0.12em', flexShrink: 0 }}>
        EXPECTATION
      </div>
      <div style={{
        fontSize: '0.7rem', fontWeight: 700,
        color: allMatch ? '#22c55e' : '#ef4444', flexShrink: 0,
      }}>
        {allMatch ? '✅ ALL MATCH' : '⚠️ MISMATCH'}
      </div>
      {expectations.map((e, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.6rem', flexShrink: 0 }}>
          <span style={{ color: e.match ? '#22c55e' : '#ef4444' }}>{e.match ? '✅' : '❌'}</span>
          <span style={{ color: '#64748b' }}>{e.metric}:</span>
          <span style={{ color: '#475569' }}>{e.expected}</span>
          <span style={{ color: '#334155' }}>→</span>
          <span style={{ color: e.match ? '#8892a8' : '#ef4444', fontWeight: 600 }}>{e.actual}</span>
        </div>
      ))}
    </div>
  );
}
