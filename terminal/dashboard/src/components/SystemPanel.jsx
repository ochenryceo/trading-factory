import { LineChart, Line, ResponsiveContainer } from 'recharts';

const phaseColors = {
  WARMUP: 'badge-blue',
  LEARNING: 'badge-amber',
  MATURE: 'badge-green',
};

const controlColors = {
  stable: 'badge-green',
  adapting: 'badge-amber',
  correcting: 'badge-red',
};

function trendArrow(data) {
  if (!data || data.length < 2) return '→';
  const recent = data.slice(-5);
  const first = recent[0]?.rate ?? recent[0]?.discovery_rate ?? 0;
  const last = recent[recent.length - 1]?.rate ?? recent[recent.length - 1]?.discovery_rate ?? 0;
  if (last > first * 1.05) return '↑';
  if (last < first * 0.95) return '↓';
  return '→';
}

function fmt(v, decimals = 2) {
  if (v == null || isNaN(v)) return '-';
  return Number(v).toFixed(decimals);
}

export default function SystemPanel({ system, discovery, control, fitnessHistory }) {
  const bt = system?.backtester_state ?? {};
  const health = system?.health_snapshot ?? {};
  const ctrl = control?.control_state ?? system?.control_state ?? {};
  const phase = health.phase ?? 'WARMUP';
  const generation = bt.generation ?? health.generation ?? '-';
  const discoveryData = Array.isArray(discovery) ? discovery : (discovery?.entries ?? []);
  const lastDiscovery = discoveryData.length > 0
    ? (discoveryData[discoveryData.length - 1]?.rate ?? discoveryData[discoveryData.length - 1]?.discovery_rate ?? '-')
    : (health.discovery_rate ?? '-');
  const fitMean = health.fitness_mean ?? '-';
  const fitStd = health.fitness_std ?? '-';
  const biasInfluence = health.bias_influence ?? ctrl.bias_influence ?? 0;
  const controlState = ctrl.last_action ?? health.control_action ?? 'stable';

  const sparkData = discoveryData.slice(-50).map((d, i) => ({
    i,
    v: d.rate ?? d.discovery_rate ?? 0,
  }));

  return (
    <div className="card h-full flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wider">System State</h2>
        <span className={`badge ${phaseColors[phase] ?? 'badge-gray'}`}>{phase}</span>
      </div>

      <div className="flex items-end gap-2">
        <span className="text-4xl font-bold glow-text" style={{ color: '#6366f1' }}>
          G{generation}
        </span>
        <span className="text-muted text-xs mb-1">generation</span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-muted text-xs mb-1">Discovery Rate</div>
          <div className="text-lg font-semibold text-cyan">
            {fmt(lastDiscovery)} {trendArrow(discoveryData)}
          </div>
        </div>
        <div>
          <div className="text-muted text-xs mb-1">Control</div>
          <span className={`badge ${controlColors[controlState] ?? 'badge-gray'}`}>
            {controlState}
          </span>
        </div>
      </div>

      <div>
        <div className="text-muted text-xs mb-1">Fitness Mean / Std</div>
        <div className="flex gap-4">
          <span className="text-success font-semibold">{fmt(fitMean, 4)}</span>
          <span className="text-muted">±</span>
          <span className="text-warning font-semibold">{fmt(fitStd, 4)}</span>
        </div>
        <div className="gauge-track mt-1">
          <div
            className="gauge-fill"
            style={{
              width: `${Math.min(100, Math.max(0, (Number(fitMean) || 0) * 100))}%`,
              background: 'linear-gradient(90deg, #6366f1, #06b6d4)',
            }}
          />
        </div>
      </div>

      <div>
        <div className="text-muted text-xs mb-1">Bias Influence</div>
        <div className="flex items-center gap-2">
          <div className="relative w-12 h-12">
            <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
              <circle cx="18" cy="18" r="15" fill="none" stroke="rgba(100,116,139,0.2)" strokeWidth="3" />
              <circle
                cx="18" cy="18" r="15" fill="none"
                stroke="#6366f1"
                strokeWidth="3"
                strokeDasharray={`${(Number(biasInfluence) || 0) * 0.9425} 94.25`}
                strokeLinecap="round"
              />
            </svg>
            <span className="absolute inset-0 flex items-center justify-center text-xs font-bold">
              {fmt(biasInfluence, 0)}%
            </span>
          </div>
        </div>
      </div>

      {sparkData.length > 2 && (
        <div className="mt-auto" style={{ height: 50 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={sparkData}>
              <Line type="monotone" dataKey="v" stroke="#06b6d4" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
