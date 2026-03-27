function fmt(v, decimals = 2) {
  if (v == null || isNaN(v)) return '-';
  return Number(v).toFixed(decimals);
}

function fmtDollar(v) {
  if (v == null || isNaN(v)) return '-';
  return '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const riskColors = {
  SAFE: 'badge-green',
  CAUTION: 'badge-amber',
  DANGER: 'badge-red',
  CRITICAL: 'badge-red pulse-glow',
};

const phaseLabels = {
  challenge: 'Challenge',
  phase2: 'Phase 2',
  funded: 'Funded',
};

function ddColor(pct) {
  if (pct < 3) return '#22c55e';
  if (pct < 6) return '#f59e0b';
  return '#ef4444';
}

export default function PropPanel({ prop }) {
  const acc = prop?.status ?? {};
  const balance = acc.balance ?? 50000;
  const starting = acc.starting_balance ?? 50000;
  const profitPct = starting > 0 ? ((balance - starting) / starting * 100) : 0;
  const peak = acc.peak ?? balance;
  const totalDD = peak > 0 ? ((peak - balance) / peak * 100) : 0;
  const dailyPnl = acc.daily_pnl ?? {};
  const today = new Date().toISOString().slice(0, 10);
  const dailyDD = starting > 0 ? (Math.abs(dailyPnl[today] ?? 0) / starting * 100) : 0;
  const phase = acc.phase ?? 'phase_1';
  const startDate = acc.start_date ? new Date(acc.start_date) : new Date();
  const day = Math.floor((Date.now() - startDate.getTime()) / 86400000);
  const maxDays = phase === 'phase_2' ? 60 : phase === 'funded' ? '∞' : 30;
  const totalTrades = acc.total_trades ?? 0;
  const wins = acc.wins ?? 0;
  const winRate = totalTrades > 0 ? (wins / totalTrades * 100).toFixed(0) + '%' : '-';
  // Risk zone from DD
  const riskZone = totalDD < 2 ? 'SAFE' : totalDD < 4 ? 'CAUTION' : totalDD < 5 ? 'DANGER' : 'CRITICAL';
  const pressure = totalDD < 2 ? 1.0 : totalDD < 4 ? 0.7 : totalDD < 5 ? 0.4 : 0.2;
  const targetPct = phase === 'phase_2' ? 5 : phase === 'funded' ? null : 10;

  return (
    <div className="card h-full flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wider">Prop Account</h2>
        <span className="badge badge-purple">{phaseLabels[phase] ?? phase}</span>
      </div>

      <div>
        <div className="text-3xl font-bold" style={{ color: '#06b6d4' }}>
          {fmtDollar(balance)}
        </div>
      </div>

      <div>
        <div className="flex justify-between text-xs mb-1">
          <span className="text-muted">Profit</span>
          <span className="text-success">{fmt(profitPct)}% / {fmt(targetPct)}%</span>
        </div>
        <div className="gauge-track">
          <div
            className="gauge-fill"
            style={{
              width: `${Math.min(100, Math.max(0, (profitPct / targetPct) * 100))}%`,
              background: 'linear-gradient(90deg, #22c55e, #06b6d4)',
            }}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-muted text-xs mb-1">Total DD</div>
          <div className="text-lg font-semibold" style={{ color: ddColor(totalDD) }}>
            {fmt(totalDD)}%
          </div>
          <div className="gauge-track mt-1">
            <div
              className="gauge-fill"
              style={{
                width: `${Math.min(100, (totalDD / 10) * 100)}%`,
                background: ddColor(totalDD),
              }}
            />
          </div>
        </div>
        <div>
          <div className="text-muted text-xs mb-1">Daily DD</div>
          <div className="text-lg font-semibold" style={{ color: ddColor(dailyDD) }}>
            {fmt(dailyDD)}%
          </div>
          <div className="gauge-track mt-1">
            <div
              className="gauge-fill"
              style={{
                width: `${Math.min(100, (dailyDD / 5) * 100)}%`,
                background: ddColor(dailyDD),
              }}
            />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className="text-muted text-xs">Day</div>
          <div className="font-semibold">{day} / {maxDays}</div>
        </div>
        <div>
          <div className="text-muted text-xs">Win Rate</div>
          <div className="font-semibold text-success">{typeof winRate === 'number' ? fmt(winRate) + '%' : winRate}</div>
        </div>
        <div>
          <div className="text-muted text-xs">Pressure</div>
          <div className="font-semibold" style={{ color: pressure > 1.5 ? '#ef4444' : pressure > 1.2 ? '#f59e0b' : '#e2e8f0' }}>
            {fmt(pressure, 1)}x
          </div>
        </div>
      </div>

      <div className="mt-auto flex justify-center">
        <span className={`badge ${riskColors[riskZone] ?? 'badge-gray'}`}>
          ● {riskZone}
        </span>
      </div>
    </div>
  );
}
