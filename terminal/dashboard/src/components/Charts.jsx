import {
  LineChart, Line, AreaChart, Area,
  XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid,
} from 'recharts';

const tooltipStyle = {
  backgroundColor: 'rgba(15, 20, 40, 0.95)',
  border: '1px solid rgba(99, 102, 241, 0.3)',
  borderRadius: '8px',
  fontSize: '12px',
  color: '#e2e8f0',
};

function fmt(v) {
  if (v == null) return '-';
  return Number(v).toFixed(4);
}

export default function Charts({ discovery, fitnessHistory }) {
  const discoveryData = (Array.isArray(discovery) ? discovery : (discovery?.entries ?? []))
    .slice(-50)
    .map((d, i) => ({
      gen: d.generation ?? d.gen ?? i,
      rate: d.rate ?? d.discovery_rate ?? 0,
    }));

  const fitnessData = (Array.isArray(fitnessHistory) ? fitnessHistory : (fitnessHistory?.entries ?? []))
    .map((d, i) => ({
      gen: d.generation ?? d.gen ?? i,
      mean: d.mean ?? d.fitness_mean ?? 0,
      std: d.std ?? d.fitness_std ?? 0,
      upper: (d.mean ?? d.fitness_mean ?? 0) + (d.std ?? d.fitness_std ?? 0),
      lower: Math.max(0, (d.mean ?? d.fitness_mean ?? 0) - (d.std ?? d.fitness_std ?? 0)),
    }));

  return (
    <div className="card">
      <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Trends</h2>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Discovery Rate */}
        <div>
          <div className="text-xs text-muted mb-2">Discovery Rate (Last 50 Generations)</div>
          <div style={{ height: 160 }}>
            {discoveryData.length > 1 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={discoveryData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(100,116,139,0.15)" />
                  <XAxis
                    dataKey="gen"
                    tick={{ fill: '#64748b', fontSize: 10 }}
                    axisLine={{ stroke: 'rgba(100,116,139,0.2)' }}
                  />
                  <YAxis
                    tick={{ fill: '#64748b', fontSize: 10 }}
                    axisLine={{ stroke: 'rgba(100,116,139,0.2)' }}
                    tickFormatter={fmt}
                  />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Line
                    type="monotone"
                    dataKey="rate"
                    stroke="#06b6d4"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 3, fill: '#06b6d4' }}
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="text-muted text-center py-10 text-sm">Waiting for data...</div>
            )}
          </div>
        </div>

        {/* Fitness Mean + Std */}
        <div>
          <div className="text-xs text-muted mb-2">Fitness Mean ± Std</div>
          <div style={{ height: 160 }}>
            {fitnessData.length > 1 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={fitnessData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(100,116,139,0.15)" />
                  <XAxis
                    dataKey="gen"
                    tick={{ fill: '#64748b', fontSize: 10 }}
                    axisLine={{ stroke: 'rgba(100,116,139,0.2)' }}
                  />
                  <YAxis
                    tick={{ fill: '#64748b', fontSize: 10 }}
                    axisLine={{ stroke: 'rgba(100,116,139,0.2)' }}
                    tickFormatter={fmt}
                  />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Area
                    type="monotone"
                    dataKey="upper"
                    stroke="none"
                    fill="rgba(99, 102, 241, 0.15)"
                  />
                  <Area
                    type="monotone"
                    dataKey="lower"
                    stroke="none"
                    fill="#0a0a1a"
                  />
                  <Line
                    type="monotone"
                    dataKey="mean"
                    stroke="#6366f1"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 3, fill: '#6366f1' }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="text-muted text-center py-10 text-sm">Waiting for data...</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
