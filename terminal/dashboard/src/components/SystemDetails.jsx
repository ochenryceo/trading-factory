import { useMemo } from 'react';

export default function SystemDetails({ data }) {
  const details = useMemo(() => {
    const cs = data?.control?.control_state || data?.system?.control_state || {};
    const bs = data?.system?.backtester_state || {};
    const drift = data?.drift || {};
    const prop = data?.prop?.status || {};
    const brain = data?.brain || {};

    return {
      gen: bs.generation || '-',
      tested: (bs.total_strategies_tested || 0).toLocaleString(),
      passed: bs.total_passed || 0,
      stagnation: cs.stagnation_counter || 0,
      exploreBoost: ((cs.exploration_boost || 0) * 100).toFixed(0) + '%',
      biasPenalty: ((cs.bias_penalty || 0) * 100).toFixed(0) + '%',
      shockFreq: (cs.shock_frequency_mult || 1).toFixed(1) + 'x',
      mutationBoost: ((cs.mutation_range_boost || 0) * 100).toFixed(0) + '%',
      propBalance: prop.balance ? `$${Number(prop.balance).toLocaleString()}` : '-',
      propPhase: prop.phase || '-',
      propDD: prop.peak && prop.balance ? ((prop.peak - prop.balance) / prop.peak * 100).toFixed(1) + '%' : '0%',
    };
  }, [data]);

  return (
    <div className="glass-card" style={{ padding: '16px 24px' }}>
      <div style={{
        fontSize: '0.65rem', color: '#64748b', fontWeight: 700,
        letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '12px',
      }}>
        DETAILS (DE-EMPHASIZED)
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px' }}>
        <Stat label="Tested" value={details.tested} />
        <Stat label="Passed" value={details.passed} />
        <Stat label="Stagnation" value={`${details.stagnation}/500`} />
        <Stat label="Explore Boost" value={details.exploreBoost} />
        <Stat label="Bias Penalty" value={details.biasPenalty} />
        <Stat label="Shock Freq" value={details.shockFreq} />
        <Stat label="Mutation Boost" value={details.mutationBoost} />
        <Stat label="Prop Balance" value={details.propBalance} />
        <Stat label="Prop Phase" value={details.propPhase} />
        <Stat label="Prop DD" value={details.propDD} />
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div style={{ padding: '8px 12px', borderRadius: '8px', background: 'rgba(255,255,255,0.02)' }}>
      <div style={{ fontSize: '0.6rem', color: '#475569', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
        {label}
      </div>
      <div style={{ fontSize: '0.9rem', color: '#94a3b8', fontWeight: 600, marginTop: '2px' }}>
        {value}
      </div>
    </div>
  );
}
