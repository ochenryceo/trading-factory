import { useMemo } from 'react';

export default function NarrativePanel({ data }) {
  const n = useMemo(() => {
    const cs = data?.control?.control_state || data?.system?.control_state || {};
    const bs = data?.system?.backtester_state || {};
    const stagnation = cs.stagnation_counter || 0;
    const tested = bs.total_strategies_tested || 0;
    const passed = bs.total_passed || 0;

    if (stagnation >= 500) {
      return {
        phase: 'Expansion Phase',
        phaseSignificance: 'DISCOVERY PHASE — New dimensions active. Watching for lineage emergence.',
        interpretation: 'New search dimensions are active. The system broke through its plateau and is exploring previously unreachable parameter regions.',
        happening: 'Evolution is testing 5m/30m timeframes, session-biased entries, ATR regime gating, and dynamic thresholds. 20-50% of batch uses expanded dimensions.',
        expectation: 'First 20-50 gens: new strategy types appear. 50-150 gens: first surviving lineage emerges. This is discovery, not production.',
      };
    }
    if (stagnation >= 400) {
      return {
        phase: 'Post-Restart / Pre-Expansion',
        phaseSignificance: 'TRANSITION PHASE — System armed. Expansion imminent.',
        interpretation: `Backtester restarted with expansion code. Stagnation at ${stagnation}/500 — trigger approaching. Current space proven exhausted.`,
        happening: 'Discovery rate remains at 0%. This is expected and correct. The system is armed and waiting for the stagnation threshold to fire.',
        expectation: 'No valid strategies before expansion. Next meaningful event: expansion trigger at stagnation 500.',
      };
    }
    return {
      phase: 'Late-Stage Exploration',
      phaseSignificance: 'PRE-EXPANSION PHASE — No strategies expected. System preparing for phase transition.',
      interpretation: `Search space exhausted → pressure building. ${tested.toLocaleString()} strategies tested, ${passed} passed Darwin. The system has mapped the current parameter space and found its boundaries.`,
      happening: `Stagnation at ${stagnation}/500. Every generation confirms: current dimensions cannot produce new edge. This pressure is what triggers expansion — the system is working correctly.`,
      expectation: 'Next meaningful signal = expansion trigger. No intervention. No doubt. The system is doing exactly what it should.',
    };
  }, [data]);

  return (
    <div className="glass-card" style={{ padding: '18px 20px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontSize: '0.6rem', color: '#475569', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '12px' }}>
        SYSTEM NARRATIVE
      </div>

      <div style={{ fontSize: '0.95rem', fontWeight: 700, color: '#e2e8f0', marginBottom: '4px' }}>
        {n.phase}
      </div>
      {n.phaseSignificance && (
        <div style={{
          fontSize: '0.65rem', color: '#f59e0b', fontWeight: 600,
          marginBottom: '12px', letterSpacing: '0.03em',
          padding: '4px 8px', borderRadius: '6px',
          background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.15)',
          display: 'inline-block',
        }}>
          {n.phaseSignificance}
        </div>
      )}

      <Section title="INTERPRETATION" color="#6366f1">{n.interpretation}</Section>
      <Section title="WHAT'S HAPPENING" color="#06b6d4">{n.happening}</Section>
      <Section title="EXPECTATION" color="#f59e0b">{n.expectation}</Section>
    </div>
  );
}

function Section({ title, color, children }) {
  return (
    <div style={{ marginBottom: '10px' }}>
      <div style={{ fontSize: '0.55rem', color, fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: '3px' }}>
        {title}
      </div>
      <div style={{ fontSize: '0.75rem', color: '#8892a8', lineHeight: 1.6 }}>
        {children}
      </div>
    </div>
  );
}
