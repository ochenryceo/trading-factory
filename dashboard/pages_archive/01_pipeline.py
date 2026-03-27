"""Pipeline Board — 8-column Kanban view with confidence scores & queue status."""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from components.layout import inject_theme, fetch, page_header, format_pnl, format_pct, format_sharpe, pnl_color, STYLE_EMOJI, MODE_EMOJI
from components.strategy_card import render_card_with_expander, confidence_bar_html, queue_badge_html
from components.metric_tile import metric_row

st.set_page_config(page_title="Pipeline Board", page_icon="🔄", layout="wide")
inject_theme()
page_header("🔄 PIPELINE BOARD", "Strategy factory floor — 8-stage gated pipeline")

# Fetch pipeline data
pipeline = fetch("/pipeline")
summary = fetch("/metrics/summary")

if not pipeline:
    st.error("⚠️ Could not load pipeline data from API")
    st.stop()

# Summary metrics
if summary:
    metric_row([
        {"label": "Total Strategies", "value": str(summary["total_strategies"])},
        {"label": "Active", "value": str(summary["active_strategies"]), "color": "#00c853"},
        {"label": "Total PnL", "value": f"${summary['total_pnl']:,.0f}", "color": "#00c853" if summary["total_pnl"] > 0 else "#ff1744"},
        {"label": "Avg Sharpe", "value": f"{summary['avg_sharpe']:.2f}", "color": "#00e5ff"},
    ])
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

# Build stage map
STAGES_ORDER = ["IDEA", "FAST_VALIDATION", "BACKTEST", "VALIDATION", "PAPER", "DEGRADATION", "DEPENDENCY", "MICRO_LIVE", "FULL_LIVE"]
stage_map = {}
for entry in pipeline:
    stage_map[entry["stage"]] = entry.get("strategies", [])

# Load fast validation results for badges, confidence, queue
import json as _json
_fv_results_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "mock", "fast_validation_results.json")
_fv_map = {}  # strategy_id -> full result dict
if os.path.exists(_fv_results_path):
    with open(_fv_results_path) as _f:
        for _r in _json.load(_f):
            _fv_map[_r["strategy_id"]] = _r

# ── Queue Status Section ─────────────────────────────────────────────
queue_counts = {"IMMEDIATE": 0, "BATCH": 0, "ARCHIVE": 0, "FAILED": 0}
for sid, fv in _fv_map.items():
    if fv["status"] == "FAIL":
        queue_counts["FAILED"] += 1
    else:
        priority = fv.get("queue_priority", "ARCHIVE")
        queue_counts[priority] = queue_counts.get(priority, 0) + 1

st.markdown("#### 📋 Queue Status")
qc = st.columns(4)
with qc[0]:
    st.markdown(f"""
    <div style="text-align:center;background:#1a0000;border:1px solid #ff1744;border-radius:4px;padding:10px;">
        <div style="font-size:1.6rem;font-weight:800;color:#ff1744;">🔴 {queue_counts['IMMEDIATE']}</div>
        <div style="font-size:0.65rem;color:#ff1744;text-transform:uppercase;letter-spacing:1px;">IMMEDIATE</div>
        <div style="font-size:0.55rem;color:#666;">Priority Darwin runs</div>
    </div>
    """, unsafe_allow_html=True)
with qc[1]:
    st.markdown(f"""
    <div style="text-align:center;background:#1a1500;border:1px solid #ffc107;border-radius:4px;padding:10px;">
        <div style="font-size:1.6rem;font-weight:800;color:#ffc107;">🟡 {queue_counts['BATCH']}</div>
        <div style="font-size:0.65rem;color:#ffc107;text-transform:uppercase;letter-spacing:1px;">BATCH</div>
        <div style="font-size:0.55rem;color:#666;">Next cycle queue</div>
    </div>
    """, unsafe_allow_html=True)
