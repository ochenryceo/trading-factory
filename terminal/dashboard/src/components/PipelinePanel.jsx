import { useMemo } from 'react';

const STAGES = [
  { id: 'exploration', label: 'EXPLORATION', icon: '🔍' },
  { id: 'expansion', label: 'EXPANSION', icon: '🚀' },
  { id: 'promotion', label: 'PROMOTION', icon: '🏆' },
  { id: 'gate', label: 'PROD GATE', icon: '🧪' },
  { id: 'paper', label: 'PAPER TRADING', icon: '📊' },
];

const ALIVE_STATUS = {
  ACTIVE: { label: 'ACTIVE', desc: 'Processing' },
  STANDBY: { label: 'CHARGING', desc: 'Awaiting trigger' },
  LOCKED: { label: 'LOCKED', desc: 'Awaiting lineage' },
  WAITING: { label: 'DORMANT', desc: 'Awaiting promotion' },
  IDLE: { label: 'SLEEPING', desc: 'Awaiting approval' },
};

export default function PipelinePanel({ data }) {
  const states = useMemo(() => {
    const cs = data?.control?.control_state || data?.system?.control_state || {};
    const stagnation = cs.stagnation_counter || 0;

    return STAGES.map(s => {
      if (s.id === 'exploration') return { ...s, status: 'ACTIVE', color: '#22c55e', anim: true };
      if (s.id === 'expansion') {
        if (stagnation >= 500) return { ...s, status: 'ACTIVE', statusLabel: 'ACTIVE', statusDesc: 'Dimensions unlocked', color: '#22c55e', anim: true };
        return { ...s, status: 'STANDBY', statusLabel: '⚡ CHARGING', statusDesc: `Trigger at 500 (${stagnation}/500)`, color: '#f59e0b', anim: stagnation >= 350 };
      }
      if (s.id === 'promotion') return { ...s, status: 'LOCKED', statusLabel: '🔒 LOCKED', statusDesc: 'Awaiting lineage emergence', color: '#334155', anim: false };
      if (s.id === 'gate') return { ...s, status: 'WAITING', statusLabel: '💤 DORMANT', statusDesc: 'Awaiting promotion', color: '#334155', anim: false };
      if (s.id === 'paper') return { ...s, status: 'IDLE', statusLabel: '💤 SLEEPING', statusDesc: 'Awaiting gate approval', color: '#334155', anim: false };
      return { ...s, status: '?', color: '#334155', anim: false };
    });
  }, [data]);

  return (
    <div className="glass-card" style={{ padding: '20px 16px', display: 'flex', flexDirection: 'column' }}>
      <div style={{
        fontSize: '0.6rem', color: '#475569', fontWeight: 700,
        letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '16px',
      }}>
        PIPELINE STATUS
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {states.map((stage, i) => {
          const isActive = stage.status === 'ACTIVE';
          const bg = isActive ? `${stage.color}12` : 'rgba(255,255,255,0.015)';
          const border = isActive ? `${stage.color}40` : 'rgba(255,255,255,0.04)';
          const statusBadge = {
            ACTIVE: { bg: '#22c55e20', color: '#22c55e', border: '#22c55e40' },
            STANDBY: { bg: '#f59e0b15', color: '#f59e0b', border: '#f59e0b30' },
            LOCKED: { bg: 'rgba(255,255,255,0.03)', color: '#475569', border: 'rgba(255,255,255,0.06)' },
            WAITING: { bg: 'rgba(255,255,255,0.03)', color: '#475569', border: 'rgba(255,255,255,0.06)' },
            IDLE: { bg: 'rgba(255,255,255,0.03)', color: '#475569', border: 'rgba(255,255,255,0.06)' },
          }[stage.status] || { bg: 'transparent', color: '#475569', border: 'transparent' };

          return (
            <div key={stage.id}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: '10px',
                padding: '10px 12px', borderRadius: '10px',
                background: bg, border: `1px solid ${border}`,
                transition: 'all 0.3s',
              }}>
                <span style={{ fontSize: '1.1rem', opacity: isActive ? 1 : 0.4 }}>{stage.icon}</span>
                <div style={{ flex: 1 }}>
                  <div style={{
                    fontSize: '0.7rem', fontWeight: 700, color: isActive ? '#e2e8f0' : '#475569',
                    letterSpacing: '0.06em',
                  }}>
                    {stage.label}
                  </div>
                  {stage.statusDesc && (
                    <div style={{ fontSize: '0.55rem', color: '#3f4a5e', marginTop: '1px' }}>
                      {stage.statusDesc}
                    </div>
                  )}
                </div>
                <div style={{
                  fontSize: '0.5rem', fontWeight: 700, padding: '2px 8px', borderRadius: '999px',
                  background: statusBadge.bg, color: statusBadge.color,
                  border: `1px solid ${statusBadge.border}`,
                  letterSpacing: '0.06em',
                  animation: stage.anim ? 'pulse-glow 3s ease-in-out infinite' : 'none',
                  whiteSpace: 'nowrap',
                }}>
                  {stage.statusLabel || stage.status}
                </div>
              </div>
              {i < states.length - 1 && (
                <div style={{
                  width: '2px', height: '8px', marginLeft: '22px',
                  background: isActive ? '#22c55e30' : 'rgba(255,255,255,0.03)',
                }} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
