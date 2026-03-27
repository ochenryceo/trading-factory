"""Performance Console — Leaderboard ranked by robustness."""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from components.layout import inject_theme, fetch, page_header, format_pnl, format_pct, format_sharpe, pnl_color, STYLE_EMOJI
from components.metric_tile import metric_row
from components.strategy_card import confidence_bar_html

st.set_page_config(page_title="Performance", page_icon="📊", layout="wide")
inject_theme()
page_header("📊 PERFORMANCE CONSOLE", "Leaderboard ranked by ROBUSTNESS — not raw PnL")

strategies = fetch("/strategies") or []
summary = fetch("/metrics/summary")

# Load fast validation stats
import json as _json
_fv_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "mock", "fast_validation_results.json")
_fv_stats = {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0.0}
_fv_map = {}
if os.path.exists(_fv_path):
    with open(_fv_path) as _f:
        _fv_all = _json.load(_f)
        _fv_stats["total"] = len(_fv_all)
        _fv_stats["passed"] = sum(1 for r in _fv_all if r["status"] == "PASS")
        _fv_stats["failed"] = _fv_stats["total"] - _fv_stats["passed"]
        _fv_stats["pass_rate"] = _fv_stats["passed"] / _fv_stats["total"] * 100 if _fv_stats["total"] else 0
        for r in _fv_all:
            _fv_map[r["strategy_id"]] = r

# Confidence distribution
_conf_values = [r.get("confidence", 0) for r in _fv_map.values()]
_conf_high = sum(1 for c in _conf_values if c >= 0.6)
_conf_mid = sum(1 for c in _conf_values if 0.3 <= c < 0.6)
_conf_low = sum(1 for c in _conf_values if c < 0.3)
_avg_conf = sum(_conf_values) / len(_conf_values) if _conf_values else 0

if not strategies:
    st.warning("No strategies loaded")
    st.stop()

active = [s for s in strategies if s.get("is_active")]

# Compute robustness score: weighted Sharpe, controlled drawdown, consistency
def robustness_score(s):
    sharpe = s.get("latest_sharpe", 0)
    dd = s.get("latest_drawdown", 0)
    wr = s.get("latest_win_rate", 0)
    trades = s.get("latest_trade_count", 0)
    trade_factor = min(trades / 500, 1.0)  # maturity bonus
    return (sharpe * 40) + (wr * 30) - (dd * 200) + (trade_factor * 10)

ranked = sorted(active, key=robustness_score, reverse=True)

# Summary tiles
if active:
    best_pnl = max(active, key=lambda s: s.get("latest_pnl", 0))
    worst_dd = max(active, key=lambda s: s.get("latest_drawdown", 0))
    best_sharpe = max(active, key=lambda s: s.get("latest_sharpe", 0))
    total_pnl = sum(s.get("latest_pnl", 0) for s in active)

    metric_row([
        {"label": "Best PnL", "value": format_pnl(best_pnl["latest_pnl"]), "color": "#00c853",
         "delta": best_pnl["strategy_code"], "delta_color": "#00e5ff"},
        {"label": "Worst Drawdown", "value": format_pct(worst_dd["latest_drawdown"]), "color": "#ff1744",
         "delta": worst_dd["strategy_code"], "delta_color": "#00e5ff"},
        {"label": "Best Sharpe", "value": format_sharpe(best_sharpe["latest_sharpe"]), "color": "#00e5ff",
         "delta": best_sharpe["strategy_code"], "delta_color": "#00e5ff"},
        {"label": "Total Active PnL", "value": f"${total_pnl:,.0f}", "color": "#00c853" if total_pnl > 0 else "#ff1744"},
        {"label": "Active Strategies", "value": str(len(active)), "color": "#e0e0e0"},
    ])

    # Fast validation summary tiles
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    st.markdown("#### ⚡ Fast Validation Summary")
    metric_row([
        {"label": "Total Validations", "value": str(_fv_stats["total"]), "color": "#e0e0e0"},
        {"label": "Passed", "value": str(_fv_stats["passed"]), "color": "#00c853"},
        {"label": "Failed", "value": str(_fv_stats["failed"]), "color": "#ff1744"},
        {"label": "Pass Rate", "value": f"{_fv_stats['pass_rate']:.1f}%", "color": "#00e5ff"},
    ])

    # Confidence distribution
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    st.markdown("#### 🎯 Confidence Distribution")
    metric_row([
        {"label": "Avg Confidence", "value": f"{_avg_conf:.1%}", "color": "#00e5ff"},
        {"label": "High (≥60%)", "value": str(_conf_high), "color": "#00c853"},
        {"label": "Medium (30-60%)", "value": str(_conf_mid), "color": "#ffc107"},
        {"label": "Low (<30%)", "value": str(_conf_low), "color": "#ff1744"},
    ])

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

