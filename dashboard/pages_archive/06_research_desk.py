"""Research Desk — Trader inspiration engine by style."""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from components.layout import inject_theme, fetch, page_header, STYLE_EMOJI

st.set_page_config(page_title="Research Desk", page_icon="🔬", layout="wide")
inject_theme()
page_header("🔬 RESEARCH DESK", "Trader-inspired strategy provenance — who influenced what")

research = fetch("/research/styles") or {}
strategies = fetch("/strategies") or []

if not research:
    st.warning("No research data available")
    st.stop()

# Build style -> strategies map
style_strats = {}
for s in strategies:
    style = s.get("style", "unknown")
    style_strats.setdefault(style, []).append(s)

# Render per style
for style, traders in research.items():
    emoji = STYLE_EMOJI.get(style, "📋")
    strats = style_strats.get(style, [])
    strat_codes = ", ".join(s["strategy_code"] for s in strats[:6])

    st.markdown(f"""
    <div style="margin:20px 0 8px 0;">
        <span style="font-size:1.1rem;font-weight:800;color:#e0e0e0;">{emoji} {style.replace('_',' ').upper()}</span>
        <span style="color:#555;font-size:0.75rem;margin-left:12px;">{len(strats)} strategies · {len(traders)} researchers</span>
        <span style="color:#444;font-size:0.7rem;margin-left:8px;">[ {strat_codes} ]</span>
    </div>
    """, unsafe_allow_html=True)

    cols = st.columns(min(len(traders), 5))
    for col, t in zip(cols, traders[:5]):
        with col:
            patterns = t.get("extracted_patterns_json", {}) or {}
            pattern_str = patterns.get("key_pattern", "—")
            risk_str = patterns.get("risk_approach", "—")
            tf_str = patterns.get("timeframe_focus", "—")
            status = t.get("activity_status", "")
            status_c = "#00c853" if status == "active" else "#ffc107"

            st.markdown(f"""
            <div style="background:#161616;border:1px solid #222;border-radius:6px;padding:12px;min-height:180px;">
                <div style="font-weight:700;color:#00e5ff;font-size:0.88rem;">{t.get('trader_name','Unknown')}</div>
                <div style="color:#888;font-size:0.7rem;margin:2px 0 8px 0;">
                    {t.get('market_focus','')} · <span style="color:{status_c}">{status.upper()}</span>
                </div>
                <div style="color:#999;font-size:0.72rem;line-height:1.4;margin-bottom:8px;">
                    {t.get('research_notes','')[:120]}
                </div>
                <div style="border-top:1px solid #222;padding-top:6px;font-size:0.68rem;color:#666;">
                    <div>🎯 Pattern: <span style="color:#e0e0e0;">{pattern_str}</span></div>
                    <div>🛡️ Risk: <span style="color:#e0e0e0;">{risk_str}</span></div>
                    <div>⏱️ Timeframe: <span style="color:#e0e0e0;">{tf_str}</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

    # Which strategies influenced
    if strats:
        with st.expander(f"📋 Strategies influenced by {style.replace('_',' ')} research", expanded=False):
            for s in strats:
                pnl = s.get("latest_pnl", 0)
                pc = "#00c853" if pnl > 0 else "#ff1744"
                st.markdown(f"""
                <div style="display:flex;gap:12px;padding:4px 0;font-size:0.78rem;border-bottom:1px solid #1a1a1a;">
                    <span style="font-weight:700;font-family:'JetBrains Mono',monospace;min-width:80px;">{s['strategy_code']}</span>
                    <span style="color:#888;flex:1;">{s.get('name','')}</span>
                    <span style="color:{pc};font-family:'JetBrains Mono',monospace;">{'+'if pnl>0 else ''}${pnl:,.0f}</span>
                    <span style="color:#888;">{s.get('current_stage','').replace('_',' ')}</span>
                </div>
                """, unsafe_allow_html=True)
