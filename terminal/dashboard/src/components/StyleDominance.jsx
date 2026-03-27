export default function StyleDominance({ data }) {
  const discovery = data?.discovery_rate;
  if (!discovery) return null;

  const dist = discovery.style_distribution || {};
  const total = Object.values(dist).reduce((a, b) => a + b, 0) || 1;
  const dominant = discovery.dominant_style || 'none';
  const dominance = discovery.style_dominance || 0;
  const buckets = discovery.trade_buckets || {};

  const styles = Object.entries(dist).sort((a, b) => b[1] - a[1]);
  const colors = {
    trend_following: '#3b82f6',
    mean_reversion: '#10b981',
    momentum_breakout: '#f59e0b',
    scalping: '#ef4444',
    volume_orderflow: '#8b5cf6',
    news: '#ec4899',
    news_reaction: '#f97316',
  };

  return (
    <div style={{
      background: 'rgba(255,255,255,0.03)',
      border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: '12px',
      padding: '16px 20px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <h3 style={{ margin: 0, fontSize: '0.85rem', color: '#94a3b8', fontWeight: 600 }}>
          STYLE DISTRIBUTION
        </h3>
        {dominance > 0.7 && (
          <span style={{ fontSize: '0.75rem', color: '#f59e0b', fontWeight: 600 }}>
            ⚠ {dominant} dominance {(dominance * 100).toFixed(0)}%
          </span>
        )}
      </div>

      {/* Style bars */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '16px' }}>
        {styles.map(([style, count]) => (
          <div key={style} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '0.75rem', color: '#94a3b8', width: '140px', textAlign: 'right' }}>
              {style.replace(/_/g, ' ')}
            </span>
            <div style={{ flex: 1, height: '8px', background: 'rgba(255,255,255,0.05)', borderRadius: '4px', overflow: 'hidden' }}>
              <div style={{
                width: `${(count / total * 100)}%`,
                height: '100%',
                background: colors[style] || '#64748b',
                borderRadius: '4px',
                transition: 'width 0.3s ease',
              }} />
            </div>
            <span style={{ fontSize: '0.75rem', color: '#64748b', width: '40px' }}>
              {(count / total * 100).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>

      {/* Trade count buckets */}
      {Object.keys(buckets).length > 0 && (
        <>
          <h4 style={{ margin: '0 0 8px', fontSize: '0.8rem', color: '#94a3b8', fontWeight: 600 }}>
            TRADE COUNT DISTRIBUTION
          </h4>
          <div style={{ display: 'flex', gap: '8px' }}>
            {Object.entries(buckets).map(([bucket, pct]) => (
              <div key={bucket} style={{
                flex: 1, textAlign: 'center', padding: '8px',
                background: bucket === '100+' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(255,255,255,0.03)',
                border: `1px solid ${bucket === '100+' ? 'rgba(16, 185, 129, 0.3)' : 'rgba(255,255,255,0.06)'}`,
                borderRadius: '8px',
              }}>
                <div style={{ fontSize: '0.7rem', color: '#64748b', marginBottom: '4px' }}>{bucket}</div>
                <div style={{
                  fontSize: '1rem', fontWeight: 700,
                  color: bucket === '100+' ? '#10b981' : bucket === '50-100' ? '#3b82f6' : '#94a3b8',
                }}>
                  {(pct * 100).toFixed(0)}%
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
