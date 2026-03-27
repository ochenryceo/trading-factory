"""Reusable metric tile component."""
import streamlit as st


def metric_tile(label: str, value: str, color: str = "#e0e0e0", delta: str = "", delta_color: str = "#888"):
    """Render a compact metric tile with HTML."""
    delta_html = ""
    if delta:
        delta_html = f'<div style="font-size:0.7rem;color:{delta_color};margin-top:2px;">{delta}</div>'
    st.markdown(f"""
    <div class="metric-tile">
        <div class="metric-value" style="color:{color};">{value}</div>
        <div class="metric-label">{label}</div>
        {delta_html}
    </div>
    """, unsafe_allow_html=True)


def metric_row(metrics: list[dict]):
    """Render a row of metric tiles. Each dict: {label, value, color?, delta?, delta_color?}"""
    cols = st.columns(len(metrics))
    for col, m in zip(cols, metrics):
        with col:
            metric_tile(
                label=m["label"],
                value=m["value"],
                color=m.get("color", "#e0e0e0"),
                delta=m.get("delta", ""),
                delta_color=m.get("delta_color", "#888"),
            )
