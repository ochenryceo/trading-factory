import { useMemo } from 'react';

function detectPhase(data) {
  const cs = data?.control?.control_state || data?.system?.control_state || {};
  const bs = data?.system?.backtester_state || {};
  const stagnation = cs.stagnation_counter || 0;
  const rates = cs.last_discovery_rates || [];
  const discoveryDead = rates.length >= 10 && rates.slice(-10).every(r => r === 0);

  // Check expansion/promotion/gate from API
  const prop = data?.prop?.status || {};

  if (stagnation >= 500 && discoveryDead) return { phase: 'ACTIVE', emoji: '🚀', label: 'Expansion Active', color: '#22c55e' };
  if (stagnation >= 400) return { phase: 'READY', emoji: '⚡', label: 'Ready (Post-Restart)', color: '#06b6d4' };
  if (stagnation >= 200) return { phase: 'PREPARING', emoji: '⏳', label: 'Preparing', color: '#f59e0b' };
  return { phase: 'EXPLORING', emoji: '🌱', label: 'Exploring', color: '#6366f1' };
}

function computeConfidence(data) {
  let score = 100;
  const issues = [];
  const bs = data?.system?.backtester_state;
  if (!bs || !bs.generation) { score -= 30; issues.push('No backtester data'); }
  const cs = data?.control?.control_state || data?.system?.control_state || {};
  if (cs.stagnation_counter >= 500 && !data?.system?.expansion_active) {
    score -= 25; issues.push('Expansion should be active');
  }
  return { score: Math.max(0, score), issues };
}

function computeHealth(data) {
  const drift = data?.drift?.strategies || {};
  const kills = Object.values(drift).filter(s => s.status === 'KILL').length;
  const prop = data?.prop?.status || {};
  let dd = 0;
  if (prop.peak > 0) dd = ((prop.peak - (prop.balance || prop.peak)) / prop.peak) * 100;
  
  let score = 100;
  if (kills > 0) score -= kills * 15;
  if (dd > 5) score -= 20;
  return Math.max(0, Math.min(100, score));
}

export default function StateHeader({ data, connected }) {
  const phase = useMemo(() => detectPhase(data), [data]);
  const confidence = useMemo(() => computeConfidence(data), [data]);
  const health = useMemo(() => computeHealth(data), [data]);

  const confEmoji = confidence.score >= 90 ? '🟢' : confidence.score >= 70 ? '🟡' : '🔴';
  const confLabel = confidence.score >= 90 ? 'TRUSTED' : confidence.score >= 70 ? 'DEGRADED' : 'CRITICAL';
  const healthEmoji = health >= 85 ? '🟢' : health >= 60 ? '🟡' : '🔴';

  const bs = data?.system?.backtester_state || {};
  const gen = bs.generation || '-';

  return (
    <div style={{
      padding: '24px 32px',
      background: `linear-gradient(135deg, rgba(10,10,26,0.95), rgba(10,10,26,0.98))`,
      borderBottom: `2px solid ${phase.color}40`,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '48px',
      flexWrap: 'wrap',
    }}>
      {/* STATE — The biggest element */}
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: '0.65rem', color: '#64748b', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '4px' }}>
          SYSTEM STATE
        </div>
        <div style={{
          fontSize: '1.8rem', fontWeight: 800, color: phase.color, letterSpacing: '0.05em',
          textShadow: `0 0 30px ${phase.color}60, 0 0 60px ${phase.color}20`,
        }}>
          {phase.emoji} {phase.phase}
        </div>
        <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '2px' }}>{phase.label}</div>
      </div>

      <Divider />

      {/* CONFIDENCE */}
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: '0.65rem', color: '#64748b', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '4px' }}>
          CONFIDENCE
        </div>
        <div style={{ fontSize: '1.4rem', fontWeight: 700, color: confidence.score >= 90 ? '#22c55e' : confidence.score >= 70 ? '#f59e0b' : '#ef4444' }}>
          {confEmoji} {confidence.score}%
        </div>
        <div style={{ fontSize: '0.7rem', color: '#64748b' }}>{confLabel}</div>
      </div>

      <Divider />

      {/* HEALTH */}
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: '0.65rem', color: '#64748b', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '4px' }}>
          HEALTH
        </div>
        <div style={{ fontSize: '1.4rem', fontWeight: 700, color: health >= 85 ? '#22c55e' : health >= 60 ? '#f59e0b' : '#ef4444' }}>
          {healthEmoji} {health}%
        </div>
      </div>

      <Divider />

      {/* GEN */}
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: '0.65rem', color: '#64748b', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '4px' }}>
          GENERATION
        </div>
        <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#6366f1' }}>
          {gen.toLocaleString?.() || gen}
        </div>
      </div>

      {!connected && (
        <>
          <Divider />
          <span style={{ color: '#ef4444', fontWeight: 700, fontSize: '0.85rem', animation: 'pulse-glow 1.5s ease-in-out infinite' }}>● DISCONNECTED</span>
        </>
      )}
    </div>
  );
}

function Divider() {
  return <div style={{ width: '1px', height: '48px', background: 'rgba(99,102,241,0.15)' }} />;
}
