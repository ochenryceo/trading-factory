"""Kill Feed — Scrolling operational event feed with intelligent failure analysis."""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from components.layout import inject_theme, fetch, page_header
from components.strategy_card import confidence_bar_html

st.set_page_config(page_title="Kill Feed", page_icon="💀", layout="wide")
inject_theme()
page_header("💀 KILL FEED", "Kills · Failed promotions · Risk shutdowns · Failure intelligence")

events = fetch("/events/kill-feed") or []

# Load fast validation failures with detailed reasons
import json as _json
_fv_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "mock", "fast_validation_results.json")
_fv_kill_events = []
_failure_patterns = {"trade_count": 0, "drawdown": 0, "pnl": 0, "win_rate": 0}
if os.path.exists(_fv_path):
    with open(_fv_path) as _f:
        for _r in _json.load(_f):
            if _r["status"] == "FAIL":
                fail_reasons = _r.get("fail_reasons", [])
                # If no fail_reasons in data, parse from reason string
                if not fail_reasons and _r.get("reason"):
                    for part in _r["reason"].split("; "):
                        if "trade_count" in part:
                            fail_reasons.append(f"❌ {part}")
                        elif "max_drawdown" in part:
                            fail_reasons.append(f"❌ {part}")
                        elif "total_pnl" in part:
                            fail_reasons.append(f"❌ {part}")
                        elif "win_rate" in part:
                            fail_reasons.append(f"❌ {part}")

                # Track patterns
                for r in fail_reasons:
                    rl = r.lower()
                    if "trade count" in rl or "trade_count" in rl:
                        _failure_patterns["trade_count"] += 1
                    if "drawdown" in rl:
                        _failure_patterns["drawdown"] += 1
                    if "pnl" in rl:
                        _failure_patterns["pnl"] += 1
                    if "win rate" in rl or "win_rate" in rl:
                        _failure_patterns["win_rate"] += 1

                _fv_kill_events.append({
                    "event_type": "FAST_VALIDATION_FAILED",
                    "strategy_code": _r["strategy_id"],
                    "source_service": "fast-validation",
                    "created_at": "",
                    "payload_json": {
                        "reason": _r.get("reason", ""),
                        "metrics": _r.get("metrics", {}),
                        "fail_reasons": fail_reasons,
                        "confidence": _r.get("confidence", 0),
                    },
                })

events = events + _fv_kill_events

# Event type styling
EVENT_STYLES = {
    "STRATEGY_KILLED":         {"icon": "💀", "color": "#ff1744", "label": "KILLED"},
    "STAGE_REJECTED":          {"icon": "❌", "color": "#ff6d00", "label": "REJECTED"},
    "STRATEGY_DEMOTED":        {"icon": "⬇️", "color": "#ffc107", "label": "DEMOTED"},
    "STRATEGY_RETIRED":        {"icon": "🪦", "color": "#555", "label": "RETIRED"},
    "OVERRIDE_ATTEMPTED":      {"icon": "⚠️", "color": "#ffc107", "label": "OVERRIDE ATTEMPT"},
    "OVERRIDE_REJECTED":       {"icon": "🚫", "color": "#ff1744", "label": "OVERRIDE DENIED"},
    "OVERRIDE_APPROVED":       {"icon": "✅", "color": "#00c853", "label": "OVERRIDE APPROVED"},
    "RISK_LIMIT_HIT":          {"icon": "🛑", "color": "#ff1744", "label": "RISK LIMIT"},
    "TRADE_REJECTED":          {"icon": "🚫", "color": "#ff6d00", "label": "TRADE REJECTED"},
    "FAST_VALIDATION_FAILED":  {"icon": "⚡", "color": "#ff6d00", "label": "FAST VALIDATION FAIL"},
}

# Reason color coding
REASON_COLORS = {
    "trade count": "#2979ff",   # blue
    "trade_count": "#2979ff",
    "drawdown": "#ff1744",      # red
    "pnl": "#ff6d00",           # orange
    "win rate": "#ffc107",      # yellow
    "win_rate": "#ffc107",
}

def get_reason_color(reason_text: str) -> str:
    rl = reason_text.lower()
    for key, color in REASON_COLORS.items():
        if key in rl:
            return color
    return "#888"


