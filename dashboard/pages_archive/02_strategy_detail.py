"""Strategy Detail — Deep inspection of a single strategy."""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from components.layout import inject_theme, fetch, page_header, format_pnl, format_pct, format_sharpe, pnl_color, status_color, stage_color, STYLE_EMOJI
from components.strategy_card import confidence_bar_html, queue_badge_html

st.set_page_config(page_title="Strategy Detail", page_icon="🔍", layout="wide")
inject_theme()
page_header("🔍 STRATEGY DETAIL", "Deep inspection — identity, metrics, trades, research, audit")

# Get strategy list for selector
strategies = fetch("/strategies") or []
if not strategies:
    st.warning("No strategies available")
    st.stop()

# Strategy selector
options = {s["id"]: f"{s['strategy_code']} — {s['name']}" for s in strategies}
selected_id = st.selectbox("Select Strategy", options.keys(), format_func=lambda x: options[x])

# Fetch full detail
detail = fetch(f"/strategies/{selected_id}")
if not detail:
    st.error("Could not load strategy detail")
    st.stop()

strat = detail.get("strategy", {})
metrics_list = detail.get("metrics", [])
history = detail.get("history", [])
trades = detail.get("trade_explanations", [])
research = detail.get("research_links", [])

# Identity header
sc = status_color(strat.get("status", ""))
style_e = STYLE_EMOJI.get(strat.get("style", ""), "📋")
st.markdown(f"""
<div style="background:#161616;border:1px solid #222;border-left:4px solid {sc};border-radius:4px;padding:14px 18px;margin:8px 0 16px 0;">
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
            <span style="font-size:1.3rem;font-weight:800;font-family:'JetBrains Mono',monospace;color:#e0e0e0;">
                {strat.get('strategy_code','')}
            </span>
            <span style="color:#666;margin-left:12px;font-size:0.9rem;">{strat.get('name','')}</span>
        </div>
        <div style="font-size:0.85rem;">
            {style_e} {strat.get('style','').replace('_',' ').title()} · {strat.get('asset','')}
        </div>
    </div>
    <div style="margin-top:8px;display:flex;gap:24px;font-size:0.8rem;color:#888;">
        <span>Status: <b style="color:{sc}">{strat.get('status','')}</b></span>
        <span>Stage: <b style="color:{stage_color(strat.get('current_stage',''))}">{strat.get('current_stage','').replace('_',' ')}</b></span>
        <span>Mode: <b>{strat.get('current_mode','—')}</b></span>
        <span>Rank: <b style="color:#00e5ff">#{strat.get('current_rank','—')}</b></span>
        <span>Demotions: <b>{strat.get('consecutive_demotions',0)}</b></span>
    </div>
</div>
""", unsafe_allow_html=True)

# Load fast validation results
import json as _json
_fv_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "mock", "fast_validation_results.json")
_fv_data = {}
if os.path.exists(_fv_path):
    with open(_fv_path) as _f:
        for _r in _json.load(_f):
            _fv_data[_r["strategy_id"]] = _r

# Tabs
tab_overview, tab_fv, tab_metrics, tab_trades, tab_research, tab_audit = st.tabs(
    ["📋 Overview", "⚡ Fast Validation", "📊 Metrics", "💡 Trade Explanations", "🔬 Research", "📝 Audit"]
)

with tab_overview:
    c1, c2, c3, c4 = st.columns(4)
    if metrics_list:
        m = metrics_list[0]
        c1.metric("PnL", format_pnl(m.get("pnl", 0)))
        c2.metric("Sharpe", format_sharpe(m.get("sharpe", 0)))
        c3.metric("Max Drawdown", format_pct(m.get("drawdown", 0)))
        c4.metric("Win Rate", format_pct(m.get("win_rate", 0)))
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Trade Count", str(m.get("trade_count", 0)))
        c6.metric("Expectancy", f"${m.get('expectancy', 0):.2f}")
        c7.metric("Profit Factor", f"{m.get('profit_factor', 0):.2f}")
        c8.metric("Stage", m.get("stage", "—"))

    # Template config
    config = strat.get("template_config", {})
    if config:
        st.markdown("##### Strategy DNA")
        st.json(config)

    # Timeline
    if history:
        st.markdown("##### Stage Timeline")
        for h in history:
            from_s = h.get("from_stage") or "—"
            to_s = h.get("to_stage") or "—"
            evt = h.get("event_type", "")
            color = "#00c853" if "PROMOTED" in evt else "#ff1744" if "KILLED" in evt or "REJECTED" in evt or "DEMOTED" in evt else "#888"
            ts = h.get("created_at", "")[:19].replace("T", " ")
            st.markdown(f"""
            <div style="display:flex;gap:12px;padding:4px 0;font-size:0.78rem;border-bottom:1px solid #1a1a1a;">
                <span style="color:#555;font-family:'JetBrains Mono',monospace;min-width:140px;">{ts}</span>
                <span style="color:{color};font-weight:600;min-width:160px;">{evt}</span>
                <span style="color:#888;">{from_s} → {to_s}</span>
                <span style="color:#666;flex:1;">{h.get('reason','')}</span>
                <span style="color:#555;">{h.get('actor','')}</span>
            </div>
            """, unsafe_allow_html=True)

