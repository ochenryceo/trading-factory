"""🧠 BRAIN MAP — Mission Control for the AI Brain"""
import streamlit as st
import json, os, sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from components.layout import inject_theme, page_header
from components.metric_tile import metric_row

st.set_page_config(page_title="Brain Map", page_icon="🧠", layout="wide")
inject_theme()

DATA = Path(__file__).resolve().parents[2] / "data"

def load_json(path):
    try:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except:
        pass
    return {}

# ── CSS ──────────────────────────────────────────────────────────────
st.markdown("""<style>
.agent-card {
    background: #161616;
    border-radius: 6px;
    padding: 14px 10px;
    text-align: center;
    height: 100%;
}
.agent-emoji { font-size: 1.5rem; }
.agent-name { font-size: 0.85rem; font-weight: 700; color: #e0e0e0; margin-top: 4px; }
.agent-role { font-size: 0.65rem; color: #888; }
.agent-status { font-size: 0.6rem; margin-top: 6px; text-transform: uppercase; }
.agent-detail { font-size: 0.62rem; color: #00e5ff; margin-top: 4px; }
.agent-action { font-size: 0.6rem; color: #555; margin-top: 2px; }
.section-title { font-size: 0.7rem; color: #555; text-transform: uppercase; letter-spacing: 2px; margin: 20px 0 10px 0; }
.flow-box { background: #1a1a2e; border-radius: 4px; padding: 4px 10px; font-size: 0.72rem; display: inline-block; }
.flow-arrow { color: #333; font-size: 0.8rem; }
.cluster-bar { background: #222; border-radius: 2px; height: 10px; flex: 1; }
</style>""", unsafe_allow_html=True)

def card(emoji, name, role, status, border="#333", focus="", action="", detail=""):
    sc = {"active":"#00c853","thinking":"#ffc107","idle":"#555","issue":"#ff1744"}.get(status,"#555")
    f_html = f'<div class="agent-detail">📌 {focus}</div>' if focus else ""
    a_html = f'<div class="agent-action">↳ {action}</div>' if action else ""
    d_html = f'<div class="agent-detail">{detail}</div>' if detail else ""
    st.markdown(f"""
    <div class="agent-card" style="border:1px solid {border};">
        <div class="agent-emoji">{emoji}</div>
        <div class="agent-name">{name}</div>
        <div class="agent-role">{role}</div>
        <div class="agent-status" style="color:{sc};">● {status}</div>
        {f_html}{a_html}{d_html}
    </div>""", unsafe_allow_html=True)

# ── Load Data ────────────────────────────────────────────────────────
brain = load_json(DATA / "brain_intelligence.json")
metrics = brain.get("metrics", {})
intel = brain.get("intelligence", {})
best_c = brain.get("best_clusters", [])
worst_c = brain.get("worst_clusters", [])
vault = load_json(DATA / "vault_knowledge.json")
lb = load_json(DATA / "continuous_leaderboard.json")
fp = load_json(DATA / "failure_patterns.json")

sph = metrics.get("strategies_per_hour", 0)
pr = metrics.get("pass_rate", 0)
eff = metrics.get("compute_efficiency", 0)
tested = metrics.get("total_tested", 0)
passed = metrics.get("total_passed", 0)
top_c = best_c[0]["cluster"] if best_c else "—"
weak_c = worst_c[0]["cluster"] if worst_c else "—"

# ── HEADER ───────────────────────────────────────────────────────────
page_header("🧠 BRAIN MAP", "Mission Control — Live Intelligence Flow")

metric_row([
    {"label": "⚡ Strategies/hr", "value": f"{sph:,}", "color": "#00e5ff"},
    {"label": "✅ Pass Rate", "value": f"{pr:.0%}", "color": "#00c853" if pr > 0.1 else "#ffc107"},
    {"label": "📊 Total Tested", "value": f"{tested:,}", "color": "#e0e0e0"},
    {"label": "🏆 Top Cluster", "value": top_c[:18], "color": "#00c853"},
    {"label": "📉 Weak Cluster", "value": weak_c[:18], "color": "#ff1744"},
])

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

