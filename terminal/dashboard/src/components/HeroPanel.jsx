import { useMemo } from 'react';

export default function HeroPanel({ data }) {
  const cs = data?.control?.control_state || data?.system?.control_state || {};
  const stagnation = cs.stagnation_counter || 0;

  const info = useMemo(() => {
    const disc = Array.isArray(data?.discovery) ? data.discovery : [];
    let gph = 48;
    if (disc.length >= 20) {
      const first = disc[disc.length - 20];
      const last = disc[disc.length - 1];
      const gd = (last?.generation || 0) - (first?.generation || 0);
      const hd = Math.max(0.1, (new Date(last?.timestamp || 0) - new Date(first?.timestamp || 0)) / 3600000);
      if (gd > 0) gph = gd / hd;
    }

    const gensToRestart = Math.max(0, 400 - stagnation);
    const gensToExpansion = Math.max(0, 500 - stagnation);
    const progress = (stagnation / 500) * 100;

    if (stagnation >= 500) {
      return {
        title: 'EXPANSION ACTIVE', icon: '🚀',
        subtitle: 'New dimensions unlocked — monitoring lineage emergence',
        bigNumber: null, bigLabel: null,
        progress: 100, color: '#22c55e', pulse: true,
        details: ['5m + 30m timeframes active', 'Session filters + ATR gating enabled', 'Dynamic thresholds operational', 'Watching for first surviving lineage'],
        detailsTitle: 'ACTIVE DIMENSIONS',
        etaLine: null,
      };
    }
    if (stagnation >= 400) {
      const eta = (gensToExpansion / gph).toFixed(1);
      return {
        title: 'SYSTEM ARMED', icon: '⚡',
        subtitle: 'Expansion code loaded — awaiting activation trigger',
        bigNumber: gensToExpansion, bigLabel: 'GENS TO TRIGGER',
        progress, color: '#06b6d4', pulse: true,
        details: ['Backtester restarted ✅', 'EXPANSION_READY validated ✅', 'Trigger guard active ✅', 'Awaiting stagnation ≥ 500'],
        detailsTitle: 'READINESS CHECK',
        etaLine: `~${eta}h to expansion`,
      };
    }

    const etaR = gensToRestart > 0 ? (gensToRestart / gph).toFixed(1) : '0';
    const etaE = (gensToExpansion / gph).toFixed(1);
    return {
      title: 'EXPANSION INCOMING', icon: '🚀',
      subtitle: `Phase transition approaching — this changes everything`,
      bigNumber: gensToExpansion, bigLabel: 'GENS TO EXPANSION',
      progress, color: '#f59e0b', pulse: stagnation >= 350,
      details: ['New timeframes (5m, 30m)', 'Session filters + ATR gating', 'Dynamic thresholds + holding logic', 'First lineage formation enabled'],
      detailsTitle: 'WHAT THIS UNLOCKS',
      etaLine: `Restart in ~${etaR}h (${gensToRestart} gens) → Trigger in ~${etaE}h`,
    };
  }, [data, stagnation]);

  return (
    <div style={{
      position: 'relative', overflow: 'hidden',
      borderRadius: '16px',
      border: `1px solid ${info.color}25`,
      background: `radial-gradient(ellipse at 50% 40%, ${info.color}08, transparent 70%), rgba(15,20,40,0.7)`,
      padding: '32px',
    }}>
      {/* Animated pulse ring */}
      {info.pulse && (
        <>
          <div style={{
            position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
            width: '300px', height: '300px', borderRadius: '50%',
            border: `2px solid ${info.color}15`,
            animation: 'pulse-glow 3s ease-in-out infinite',
          }} />
          <div style={{
            position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
            width: '450px', height: '450px', borderRadius: '50%',
            border: `1px solid ${info.color}08`,
            animation: 'pulse-glow 4s ease-in-out infinite',
            animationDelay: '1s',
          }} />
        </>
      )}

      <div style={{ position: 'relative', zIndex: 1 }}>
        {/* Title */}
        <div style={{ textAlign: 'center' }}>
          <div style={{
            fontSize: '2.6rem', fontWeight: 900, color: info.color,
            textShadow: `0 0 60px ${info.color}50, 0 0 120px ${info.color}15`,
            letterSpacing: '0.06em', lineHeight: 1,
          }}>
            {info.icon} {info.title}
          </div>
          <div style={{ fontSize: '0.85rem', color: '#7a8599', marginTop: '8px' }}>
            {info.subtitle}
          </div>
        </div>

        {/* Big counter */}
        {info.bigNumber !== null && (
          <div style={{ textAlign: 'center', margin: '20px 0' }}>
            <div style={{
              fontSize: '4.5rem', fontWeight: 900, color: info.color,
              textShadow: `0 0 40px ${info.color}35`,
              fontVariantNumeric: 'tabular-nums', lineHeight: 1,
            }}>
              {info.bigNumber}
            </div>
            <div style={{
              fontSize: '0.6rem', color: '#475569', fontWeight: 700,
              letterSpacing: '0.2em', textTransform: 'uppercase', marginTop: '4px',
            }}>
              {info.bigLabel}
            </div>
            {info.etaLine && (
              <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '6px' }}>
                {info.etaLine}
              </div>
            )}
          </div>
        )}

        {/* Progress bar */}
        <div style={{ maxWidth: '600px', margin: '0 auto' }}>
          <div style={{
            height: '10px', borderRadius: '5px',
            background: 'rgba(255,255,255,0.04)', overflow: 'hidden',
          }}>
            <div style={{
              height: '100%', borderRadius: '5px',
              width: `${Math.min(100, info.progress)}%`,
              background: `linear-gradient(90deg, ${info.color}50, ${info.color})`,
              transition: 'width 1s ease',
              boxShadow: `0 0 16px ${info.color}40`,
            }} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '4px', fontSize: '0.55rem', color: '#334155' }}>
            <span>0</span>
            <span style={{ color: stagnation >= 400 ? '#06b6d4' : '#475569' }}>Restart @ 400</span>
            <span>Trigger @ 500</span>
          </div>
        </div>

        {/* What this unlocks */}
        <div style={{
          marginTop: '20px', padding: '14px 18px', borderRadius: '10px',
          background: `${info.color}06`, border: `1px solid ${info.color}12`,
          maxWidth: '600px', margin: '20px auto 0',
        }}>
          <div style={{
            fontSize: '0.55rem', color: info.color, fontWeight: 700,
            letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '8px',
          }}>
            {info.detailsTitle}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 16px' }}>
            {info.details.map((d, i) => (
              <div key={i} style={{ fontSize: '0.72rem', color: '#6b7a8e' }}>• {d}</div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
