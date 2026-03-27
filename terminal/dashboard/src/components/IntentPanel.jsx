export default function IntentPanel({ data }) {
  const intent = data?.intelligence?.intent || {};

  return (
    <div className="glass-card" style={{ padding: '16px 14px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontSize: '0.5rem', color: '#475569', fontWeight: 700, letterSpacing: '0.15em', marginBottom: '14px' }}>
        SYSTEM INTENT
      </div>

      <Section color="#6366f1" label="PRIMARY GOAL">
        {intent.goal || 'Initializing...'}
      </Section>

      <Section color="#06b6d4" label="CURRENT STRATEGY">
        {intent.strategy || '...'}
      </Section>

      <Section color="#22c55e" label="NEXT OBJECTIVE">
        {intent.next_objective || '...'}
      </Section>

      <div style={{ marginTop: 'auto', paddingTop: '10px', borderTop: '1px solid rgba(255,255,255,0.03)' }}>
        <div style={{ fontSize: '0.6rem', color: '#334155', fontStyle: 'italic' }}>
          The system is an active intelligence — not a process.
        </div>
      </div>
    </div>
  );
}

function Section({ label, color, children }) {
  return (
    <div style={{ marginBottom: '12px' }}>
      <div style={{ fontSize: '0.45rem', color, fontWeight: 700, letterSpacing: '0.12em', marginBottom: '3px' }}>{label}</div>
      <div style={{ fontSize: '0.75rem', color: '#c8d0dc', lineHeight: 1.5, fontWeight: 500 }}>{children}</div>
    </div>
  );
}
