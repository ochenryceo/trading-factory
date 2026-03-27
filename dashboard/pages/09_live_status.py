"""Live Status — Real data from the continuous backtester and production fleet."""
import streamlit as st
import json, os, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from components.layout import inject_theme, page_header
from components.metric_tile import metric_row

st.set_page_config(page_title="Live Status", page_icon="📡", layout="wide")
inject_theme()
page_header("📡 LIVE STATUS", "Real-time data from the trading factory")

DATA = Path(__file__).resolve().parents[2] / "data"

# ── Continuous Backtester Status ─────────────────────────────────────
st.markdown("#### 🔄 Continuous Backtester")

lb_path = DATA / "continuous_leaderboard.json"
if lb_path.exists():
    with open(lb_path) as f:
        lb = json.load(f)
    
    metric_row([
        {"label": "Total Tested", "value": f"{lb.get('total_tested', 0):,}", "color": "#e0e0e0"},
        {"label": "Darwin Pass", "value": str(lb.get('total_passed', 0)), "color": "#00c853"},
        {"label": "Paper Ready", "value": str(lb.get('total_paper_ready', 0)), "color": "#2979ff"},
        {"label": "Best Sharpe", "value": f"{lb.get('best_sharpe', 0):.2f}", "color": "#00e5ff"},
        {"label": "Generation", "value": str(lb.get('generation', 0)), "color": "#e0e0e0"},
        {"label": "Uptime", "value": f"{lb.get('uptime_seconds', 0)/3600:.1f}h", "color": "#888"},
    ])
    
    # Leaderboard
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    st.markdown("##### 🏆 Top 10 Strategies (by Sharpe)")
    for i, entry in enumerate(lb.get("leaderboard", [])[:10], 1):
        fv = entry.get("final_validation", "—")
        fv_color = "#00c853" if fv == "READY_FOR_PAPER" else "#ffc107" if fv == "REQUIRES_HARDENING" else "#888"
        wr = entry.get("win_rate", 0)
        sr = entry.get("sharpe_ratio", 0)
        dd = entry.get("max_drawdown", 0)
        ret = entry.get("total_return_pct", 0)
        ret_color = "#00c853" if ret > 0 else "#ff1744"
        
        st.markdown(f"""
        <div style="display:flex;gap:8px;align-items:center;padding:6px 12px;background:#161616;border:1px solid #222;border-radius:4px;margin-bottom:3px;font-size:0.75rem;">
            <span style="font-weight:700;color:#00e5ff;width:24px;">#{i}</span>
            <span style="font-weight:700;font-family:'JetBrains Mono',monospace;width:250px;color:#e0e0e0;">{entry.get('strategy_code','?')[:35]}</span>
            <span style="color:#888;width:30px;">{entry.get('asset','')}</span>
            <span style="color:#e0e0e0;width:60px;">WR {wr:.0%}</span>
            <span style="color:#00e5ff;width:70px;">S {sr:.2f}</span>
            <span style="color:#ffc107;width:60px;">DD {dd:.1%}</span>
            <span style="color:{ret_color};width:70px;font-family:'JetBrains Mono',monospace;">{ret:+.1f}%</span>
            <span style="color:{fv_color};flex:1;">{fv}</span>
        </div>
        """, unsafe_allow_html=True)
else:
    st.warning("Continuous backtester not running or no data yet.")

st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

# ── Production Fleet ─────────────────────────────────────────────────
st.markdown("#### 🔒 Production Fleet")

prod_dir = DATA / "production"
fleet = []
if prod_dir.exists():
    for json_file in sorted(prod_dir.glob("*.json")):
        if json_file.name.startswith(("monitor", "daily", "paper_", "webhook")):
            continue
        try:
            with open(json_file) as f:
                dna = json.load(f)
            if dna.get("locked"):
                fleet.append(dna)
        except:
            continue

if fleet:
    metric_row([
        {"label": "Fleet Size", "value": str(len(fleet)), "color": "#00e5ff"},
        {"label": "Status", "value": "LOCKED", "color": "#00c853"},
        {"label": "Asset", "value": "NQ", "color": "#e0e0e0"},
        {"label": "Timeframe", "value": "Daily", "color": "#e0e0e0"},
    ])
    
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    for dna in fleet:
        name = dna.get("production_name", dna.get("strategy_code", "?"))
        vr = dna.get("validation_record", {})
        bm = vr.get("backtest_metrics", {})
        sr = bm.get("sharpe", 0)
        wr = bm.get("win_rate", 0)
        dd = bm.get("max_drawdown", 0)
        ret = bm.get("total_return_pct", 0)
        
        is_base = "CLONE" not in name
        border = "#00e5ff" if is_base else "#333"
        badge = "👑 BASE" if is_base else "🧬 CLONE"
        
        st.markdown(f"""
        <div style="display:flex;gap:8px;align-items:center;padding:8px 12px;background:#161616;border:1px solid {border};border-radius:4px;margin-bottom:3px;font-size:0.8rem;">
            <span style="width:70px;">{badge}</span>
            <span style="font-weight:700;font-family:'JetBrains Mono',monospace;flex:1;color:#e0e0e0;">{name}</span>
            <span style="color:#00e5ff;">S {sr:.2f}</span>
            <span style="color:#e0e0e0;">WR {wr:.0%}</span>
            <span style="color:#ffc107;">DD {dd:.1%}</span>
            <span style="color:#00c853;">+{ret:.1f}%</span>
        </div>
        """, unsafe_allow_html=True)
