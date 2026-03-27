import { useMemo } from 'react';

export default function MissionLog({ data }) {
  const entries = useMemo(() => {
    const cs = data?.control?.control_state || data?.system?.control_state || {};
    const bs = data?.system?.backtester_state || {};
    const stagnation = cs.stagnation_counter || 0;
    const gen = bs.generation || 0;
    const passed = bs.total_passed || 0;
    const tested = bs.total_strategies_tested || 0;
    const lastAction = cs.last_action || 'stable';

    const log = [];

    // Current state events
    log.push({ emoji: '🟢', text: 'System operational', color: '#22c55e', time: 'now' });

    if (lastAction !== 'stable') {
      log.push({ emoji: '⚙️', text: `Control: ${lastAction}`, color: '#f59e0b', time: 'active' });
    }

    if (stagnation > 0) {
      log.push({
        emoji: stagnation >= 400 ? '🔥' : '⏳',
        text: `Stagnation: ${stagnation}/500`,
        color: stagnation >= 400 ? '#f97316' : '#64748b',
        time: `gen ${gen}`,
      });
    }

    if (passed > 0) {
      log.push({ emoji: '✅', text: `${passed} Darwin passes (lifetime)`, color: '#22c55e', time: `of ${tested.toLocaleString()}` });
    }

    // Pipeline status
    log.push({ emoji: '⏳', text: 'Expansion: STANDBY', color: '#64748b', time: 'waiting' });
    log.push({ emoji: '⏳', text: 'Promotion: INACTIVE', color: '#64748b', time: 'waiting' });
    log.push({ emoji: '⏳', text: 'Production Gate: WAITING', color: '#64748b', time: 'waiting' });

    // Future milestones
    const gensToRestart = Math.max(0, 400 - stagnation);
    const gensToExpansion = Math.max(0, 500 - stagnation);

    if (gensToRestart > 0) {
      log.push({ emoji: '🔄', text: `Restart in ~${gensToRestart} gens`, color: '#06b6d4', time: 'upcoming' });
    }
    if (gensToExpansion > 0) {
      log.push({ emoji: '🚀', text: `Expansion in ~${gensToExpansion} gens`, color: '#6366f1', time: 'upcoming' });
    }

    return log;
  }, [data]);

  return (
    <div className="glass-card" style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column' }}>
      <div style={{
        fontSize: '0.65rem', color: '#64748b', fontWeight: 700,
        letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '12px',
      }}>
        MISSION LOG
      </div>

      <div style={{ flex: 1, overflowY: 'auto', maxHeight: '360px' }}>
        {entries.map((entry, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'flex-start', gap: '10px',
            padding: '8px 0',
            borderBottom: i < entries.length - 1 ? '1px solid rgba(255,255,255,0.03)' : 'none',
          }}>
            <span style={{ fontSize: '0.9rem', flexShrink: 0 }}>{entry.emoji}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: '0.8rem', color: entry.color, fontWeight: 600 }}>
                {entry.text}
              </div>
            </div>
            <div style={{ fontSize: '0.65rem', color: '#475569', flexShrink: 0, textAlign: 'right' }}>
              {entry.time}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
