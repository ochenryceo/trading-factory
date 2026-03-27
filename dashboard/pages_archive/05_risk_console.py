"""Risk Console — The blast shield."""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from components.layout import inject_theme, fetch, page_header
from components.metric_tile import metric_row

st.set_page_config(page_title="Risk Console", page_icon="🛡️", layout="wide")
inject_theme()
page_header("🛡️ RISK CONSOLE", "Global risk state — the blast shield")

risk = fetch("/risk/state")
strategies = fetch("/strategies") or []

if not risk:
    st.error("⚠️ Could not load risk state")
    st.stop()

# System mode banner
mode = risk.get("mode", "UNKNOWN")
if mode == "NORMAL":
    mode_color = "#00c853"
    mode_bg = "#0a1a0a"
    mode_icon = "✅"
elif mode == "WARNING":
    mode_color = "#ffc107"
    mode_bg = "#1a1500"
    mode_icon = "⚠️"
else:
    mode_color = "#ff1744"
    mode_bg = "#1a0a0a"
    mode_icon = "🛑"

st.markdown(f"""
<div style="background:{mode_bg};border:2px solid {mode_color};border-radius:6px;padding:16px 24px;text-align:center;margin-bottom:16px;">
    <div style="font-size:2rem;">{mode_icon}</div>
    <div style="font-size:1.4rem;font-weight:800;color:{mode_color};font-family:'JetBrains Mono',monospace;letter-spacing:2px;">
        SYSTEM MODE: {mode}
    </div>
</div>
""", unsafe_allow_html=True)

# Core risk metrics
daily_loss = risk.get("daily_loss", 0)
total_dd = risk.get("total_drawdown", 0)
positions = risk.get("active_positions", 0)
capital = risk.get("capital_at_risk", 0)
warnings = risk.get("strategies_under_warning", 0)
kills = risk.get("kill_switches_triggered", [])

dl_color = "#00c853" if daily_loss < 0.02 else "#ffc107" if daily_loss < 0.05 else "#ff1744"
dd_color = "#00c853" if total_dd < 0.05 else "#ffc107" if total_dd < 0.10 else "#ff1744"

metric_row([
    {"label": "Daily Loss", "value": f"{daily_loss*100:.2f}%", "color": dl_color},
    {"label": "Total Drawdown", "value": f"{total_dd*100:.2f}%", "color": dd_color},
    {"label": "Active Positions", "value": str(positions), "color": "#00e5ff"},
    {"label": "Capital at Risk", "value": f"${capital:,.0f}", "color": "#ffc107"},
    {"label": "Warnings", "value": str(warnings), "color": "#ffc107" if warnings > 0 else "#00c853"},
    {"label": "Kill Switches", "value": str(len(kills)), "color": "#ff1744" if kills else "#00c853"},
])

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# Kill switches
st.markdown("#### ⚡ Kill Switch Status")
if kills:
    for k in kills:
        st.markdown(f"""
        <div style="background:#1a0a0a;border:1px solid #ff1744;border-radius:4px;padding:8px 14px;margin-bottom:4px;">
            <span style="color:#ff1744;font-weight:700;">🛑 {k}</span>
        </div>
        """, unsafe_allow_html=True)
else:
    st.markdown("""
    <div style="background:#0a1a0a;border:1px solid #1b5e20;border-radius:4px;padding:12px 14px;text-align:center;">
        <span style="color:#00c853;font-weight:600;">✅ No kill switches triggered — all systems nominal</span>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# Live strategies risk overview
live_strategies = [s for s in strategies if s.get("current_stage") in ("MICRO_LIVE", "FULL_LIVE")]
if live_strategies:
    st.markdown("#### 📊 Live Strategies Risk")
    for s in sorted(live_strategies, key=lambda x: x.get("latest_drawdown", 0), reverse=True):
        dd = s.get("latest_drawdown", 0)
        pnl = s.get("latest_pnl", 0)
        dd_c = "#00c853" if dd < 0.05 else "#ffc107" if dd < 0.08 else "#ff1744"
        pnl_c = "#00c853" if pnl > 0 else "#ff1744"
        mode = s.get("current_mode", "?")
        mode_label = "⚡FULL" if mode == "full" else "🟣MICRO" if mode == "micro" else mode

        # DD bar
        bar_width = min(dd * 1000, 100)
        st.markdown(f"""
        <div style="background:#161616;border:1px solid #222;border-radius:4px;padding:8px 14px;margin-bottom:3px;">
            <div style="display:flex;gap:14px;align-items:center;font-size:0.8rem;">
                <span style="font-weight:700;font-family:'JetBrains Mono',monospace;min-width:80px;color:#e0e0e0;">{s['strategy_code']}</span>
                <span style="color:#888;min-width:50px;">{mode_label}</span>
                <span style="color:{pnl_c};font-family:'JetBrains Mono',monospace;min-width:80px;">{'+'if pnl>0 else ''}${pnl:,.0f}</span>
                <div style="flex:1;background:#222;height:8px;border-radius:4px;overflow:hidden;">
                    <div style="width:{bar_width}%;height:100%;background:{dd_c};border-radius:4px;"></div>
                </div>
                <span style="color:{dd_c};font-family:'JetBrains Mono',monospace;min-width:60px;">{dd*100:.1f}% DD</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

# Strategies under warning
st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
st.markdown("#### ⚠️ Risk Watchlist")
high_dd = [s for s in strategies if s.get("latest_drawdown", 0) > 0.06 and s.get("is_active")]
if high_dd:
    for s in sorted(high_dd, key=lambda x: x.get("latest_drawdown", 0), reverse=True):
        dd = s.get("latest_drawdown", 0)
        st.markdown(f"""
        <div style="display:flex;gap:12px;padding:5px 14px;background:#161616;border:1px solid #222;border-left:3px solid #ffc107;border-radius:4px;margin-bottom:3px;font-size:0.78rem;">
            <span style="font-weight:700;font-family:'JetBrains Mono',monospace;color:#ffc107;">{s['strategy_code']}</span>
            <span style="color:#888;">{s.get('name','')}</span>
            <span style="color:#ff1744;font-family:'JetBrains Mono',monospace;margin-left:auto;">DD: {dd*100:.1f}%</span>
        </div>
        """, unsafe_allow_html=True)
else:
    st.markdown("""
    <div style="text-align:center;color:#00c853;font-size:0.8rem;padding:8px;">
        ✅ No strategies on risk watchlist
    </div>
    """, unsafe_allow_html=True)
