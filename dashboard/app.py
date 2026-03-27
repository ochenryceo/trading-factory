"""Trading Factory — Institutional Command Center v3"""
import streamlit as st
import json, os, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

st.set_page_config(page_title="Trading Factory", page_icon="🏭", layout="wide", initial_sidebar_state="collapsed")

DATA = Path(__file__).resolve().parents[1] / "data"

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

pt_count = 0
pt_path = DATA / "production" / "paper_trades.jsonl"
if pt_path.exists():
    with open(pt_path) as f:
        pt_count = sum(1 for line in f if line.strip())

# ── Compute decision ─────────────────────────────────────────────────
peak_count = sum(1 for c in lc_clusters.values() if c.get("stage") == "PEAK")
growing_count = sum(1 for c in lc_clusters.values() if c.get("stage") == "GROWING")
birth_count = sum(1 for c in lc_clusters.values() if c.get("stage") == "BIRTH")
nq_pct = fv_assets.get("NQ", 0) / max(total_realistic, 1) * 100
has_diversity = len(fv_assets) >= 2 and nq_pct < 70
has_persistence = peak_count >= 2 or growing_count >= 5
sph = metrics.get("strategies_per_hour", 0)
eff = metrics.get("compute_efficiency", 0)
total_tested = metrics.get("total_tested", 0)
total_passed = metrics.get("total_passed", 0)
pass_rate = metrics.get("pass_rate", 0)
p_score = portfolio.get("score", 0) if portfolio else 0

if has_diversity and has_persistence:
    d_status, d_color, d_bg, d_reason = "DEPLOY", "#00FFAA", "#00FFAA10", "Clusters stable. Multi-asset ready."
    d_action, d_conf = "Deploy top portfolio strategies", 82
elif has_persistence:
    d_status, d_color, d_bg, d_reason = "WAIT", "#FFD54F", "#FFD54F10", f"NQ concentration {nq_pct:.0f}%. Awaiting GC/CL."
    d_action, d_conf = "Factory grinding. Monitor diversification.", 55
else:
    d_status, d_color, d_bg, d_reason = "WAIT", "#FFD54F", "#FFD54F10", f"{birth_count} birth, {growing_count} growing clusters."
    d_action, d_conf = "Let factory run. Monitor persistence.", 40

# ── GLOBAL STYLE ─────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&display=swap');

