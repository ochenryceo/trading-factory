import { useMemo } from 'react';

export default function MetricsPanel({ data }) {
  const m = useMemo(() => {
    const cs = data?.control?.control_state || data?.system?.control_state || {};
    const bs = data?.system?.backtester_state || {};
    const prop = data?.prop?.status || {};
    const disc = Array.isArray(data?.discovery) ? data.discovery : [];

    let gph = 48;
    if (disc.length >= 20) {
      const first = disc[disc.length - 20];
      const last = disc[disc.length - 1];
      const gd = (last?.generation || 0) - (first?.generation || 0);
      const hd = Math.max(0.1, (new Date(last?.timestamp || 0) - new Date(first?.timestamp || 0)) / 3600000);
      if (gd > 0) gph = gd / hd;
    }

    return [
      { label: 'Tested', value: (bs.total_strategies_tested || 0).toLocaleString() },
      { label: 'Passed', value: bs.total_passed || 0 },
      { label: 'Speed', value: `${Math.round(gph)} gen/h` },
      { label: 'Prop', value: prop.balance ? `$${Number(prop.balance).toLocaleString()}` : '-' },
      { label: 'Explore', value: `${((cs.exploration_boost || 0) * 100).toFixed(0)}%` },
      { label: 'Bias Pen.', value: `${((cs.bias_penalty || 0) * 100).toFixed(0)}%` },
      { label: 'Shock', value: `${(cs.shock_frequency_mult || 1).toFixed(1)}x` },
      { label: 'Mutation', value: `${((cs.mutation_range_boost || 0) * 100).toFixed(0)}%` },
    ];
  }, [data]);

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '16px',
      padding: '10px 20px', borderRadius: '10px',
      background: 'rgba(255,255,255,0.015)',
      border: '1px solid rgba(255,255,255,0.03)',
      overflowX: 'auto',
    }}>
      <div style={{ fontSize: '0.55rem', color: '#334155', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', flexShrink: 0 }}>
        METRICS
      </div>
      {m.map((item, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'baseline', gap: '4px', flexShrink: 0 }}>
          <span style={{ fontSize: '0.55rem', color: '#334155', fontWeight: 600 }}>{item.label}:</span>
          <span style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600 }}>{item.value}</span>
        </div>
      ))}
    </div>
  );
}
