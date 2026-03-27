"""Live Ops — Active signals, trade approvals, current mode."""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from components.layout import inject_theme, fetch, page_header, format_pnl, pnl_color, STYLE_EMOJI
from components.metric_tile import metric_row

st.set_page_config(page_title="Live Ops", page_icon="⚡", layout="wide")
inject_theme()
page_header("⚡ LIVE OPS", "Active signals · Trade approvals · Current trading desk")

live_ops = fetch("/live-ops")
strategies = fetch("/strategies") or []

if not live_ops:
    st.warning("Could not load live ops data")
    st.stop()

# Active live strategies
live = [s for s in strategies if s.get("current_stage") in ("MICRO_LIVE", "FULL_LIVE")]
paper = [s for s in strategies if s.get("current_stage") == "PAPER"]

# Mode overview
metric_row([
    {"label": "Full Live", "value": str(len([s for s in live if s.get("current_mode") == "full"])), "color": "#ffffff"},
    {"label": "Micro Live", "value": str(len([s for s in live if s.get("current_mode") == "micro"])), "color": "#aa00ff"},
    {"label": "Paper", "value": str(len(paper)), "color": "#2979ff"},
    {"label": "Active Signals", "value": str(len(live_ops.get("active_signals", []))), "color": "#00e5ff"},
    {"label": "Recent Trades", "value": str(len(live_ops.get("recent_trades", []))), "color": "#e0e0e0"},
])

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

# Active strategies table
st.markdown("#### 🟢 Live Strategies")
id_to_strat = {s["id"]: s for s in strategies}
for s in sorted(live, key=lambda x: 0 if x.get("current_mode") == "full" else 1):
    mode = s.get("current_mode", "?")
    if mode == "full":
        mode_label = "⚡ FULL LIVE"
        mode_c = "#ffffff"
        border_c = "#ffffff"
    else:
        mode_label = "🟣 MICRO LIVE"
        mode_c = "#aa00ff"
        border_c = "#aa00ff"

    pnl = s.get("latest_pnl", 0)
    pc = pnl_color(pnl)
    style_e = STYLE_EMOJI.get(s.get("style", ""), "📋")

    st.markdown(f"""
    <div style="background:#161616;border:1px solid #222;border-left:4px solid {border_c};border-radius:4px;padding:10px 14px;margin-bottom:4px;">
        <div style="display:flex;gap:16px;align-items:center;font-size:0.82rem;">
            <span style="font-weight:700;font-family:'JetBrains Mono',monospace;min-width:80px;color:#e0e0e0;">{s['strategy_code']}</span>
            <span style="color:{mode_c};font-weight:600;min-width:100px;">{mode_label}</span>
            <span style="min-width:20px;">{style_e}</span>
            <span style="color:#888;flex:1;">{s.get('name','')}</span>
            <span style="color:{pc};font-family:'JetBrains Mono',monospace;">{'+'if pnl>0 else ''}${pnl:,.0f}</span>
            <span style="color:#888;font-family:'JetBrains Mono',monospace;">S:{s.get('latest_sharpe',0):.2f}</span>
            <span style="color:#888;font-family:'JetBrains Mono',monospace;">DD:{s.get('latest_drawdown',0)*100:.1f}%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# Active signals
signals = live_ops.get("active_signals", [])
st.markdown("#### 📡 Active Signals")
if signals:
    for sig in signals:
        st.markdown(f"""
        <div style="background:#161616;border:1px solid #222;border-left:3px solid #00e5ff;border-radius:4px;padding:8px 14px;margin-bottom:4px;font-size:0.8rem;">
            <span style="color:#00e5ff;font-weight:700;">{sig.get('strategy_code','')}</span>
            <span style="color:#888;margin-left:8px;">{sig.get('signal_type','')}</span>
            <span style="color:#666;margin-left:8px;">{sig.get('details','')}</span>
        </div>
        """, unsafe_allow_html=True)
else:
    st.markdown("""
    <div style="text-align:center;color:#555;font-size:0.8rem;padding:12px;">
        No active signals — market idle or session closed
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# Recent trades
trades = live_ops.get("recent_trades", [])
st.markdown("#### 📋 Recent Trade Activity")
if trades:
    for t in trades:
        result = t.get("result", "")
        rc = "#00c853" if result == "WIN" else "#ff1744" if result == "LOSS" else "#ffc107"
        pnl_val = t.get("pnl", 0)
        ts = t.get("created_at", "")[:19].replace("T", " ")
        tid = t.get("trade_id", "")
        # Get strategy code from ID
        strat = id_to_strat.get(t.get("strategy_id", ""), {})
        code = strat.get("strategy_code", "???")

        st.markdown(f"""
        <div style="background:#161616;border:1px solid #222;border-left:3px solid {rc};border-radius:4px;padding:10px 14px;margin-bottom:4px;">
            <div style="display:flex;justify-content:space-between;align-items:center;font-size:0.8rem;">
                <div style="display:flex;gap:12px;align-items:center;">
                    <span style="font-weight:700;font-family:'JetBrains Mono',monospace;color:#e0e0e0;">{code}</span>
                    <span style="color:#888;font-family:'JetBrains Mono',monospace;">{tid}</span>
                    <span style="color:{rc};font-weight:700;">{result}</span>
                    <span style="color:{rc};font-family:'JetBrains Mono',monospace;">{'+'if pnl_val>0 else ''}${pnl_val:.2f}</span>
                </div>
                <span style="color:#444;font-family:'JetBrains Mono',monospace;font-size:0.68rem;">{ts}</span>
            </div>
            <div style="color:#999;font-size:0.74rem;margin-top:4px;line-height:1.4;">
                {t.get('explanation_text','')[:200]}
            </div>
        </div>
        """, unsafe_allow_html=True)
else:
    st.markdown("""
    <div style="text-align:center;color:#555;font-size:0.8rem;padding:12px;">
        No recent trade activity
    </div>
    """, unsafe_allow_html=True)