with qc[2]:
    st.markdown(f"""
    <div style="text-align:center;background:#111;border:1px solid #555;border-radius:4px;padding:10px;">
        <div style="font-size:1.6rem;font-weight:800;color:#888;">⚫ {queue_counts['ARCHIVE']}</div>
        <div style="font-size:0.65rem;color:#888;text-transform:uppercase;letter-spacing:1px;">ARCHIVE</div>
        <div style="font-size:0.55rem;color:#666;">Low confidence, stored</div>
    </div>
    """, unsafe_allow_html=True)
with qc[3]:
    st.markdown(f"""
    <div style="text-align:center;background:#161616;border:1px solid #222;border-radius:4px;padding:10px;">
        <div style="font-size:1.6rem;font-weight:800;color:#ff6d00;">💀 {queue_counts['FAILED']}</div>
        <div style="font-size:0.65rem;color:#ff6d00;text-transform:uppercase;letter-spacing:1px;">FAILED</div>
        <div style="font-size:0.55rem;color:#666;">Did not pass gate</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

# Column headers with colors
STAGE_HEADER_COLORS = {
    "IDEA": "#888", "FAST_VALIDATION": "#ff6d00", "BACKTEST": "#888", "VALIDATION": "#ffc107",
    "PAPER": "#2979ff", "DEGRADATION": "#ffc107", "DEPENDENCY": "#ffc107",
    "MICRO_LIVE": "#aa00ff", "FULL_LIVE": "#fff",
}
STAGE_ICONS = {
    "IDEA": "💡", "FAST_VALIDATION": "⚡", "BACKTEST": "📊", "VALIDATION": "✅",
    "PAPER": "📝", "DEGRADATION": "🔥", "DEPENDENCY": "🔗",
    "MICRO_LIVE": "🟣", "FULL_LIVE": "⚡",
}

# Render 9 columns
cols = st.columns(len(STAGES_ORDER), gap="small")
for col, stage in zip(cols, STAGES_ORDER):
    strategies = stage_map.get(stage, [])
    color = STAGE_HEADER_COLORS[stage]
    icon = STAGE_ICONS[stage]
    label = stage.replace("_", " ")
    with col:
        st.markdown(f"""
        <div style="
            background:#111;border:1px solid #222;border-bottom:2px solid {color};
            border-radius:4px;padding:6px 4px;text-align:center;margin-bottom:8px;
        ">
            <div style="font-size:0.9rem;">{icon}</div>
            <div style="font-size:0.65rem;font-weight:700;color:{color};text-transform:uppercase;letter-spacing:1px;">
                {label}
            </div>
            <div style="font-size:0.6rem;color:#555;">{len(strategies)} strategies</div>
        </div>
        """, unsafe_allow_html=True)

        if not strategies:
            st.markdown("""
            <div style="text-align:center;color:#333;padding:20px 0;font-size:0.7rem;">
                — empty —
            </div>
            """, unsafe_allow_html=True)
        else:
            for s in strategies:
                code = s.get("strategy_code", "")
                fv = _fv_map.get(code, None)
                render_card_with_expander(s, fv)

# Rejected section (strategies that failed fast validation)
rejected_fvs = [(sid, fv) for sid, fv in _fv_map.items() if fv["status"] == "FAIL"]
if rejected_fvs:
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    st.markdown("#### 🔴 Rejected by Fast Validation")
    rej_cols = st.columns(5)
    for i, (sid, fv) in enumerate(rejected_fvs):
        conf = fv.get("confidence", 0)
        fail_reasons = fv.get("fail_reasons", [])
        reasons_html = "".join(f"<div style='font-size:0.55rem;color:#ff6d00;'>{r}</div>" for r in fail_reasons[:3])
        with rej_cols[i % 5]:
            st.markdown(f"""
            <div style="background:#1a0a0a;border:1px solid #331111;border-radius:4px;padding:6px 8px;margin-bottom:4px;">
                <div style="font-size:0.75rem;font-weight:700;color:#ff1744;font-family:'JetBrains Mono',monospace;text-align:center;">
                    🔴 {sid}
                </div>
                <div style="font-size:0.6rem;color:#555;text-align:center;">REJECTED_FAST</div>
                {confidence_bar_html(conf)}
                {reasons_html}
            </div>
            """, unsafe_allow_html=True)