# ── Failure Pattern Analysis ─────────────────────────────────────────
total_failures = len(_fv_kill_events)
if total_failures > 0:
    st.markdown("#### 📊 Failure Pattern Analysis")
    st.markdown(f"<div style='font-size:0.8rem;color:#888;margin-bottom:8px;'>{total_failures} strategies failed fast validation</div>", unsafe_allow_html=True)

    pat_cols = st.columns(4)
    pattern_items = [
        ("Trade Count", _failure_patterns["trade_count"], "#2979ff", "Too few trades"),
        ("Drawdown", _failure_patterns["drawdown"], "#ff1744", "Exceeded max DD"),
        ("PnL", _failure_patterns["pnl"], "#ff6d00", "Below min PnL"),
        ("Win Rate", _failure_patterns["win_rate"], "#ffc107", "Below min WR"),
    ]
    for col, (name, count, color, desc) in zip(pat_cols, pattern_items):
        pct = (count / total_failures * 100) if total_failures > 0 else 0
        bar_width = int(pct)
        with col:
            st.markdown(f"""
            <div style="background:#161616;border:1px solid #222;border-radius:4px;padding:10px;">
                <div style="font-size:0.7rem;color:{color};font-weight:700;text-transform:uppercase;">{name}</div>
                <div style="font-size:1.4rem;font-weight:800;color:{color};font-family:'JetBrains Mono',monospace;">{count}</div>
                <div style="background:#222;border-radius:2px;height:6px;margin:4px 0;overflow:hidden;">
                    <div style="width:{bar_width}%;height:100%;background:{color};border-radius:2px;"></div>
                </div>
                <div style="font-size:0.6rem;color:#666;">{pct:.0f}% of failures · {desc}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

# Count by type
st.markdown(f"""
<div style="display:flex;gap:12px;margin-bottom:16px;">
    <div style="background:#161616;border:1px solid #222;border-radius:4px;padding:8px 16px;">
        <span style="color:#ff1744;font-weight:700;font-size:1.2rem;">{len(events)}</span>
        <span style="color:#888;font-size:0.75rem;margin-left:6px;">TOTAL EVENTS</span>
    </div>
</div>
""", unsafe_allow_html=True)

# Render feed
for event in events:
    evt_type = event.get("event_type", "UNKNOWN")
    style = EVENT_STYLES.get(evt_type, {"icon": "📋", "color": "#888", "label": evt_type})
    ts = event.get("created_at", "")[:19].replace("T", " ")
    code = event.get("strategy_code", "???")
    source = event.get("source_service", "")
    payload = event.get("payload_json", {})

    # Extract reason from payload
    reason = ""
    fail_reasons_html = ""
    confidence_html = ""

    if isinstance(payload, dict):
        reason = payload.get("reason", payload.get("rule", ""))
        if payload.get("value") is not None and payload.get("threshold") is not None:
            reason += f" (val={payload['value']}, limit={payload['threshold']})"

        # Detailed fail reasons (UPGRADE 3)
        fail_reasons = payload.get("fail_reasons", [])
        if fail_reasons:
            reasons_parts = []
            for fr in fail_reasons:
                rc = get_reason_color(fr)
                reasons_parts.append(f'<div style="color:{rc};font-size:0.74rem;margin:2px 0;padding-left:12px;">• {fr}</div>')
            fail_reasons_html = "".join(reasons_parts)

        # Confidence score
        conf = payload.get("confidence", None)
        if conf is not None:
            confidence_html = f"""
            <div style="margin-top:4px;max-width:200px;">
                {confidence_bar_html(conf)}
            </div>
            """

    st.markdown(f"""
    <div style="
        background:#161616;border:1px solid #222;border-left:3px solid {style['color']};
        border-radius:4px;padding:10px 14px;margin-bottom:4px;
    ">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <div style="display:flex;gap:10px;align-items:center;">
                <span style="font-size:1rem;">{style['icon']}</span>
                <span style="font-weight:700;color:{style['color']};font-size:0.82rem;font-family:'JetBrains Mono',monospace;">
                    {style['label']}
                </span>
                <span style="font-weight:700;color:#e0e0e0;font-family:'JetBrains Mono',monospace;font-size:0.82rem;">
                    {code}
                </span>
                <span style="color:#555;font-size:0.72rem;">via {source}</span>
            </div>
            <span style="color:#444;font-family:'JetBrains Mono',monospace;font-size:0.68rem;">{ts}</span>
        </div>
        {fail_reasons_html if fail_reasons_html else ("<div style='color:#999;font-size:0.76rem;margin-top:4px;'>" + reason + "</div>" if reason else "")}
        {confidence_html}
    </div>
    """, unsafe_allow_html=True)
