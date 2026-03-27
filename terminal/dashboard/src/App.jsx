import { useApi } from './hooks/useApi';
import CommandBar from './components/CommandBar';
import IntentPanel from './components/IntentPanel';
import HeroPanel from './components/HeroPanel';
import RiskCore from './components/RiskCore';
import BlockersPanel from './components/BlockersPanel';
import PipelinePanel from './components/PipelinePanel';
import PressurePanel from './components/PressurePanel';
import AlertFeed from './components/AlertFeed';
import ExpectationBar from './components/ExpectationBar';
import MetricsPanel from './components/MetricsPanel';

export default function App() {
  const { data, connected } = useApi();

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: '#0a0a1a' }}>
      {/* ① GLOBAL COMMAND BAR */}
      <CommandBar data={data} connected={connected} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', padding: '10px 14px 20px', maxWidth: '1700px', margin: '0 auto', width: '100%' }}>

        {!connected && (
          <div style={{
            textAlign: 'center', padding: '8px',
            background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
            borderRadius: '8px', color: '#ef4444', fontWeight: 600, fontSize: '0.75rem',
            animation: 'pulse-glow 2s ease-in-out infinite',
          }}>
            ⚠ CONNECTION LOST — Attempting reconnect...
          </div>
        )}

        {/* ② ③ ④ Row: Intent (20%) + Hero (50%) + Risk (30%) */}
        <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr 280px', gap: '10px' }}>
          <IntentPanel data={data} />
          <HeroPanel data={data} />
          <RiskCore data={data} />
        </div>

        {/* ⑤ ⑥ ⑦ ⑧ Row: Blockers + Pipeline + Pressure + Alerts */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 220px 1fr 1fr', gap: '10px' }}>
          <BlockersPanel data={data} />
          <PipelinePanel data={data} />
          <PressurePanel data={data} />
          <AlertFeed data={data} />
        </div>

        {/* Expectation match bar */}
        <ExpectationBar data={data} />

        {/* Metrics footer */}
        <MetricsPanel data={data} />
      </div>
    </div>
  );
}
