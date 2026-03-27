import { useMemo } from 'react';

export default function HeroCountdown({ data }) {
  const info = useMemo(() => {
    const cs = data?.control?.control_state || data?.system?.control_state || {};
    const stagnation = cs.stagnation_counter || 0;

    // Estimate speed from discovery data
    const disc = Array.isArray(data?.discovery) ? data.discovery : [];
    let gensPerHour = 48; // default
    if (disc.length >= 20) {
      const first = disc[disc.length - 20];
      const last = disc[disc.length - 1];
      const genDiff = (last?.generation || 0) - (first?.generation || 0);
      const t1 = new Date(first?.timestamp || 0);
      const t2 = new Date(last?.timestamp || 0);
      const hoursDiff = Math.max(0.1, (t2 - t1) / 3600000);
      if (genDiff > 0) gensPerHour = genDiff / hoursDiff;
    }

    const gensToRestart = Math.max(0, 400 - stagnation);
    const gensToExpansion = Math.max(0, 500 - stagnation);

    if (stagnation >= 500) {
      return { headline: '🚀 EXPANSION ACTIVE', sub: 'New dimensions unlocked', progress: 100, color: '#22c55e', pulse: true };
    }
    if (stagnation >= 400) {
      const eta = (gensToExpansion / gensPerHour).toFixed(1);
      return {
        headline: `🚀 EXPANSION IN ${gensToExpansion} GENS`,
        sub: `~${eta}h • Restart complete • Waiting for trigger`,
        progress: ((stagnation - 400) / 100) * 100,
        color: '#06b6d4',
        pulse: true,
      };
    }

    const etaRestart = (gensToRestart / gensPerHour).toFixed(1);
    const etaExpansion = (gensToExpansion / gensPerHour).toFixed(1);
    const overallProgress = (stagnation / 500) * 100;

    return {
      headline: `⏳ EXPANSION IN ${gensToExpansion} GENS`,
      sub: `Restart in ${gensToRestart} gens (~${etaRestart}h) • Expansion in ~${etaExpansion}h`,
      progress: overallProgress,
      color: '#f59e0b',
      pulse: false,
    };
  }, [data]);

  return (
    <div className="glass-card" style={{ padding: '24px 32px', position: 'relative', overflow: 'hidden' }}>
      {info.pulse && (
        <div style={{
          position: 'absolute', inset: 0,
          background: `radial-gradient(ellipse at 50% 50%, ${info.color}10, transparent 70%)`,
          animation: 'pulse-glow 3s ease-in-out infinite',
        }} />
      )}
      <div style={{ position: 'relative', zIndex: 1 }}>
        <div style={{
          fontSize: '1.5rem', fontWeight: 800, color: info.color, textAlign: 'center',
          textShadow: `0 0 30px ${info.color}50`,
          letterSpacing: '0.02em',
        }}>
          {info.headline}
        </div>
        <div style={{ fontSize: '0.8rem', color: '#94a3b8', textAlign: 'center', marginTop: '6px' }}>
          {info.sub}
        </div>

        {/* Progress bar */}
        <div style={{
          marginTop: '16px', height: '8px', borderRadius: '4px',
          background: 'rgba(255,255,255,0.05)', overflow: 'hidden',
        }}>
          <div style={{
            height: '100%', borderRadius: '4px',
            width: `${Math.min(100, info.progress)}%`,
            background: `linear-gradient(90deg, ${info.color}80, ${info.color})`,
            transition: 'width 1s ease',
            boxShadow: `0 0 12px ${info.color}40`,
          }} />
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '6px', fontSize: '0.65rem', color: '#64748b' }}>
          <span>0</span>
          <span style={{ color: '#94a3b8' }}>Restart @ 400</span>
          <span>500</span>
        </div>
      </div>
    </div>
  );
}
