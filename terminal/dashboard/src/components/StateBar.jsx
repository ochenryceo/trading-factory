import { useMemo } from 'react';

function detectState(data) {
  const cs = data?.control?.control_state || data?.system?.control_state || {};
  const stagnation = cs.stagnation_counter || 0;
  if (stagnation >= 500) return { id: 'ACTIVE', label: 'Expansion Active', color: '#22c55e', glow: '#22c55e' };
  if (stagnation >= 400) return { id: 'READY', label: 'Ready (Post-Restart)', color: '#f59e0b', glow: '#f59e0b' };
  return { id: 'PREPARING', label: 'Pre-Expansion', color: '#6366f1', glow: '#6366f1' };
}

function getConfidence(data) {
  let score = 100;
  const bs = data?.system?.backtester_state;
  if (!bs?.generation) score -= 30;
  const cs = data?.control?.control_state || data?.system?.control_state || {};
  if (cs.stagnation_counter >= 500 && !data?.system?.expansion_active) score -= 25;
  score = Math.max(0, Math.min(100, score));
  const emoji = score >= 90 ? '🟢' : score >= 70 ? '🟡' : '🔴';
  const label = score >= 90 ? 'TRUSTED' : score >= 70 ? 'DEGRADED' : 'CRITICAL';
  const pulse = score < 90;
  return { score, emoji, label, pulse };
}

function getHealth(data) {
  const drift = data?.drift?.strategies || {};
  const kills = Object.values(drift).filter(s => s.status === 'KILL').length;
  const prop = data?.prop?.status || {};
  let dd = prop.peak > 0 ? ((prop.peak - (prop.balance || prop.peak)) / prop.peak) * 100 : 0;
  let score = 100 - kills * 15 - (dd > 5 ? 20 : 0);
  score = Math.max(0, Math.min(100, score));
  return { score, emoji: score >= 85 ? '🟢' : score >= 60 ? '🟡' : '🔴', label: score >= 85 ? 'HEALTHY' : score >= 60 ? 'DEGRADED' : 'CRITICAL' };
}

function getRisk(data) {
  const cs = data?.control?.control_state || data?.system?.control_state || {};
  const stagnation = cs.stagnation_counter || 0;
  if (stagnation > 450) return { label: 'MEDIUM', color: '#f59e0b' };
  return { label: 'LOW', color: '#22c55e' };
}

export default function StateBar({ data, connected }) {
  const state = useMemo(() => detectState(data), [data]);
  const confidence = useMemo(() => getConfidence(data), [data]);
  const health = useMemo(() => getHealth(data), [data]);
  const risk = useMemo(() => getRisk(data), [data]);

  // Build the state transition display
  const states = ['PREPARING', 'READY', 'ACTIVE'];
  const activeIdx = states.indexOf(state.id);

  return (
    <div style={{
      padding: '20px 32px',
      background: 'linear-gradient(180deg, rgba(10,10,26,0.98), rgba(10,10,26,0.92))',
      borderBottom: `2px solid ${state.color}30`,
    }}>
      {/* State transition — biggest element */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', marginBottom: '16px' }}>
        {states.map((s, i) => {
          const isActive = i === activeIdx;
          const isPast = i < activeIdx;
          const c = isActive ? state.color : isPast ? '#22c55e' : '#1e293b';
          return (
            <div key={s} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{
                padding: isActive ? '8px 28px' : '6px 18px',
                borderRadius: '8px',
                background: isActive ? `${c}20` : 'transparent',
                border: `2px solid ${isActive ? c : isPast ? '#22c55e40' : '#1e293b'}`,
                color: isActive ? c : isPast ? '#22c55e' : '#334155',
                fontSize: isActive ? '1.6rem' : '0.9rem',
                fontWeight: isActive ? 900 : 600,
                letterSpacing: '0.08em',
                textShadow: isActive ? `0 0 30px ${c}60, 0 0 60px ${c}20` : 'none',
                transition: 'all 0.5s ease',
                position: 'relative',
              }}>
                {isPast && <span style={{ marginRight: '6px', fontSize: '0.8rem' }}>✅</span>}
                {s}
                {isActive && (
                  <div style={{
                    position: 'absolute', bottom: '-14px', left: '50%', transform: 'translateX(-50%)',
                    fontSize: '0.5rem', color: c, fontWeight: 700, letterSpacing: '0.15em',
                    whiteSpace: 'nowrap',
                  }}>
                    ▲ YOU ARE HERE
                  </div>
                )}
              </div>
              {i < states.length - 1 && (
                <div style={{
                  width: '40px', height: '2px',
                  background: isPast ? '#22c55e40' : '#1e293b',
                }} />
              )}
            </div>
          );
        })}
      </div>

      {/* Indicators row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '40px', marginTop: '8px' }}>
        <Indicator label="CONFIDENCE" value={`${confidence.score}%`} sub={confidence.label} emoji={confidence.emoji} color={confidence.score >= 90 ? '#22c55e' : '#f59e0b'} pulse={confidence.pulse} />
        <Sep />
        <Indicator label="HEALTH" value={health.label} emoji={health.emoji} color={health.score >= 85 ? '#22c55e' : '#f59e0b'} />
        <Sep />
        <Indicator label="RISK" value={risk.label} color={risk.color} />
        <Sep />
        <Indicator label="GEN" value={(data?.system?.backtester_state?.generation || '-').toLocaleString?.()} color="#6366f1" />
        {!connected && (
          <>
            <Sep />
            <span style={{ color: '#ef4444', fontWeight: 700, fontSize: '0.8rem', animation: 'pulse-glow 1.5s ease-in-out infinite' }}>● DISCONNECTED</span>
          </>
        )}
      </div>
    </div>
  );
}

function Indicator({ label, value, sub, emoji, color, pulse }) {
  return (
    <div style={{ textAlign: 'center', animation: pulse ? 'pulse-glow 2s ease-in-out infinite' : 'none' }}>
      <div style={{ fontSize: '0.55rem', color: '#475569', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '3px' }}>{label}</div>
      <div style={{ fontSize: '1.1rem', fontWeight: 700, color }}>
        {emoji && <span style={{ marginRight: '4px' }}>{emoji}</span>}{value}
      </div>
      {sub && <div style={{ fontSize: '0.6rem', color: '#475569', marginTop: '1px' }}>{sub}</div>}
    </div>
  );
}

function Sep() {
  return <div style={{ width: '1px', height: '36px', background: 'rgba(99,102,241,0.12)' }} />;
}
