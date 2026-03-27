"""🧠 DECISION CENTER v2 — Institutional Command Center"""
import streamlit as st
import json, os, sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from components.layout import inject_theme, page_header

st.set_page_config(page_title="Decision Center", page_icon="🧠", layout="wide")
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

# ── Load Data ────────────────────────────────────────────────────────
brain = load_json(DATA / "brain_intelligence.json")
metrics = brain.get("metrics", {})
fp = load_json(DATA / "failure_patterns.json")
lifecycle = load_json(DATA / "cluster_lifecycle.json")
portfolio = load_json(DATA / "portfolio_recommendation.json")
lb = load_json(DATA / "continuous_leaderboard.json")
vault = load_json(DATA / "vault_knowledge.json")

edge_map = brain.get("intelligence", {}).get("edge_map", []) if brain.get("intelligence") else []
lc_clusters = lifecycle.get("clusters", {})

# Count candidates by asset
fv_assets = {}
total_realistic = 0
fv_path = DATA / "final_validation_log.jsonl"
if fv_path.exists():
    with open(fv_path) as f:
        for line in f:
            try:
                d = json.loads(line.strip())
                if d.get("tag") == "READY_FOR_PAPER":
                    sr, wr, dd = d.get("baseline_sharpe",0), d.get("baseline_win_rate",0), d.get("baseline_max_dd",0)
                    if 0.8 <= sr <= 3.0 and 0.45 <= wr <= 0.75 and 0.02 <= dd <= 0.12:
                        a = d.get("asset", "?")
                        fv_assets[a] = fv_assets.get(a, 0) + 1
                        total_realistic += 1
            except:
                pass