with tab_fv:
    fv = _fv_data.get(strat.get("strategy_code", ""), None)
    if fv:
        fv_status = fv.get("status", "PENDING")
        fv_color = "#00c853" if fv_status == "PASS" else "#ff1744"
        fv_badge = "🟢 PASS" if fv_status == "PASS" else "🔴 FAIL"
        fv_metrics = fv.get("metrics", {})
        confidence = fv.get("confidence", 0)
        queue_priority = fv.get("queue_priority", "")

        # Header with status, confidence, and queue badge
        queue_html = queue_badge_html(queue_priority) if queue_priority else ""
        st.markdown(f"""
        <div style="background:#161616;border:1px solid #222;border-left:4px solid {fv_color};border-radius:4px;padding:14px 18px;margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div style="font-size:1.1rem;font-weight:700;color:{fv_color};">{fv_badge}</div>
                <div>{queue_html}</div>
            </div>
            <div style="color:#888;font-size:0.8rem;margin-top:4px;">
                Tested Window: <b>{fv.get('tested_window', 'N/A')}</b>
            </div>
            <div style="margin-top:6px;max-width:300px;">
                <div style="font-size:0.75rem;color:#888;margin-bottom:2px;">Confidence Score</div>
                {confidence_bar_html(confidence)}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Threshold checks — show each as green ✅ or red ❌
        from services.fast_validation.pass_fail import FAST_VALIDATION_RULES, generate_pass_checks
        checks = generate_pass_checks(fv_metrics)
        REASON_COLORS = {
            "trade count": "#2979ff",
            "drawdown": "#ff1744",
            "pnl": "#ff6d00",
            "win rate": "#ffc107",
        }

        st.markdown("##### Threshold Checks")
        for check in checks:
            cl = check.lower()
            color = "#888"
            for key, c in REASON_COLORS.items():
                if key in cl:
                    color = c
                    break
            is_pass = check.startswith("✅")
            border_color = "#00c853" if is_pass else "#ff1744"
            st.markdown(f"""
            <div style="padding:4px 12px;border-left:3px solid {border_color};margin-bottom:3px;font-size:0.8rem;color:{color};">
                {check}
            </div>
            """, unsafe_allow_html=True)

        # Detailed fail reasons (if failed)
        fail_reasons = fv.get("fail_reasons", [])
        if fail_reasons:
            st.markdown("##### Failure Reasons")
            for fr in fail_reasons:
                fr_lower = fr.lower()
                color = "#888"
                for key, c in REASON_COLORS.items():
                    if key in fr_lower:
                        color = c
                        break
                st.markdown(f'<div style="color:{color};font-size:0.82rem;padding:2px 0;">• {fr}</div>', unsafe_allow_html=True)

        if fv_metrics:
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Trade Count", str(fv_metrics.get("trade_count", 0)))
            c2.metric("Win Rate", f"{fv_metrics.get('win_rate', 0)*100:.1f}%")
            c3.metric("PnL", f"${fv_metrics.get('total_pnl', 0):,.2f}")
            c4.metric("Max Drawdown", f"{fv_metrics.get('max_drawdown', 0)*100:.1f}%")
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            c5, c6, c7 = st.columns(3)
            c5.metric("Sharpe Ratio", f"{fv_metrics.get('sharpe_ratio', 0):.2f}")
            c6.metric("Total Return", f"{fv_metrics.get('total_return_pct', 0):.2f}%")
            c7.metric("Confidence", f"{confidence:.1%}")
    else:
        st.info("🟡 No fast validation data for this strategy")

with tab_metrics:
    if metrics_list:
        for m in metrics_list:
            pnl_c = pnl_color(m.get("pnl", 0))
            st.markdown(f"""
            <div style="background:#161616;border:1px solid #222;border-radius:4px;padding:10px 14px;margin-bottom:6px;">
                <div style="display:flex;gap:20px;font-size:0.82rem;font-family:'JetBrains Mono',monospace;">
                    <span style="color:#00e5ff;font-weight:700;min-width:100px;">{m.get('stage','')}</span>
                    <span style="color:{pnl_c};">PnL: {format_pnl(m.get('pnl',0))}</span>
                    <span>Sharpe: {format_sharpe(m.get('sharpe',0))}</span>
                    <span>DD: {format_pct(m.get('drawdown',0))}</span>
                    <span>WR: {format_pct(m.get('win_rate',0))}</span>
                    <span>Trades: {m.get('trade_count',0)}</span>
                    <span>Expect: ${m.get('expectancy',0):.1f}</span>
                    <span>PF: {m.get('profit_factor',0):.2f}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No metrics data available for this strategy")

with tab_trades:
    if trades:
        for t in trades:
            result = t.get("result", "")
            rc = "#00c853" if result == "WIN" else "#ff1744"
            pnl_val = t.get("pnl", 0)
            ts = t.get("created_at", "")[:19].replace("T", " ")
            st.markdown(f"""
            <div style="background:#161616;border:1px solid #222;border-left:3px solid {rc};border-radius:4px;padding:10px 14px;margin-bottom:5px;">
                <div style="display:flex;justify-content:space-between;font-size:0.8rem;">
                    <span style="font-weight:700;font-family:'JetBrains Mono',monospace;color:#e0e0e0;">
                        {t.get('trade_id','')}
                    </span>
                    <span style="color:#555;font-family:'JetBrains Mono',monospace;font-size:0.7rem;">{ts}</span>
                </div>
                <div style="color:{rc};font-weight:600;font-size:0.78rem;margin:4px 0;">
                    {result} · {'+' if pnl_val>0 else ''}${pnl_val:.2f}
                </div>
                <div style="color:#999;font-size:0.76rem;line-height:1.4;">{t.get('explanation_text','')}</div>
                <div style="color:#555;font-size:0.68rem;margin-top:4px;">
                    Factors: {', '.join(f'{k}={v}' for k,v in (t.get('contributing_factors_json',{}) or {}).items())}
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No trade explanations available")

with tab_research:
    if research:
        for r in research:
            src = r.get("source", {})
            st.markdown(f"""
            <div style="background:#161616;border:1px solid #222;border-radius:4px;padding:10px 14px;margin-bottom:6px;">
                <div style="font-weight:700;color:#00e5ff;font-size:0.9rem;">{src.get('trader_name','Unknown')}</div>
                <div style="color:#888;font-size:0.75rem;margin:2px 0;">
                    {src.get('market_focus','')} · {src.get('activity_status','').upper()}
                </div>
                <div style="color:#999;font-size:0.78rem;margin:4px 0;">{src.get('research_notes','')}</div>
                <div style="color:#666;font-size:0.7rem;">
                    Influence: {r.get('influence_weight',0)*100:.0f}% · {r.get('notes','')}
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No research links for this strategy")

with tab_audit:
    # Fetch audit for this strategy
    audit = fetch("/audit", params={"strategy_id": selected_id}) or []
    strat_audit = [a for a in audit if a.get("strategy_id") == selected_id]
    if strat_audit:
        for a in strat_audit:
            evt = a.get("event_type", "")
            color = "#00c853" if "CREATED" in evt or "PROMOTED" in evt or "APPROVED" in evt else "#ff1744" if "KILLED" in evt or "REJECTED" in evt or "RISK" in evt else "#ffc107"
            ts = a.get("created_at", "")[:19].replace("T", " ")
            st.markdown(f"""
            <div style="display:flex;gap:12px;padding:5px 0;font-size:0.78rem;border-bottom:1px solid #1a1a1a;">
                <span style="color:#555;font-family:'JetBrains Mono',monospace;min-width:140px;">{ts}</span>
                <span style="color:{color};font-weight:600;min-width:180px;">{evt}</span>
                <span style="color:#888;">{a.get('source_service','')}</span>
                <span style="color:#666;flex:1;">{str(a.get('payload_json',{}))[:120]}</span>
                <span style="color:{'#00c853' if a.get('success') else '#ff1744'};">{'✓' if a.get('success') else '✗'}</span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No audit events for this strategy")