# ── INTELLIGENCE FLOW ────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center;padding:14px;background:#0a0a0a;border:1px solid #1a1a2e;border-radius:8px;margin-bottom:20px;">
    <div class="section-title">Command Chain</div>
    <div style="display:flex;align-items:center;justify-content:center;gap:6px;flex-wrap:wrap;margin-top:8px;">
        <span class="flow-box" style="border:1px solid #00e5ff;color:#00e5ff;">🧠 Henry</span>
        <span class="flow-arrow">→</span>
        <span class="flow-box" style="border:1px solid #ffc107;color:#ffc107;">🎯 Apex</span>
        <span class="flow-arrow">→</span>
        <span class="flow-box" style="border:1px solid #aa00ff;color:#aa00ff;">🧠⚡ Think</span>
        <span class="flow-arrow">→</span>
        <span class="flow-box" style="border:1px solid #ff6d00;color:#ff6d00;">📋 Schedule</span>
        <span class="flow-arrow">→</span>
        <span class="flow-box" style="border:1px solid #00c853;color:#00c853;">🎮 GPU</span>
        <span class="flow-arrow">→</span>
        <span class="flow-box" style="border:1px solid #2979ff;color:#2979ff;">🤖 Validate</span>
        <span class="flow-arrow">→</span>
        <span class="flow-box" style="border:1px solid #e0e0e0;color:#e0e0e0;">👁️ Decide</span>
        <span class="flow-arrow">→</span>
        <span class="flow-box" style="border:1px solid #555;color:#888;">🔐 Store</span>
    </div>
    <div style="font-size:0.55rem;color:#333;margin-top:8px;">
        🔄 Learning: Darwin → Vault → Strategist → Scheduler &nbsp;&nbsp;|&nbsp;&nbsp;
        ❌ Failure: Rejected → Vault → Rebel → Strategist &nbsp;&nbsp;|&nbsp;&nbsp;
        ⚡ Resource: Sentinel → Henry → Scheduler
    </div>
