import { useMemo } from 'react';

export default function NarrativeBox({ data }) {
  const narrative = useMemo(() => {
    const cs = data?.control?.control_state || data?.system?.control_state || {};
    const bs = data?.system?.backtester_state || {};
    const stagnation = cs.stagnation_counter || 0;
    const tested = bs.total_strategies_tested || 0;
    const passed = bs.total_passed || 0;
    const lastAction = cs.last_action || 'stable';

    if (stagnation >= 500) {
      return {
        title: 'Expansion Phase',
        lines: [
          'New search dimensions are active.',
          'System exploring: 5m/30m timeframes, session filters, ATR regimes, dynamic thresholds.',
          'Watching for first surviving lineage — that\'s the key signal.',
          'No production candidates expected during expansion — this is discovery phase.',
        ],
        expectation: 'First 20-50 gens: new strategy types appear. 50-150 gens: first lineage emerges.',
        action: 'Observe — no intervention.',
      };
    }
    if (stagnation >= 400) {
      return {
        title: 'Post-Restart / Pre-Expansion',
        lines: [
          `Backtester restarted with expansion code loaded.`,
          `Stagnation at ${stagnation}/500 — trigger approaching.`,
          `System has proven current space is exhausted.`,
          `Expansion will unlock new dimensions when stagnation reaches 500.`,
        ],
        expectation: 'Discovery rate = 0.0% is expected. No valid strategies before expansion.',
        action: 'None — waiting for trigger.',
      };
    }

    return {
      title: 'Late-Stage Exploration',
      lines: [
        `${tested.toLocaleString()} strategies tested, ${passed} passed Darwin.`,
        `Stagnation at ${stagnation}/500 — search space pressure building.`,
        `Discovery rate = 0.0% is NORMAL in this phase.`,
        `Control layer: ${lastAction}. Diversity stabilizer active.`,
      ],
      expectation: 'No valid strategies expected before expansion. System correctly exhausting current space.',
      action: 'None — system behaving as designed.',
    };
  }, [data]);

  return (
    <div className="glass-card" style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column' }}>
      <div style={{
        fontSize: '0.65rem', color: '#64748b', fontWeight: 700,
        letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '12px',
      }}>
        SYSTEM NARRATIVE
      </div>

      <div style={{ fontSize: '1rem', fontWeight: 700, color: '#e2e8f0', marginBottom: '10px' }}>
        {narrative.title}
      </div>

      <div style={{ flex: 1 }}>
        {narrative.lines.map((line, i) => (
          <div key={i} style={{ fontSize: '0.8rem', color: '#94a3b8', marginBottom: '6px', lineHeight: 1.5 }}>
            • {line}
          </div>
        ))}
      </div>

      <div style={{
        marginTop: '12px', padding: '10px 12px', borderRadius: '8px',
        background: 'rgba(99,102,241,0.06)', border: '1px solid rgba(99,102,241,0.1)',
      }}>
        <div style={{ fontSize: '0.65rem', color: '#6366f1', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: '4px' }}>
          EXPECTATION
        </div>
        <div style={{ fontSize: '0.75rem', color: '#94a3b8', lineHeight: 1.5 }}>
          {narrative.expectation}
        </div>
      </div>

      <div style={{
        marginTop: '8px', padding: '8px 12px', borderRadius: '8px',
        background: 'rgba(34,197,94,0.05)', border: '1px solid rgba(34,197,94,0.1)',
      }}>
        <div style={{ fontSize: '0.65rem', color: '#22c55e', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: '2px' }}>
          ACTION REQUIRED
        </div>
        <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
          {narrative.action}
        </div>
      </div>
    </div>
  );
}