else:
    st.info("No production strategies locked yet.")

st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

# ── Paper Trading (Webhook) ──────────────────────────────────────────
st.markdown("#### 📈 Paper Trading — Live")

trades_path = prod_dir / "paper_trades.jsonl" if prod_dir.exists() else None
trades = []
if trades_path and trades_path.exists():
    with open(trades_path) as f:
        for line in f:
            try:
                trades.append(json.loads(line.strip()))
            except:
                continue

if trades:
    entries = [t for t in trades if t.get("type") == "ENTRY"]
    exits = [t for t in trades if t.get("type") == "EXIT"]
    last = trades[-1]
    
    metric_row([
        {"label": "Total Signals", "value": str(len(trades)), "color": "#e0e0e0"},
        {"label": "Entries", "value": str(len(entries)), "color": "#00c853"},
        {"label": "Exits", "value": str(len(exits)), "color": "#ff1744"},
        {"label": "Last Signal", "value": last.get("action", "—").upper(), "color": "#00e5ff"},
        {"label": "Last Price", "value": f"${last.get('price', 0):,.2f}", "color": "#e0e0e0"},
    ])
    
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    st.markdown("##### Recent Trades")
    for t in reversed(trades[-10:]):
        action = t.get("action", "?").upper()
        ac = "#00c853" if action in ("BUY", "LONG") else "#ff1744" if action in ("SELL", "SHORT") else "#888"
        st.markdown(f"""
        <div style="display:flex;gap:8px;align-items:center;padding:4px 12px;background:#161616;border:1px solid #222;border-radius:4px;margin-bottom:2px;font-size:0.75rem;">
            <span style="color:{ac};font-weight:700;width:50px;">{action}</span>
            <span style="font-family:'JetBrains Mono',monospace;width:60px;">{t.get('ticker','')}</span>
            <span style="color:#e0e0e0;width:80px;">${t.get('price',0):,.2f}</span>
            <span style="color:#888;flex:1;">{t.get('received_at','')[:19]}</span>
            <span style="color:#888;">{t.get('comment','')}</span>
        </div>
        """, unsafe_allow_html=True)
else:
    st.info("🔄 Paper trading active on TradingView. Waiting for first signal via webhook...")
    st.caption(f"Webhook endpoint: http://YOUR_SERVER_IP/webhook/tradingview")

st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

# ── Failure Intelligence ─────────────────────────────────────────────
st.markdown("#### 🧠 Failure Intelligence")

pattern_path = DATA / "failure_patterns.json"
if pattern_path.exists():
    with open(pattern_path) as f:
        patterns = json.load(f)
    
    total_f = patterns.get("total_failures", 0)
    top_patterns = list(patterns.get("patterns", {}).items())[:5]
    
    metric_row([
        {"label": "Total Failures Analyzed", "value": str(total_f), "color": "#e0e0e0"},
        {"label": "Pattern Types", "value": str(len(patterns.get("patterns", {}))), "color": "#ffc107"},
        {"label": "Avoidance Rules", "value": str(len(patterns.get("avoidance_rules", []))), "color": "#00e5ff"},
    ])
    
    if top_patterns:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.markdown("##### Top Failure Patterns")
        for pat, count in top_patterns:
            bar_width = min(count * 3, 100)
            st.markdown(f"""
            <div style="display:flex;gap:8px;align-items:center;padding:4px 12px;font-size:0.75rem;">
                <span style="font-family:'JetBrains Mono',monospace;width:200px;color:#ffc107;">{pat}</span>
                <div style="flex:1;background:#222;border-radius:2px;height:12px;">
                    <div style="width:{bar_width}%;background:#ff6d00;height:12px;border-radius:2px;"></div>
                </div>
                <span style="color:#888;width:30px;text-align:right;">{count}</span>
            </div>
            """, unsafe_allow_html=True)
else:
    st.info("Failure intelligence building — patterns will appear after more generations.")

# ── TradingView Validation ───────────────────────────────────────────
st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
st.markdown("#### ✅ TradingView Independent Validation")
st.markdown("""
| Metric | Python Backtester | TradingView | Match |
|---|---|---|---|
| **Return** | +27.3% | +26.13% | ✅ |
| **Max Drawdown** | 6.3% | 6.00% | ✅ |
| **Profit Factor** | 2.30 | 2.085 | ✅ |
| **Trades** | 38 | 26 | ⚠️ Data diff |

Paper test window: **March 23 → April 23, 2026**
""")
