const severityColors = {
  CRITICAL: 'badge-red',
  HIGH: 'badge-amber',
  MEDIUM: 'badge-blue',
  LOW: 'badge-gray',
};

const severityDot = {
  CRITICAL: '#ef4444',
  HIGH: '#f59e0b',
  MEDIUM: '#06b6d4',
  LOW: '#64748b',
};

function formatTime(ts) {
  if (!ts) return '-';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  } catch {
    return String(ts);
  }
}

export default function AlertsPanel({ alerts }) {
  const items = (Array.isArray(alerts) ? alerts : (alerts?.alerts ?? [])).slice(0, 10);

  return (
    <div className="card h-full flex flex-col">
      <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Alerts</h2>
      
      {items.length === 0 ? (
        <div className="text-muted text-center py-6 flex-1 flex items-center justify-center">
          No alerts
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto space-y-2 pr-1" style={{ maxHeight: '300px' }}>
          {items.map((alert, i) => {
            const severity = (alert.severity ?? alert.level ?? 'LOW').toUpperCase();
            return (
              <div
                key={i}
                className="flex items-start gap-2 py-1.5 px-2 rounded-lg"
                style={{ background: 'rgba(15, 20, 40, 0.5)' }}
              >
                <div
                  className="w-2 h-2 rounded-full mt-1.5 shrink-0"
                  style={{ background: severityDot[severity] ?? '#64748b' }}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`badge ${severityColors[severity] ?? 'badge-gray'}`} style={{ fontSize: '0.6rem' }}>
                      {severity}
                    </span>
                    <span className="text-muted text-xs">{formatTime(alert.timestamp ?? alert.ts ?? alert.time)}</span>
                  </div>
                  <div className="text-xs mt-0.5 text-text leading-relaxed truncate">
                    {alert.message ?? alert.msg ?? alert.text ?? '-'}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
