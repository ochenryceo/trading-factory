export default function PressurePanel({ data }) {
  const pressure = data?.intelligence?.edge_pressure || {};
  const signals = pressure.signals || [];
  const level = pressure.level || 'LOW';

  const config = {
    CRITICAL: { emoji: '🔴', color: '#ef4444', meaning: 'System compressing toward phase transition — imminent' },
    HIGH: { emoji: '🔥', color: '#f97316', meaning: 'Pressure building — expansion approaching' },
    MODERATE: { emoji: '🟡', color: '#f59e0b', meaning: 'Normal exploration pressure' },
    LOW: { emoji: '🟢', color: '#22c55e', meaning: 'Early exploration — wide open space' },
  }[level] || { emoji: '⚪', color: '#64748b', meaning: '?' };

  return (
    <div className="glass-card" style={{ padding: '14px 16px' }}>
      <div style={{ fontSize: '0.5rem', color: '#475569', fontWeight: 700, letterSpacing: '0.15em', marginBottom: '8px' }}>
        EDGE PRESSURE
      </div>

      <div style={{
        fontSize: '1.4rem', fontWeight: 800, color: config.color, marginBottom: '8px',
        textShadow: `0 0 20px ${config.color}30`,
      }}>
        {config.emoji} {level}
      </div>

      <div style={{ marginBottom: '10px' }}>
        {signals.map((s, i) => (
          <div key={i} style={{ fontSize: '0.65rem', color: '#64748b', marginBottom: '3px' }}>
            • {s}
          </div>
        ))}
      </div>

      <div style={{
        fontSize: '0.65rem', color: config.color, fontStyle: 'italic',
        padding: '6px 8px', borderRadius: '6px',
        background: `${config.color}08`, border: `1px solid ${config.color}12`,
        lineHeight: 1.4,
      }}>
        {config.meaning}
      </div>
    </div>
  );
}