# ── Global CSS ───────────────────────────────────────────────────────
st.markdown("""<style>
    .block-container {padding-top: 2rem; padding-bottom: 2rem;}
    .card {background: #111; border-radius: 12px; padding: 28px 24px;}
    .card-sm {background: #111; border-radius: 10px; padding: 20px;}
    .section {margin-top: 32px;}
    .label {font-size: 0.6rem; color: #444; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 12px;}
    .value-lg {font-size: 1.8rem; font-weight: 800; font-family: 'JetBrains Mono', monospace;}
    .value-md {font-size: 1rem; font-weight: 700; font-family: 'JetBrains Mono', monospace;}
    .value-sm {font-size: 0.75rem; font-family: 'JetBrains Mono', monospace;}
    .muted {color: #444; font-size: 0.7rem;}
    .row {display: flex; align-items: center; gap: 8px; padding: 6px 0;}
    .bar-bg {background: #1a1a1a; border-radius: 3px; height: 6px; flex: 1;}
    .tag {display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 0.6rem; font-weight: 700; letter-spacing: 0.5px;}
    .tag-green {background: #00c85315; color: #00c853;}
    .tag-yellow {background: #ffc10715; color: #ffc107;}
    .tag-red {background: #ff174415; color: #ff1744;}
    .tag-orange {background: #ff6d0015; color: #ff6d00;}
    .tag-cyan {background: #00e5ff15; color: #00e5ff;}
    .dot {display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin: 0 1px;}
</style>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# SECTION 1: DECISION STRIP (full width, dominant)
# ══════════════════════════════════════════════════════════════════════

peak_count = sum(1 for c in lc_clusters.values() if c.get("stage") == "PEAK")
growing_count = sum(1 for c in lc_clusters.values() if c.get("stage") == "GROWING")
birth_count = sum(1 for c in lc_clusters.values() if c.get("stage") == "BIRTH")
nq_pct = fv_assets.get("NQ", 0) / max(total_realistic, 1) * 100
has_diversity = len(fv_assets) >= 2 and nq_pct < 70
has_persistence = peak_count >= 2 or growing_count >= 5

if has_diversity and has_persistence:
    d_status, d_color, d_reason = "DEPLOY", "#00c853", "Clusters stable. Multi-asset candidates ready."
    d_action, d_conf = "Deploy top strategies from portfolio engine", 82
elif has_persistence:
    d_status, d_color, d_reason = "WAIT", "#ffc107", f"Clusters stabilizing. Asset concentration high (NQ {nq_pct:.0f}%)."
    d_action, d_conf = "Wait for GC/CL candidates. Factory grinding.", 55
else:
    d_status, d_color, d_reason = "WAIT", "#ffc107", f"Clusters forming. {birth_count} birth, {growing_count} growing."
    d_action, d_conf = "Let factory run. Monitor persistence.", 40

st.markdown(f"""
<div style="background:#0a0a0a;border-radius:16px;padding:48px 32px;text-align:center;margin-bottom:32px;">
    <div class="muted" style="margin-bottom:16px;">SYSTEM DECISION</div>
    <div style="font-size:3rem;font-weight:900;color:{d_color};letter-spacing:-2px;">
        {'🟢' if d_status == 'DEPLOY' else '🟡'} {d_status}
    </div>
    <div style="color:#666;font-size:0.85rem;margin-top:12px;max-width:500px;margin-left:auto;margin-right:auto;">
        {d_reason}
    </div>
    <div style="margin-top:20px;">
        <span style="background:#161616;padding:8px 20px;border-radius:6px;color:#e0e0e0;font-size:0.8rem;">
            → {d_action}
        </span>
    </div>
    <div style="color:#333;font-size:0.65rem;margin-top:16px;">Confidence: {d_conf}%</div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# SECTION 2: THREE CARDS — Risk / Portfolio / Compute
# ══════════════════════════════════════════════════════════════════════

c1, c2, c3 = st.columns(3, gap="medium")

# ── Risk Card ──
with c1:
    conc_risk = "HIGH" if nq_pct > 70 else "MED" if nq_pct > 50 else "LOW"
    conc_tag = "tag-red" if conc_risk == "HIGH" else "tag-yellow" if conc_risk == "MED" else "tag-green"
    stab = "HIGH" if peak_count >= 3 else "MED" if growing_count >= 5 else "LOW"
    stab_tag = "tag-green" if stab == "HIGH" else "tag-yellow" if stab == "MED" else "tag-red"
    
    overfit_count = fp.get("patterns", {}).get("OVERFIT", 0) + fp.get("patterns", {}).get("PARAM_SENSITIVE", 0)
    overfit_pct = overfit_count / max(fp.get("total_failures", 1), 1) * 100
    overfit = "HIGH" if overfit_pct > 70 else "MED" if overfit_pct > 40 else "LOW"
    overfit_tag = "tag-red" if overfit == "HIGH" else "tag-yellow" if overfit == "MED" else "tag-green"
    
    global_emoji = "🔴" if "HIGH" in [conc_risk] else "🟡" if "MED" in [conc_risk, stab] else "🟢"
    
    st.markdown(f"""
    <div class="card">
        <div class="label">⚠️ Risk</div>
        <div style="text-align:center;margin-bottom:16px;">
            <span style="font-size:1.4rem;">{global_emoji}</span>
        </div>
        <div class="row"><span class="muted" style="flex:1;">Concentration</span><span class="tag {conc_tag}">{conc_risk}</span></div>
        <div class="row"><span class="muted" style="flex:1;">Stability</span><span class="tag {stab_tag}">{stab}</span></div>
        <div class="row"><span class="muted" style="flex:1;">Overfit</span><span class="tag {overfit_tag}">{overfit}</span></div>
        <div class="row"><span class="muted" style="flex:1;">Live Drift</span><span class="tag tag-cyan">N/A</span></div>
    </div>""", unsafe_allow_html=True)

# ── Portfolio Card ──
with c2:
    p_score = portfolio.get("score", 0) if portfolio else 0
    p_strategies = portfolio.get("strategies", []) if portfolio else []
    
    asset_bars = ""
    if p_strategies:
        p_assets = {}
        for s in p_strategies:
            a = s.get("asset", "?")
            p_assets[a] = p_assets.get(a, 0) + 1
        total_p = len(p_strategies)
        for a, c_count in sorted(p_assets.items(), key=lambda x: -x[1]):
            pct = c_count / total_p * 100
            bc = "#ff1744" if pct > 60 else "#ffc107" if pct > 40 else "#00c853"
            asset_bars += f"""<div class="row">
                <span class="value-sm" style="width:28px;color:#e0e0e0;">{a}</span>
                <div class="bar-bg"><div style="width:{pct}%;background:{bc};height:6px;border-radius:3px;"></div></div>
                <span class="muted" style="width:32px;text-align:right;">{pct:.0f}%</span>
            </div>"""
    else:
        asset_bars = '<div class="muted" style="text-align:center;padding:12px;">Building...</div>'
    
    st.markdown(f"""
    <div class="card">
        <div class="label">⚖️ Portfolio</div>
        <div style="text-align:center;margin-bottom:16px;">
            <span class="value-lg" style="color:#00e5ff;">{p_score:.2f}</span>
            <div class="muted">score</div>
        </div>
        {asset_bars}
    </div>""", unsafe_allow_html=True)

# ── Compute Card ──
with c3:
    sph = metrics.get("strategies_per_hour", 0)
    eff = metrics.get("compute_efficiency", 0)
    
    alloc = [("Vol Flow", 40, "#00e5ff"), ("Scalping", 30, "#00e5ff"), ("Mean Rev", 15, "#00e5ff"), ("Momentum", 10, "#888"), ("Trend", 3, "#ff1744"), ("News", 2, "#ff1744")]
    
    alloc_html = ""
    for name, pct, color in alloc:
        alloc_html += f"""<div class="row">
            <span class="muted" style="width:70px;">{name}</span>
            <div class="bar-bg"><div style="width:{pct}%;background:{color};height:6px;border-radius:3px;"></div></div>
            <span class="muted" style="width:28px;text-align:right;">{pct}%</span>
        </div>"""
    
    st.markdown(f"""
    <div class="card">
        <div class="label">⚡ Compute</div>
        <div style="text-align:center;margin-bottom:16px;">
            <span class="value-lg" style="color:#e0e0e0;">{sph:,}</span>
            <div class="muted">strategies / hour</div>
        </div>
        {alloc_html}
    </div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# SECTION 3: CLUSTERS + FAILURES (two columns)
# ══════════════════════════════════════════════════════════════════════

st.markdown('<div class="section"></div>', unsafe_allow_html=True)
c1, c2 = st.columns(2, gap="medium")

with c1:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="label">🧬 Cluster Persistence</div>', unsafe_allow_html=True)
    
    sorted_lc = sorted(lc_clusters.items(), key=lambda x: -x[1].get("current_score", 0))
    for cluster, data in sorted_lc[:8]:
        emoji = data.get("emoji", "❓")
        cycles = min(data.get("cycles_in_stage", 0), 5)
        score = data.get("current_score", 0)
        trend = data.get("score_trend", "flat")
        
        trend_arrow = {"up": "↑", "down": "↓"}.get(trend, "→")
        trend_color = {"up": "#00c853", "down": "#ff1744"}.get(trend, "#444")
        
        dots = ""
        for i in range(5):
            c_dot = trend_color if i < cycles else "#1a1a1a"
            dots += f'<span class="dot" style="background:{c_dot};"></span>'
        
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #1a1a1a;">
            <span style="width:14px;font-size:0.8rem;">{emoji}</span>
            <span class="value-sm" style="flex:1;color:#ccc;">{cluster[:28]}</span>
            <span style="width:50px;letter-spacing:3px;">{dots}</span>
            <span style="color:{trend_color};width:12px;">{trend_arrow}</span>
        </div>""", unsafe_allow_html=True)
    
    if not lc_clusters:
        st.markdown('<div class="muted" style="padding:20px;text-align:center;">Initializing...</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with c2:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="label">🧠 Failure Intelligence</div>', unsafe_allow_html=True)
    
    fix_map = {
        "PARAM_SENSITIVE": "Widen parameter bands",
        "OVERFIT": "Simplify, reduce params",
        "LOW_TRADE_COUNT": "Loosen entry conditions",
        "FRAGILE_EDGE": "Distribute across signals",
        "NOISE_FRAGILE": "Add data smoothing",
        "ADX_CRUTCH": "Independent entry logic",
        "SLIPPAGE_SENSITIVE": "Widen stops",
    }
    
    patterns = list(fp.get("patterns", {}).items())[:6]
    max_count = patterns[0][1] if patterns else 1
    
    for pat, count in patterns:
        w = count / max_count * 100
        fix = fix_map.get(pat, "Investigate")
        st.markdown(f"""
        <div style="padding:8px 0;border-bottom:1px solid #1a1a1a;">
            <div style="display:flex;align-items:center;gap:8px;">
                <span class="value-sm" style="color:#ffc107;width:140px;">{pat}</span>
                <div class="bar-bg"><div style="width:{w}%;background:#ff6d00;height:6px;border-radius:3px;"></div></div>
                <span class="muted" style="width:28px;text-align:right;">{count}</span>
            </div>
            <div style="font-size:0.6rem;color:#00e5ff;margin-top:2px;">→ {fix}</div>
        </div>""", unsafe_allow_html=True)
    
    st.markdown('</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# SECTION 4: STRATEGY QUALITY
# ══════════════════════════════════════════════════════════════════════

st.markdown('<div class="section"></div>', unsafe_allow_html=True)
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<div class="label">🔬 Strategy Quality</div>', unsafe_allow_html=True)

for entry in (lb.get("leaderboard", []) or [])[:5]:
    code = entry.get("strategy_code", "?")[:28]
    sr = entry.get("sharpe_ratio", 0)
    wr = entry.get("win_rate", 0)
    dd = entry.get("max_drawdown", 0)
    
    if wr > 0.85 or sr > 4:
        badge, bc = "SUSPICIOUS", "tag-orange"
    elif 1.0 <= sr <= 2.5 and 0.5 <= wr <= 0.7 and 0.03 <= dd <= 0.10:
        badge, bc = "ROBUST", "tag-green"
    elif 0.5 <= sr <= 1.0:
        badge, bc = "HARDENING", "tag-yellow"
    else:
        badge, bc = "FRAGILE", "tag-red"
    
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #1a1a1a;">
        <span class="value-sm" style="color:#e0e0e0;flex:1;">{code}</span>
        <span class="muted">S {sr:.1f}</span>
        <span class="muted">WR {wr:.0%}</span>
        <span class="muted">DD {dd:.1%}</span>
        <span class="tag {bc}">{badge}</span>
    </div>""", unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# SECTION 5: LIVE vs EXPECTED (compact)
# ══════════════════════════════════════════════════════════════════════

st.markdown('<div class="section"></div>', unsafe_allow_html=True)

pt_count = 0
pt_path = DATA / "production" / "paper_trades.jsonl"
if pt_path.exists():
    with open(pt_path) as f:
        pt_count = sum(1 for _ in f)

st.markdown(f"""
<div class="card-sm" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px;">
    <div>
        <div class="label">📊 Live vs Expected</div>
        <span class="muted">Paper test: Mar 23 → Apr 23 | {pt_count} signals</span>
    </div>
    <div style="display:flex;gap:24px;">
        <div><span class="muted">Return</span><br><span class="value-sm" style="color:#e0e0e0;">+26.1%</span> <span class="muted">→ waiting</span></div>
        <div><span class="muted">Max DD</span><br><span class="value-sm" style="color:#e0e0e0;">6.0%</span> <span class="muted">→ waiting</span></div>
        <div><span class="muted">PF</span><br><span class="value-sm" style="color:#e0e0e0;">2.08</span> <span class="muted">→ waiting</span></div>
    </div>
</div>
""", unsafe_allow_html=True)
