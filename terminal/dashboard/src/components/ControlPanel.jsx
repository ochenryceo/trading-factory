function fmt(v, decimals = 2) {
  if (v == null || isNaN(v)) return '-';
  return Number(v).toFixed(decimals);
}

const actionColors = {
  stable: 'badge-green',
  adapting: 'badge-amber',
  correcting: 'badge-red',
  boosting: 'badge-blue',
};

export default function ControlPanel({ control }) {
  const cs = control?.control_state ?? {};
  const explorationBoost = cs.exploration_boost ?? 0;
  const biasPenalty = cs.bias_penalty ?? 0;
  const mutRangeBoost = cs.mutation_range_boost ?? 0;
  const shockMult = cs.shock_frequency_mult ?? 1.0;
  // Compute approximate ratios from control adjustments
  const baseRandom = 0.4 + explorationBoost;
  const baseEvolve = Math.max(0, 0.2 - biasPenalty * 0.3);
  const baseMutate = Math.max(0.1, 1.0 - baseRandom - baseEvolve);
  const randomPct = baseRandom * 100;
  const evolutionPct = baseEvolve * 100;
  const mutationPct = baseMutate * 100;
  const mutationRange = (cs.mutation_range_boost ?? 0) * 100 + 10;
  const shockFreq = Math.max(5, Math.round(50 / shockMult));
  const biasInfluence = control?.adaptive_bias ? Object.keys(control.adaptive_bias).length * 10 : 0;
  const action = cs.last_action ?? 'stable';
  const stagnation = cs.stagnation_counter ?? 0;

  const total = randomPct + evolutionPct + mutationPct || 1;
  const rW = (randomPct / total) * 100;
  const eW = (evolutionPct / total) * 100;
  const mW = (mutationPct / total) * 100;

  return (
    <div className="card h-full flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wider">Control</h2>
        <span className={`badge ${actionColors[action] ?? 'badge-gray'}`}>{action}</span>
      </div>

      <div>
        <div className="text-muted text-xs mb-1">Strategy Mix</div>
        <div className="flex rounded-md overflow-hidden h-6">
          {rW > 0 && (
            <div
              className="flex items-center justify-center text-xs font-medium"
              style={{ width: `${rW}%`, background: '#6366f1', minWidth: rW > 5 ? 'auto' : 0 }}
              title={`Random: ${fmt(randomPct)}%`}
            >
              {rW > 15 ? `R ${fmt(randomPct, 0)}%` : ''}
            </div>
          )}
          {eW > 0 && (
            <div
              className="flex items-center justify-center text-xs font-medium"
              style={{ width: `${eW}%`, background: '#06b6d4', minWidth: eW > 5 ? 'auto' : 0 }}
              title={`Evolution: ${fmt(evolutionPct)}%`}
            >
              {eW > 15 ? `E ${fmt(evolutionPct, 0)}%` : ''}
            </div>
          )}
          {mW > 0 && (
            <div
              className="flex items-center justify-center text-xs font-medium"
              style={{ width: `${mW}%`, background: '#f59e0b', minWidth: mW > 5 ? 'auto' : 0 }}
              title={`Mutation: ${fmt(mutationPct)}%`}
            >
              {mW > 15 ? `M ${fmt(mutationPct, 0)}%` : ''}
            </div>
          )}
        </div>
        <div className="flex justify-between text-xs text-muted mt-1">
          <span>Random</span>
          <span>Evolution</span>
          <span>Mutation</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-muted text-xs">Mutation Range</div>
          <div className="font-semibold">±{fmt(mutationRange)}%</div>
        </div>
        <div>
          <div className="text-muted text-xs">Shock Freq</div>
          <div className="font-semibold">{typeof shockFreq === 'number' ? `1/${shockFreq}` : shockFreq}</div>
        </div>
      </div>

      <div>
        <div className="text-muted text-xs mb-1">Bias Influence</div>
        <div className="gauge-track">
          <div
            className="gauge-fill"
            style={{
              width: `${Math.min(100, Number(biasInfluence) || 0)}%`,
              background: 'linear-gradient(90deg, #6366f1, #06b6d4)',
            }}
          />
        </div>
        <div className="text-right text-xs mt-0.5">{fmt(biasInfluence, 0)}%</div>
      </div>

      <div className="mt-auto flex items-center justify-between">
        <div>
          <div className="text-muted text-xs">Stagnation</div>
          <div className="font-semibold" style={{ color: stagnation > 10 ? '#ef4444' : stagnation > 5 ? '#f59e0b' : '#e2e8f0' }}>
            {stagnation}
          </div>
        </div>
      </div>
    </div>
  );
}