</div>
""", unsafe_allow_html=True)

# ── EXECUTIVE LAYER ──────────────────────────────────────────────────
st.markdown('<div class="section-title">🧠 EXECUTIVE LAYER</div>', unsafe_allow_html=True)

best_assets = list(intel.get("best_per_asset", {}).keys())
focus = f"{best_assets[0]} short-TF expansion" if best_assets else "Strategy discovery"

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    card("🧠", "HENRY", "Supreme Orchestrator", "active", "#00e5ff",
         focus=focus, action=f"Brain cycle: {sph:,}/hr, {pr:.0%} pass rate")
with c2:
    card("🎯", "APEX", "R&D Direction", "idle",
         detail="Activates on conflict/decision")
with c3:
    card("👁️", "OVERSEER", "Final Authority", "active", "#ff1744",
         focus="7 directives enforced", action="Monitoring all promotions")

# ── INTELLIGENCE LAYER ───────────────────────────────────────────────
st.markdown('<div class="section-title">🧬 INTELLIGENCE LAYER</div>', unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)
with c1:
    insight = f"Best: {best_c[0]['cluster']}" if best_c else "Analyzing..."
    card("🧠", "STRATEGIST", "Pattern Detection", "thinking" if best_c else "idle", "#aa00ff",
         focus="Cluster intelligence", detail=insight)
with c2:
    n_sat = len(intel.get("saturated_clusters", []))
    card("⚡", "REBEL", "Challenge Assumptions", "thinking" if n_sat else "idle", "#aa00ff",
         focus="Overfit detection", detail=f"Watching {n_sat} saturated clusters")
with c3:
    card("🤖", "DARWIN", "Truth Validation", "active", "#2979ff",
         focus=f"{passed} validated", detail=f"Pass rate: {pr:.0%}")

# ── CONTROL LAYER ────────────────────────────────────────────────────
st.markdown('<div class="section-title">⚙️ CONTROL LAYER — Telemetry</div>', unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
with c1:
    card("📋", "SCHEDULER", "CPU Allocation", "active", "#ff6d00",
         focus=f"→ {top_c[:20]}", detail=f"↓ {weak_c[:20]}")
with c2:
    card("🎮", "GPU DISPATCH", "GPU Batching", "active", "#00c853",
         focus="6 agents on Machine B", detail="L4 GPU — 23GB VRAM")
with c3:
    card("💾", "CACHE", "RAM Optimizer", "active",
         focus="24.8M bars in memory", detail="3 assets × 6 timeframes")
with c4:
    load_avg = os.getloadavg()[0]
    health = "active" if load_avg < 4 else "issue"
    card("📈", "SENTINEL", "System Health", health,
         focus=f"Load: {load_avg:.1f}", detail="Machine A: healthy")

# ── EXECUTION SUPPORT ────────────────────────────────────────────────
st.markdown('<div class="section-title">🔧 EXECUTION SUPPORT</div>', unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
with c1:
    card("📊", "FEED", "Market Data", "active", focus="NQ + GC + CL")
with c2:
    card("📰", "PULSE", "Sentiment", "idle", detail="Event-driven")
with c3:
    v_size = len(vault.get("cluster_performance", {}))
    v_out = vault.get("strategy_outcomes", {})
    card("🔐", "VAULT", "Knowledge System", "active",
         focus=f"{v_size} clusters tracked",
         detail=f"{v_out.get('passed',0)} wins / {v_out.get('failed',0)} fails")
with c4:
    card("⚙️", "BOLT", "Task Translation", "idle", detail="Event-driven")

# ── CLUSTER INTELLIGENCE ─────────────────────────────────────────────
st.markdown('<div class="section-title">🧬 CLUSTER INTELLIGENCE</div>', unsafe_allow_html=True)

c1, c2 = st.columns(2)
with c1:
    st.markdown("**🏆 Top Performers**")
    for c in best_c[:5]:
        rp = int(c["pass_rate"] * 100)
        bw = min(rp, 100)
        st.markdown(f"""<div style="display:flex;align-items:center;gap:6px;padding:3px 0;font-size:0.72rem;">
            <span style="color:#00c853;width:180px;font-family:monospace;">{c['cluster']}</span>
            <div class="cluster-bar"><div style="width:{bw}%;background:#00c853;height:10px;border-radius:2px;"></div></div>
            <span style="color:#888;width:35px;text-align:right;">{rp}%</span>
        </div>""", unsafe_allow_html=True)

with c2:
    st.markdown("**📉 Deprioritize**")
    for c in worst_c[:5]:
        rp = int(c["pass_rate"] * 100)
        st.markdown(f"""<div style="display:flex;align-items:center;gap:6px;padding:3px 0;font-size:0.72rem;">
            <span style="color:#ff1744;width:180px;font-family:monospace;">{c['cluster']}</span>
            <div class="cluster-bar"><div style="width:{max(rp,2)}%;background:#ff1744;height:10px;border-radius:2px;"></div></div>
            <span style="color:#888;width:35px;text-align:right;">{rp}%</span>
        </div>""", unsafe_allow_html=True)

# ── MACHINE B ────────────────────────────────────────────────────────
st.markdown('<div class="section-title">🧪 MACHINE B — COMPUTE PLANE (35.222.49.13)</div>', unsafe_allow_html=True)

agents_b = [
    ("🧪", "ALPHA", "NQ 5m/15m"),
    ("🧪", "BRAVO", "NQ 1h/4h"),
    ("🧪", "CHARLIE", "GC 5m/15m"),
    ("🧪", "DELTA", "GC 1h/4h"),
    ("🧪", "ECHO", "CL 5m/15m"),
    ("🧪", "FOXTROT", "CL 1h/4h"),
]
cols = st.columns(6)
for i, (em, nm, rl) in enumerate(agents_b):
    with cols[i]:
        card(em, nm, rl, "active")

# ── ENGINEERING ──────────────────────────────────────────────────────
with st.expander("🏗️ Engineering (On-Demand)"):
    cols = st.columns(4)
    for i, (em, nm, rl) in enumerate([("⚙️","DRAKE","Eng Lead"),("🏗️","NOVA","Architect"),("🛠️","FORGE","Platform"),("🔄","RUSH","DevOps")]):
        with cols[i]:
            card(em, nm, rl, "idle")

# ── FAILURE INTELLIGENCE ─────────────────────────────────────────────
st.markdown('<div class="section-title">🧠 FAILURE INTELLIGENCE</div>', unsafe_allow_html=True)

top_fp = list(fp.get("patterns", {}).items())[:5]
if top_fp:
    for pat, count in top_fp:
        bw = min(count * 2, 100)
        st.markdown(f"""<div style="display:flex;align-items:center;gap:6px;padding:2px 0;font-size:0.7rem;">
            <span style="font-family:monospace;width:180px;color:#ffc107;">{pat}</span>
            <div class="cluster-bar"><div style="width:{bw}%;background:#ff6d00;height:8px;border-radius:2px;"></div></div>
            <span style="color:#888;width:30px;text-align:right;">{count}</span>
        </div>""", unsafe_allow_html=True)