[data-testid="stAppViewContainer"] {background: #0A0A0A;}
[data-testid="stHeader"] {background: #0A0A0A;}
[data-testid="stSidebar"] {background: #0A0A0A;}
.block-container {padding: 1.5rem 2.5rem !important; max-width: 1600px;}
[data-testid="stVerticalBlock"] {gap: 0.6rem;}

* {font-family: 'Inter', sans-serif;}

.topbar {
    display: flex; justify-content: space-between; align-items: center;
    padding: 12px 0; border-bottom: 1px solid #1a1a1a; margin-bottom: 20px;
}
.topbar-title {font-size: 1.1rem; font-weight: 800; color: #e0e0e0; letter-spacing: -0.5px;}
.topbar-sub {font-size: 0.65rem; color: #444; letter-spacing: 1px; text-transform: uppercase;}
.topbar-live {font-size: 0.6rem; color: #00FFAA; display: flex; align-items: center; gap: 6px;}
.topbar-dot {width: 6px; height: 6px; border-radius: 50%; background: #00FFAA; animation: pulse 2s infinite;}
@keyframes pulse {0%,100%{opacity:1;}50%{opacity:0.3;}}

.card {
    background: #111; border-radius: 12px; padding: 24px;
    box-shadow: 0 2px 20px rgba(0,0,0,0.4);
}
.card-compact {background: #111; border-radius: 10px; padding: 18px; box-shadow: 0 2px 12px rgba(0,0,0,0.3);}

.label {font-size: 0.55rem; color: #444; text-transform: uppercase; letter-spacing: 2.5px; margin-bottom: 10px; font-weight: 600;}
.metric-value {font-size: 1.8rem; font-weight: 800; font-family: 'JetBrains Mono', monospace; color: #00E5FF;}
.metric-sm {font-size: 0.7rem; color: #444; margin-top: 2px;}

.bar-track {background: #1a1a1a; border-radius: 4px; height: 6px; width: 100%;}
.bar-fill {height: 6px; border-radius: 4px;}

.tag {display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 0.55rem; font-weight: 700; letter-spacing: 0.5px;}
.tag-g {background: #00FFAA12; color: #00FFAA;}
.tag-y {background: #FFD54F12; color: #FFD54F;}
.tag-r {background: #FF525212; color: #FF5252;}
.tag-o {background: #FF6D0012; color: #FF6D00;}
.tag-c {background: #00E5FF12; color: #00E5FF;}

.row {display: flex; align-items: center; gap: 10px; padding: 7px 0;}
.row-border {border-bottom: 1px solid #141414;}
.mono {font-family: 'JetBrains Mono', monospace;}
.text-muted {color: #444; font-size: 0.7rem;}
.text-sm {font-size: 0.72rem;}
.text-xs {font-size: 0.6rem;}

.dot {display: inline-block; width: 5px; height: 5px; border-radius: 50%; margin: 0 1.5px;}

.decision-strip {
    background: linear-gradient(180deg, #0f0f0f, #0a0a0a);
    border-radius: 16px; padding: 40px; text-align: center; margin-bottom: 24px;
    border: 1px solid #1a1a1a;
}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# TOP BAR
# ══════════════════════════════════════════════════════════════════════

st.markdown(f"""
<div class="topbar">
    <div>
        <div class="topbar-title">🏭 TRADING FACTORY</div>
        <div class="topbar-sub">Institutional Command Center</div>
    </div>
    <div style="display:flex;align-items:center;gap:24px;">
        <div class="topbar-live"><span class="topbar-dot"></span> LIVE</div>
        <div class="text-xs" style="color:#333;">9 agents • 2 machines • 24.8M bars</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# DECISION STRIP
# ══════════════════════════════════════════════════════════════════════

st.markdown(f"""
<div class="decision-strip" style="border-color:{d_color}20;">
    <div class="text-xs" style="color:#333;margin-bottom:14px;">SYSTEM DECISION</div>
    <div style="font-size:2.4rem;font-weight:900;color:{d_color};letter-spacing:-1px;">
        {'🟢' if d_status=='DEPLOY' else '🟡'} {d_status}
    </div>
    <div style="color:#555;font-size:0.8rem;margin-top:10px;">{d_reason}</div>
    <div style="margin-top:18px;">
        <span style="background:#161616;padding:8px 24px;border-radius:8px;color:#ccc;font-size:0.75rem;">→ {d_action}</span>
    </div>
    <div style="color:#2a2a2a;font-size:0.6rem;margin-top:14px;">Confidence: {d_conf}%</div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# METRICS ROW (5 cards)
# ══════════════════════════════════════════════════════════════════════

mc = st.columns(5, gap="medium")
metric_data = [
    ("Strategies / hr", f"{sph:,}", "#00E5FF"),
    ("Total Tested", f"{total_tested:,}", "#e0e0e0"),
    ("Pass Rate", f"{pass_rate:.0%}", "#00FFAA" if pass_rate > 0.2 else "#FFD54F"),
    ("Paper Ready", str(lb.get("total_paper_ready", 0)), "#00E5FF"),
    ("Portfolio Score", f"{p_score:.2f}", "#00E5FF"),
]
for i, (title, value, color) in enumerate(metric_data):
    with mc[i]:
        st.markdown(f"""
        <div class="card-compact">
            <div class="label">{title}</div>
            <div class="metric-value" style="color:{color};">{value}</div>
        </div>""", unsafe_allow_html=True)

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# MAIN GRID: Left (2/3) + Right (1/3)
# ══════════════════════════════════════════════════════════════════════

left, right = st.columns([2, 1], gap="medium")

# ── LEFT: Clusters + Strategies ──────────────────────────────────────
with left:
    # Cluster Intelligence
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="label">🧬 Cluster Intelligence</div>', unsafe_allow_html=True)
    
    sorted_lc = sorted(lc_clusters.items(), key=lambda x: -x[1].get("current_score", 0))
    for cluster, data in sorted_lc[:8]:
        emoji = data.get("emoji", "")
        cycles = min(data.get("cycles_in_stage", 0), 5)
        score = data.get("current_score", 0)
        trend = data.get("score_trend", "flat")
        tc = {"up": "#00FFAA", "down": "#FF5252"}.get(trend, "#333")
        ta = {"up": "↑", "down": "↓"}.get(trend, "→")
        
        dots = "".join(f'<span class="dot" style="background:{tc if i<cycles else "#1a1a1a"};"></span>' for i in range(5))
        bar_w = min(int(score * 100), 100)
        
        st.markdown(f"""
        <div class="row row-border">
            <span class="mono text-sm" style="color:#ccc;flex:1;">{cluster[:30]}</span>
            <span style="width:50px;letter-spacing:3px;">{dots}</span>
            <div style="width:80px;"><div class="bar-track"><div class="bar-fill" style="width:{bar_w}%;background:#00E5FF;"></div></div></div>
            <span style="color:{tc};width:12px;font-size:0.7rem;">{ta}</span>
        </div>""", unsafe_allow_html=True)
    
    if not lc_clusters:
        st.markdown('<div class="text-muted" style="padding:20px;text-align:center;">Initializing clusters...</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    
    # Strategy Quality
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="label">🔬 Strategy Quality</div>', unsafe_allow_html=True)
    
    for entry in (lb.get("leaderboard", []) or [])[:6]:
        code = entry.get("strategy_code", "?")[:28]
        sr = entry.get("sharpe_ratio", 0)
        wr = entry.get("win_rate", 0)
        dd = entry.get("max_drawdown", 0)
        
        if wr > 0.85 or sr > 4:
            badge, btag = "SUSPICIOUS", "tag-o"
        elif 1.0 <= sr <= 2.5 and 0.5 <= wr <= 0.7 and 0.03 <= dd <= 0.10:
            badge, btag = "ROBUST", "tag-g"
        elif 0.5 <= sr <= 1.0:
            badge, btag = "HARDENING", "tag-y"
        else:
            badge, btag = "FRAGILE", "tag-r"
        
        st.markdown(f"""
        <div class="row row-border">
            <span class="mono text-sm" style="color:#ccc;flex:1;">{code}</span>
            <span class="text-xs" style="color:#00E5FF;">S {sr:.1f}</span>
            <span class="text-xs text-muted">WR {wr:.0%}</span>
            <span class="text-xs text-muted">DD {dd:.1%}</span>
            <span class="tag {btag}">{badge}</span>
        </div>""", unsafe_allow_html=True)
    
    st.markdown('</div>', unsafe_allow_html=True)

# ── RIGHT: Risk + Portfolio + Compute ────────────────────────────────
with right:
    # Risk
    conc_risk = "HIGH" if nq_pct > 70 else "MED" if nq_pct > 50 else "LOW"
    stab = "HIGH" if peak_count >= 3 else "MED" if growing_count >= 5 else "LOW"
    overfit_n = fp.get("patterns", {}).get("OVERFIT", 0) + fp.get("patterns", {}).get("PARAM_SENSITIVE", 0)
    overfit_pct = overfit_n / max(fp.get("total_failures", 1), 1) * 100
    overfit = "HIGH" if overfit_pct > 70 else "MED" if overfit_pct > 40 else "LOW"
    g_emoji = "🔴" if conc_risk == "HIGH" else "🟡" if "MED" in [conc_risk, stab] else "🟢"
    
    risk_rows = [
        ("Concentration", conc_risk, f"NQ {nq_pct:.0f}%"),
        ("Stability", stab, f"{peak_count}P {growing_count}G"),
        ("Overfit", overfit, f"{overfit_pct:.0f}%"),
        ("Live Drift", "N/A", "Waiting"),
    ]
    
    risk_html = ""
    for lbl, lvl, det in risk_rows:
        tc = {"HIGH":"tag-r","MED":"tag-y","LOW":"tag-g","N/A":"tag-c"}.get(lvl,"tag-c")
        risk_html += f'<div class="row row-border"><span class="text-sm text-muted" style="flex:1;">{lbl}</span><span class="tag {tc}">{lvl}</span><span class="text-xs text-muted" style="width:50px;text-align:right;">{det}</span></div>'
    
    st.markdown(f"""
    <div class="card">
        <div class="label">⚠️ System Risk</div>
        <div style="text-align:center;font-size:1.3rem;margin-bottom:12px;">{g_emoji}</div>
        {risk_html}
    </div>""", unsafe_allow_html=True)
    
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    
    # Portfolio
    p_strats = portfolio.get("strategies", []) if portfolio else []
    p_assets = {}
    for s in p_strats:
        a = s.get("asset", "?")
        p_assets[a] = p_assets.get(a, 0) + 1
    total_p = max(len(p_strats), 1)
    
    asset_bars = ""
    for a in ["NQ", "GC", "CL"]:
        cnt = p_assets.get(a, 0) + fv_assets.get(a, 0)
        pct = min(cnt / max(total_realistic, 1) * 100, 100)
        bc = "#FF5252" if pct > 60 else "#FFD54F" if pct > 40 else "#00FFAA"
        asset_bars += f'<div class="row"><span class="mono text-sm" style="width:28px;color:#ccc;">{a}</span><div class="bar-track" style="flex:1;"><div class="bar-fill" style="width:{pct}%;background:{bc};"></div></div><span class="text-xs text-muted" style="width:32px;text-align:right;">{pct:.0f}%</span></div>'
    
    st.markdown(f"""
    <div class="card">
        <div class="label">⚖️ Portfolio</div>
        <div style="text-align:center;margin-bottom:14px;">
            <span class="metric-value" style="font-size:1.4rem;">{p_score:.2f}</span>
            <div class="text-xs text-muted">score</div>
        </div>
        {asset_bars}
    </div>""", unsafe_allow_html=True)
    
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    
    # Compute
    alloc = [("Vol Flow",40,"#00E5FF"),("Scalping",30,"#00E5FF"),("Mean Rev",15,"#00E5FF"),("Momentum",10,"#444"),("Trend",3,"#FF5252"),("News",2,"#FF5252")]
    alloc_html = ""
    for name, pct, color in alloc:
        alloc_html += f'<div class="row"><span class="text-xs text-muted" style="width:65px;">{name}</span><div class="bar-track" style="flex:1;"><div class="bar-fill" style="width:{pct}%;background:{color};"></div></div><span class="text-xs text-muted" style="width:24px;text-align:right;">{pct}%</span></div>'
    
    st.markdown(f"""
    <div class="card">
        <div class="label">⚡ Compute</div>
        <div style="text-align:center;margin-bottom:14px;">
            <span class="metric-value" style="font-size:1.4rem;">{sph:,}</span>
            <div class="text-xs text-muted">per hour</div>
        </div>
        {alloc_html}
    </div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# BOTTOM ROW: Failures + Live
# ══════════════════════════════════════════════════════════════════════

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
b1, b2 = st.columns([1, 1], gap="medium")

with b1:
    fix_map = {"PARAM_SENSITIVE":"Widen params","OVERFIT":"Simplify","LOW_TRADE_COUNT":"Loosen entries","FRAGILE_EDGE":"Distribute signals","NOISE_FRAGILE":"Add smoothing"}
    patterns = list(fp.get("patterns", {}).items())[:5]
    max_c = patterns[0][1] if patterns else 1
    
    fail_html = ""
    for pat, count in patterns:
        w = count / max_c * 100
        fix = fix_map.get(pat, "Investigate")
        fail_html += f"""<div class="row row-border">
            <span class="mono text-xs" style="color:#FFD54F;width:130px;">{pat}</span>
            <div class="bar-track" style="flex:1;"><div class="bar-fill" style="width:{w}%;background:#FF6D00;"></div></div>
            <span class="text-xs text-muted" style="width:28px;text-align:right;">{count}</span>
            <span class="text-xs" style="color:#00E5FF;width:100px;text-align:right;">{fix}</span>
        </div>"""
    
    st.markdown(f'<div class="card"><div class="label">🧠 Failure Intelligence</div>{fail_html}</div>', unsafe_allow_html=True)

with b2:
    st.markdown(f"""
    <div class="card">
        <div class="label">📊 Live vs Expected</div>
        <div style="display:flex;justify-content:space-between;margin-top:8px;">
            <div style="text-align:center;flex:1;">
                <div class="text-xs text-muted">Return</div>
                <div class="mono text-sm" style="color:#ccc;margin-top:4px;">+26.1%</div>
                <div class="text-xs text-muted">→ {'waiting' if pt_count==0 else 'tracking'}</div>
            </div>
            <div style="text-align:center;flex:1;">
                <div class="text-xs text-muted">Max DD</div>
                <div class="mono text-sm" style="color:#ccc;margin-top:4px;">6.0%</div>
                <div class="text-xs text-muted">→ {'waiting' if pt_count==0 else 'tracking'}</div>
            </div>
            <div style="text-align:center;flex:1;">
                <div class="text-xs text-muted">Profit Factor</div>
                <div class="mono text-sm" style="color:#ccc;margin-top:4px;">2.08</div>
                <div class="text-xs text-muted">→ {'waiting' if pt_count==0 else 'tracking'}</div>
            </div>
            <div style="text-align:center;flex:1;">
                <div class="text-xs text-muted">Signals</div>
                <div class="mono text-sm" style="color:{'#00FFAA' if pt_count>0 else '#444'};margin-top:4px;">{pt_count}</div>
                <div class="text-xs text-muted">Mar 23 → Apr 23</div>
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

# ── Footer ───────────────────────────────────────────────────────────
st.markdown(f"""
<div style="text-align:center;padding:24px 0 8px 0;border-top:1px solid #111;margin-top:24px;">
    <span class="text-xs" style="color:#222;">Trading Factory • 24 agents • 8 directives • Machine A (YOUR_SERVER_IP) + Machine B (YOUR_GPU_IP)</span>
</div>
""", unsafe_allow_html=True)