# Robustness leaderboard
st.markdown("#### 🏆 Robustness Leaderboard")
for i, s in enumerate(ranked, 1):
    pnl = s.get("latest_pnl", 0)
    pc = pnl_color(pnl)
    sharpe = s.get("latest_sharpe", 0)
    dd = s.get("latest_drawdown", 0)
    wr = s.get("latest_win_rate", 0)
    trades = s.get("latest_trade_count", 0)
    score = robustness_score(s)
    style_e = STYLE_EMOJI.get(s.get("style", ""), "📋")
    stage = s.get("current_stage", "").replace("_", " ")

    # Color rank badge
    if i <= 3:
        rank_color = "#ffd700" if i == 1 else "#c0c0c0" if i == 2 else "#cd7f32"
    else:
        rank_color = "#555"

    st.markdown(f"""
    <div style="display:flex;gap:12px;align-items:center;padding:7px 14px;background:#161616;border:1px solid #222;border-radius:4px;margin-bottom:3px;font-size:0.8rem;">
        <span style="font-weight:800;color:{rank_color};min-width:28px;text-align:right;">#{i}</span>
        <span style="font-weight:700;font-family:'JetBrains Mono',monospace;min-width:80px;color:#e0e0e0;">{s['strategy_code']}</span>
        <span style="color:#888;min-width:180px;">{s.get('name','')}</span>
        <span style="min-width:24px;">{style_e}</span>
        <span style="color:{pc};font-family:'JetBrains Mono',monospace;min-width:80px;">{format_pnl(pnl)}</span>
        <span style="color:#888;font-family:'JetBrains Mono',monospace;min-width:60px;">S:{sharpe:.2f}</span>
        <span style="color:#888;font-family:'JetBrains Mono',monospace;min-width:60px;">DD:{dd*100:.1f}%</span>
        <span style="color:#888;font-family:'JetBrains Mono',monospace;min-width:60px;">WR:{wr*100:.0f}%</span>
        <span style="color:#555;font-family:'JetBrains Mono',monospace;min-width:60px;">{trades}t</span>
        <span style="color:#00e5ff;font-family:'JetBrains Mono',monospace;min-width:50px;">{score:.0f}pts</span>
        <span style="color:#666;font-size:0.7rem;">{stage}</span>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# Survival by stage
if summary and summary.get("strategies_by_stage"):
    st.markdown("#### 📈 Survival by Stage")
    stages = summary["strategies_by_stage"]
    total = summary["total_strategies"]
    cols = st.columns(8)
    stages_order = ["IDEA", "BACKTEST", "VALIDATION", "PAPER", "DEGRADATION", "DEPENDENCY", "MICRO_LIVE", "FULL_LIVE"]
    cumulative = total
    for col, stage in zip(cols, stages_order):
        count = stages.get(stage, 0)
        rate = (count / total * 100) if total > 0 else 0
        # Strategies that made it TO this stage or beyond
        idx = stages_order.index(stage)
        survived = sum(stages.get(s, 0) for s in stages_order[idx:])
        surv_rate = (survived / total * 100) if total > 0 else 0
        with col:
            st.markdown(f"""
            <div style="text-align:center;background:#161616;border:1px solid #222;border-radius:4px;padding:10px 4px;">
                <div style="font-size:1.1rem;font-weight:700;color:#e0e0e0;font-family:'JetBrains Mono',monospace;">
                    {surv_rate:.0f}%
                </div>
                <div style="font-size:0.6rem;color:#666;text-transform:uppercase;margin-top:2px;">
                    {stage.replace('_',' ')}
                </div>
                <div style="font-size:0.6rem;color:#555;">{count} here</div>
            </div>
            """, unsafe_allow_html=True)

# Best by style
st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
st.markdown("#### 🎯 Best by Style")
styles = {}
for s in active:
    style = s.get("style", "unknown")
    if style not in styles or robustness_score(s) > robustness_score(styles[style]):
        styles[style] = s

cols = st.columns(len(styles))
for col, (style, s) in zip(cols, styles.items()):
    e = STYLE_EMOJI.get(style, "📋")
    with col:
        pnl = s.get("latest_pnl", 0)
        pc = pnl_color(pnl)
        st.markdown(f"""
        <div style="background:#161616;border:1px solid #222;border-radius:4px;padding:10px 8px;text-align:center;">
            <div style="font-size:1.2rem;">{e}</div>
            <div style="font-size:0.7rem;color:#888;text-transform:uppercase;">{style.replace('_',' ')}</div>
            <div style="font-weight:700;font-family:'JetBrains Mono',monospace;color:#e0e0e0;margin:4px 0;">{s['strategy_code']}</div>
            <div style="color:{pc};font-family:'JetBrains Mono',monospace;font-size:0.82rem;">{format_pnl(pnl)}</div>
            <div style="color:#888;font-size:0.7rem;">S:{s.get('latest_sharpe',0):.2f}</div>
        </div>
        """, unsafe_allow_html=True)

# Best by asset
st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
st.markdown("#### 🌐 Best by Asset")
assets = {}
for s in active:
    asset = s.get("asset", "?")
    if asset not in assets or robustness_score(s) > robustness_score(assets[asset]):
        assets[asset] = s

cols = st.columns(len(assets))
for col, (asset, s) in zip(cols, assets.items()):
    with col:
        pnl = s.get("latest_pnl", 0)
        pc = pnl_color(pnl)
        st.markdown(f"""
        <div style="background:#161616;border:1px solid #222;border-radius:4px;padding:10px 8px;text-align:center;">
            <div style="font-size:1rem;font-weight:800;color:#00e5ff;">{asset}</div>
            <div style="font-weight:700;font-family:'JetBrains Mono',monospace;color:#e0e0e0;margin:4px 0;">{s['strategy_code']}</div>
            <div style="color:{pc};font-family:'JetBrains Mono',monospace;font-size:0.82rem;">{format_pnl(pnl)}</div>
            <div style="color:#888;font-size:0.7rem;">S:{s.get('latest_sharpe',0):.2f}</div>
        </div>
        """, unsafe_allow_html=True)
