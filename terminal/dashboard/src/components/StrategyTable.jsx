function fmt(v, decimals = 2) {
  if (v == null || isNaN(v)) return '-';
  return Number(v).toFixed(decimals);
}

const statusColors = {
  OK: 'badge-green',
  WARMUP: 'badge-blue',
  REDUCE: 'badge-amber',
  KILL: 'badge-red',
};

const statusRowBg = {
  OK: '',
  WARMUP: 'bg-cyan/5',
  REDUCE: 'bg-warning/5',
  KILL: 'bg-danger/10',
};

export default function StrategyTable({ drift, brain }) {
  // drift.strategies is an object {name: {status, ...}} — convert to array
  const rawStrats = drift?.strategies ?? {};
  const strategies = Array.isArray(rawStrats)
    ? rawStrats
    : Object.entries(rawStrats).map(([name, data]) => ({ name, ...data }));
  const allocations = brain?.allocations ?? brain?.portfolio?.allocations ?? [];

  if (strategies.length === 0) {
    return (
      <div className="card">
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Active Strategies</h2>
        <div className="text-muted text-center py-6">No active strategies</div>
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Active Strategies</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-muted text-xs uppercase tracking-wider">
              <th className="text-left py-2 px-3">Strategy</th>
              <th className="text-left py-2 px-3">Style</th>
              <th className="text-center py-2 px-3">Status</th>
              <th className="text-right py-2 px-3">Weight</th>
              <th className="text-right py-2 px-3">Z-Score</th>
              <th className="text-right py-2 px-3">DD Ratio</th>
              <th className="text-right py-2 px-3">Exec Score</th>
              <th className="text-right py-2 px-3">Pressure</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map((s, i) => {
              const name = s.strategy ?? s.name ?? `Strategy ${i}`;
              const status = (s.status ?? s.action ?? 'OK').toUpperCase();
              const brainWeight = allocations[name];
              return (
                <tr
                  key={name + i}
                  className={`border-b border-border/30 hover:bg-accent/5 transition-colors ${statusRowBg[status] ?? ''}`}
                >
                  <td className="py-2 px-3 font-medium">{name}</td>
                  <td className="py-2 px-3 text-muted">{s.style ?? '-'}</td>
                  <td className="py-2 px-3 text-center">
                    <span className={`badge ${statusColors[status] ?? 'badge-gray'}`}>{status}</span>
                  </td>
                  <td className="py-2 px-3 text-right">
                    {fmt(s.weight ?? s.allocation, 1)}%
                    {brainWeight != null && brainWeight !== s.weight && (
                      <span className="text-muted text-xs ml-1">(→{fmt(brainWeight, 1)})</span>
                    )}
                  </td>
                  <td className="py-2 px-3 text-right" style={{
                    color: (s.z_score ?? s.zScore ?? 0) > 2 ? '#ef4444' : (s.z_score ?? s.zScore ?? 0) > 1 ? '#f59e0b' : '#e2e8f0'
                  }}>
                    {fmt(s.z_score ?? s.zScore)}
                  </td>
                  <td className="py-2 px-3 text-right">{fmt(s.dd_ratio ?? s.ddRatio)}</td>
                  <td className="py-2 px-3 text-right">{fmt(s.exec_score ?? s.execScore)}</td>
                  <td className="py-2 px-3 text-right" style={{
                    color: (s.prop_pressure ?? s.propPressure ?? 0) > 1.5 ? '#ef4444' : '#e2e8f0'
                  }}>
                    {fmt(s.prop_pressure ?? s.propPressure, 1)}x
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
