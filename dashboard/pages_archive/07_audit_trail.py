"""Audit Trail — Queryable event history."""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from components.layout import inject_theme, fetch, page_header

st.set_page_config(page_title="Audit Trail", page_icon="📝", layout="wide")
inject_theme()
page_header("📝 AUDIT TRAIL", "Full traceability — every system event, queryable")

# Filters
strategies = fetch("/strategies") or []
audit_events = fetch("/audit") or []

if not audit_events:
    st.info("No audit events recorded")
    st.stop()

# Extract unique values for filters
all_types = sorted(set(e.get("event_type", "") for e in audit_events))
all_services = sorted(set(e.get("source_service", "") for e in audit_events))
all_codes = sorted(set(s.get("strategy_code", "") for s in strategies))

col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    filter_type = st.multiselect("Event Type", all_types, default=[])
with col_f2:
    filter_service = st.multiselect("Source Service", all_services, default=[])
with col_f3:
    filter_strategy = st.multiselect("Strategy", all_codes, default=[])

# Map strategy codes to IDs
code_to_id = {s["strategy_code"]: s["id"] for s in strategies}
filter_ids = [code_to_id[c] for c in filter_strategy if c in code_to_id]

# Apply filters
filtered = audit_events
if filter_type:
    filtered = [e for e in filtered if e.get("event_type") in filter_type]
if filter_service:
    filtered = [e for e in filtered if e.get("source_service") in filter_service]
if filter_ids:
    filtered = [e for e in filtered if e.get("strategy_id") in filter_ids]

# ID to code map
id_to_code = {s["id"]: s["strategy_code"] for s in strategies}

st.markdown(f"""
<div style="color:#888;font-size:0.75rem;margin:8px 0;">
    Showing {len(filtered)} of {len(audit_events)} events
</div>
""", unsafe_allow_html=True)

# Event colors
EVENT_COLORS = {
    "STRATEGY_CREATED": "#00c853",
    "STAGE_PROMOTED": "#00c853",
    "STAGE_REJECTED": "#ff6d00",
    "STRATEGY_KILLED": "#ff1744",
    "STRATEGY_DEMOTED": "#ffc107",
    "STRATEGY_RETIRED": "#555",
    "OVERRIDE_ATTEMPTED": "#ffc107",
    "OVERRIDE_APPROVED": "#00c853",
    "OVERRIDE_REJECTED": "#ff1744",
    "TRADE_APPROVED": "#00c853",
    "TRADE_REJECTED": "#ff6d00",
    "RISK_LIMIT_HIT": "#ff1744",
    "PAPER_STARTED": "#2979ff",
    "MICRO_LIVE_STARTED": "#aa00ff",
    "FULL_LIVE_STARTED": "#fff",
}

# Render events
for e in filtered[:200]:  # Cap at 200
    evt = e.get("event_type", "")
    color = EVENT_COLORS.get(evt, "#888")
    ts = e.get("created_at", "")[:19].replace("T", " ")
    strat_id = e.get("strategy_id", "")
    code = id_to_code.get(strat_id, "—")
    service = e.get("source_service", "")
    success = e.get("success")
    payload = e.get("payload_json", {})
    payload_str = ""
    if isinstance(payload, dict):
        payload_str = " · ".join(f"{k}={v}" for k, v in payload.items())

    success_icon = "✓" if success else "✗" if success is not None else "—"
    success_color = "#00c853" if success else "#ff1744" if success is not None else "#555"

    st.markdown(f"""
    <div style="display:flex;gap:10px;padding:5px 8px;font-size:0.76rem;border-bottom:1px solid #1a1a1a;align-items:center;">
        <span style="color:#444;font-family:'JetBrains Mono',monospace;min-width:130px;font-size:0.68rem;">{ts}</span>
        <span style="color:{color};font-weight:600;min-width:170px;font-size:0.72rem;">{evt}</span>
        <span style="color:#00e5ff;font-family:'JetBrains Mono',monospace;min-width:70px;">{code}</span>
        <span style="color:#666;min-width:100px;">{service}</span>
        <span style="color:#888;flex:1;font-size:0.7rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{payload_str[:100]}</span>
        <span style="color:{success_color};font-weight:700;">{success_icon}</span>
    </div>
    """, unsafe_allow_html=True)
