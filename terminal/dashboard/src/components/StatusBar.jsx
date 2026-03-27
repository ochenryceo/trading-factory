import { useMemo } from 'react';

function computeHealthScore(data) {
  const discovery = data?.discovery;
  const prop = data?.prop?.status;
  const lastEntries = Array.isArray(discovery) ? discovery.slice(-10) : [];

  // Discovery rate trend (25%)
  let discTrend = 50;
  if (lastEntries.length >= 2) {
    const recent = lastEntries.slice(-5).reduce((s, e) => s + (e.rate || 0), 0) / Math.max(lastEntries.slice(-5).length, 1);
    const older = lastEntries.slice(0, 5).reduce((s, e) => s + (e.rate || 0), 0) / Math.max(lastEntries.slice(0, 5).length, 1);
    discTrend = older > 0 ? Math.min(100, Math.max(0, (recent / older) * 50)) : 50;
  }

  // Fitness mean (25%) — normalize 0-1 to 0-100
  const fitMean = lastEntries.length > 0 ? Math.min(100, Math.max(0, (lastEntries[lastEntries.length - 1]?.fitness_mean || 0) * 100)) : 50;

  // Fitness std (25%) — lower is better
  const fitStd = lastEntries.length > 0 ? Math.min(100, Math.max(0, 100 - (lastEntries[lastEntries.length - 1]?.fitness_std || 0) * 200)) : 50;

  // Prop health (25%)
  let propHealth = 50;
  if (prop) {
    const dd = prop.peak > 0 ? ((prop.peak - prop.balance) / prop.peak) * 100 : 0;
    propHealth = Math.max(0, Math.min(100, 100 - dd * 10));
  }

  return Math.round(discTrend * 0.25 + fitMean * 0.25 + fitStd * 0.25 + propHealth * 0.25);
}

function computeRisk(data) {
  const prop = data?.prop?.status;
  const drift = data?.drift?.strategies || {};
  const kills = Object.values(drift).filter(s => s.status === 'KILL').length;
  let dd = 0;
  if (prop && prop.peak > 0) dd = ((prop.peak - prop.balance) / prop.peak) * 100;
  if (dd > 5 || kills > 3) return { label: 'CRITICAL', color: '#ef4444' };
  if (dd > 4 || kills > 2) return { label: 'HIGH', color: '#f97316' };
  if (dd > 2 || kills > 1) return { label: 'MODERATE', color: '#f59e0b' };
  return { label: 'LOW', color: '#22c55e' };
}

export default function StatusBar({ data, connected }) {
  const health = useMemo(() => computeHealthScore(data), [data]);
  const risk = useMemo(() => computeRisk(data), [data]);

  const prop = data?.prop?.status;
  const system = data?.system;
  const controlState = system?.control_state || data?.control?.control_state;
  const backtester = system?.backtester_state;
  const lastDiscovery = Array.isArray(data?.discovery) && data.discovery.length > 0 ? data.discovery[data.discovery.length - 1] : null;

  const generation = lastDiscovery?.generation ?? backtester?.generation ?? '-';
  const phase = prop?.phase || 'UNKNOWN';
  const balance = prop?.balance;

  const barClass = health > 70 ? 'status-bar-green' : health > 40 ? 'status-bar-yellow' : 'status-bar-red';
  const healthColor = health > 70 ? '#22c55e' : health > 40 ? '#f59e0b' : '#ef4444';
  const healthEmoji = health > 70 ? '🟢' : health > 40 ? '🟡' : '🔴';

  const phaseBadge = {
    WARMUP: 'badge-cyan', LEARNING: 'badge-indigo', MATURE: 'badge-green',
    FUNDED: 'badge-green', EVALUATION: 'badge-amber', UNKNOWN: 'badge-gray',
  }[phase?.toUpperCase()] || 'badge-gray';

  const statusLabel = controlState?.last_action || backtester?.status || 'IDLE';

  return (
    <div className={`status-bar ${barClass}`} style={{
      padding: '10px 24px', display: 'flex', alignItems: 'center', justifyContent: 'center',
      gap: '24px', flexWrap: 'wrap', position: 'sticky', top: 0, zIndex: 100,
    }}>
      {/* Health */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '0.7rem', color: '#94a3b8', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>System Health</span>
        <span style={{ fontSize: '1.1rem', fontWeight: 700, color: healthColor }}>{health}/100</span>
        <span>{healthEmoji}</span>
      </div>

      <Divider />

      {/* Phase */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <span style={{ fontSize: '0.7rem', color: '#94a3b8', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Phase</span>
        <span className={`badge ${phaseBadge}`}>{phase}</span>
      </div>

      <Divider />

      {/* Generation */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <span style={{ fontSize: '0.7rem', color: '#94a3b8', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Gen</span>
        <span style={{ fontSize: '1rem', fontWeight: 700, color: '#6366f1' }}>{generation}</span>
      </div>

      <Divider />

      {/* Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <span style={{ fontSize: '0.7rem', color: '#94a3b8', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Status</span>
        <span className="badge badge-indigo">{statusLabel}</span>
      </div>

      <Divider />

      {/* Risk */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <span style={{ fontSize: '0.7rem', color: '#94a3b8', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Risk</span>
        <span style={{ fontWeight: 700, color: risk.color, fontSize: '0.85rem' }}>{risk.label}</span>
      </div>

      <Divider />

      {/* Prop */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <span style={{ fontSize: '0.7rem', color: '#94a3b8', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Prop</span>
        <span style={{
          fontWeight: 700, fontSize: '0.9rem',
          color: balance != null ? (balance >= (prop?.starting_balance || 0) ? '#22c55e' : '#ef4444') : '#94a3b8'
        }}>
          {balance != null ? `$${Number(balance).toLocaleString()}` : '-'}
        </span>
      </div>

      {!connected && (
        <>
          <Divider />
          <span style={{ color: '#ef4444', fontWeight: 700, fontSize: '0.75rem', animation: 'pulse-glow 1.5s ease-in-out infinite' }}>● DISCONNECTED</span>
        </>
      )}
    </div>
  );
}

function Divider() {
  return <span style={{ color: 'rgba(99, 102, 241, 0.2)', fontSize: '0.9rem' }}>│</span>;
}
