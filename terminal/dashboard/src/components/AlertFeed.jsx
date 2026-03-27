import { useMemo } from 'react';

export default function AlertFeed({ data }) {
  const entries = useMemo(() => {
    const cs = data?.control?.control_state || data?.system?.control_state || {};
    const bs = data?.system?.backtester_state || {};
    const stagnation = cs.stagnation_counter || 0;
    const gen = bs.generation || 0;
    const lastAction = cs.last_action || 'stable';

    const now = new Date();
    const fmt = (d) => d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });

    const log = [];

    // System status
    log.push({ emoji: '🟢', text: 'System operational', color: '#22c55e', time: fmt(now) });

    // Control action
    if (lastAction === 'stable') {
      log.push({ emoji: '🟢', text: 'Control: stable', color: '#22c55e', time: fmt(now) });
    } else {
      log.push({ emoji: '⚙️', text: `Control: ${lastAction}`, color: '#f59e0b', time: fmt(now) });
    }

    // Stagnation milestones
    if (stagnation >= 490) {
      log.push({ emoji: '🔥', text: `Expansion imminent (${stagnation}/500)`, color: '#ef4444', time: `gen ${gen}` });
    } else if (stagnation >= 400) {
      log.push({ emoji: '⚡', text: `Post-restart — awaiting trigger (${stagnation}/500)`, color: '#06b6d4', time: `gen ${gen}` });
    } else if (stagnation >= 350) {
      log.push({ emoji: '⏳', text: `Approaching expansion (${stagnation}/500)`, color: '#f59e0b', time: `gen ${gen}` });
    }

    // Phase-aware events
    const gensToRestart = Math.max(0, 400 - stagnation);
    const gensToExpansion = Math.max(0, 500 - stagnation);

    if (stagnation >= 490) {
      log.push({ emoji: '🔥', text: 'PHASE CHANGE IMMINENT', color: '#ef4444', time: `${500-stagnation} gens` });
    }
    if (gensToRestart > 0 && gensToRestart < 20) {
      log.push({ emoji: '⚡', text: `Restart approaching (${gensToRestart} gens)`, color: '#06b6d4', time: 'soon' });
    }

    // Pipeline state
    log.push({ emoji: '⚡', text: 'Expansion module: charging', color: '#f59e0b', time: `${stagnation}/500` });
    log.push({ emoji: '🔒', text: 'Promotion: locked (awaiting lineage)', color: '#334155', time: '-' });
    log.push({ emoji: '💤', text: 'Production Gate: dormant', color: '#334155', time: '-' });

    // Upcoming milestones
    if (gensToExpansion > 0) {
      log.push({ emoji: '🚀', text: `Expansion trigger in ~${gensToExpansion} gens`, color: '#6366f1', time: 'upcoming' });
    }

    // Future events (what to watch for)
    log.push({ emoji: '🔮', text: 'Next: 🚀 EXPANSION TRIGGERED', color: '#475569', time: 'future' });
    log.push({ emoji: '🔮', text: 'Then: 🧬 LINEAGE DETECTED', color: '#334155', time: 'future' });
    log.push({ emoji: '🔮', text: 'Then: 🔥 STRONG LINEAGE', color: '#334155', time: 'future' });
    log.push({ emoji: '🔮', text: 'Then: 🏆 PROMOTION ACTIVE', color: '#334155', time: 'future' });

    return log;
  }, [data]);

  return (
    <div className="glass-card" style={{ padding: '18px 20px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontSize: '0.6rem', color: '#475569', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '12px' }}>
        MISSION LOG
      </div>

      <div style={{ flex: 1, overflowY: 'auto', maxHeight: '320px' }}>
        {entries.map((entry, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            padding: '7px 0',
            borderBottom: i < entries.length - 1 ? '1px solid rgba(255,255,255,0.025)' : 'none',
          }}>
            <span style={{ fontSize: '0.85rem', flexShrink: 0 }}>{entry.emoji}</span>
            <div style={{ flex: 1, fontSize: '0.75rem', color: entry.color, fontWeight: 500 }}>
              {entry.text}
            </div>
            <div style={{ fontSize: '0.6rem', color: '#334155', flexShrink: 0 }}>
              {entry.time}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
