import { useMemo } from 'react';

function detectState(data) {
  const cs = data?.control?.control_state || data?.system?.control_state || {};
  const s = cs.stagnation_counter || 0;
  if (s >= 500) return { id: 'ACTIVE', color: '#22c55e' };
  if (s >= 400) return { id: 'READY', color: '#f59e0b' };
  return { id: 'PREPARING', color: '#6366f1' };
}

export default function CommandBar({ data, connected }) {
  const state = useMemo(() => detectState(data), [data]);
  const intel = data?.intelligence || {};
  const conf = useMemo(() => {
    let s = 100;
    if (!data?.system?.backtester_state?.generation) s -= 30;
    return Math.max(0, Math.min(100, s));
  }, [data]);

  const health = useMemo(() => {
    const drift = data?.drift?.strategies || {};
    const kills = Object.values(drift).filter(s => s.status === 'KILL').length;
    return Math.max(0, 100 - kills * 15);
  }, [data]);

  const risk = intel.edge_pressure?.level || 'LOW';
  const failMode = intel.failure_mode?.mode || 'NONE';

  const states = ['PREPARING', 'READY', 'ACTIVE'];
  const idx = states.indexOf(state.id);

  return (
    <div style={{
      padding: '14px 24px',
      background: 'linear-gradient(180deg, rgba(10,10,26,0.98), rgba(10,10,26,0.94))',
      borderBottom: `2px solid ${state.color}30`,
    }}>
      {/* State machine */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', marginBottom: '10px' }}>
        {states.map((s, i) => {
          const active = i === idx;
          const past = i < idx;
          const c = active ? state.color : past ? '#22c55e' : '#1e293b';
          return (
            <div key={s} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{
                padding: active ? '6px 24px' : '4px 14px',
                borderRadius: '6px',
                background: active ? `${c}18` : 'transparent',
                border: `2px solid ${active ? c : past ? '#22c55e30' : '#1e293b'}`,
                color: active ? c : past ? '#22c55e80' : '#283040',
                fontSize: active ? '1.4rem' : '0.8rem',
                fontWeight: active ? 900 : 600,
                letterSpacing: '0.08em',
                textShadow: active ? `0 0 24px ${c}50` : 'none',
                position: 'relative',
              }}>
                {past && <span style={{ marginRight: '4px', fontSize: '0.7rem' }}>✅</span>}
                {s}
                {active && (
                  <div style={{
                    position: 'absolute', bottom: '-12px', left: '50%', transform: 'translateX(-50%)',
                    fontSize: '0.45rem', color: c, fontWeight: 700, letterSpacing: '0.15em', whiteSpace: 'nowrap',
                  }}>▲ YOU ARE HERE</div>
                )}
              </div>
              {i < 2 && <div style={{ width: '30px', height: '2px', background: past ? '#22c55e30' : '#1e293b' }} />}
            </div>
          );
        })}
      </div>

      {/* Indicators */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '28px', marginTop: '4px' }}>
        <Ind label="CONFIDENCE" value={`${conf}%`} sub={conf >= 90 ? 'TRUSTED' : 'DEGRADED'} color={conf >= 90 ? '#22c55e' : '#f59e0b'} emoji={conf >= 90 ? '🟢' : '🟡'} />
        <Sep />
        <Ind label="HEALTH" value={health >= 85 ? 'HEALTHY' : 'DEGRADED'} color={health >= 85 ? '#22c55e' : '#f59e0b'} emoji={health >= 85 ? '🟢' : '🟡'} />
        <Sep />
        <Ind label="RISK" value={risk} color={risk === 'LOW' ? '#22c55e' : risk === 'HIGH' ? '#f97316' : '#f59e0b'} />
        <Sep />
        <Ind label="FAILURE MODE" value={failMode === 'NONE' ? 'NONE' : failMode.split(' ').slice(0,2).join(' ')} color={failMode === 'NONE' ? '#22c55e' : '#f59e0b'} sub={failMode !== 'NONE' ? '(expected)' : ''} />
        <Sep />
        <Ind label="GEN" value={(data?.system?.backtester_state?.generation || 0).toLocaleString()} color="#6366f1" />
        {!connected && <><Sep /><span style={{ color: '#ef4444', fontWeight: 700, fontSize: '0.75rem', animation: 'pulse-glow 1.5s ease-in-out infinite' }}>● OFFLINE</span></>}
      </div>
    </div>
  );
}

function Ind({ label, value, sub, color, emoji }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: '0.5rem', color: '#3f4a5e', fontWeight: 700, letterSpacing: '0.15em', marginBottom: '2px' }}>{label}</div>
      <div style={{ fontSize: '0.95rem', fontWeight: 700, color }}>{emoji && <span style={{ marginRight: '3px' }}>{emoji}</span>}{value}</div>
      {sub && <div style={{ fontSize: '0.5rem', color: '#3f4a5e' }}>{sub}</div>}
    </div>
  );
}

function Sep() { return <div style={{ width: '1px', height: '32px', background: 'rgba(99,102,241,0.1)' }} />; }
