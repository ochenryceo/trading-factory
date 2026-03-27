import { useMemo } from 'react';

const STAGES = [
  { id: 'preparing', label: 'PREPARING', desc: 'Exhausting search space', threshold: 0 },
  { id: 'ready', label: 'READY', desc: 'Code loaded, awaiting trigger', threshold: 400 },
  { id: 'expansion', label: 'EXPANSION', desc: 'New dimensions active', threshold: 500 },
  { id: 'lineage', label: 'LINEAGE', desc: 'Surviving families emerge', threshold: null },
  { id: 'promotion', label: 'PROMOTION', desc: 'Focused refinement', threshold: null },
  { id: 'gate', label: 'PROD GATE', desc: '10-check validation', threshold: null },
  { id: 'deployed', label: 'DEPLOYED', desc: 'Paper trading live', threshold: null },
];

export default function PipelineFlow({ data }) {
  const activeIdx = useMemo(() => {
    const cs = data?.control?.control_state || data?.system?.control_state || {};
    const stagnation = cs.stagnation_counter || 0;

    // TODO: check expansion/promotion/gate state from API when available
    if (stagnation >= 500) return 2; // expansion
    if (stagnation >= 400) return 1; // ready
    return 0; // preparing
  }, [data]);

  return (
    <div className="glass-card" style={{ padding: '20px 24px' }}>
      <div style={{
        fontSize: '0.65rem', color: '#64748b', fontWeight: 700,
        letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '16px',
      }}>
        PIPELINE
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '0', overflowX: 'auto' }}>
        {STAGES.map((stage, i) => {
          const isActive = i === activeIdx;
          const isPast = i < activeIdx;
          const isFuture = i > activeIdx;

          const bgColor = isActive ? 'rgba(99,102,241,0.2)' : isPast ? 'rgba(34,197,94,0.1)' : 'rgba(255,255,255,0.02)';
          const borderColor = isActive ? '#6366f1' : isPast ? '#22c55e50' : 'rgba(255,255,255,0.05)';
          const textColor = isActive ? '#e2e8f0' : isPast ? '#22c55e' : '#475569';
          const descColor = isActive ? '#94a3b8' : isPast ? '#22c55e80' : '#334155';

          return (
            <div key={stage.id} style={{ display: 'flex', alignItems: 'center' }}>
              <div style={{
                padding: '12px 16px', borderRadius: '12px',
                border: `1px solid ${borderColor}`,
                background: bgColor,
                minWidth: '120px', textAlign: 'center',
                position: 'relative',
                boxShadow: isActive ? `0 0 20px ${borderColor}30` : 'none',
                transition: 'all 0.3s ease',
              }}>
                {isActive && (
                  <div style={{
                    position: 'absolute', top: '-8px', left: '50%', transform: 'translateX(-50%)',
                    fontSize: '0.55rem', fontWeight: 800, color: '#6366f1',
                    background: '#0a0a1a', padding: '1px 8px', borderRadius: '4px',
                    border: '1px solid #6366f140', letterSpacing: '0.1em',
                  }}>
                    YOU ARE HERE
                  </div>
                )}
                {isPast && (
                  <div style={{ position: 'absolute', top: '-6px', right: '-6px', fontSize: '0.8rem' }}>✅</div>
                )}
                <div style={{ fontSize: '0.7rem', fontWeight: 700, color: textColor, letterSpacing: '0.08em' }}>
                  {stage.label}
                </div>
                <div style={{ fontSize: '0.6rem', color: descColor, marginTop: '2px' }}>
                  {stage.desc}
                </div>
              </div>

              {i < STAGES.length - 1 && (
                <div style={{
                  width: '24px', height: '2px',
                  background: isPast ? '#22c55e40' : 'rgba(255,255,255,0.05)',
                  flexShrink: 0,
                }} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
