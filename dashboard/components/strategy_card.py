"""Reusable strategy card component for pipeline board — with confidence & queue badges."""
import streamlit as st
from components.layout import (
    status_color, stage_color, pnl_color, format_pnl, format_pct, format_sharpe,
    STYLE_EMOJI, MODE_EMOJI,
)


def _card_border_color(s: dict) -> str:
    """Determine left-border color based on status + stage."""
    status = s.get("status", "")
    stage = s.get("current_stage", "")
    mode = s.get("current_mode")
    if status == "KILLED":
        return "#ff1744"
    if status == "RETIRED":
        return "#555555"
    if stage == "FULL_LIVE":
        return "#ffffff"
    if stage == "MICRO_LIVE":
        return "#aa00ff"
    if mode == "paper" or stage == "PAPER":
        return "#2979ff"
    if status == "ACTIVE":
        return "#00c853"
    return "#888888"


def confidence_bar_html(confidence: float) -> str:
    """Generate an inline confidence gradient bar."""
    pct = int(confidence * 100)
    if confidence >= 0.6:
        color = "#00c853"
    elif confidence >= 0.3:
        color = "#ffc107"
    else:
        color = "#ff1744"
    return f"""
    <div style="display:flex;align-items:center;gap:6px;margin-top:3px;">
        <div style="flex:1;background:#222;border-radius:2px;height:4px;overflow:hidden;">
            <div style="width:{pct}%;height:100%;background:{color};border-radius:2px;"></div>
        </div>
        <span style="font-size:0.62rem;color:{color};font-family:'JetBrains Mono',monospace;font-weight:700;min-width:32px;">{confidence:.0%}</span>
    </div>
    """


def queue_badge_html(priority: str) -> str:
    """Generate a queue priority badge."""
    if priority == "IMMEDIATE":
        return '<span style="font-size:0.6rem;background:#ff1744;color:#fff;padding:1px 5px;border-radius:2px;font-weight:700;">🔴 IMMEDIATE</span>'
    elif priority == "BATCH":
        return '<span style="font-size:0.6rem;background:#ffc107;color:#000;padding:1px 5px;border-radius:2px;font-weight:700;">🟡 BATCH</span>'
    elif priority == "ARCHIVE":
        return '<span style="font-size:0.6rem;background:#555;color:#ccc;padding:1px 5px;border-radius:2px;font-weight:700;">⚫ ARCHIVE</span>'
    return ''


def strategy_card_html(s: dict, fv_data: dict = None) -> str:
    """Return HTML for a single strategy card with confidence bar and queue badge."""
    border = _card_border_color(s)
    pnl = s.get("latest_pnl", 0)
    sharpe = s.get("latest_sharpe", 0)
    dd = s.get("latest_drawdown", 0)
    trades = s.get("latest_trade_count", 0)
    wr = s.get("latest_win_rate", 0)
    style = s.get("style", "")
    asset = s.get("asset", "")
    code = s.get("strategy_code", "???")
    name = s.get("name", "")
    mode = s.get("current_mode")
    mode_e = MODE_EMOJI.get(mode, "")
    style_e = STYLE_EMOJI.get(style, "")
    pc = pnl_color(pnl)

    # Confidence & queue from FV data
    confidence_html = ""
    queue_html = ""
    if fv_data:
        confidence = fv_data.get("confidence", 0)
        priority = fv_data.get("queue_priority", "")
        confidence_html = confidence_bar_html(confidence)
        if priority:
            queue_html = queue_badge_html(priority)

    return f"""
    <div style="
        background:#161616;border:1px solid #222;border-left:4px solid {border};
        border-radius:4px;padding:8px 10px;margin-bottom:5px;font-size:0.78rem;line-height:1.35;
    ">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="font-weight:700;font-family:'JetBrains Mono',monospace;font-size:0.82rem;color:#e0e0e0;">
                {code}
            </span>
            <span style="font-size:0.7rem;">{style_e} {asset} {mode_e}</span>
        </div>
        <div style="color:#777;font-size:0.7rem;margin:1px 0 4px 0;">{name}</div>
        <div style="display:flex;gap:10px;font-family:'JetBrains Mono',monospace;font-size:0.7rem;color:#888;">
            <span style="color:{pc};">{format_pnl(pnl)}</span>
            <span>S:{format_sharpe(sharpe)}</span>
            <span>DD:{format_pct(dd)}</span>
            <span>W:{format_pct(wr)}</span>
        </div>
        <div style="color:#555;font-size:0.65rem;margin-top:3px;">{trades} trades</div>
        {confidence_html}
        {f'<div style="margin-top:3px;">{queue_html}</div>' if queue_html else ''}
    </div>
    """


def render_strategy_card(s: dict, fv_data: dict = None):
    """Render a strategy card with an expander for details."""
    st.markdown(strategy_card_html(s, fv_data), unsafe_allow_html=True)


def render_card_with_expander(s: dict, fv_data: dict = None):
    """Render card HTML then an expander with more details."""
    st.markdown(strategy_card_html(s, fv_data), unsafe_allow_html=True)
    with st.expander(f"📋 {s.get('strategy_code', '')} details", expanded=False):
        c1, c2, c3 = st.columns(3)
        c1.metric("PnL", format_pnl(s.get("latest_pnl", 0)))
        c2.metric("Sharpe", format_sharpe(s.get("latest_sharpe", 0)))
        c3.metric("Drawdown", format_pct(s.get("latest_drawdown", 0)))

        # Show confidence if available
        if fv_data:
            conf = fv_data.get("confidence", 0)
            priority = fv_data.get("queue_priority", "N/A")
            st.markdown(f"**Confidence:** {conf:.1%} | **Queue:** {priority}")

        st.caption(f"Style: {s.get('style','')} | Asset: {s.get('asset','')} | "
                   f"Status: {s.get('status','')} | Mode: {s.get('current_mode','—')} | "
                   f"Rank: {s.get('current_rank','—')} | Demotions: {s.get('consecutive_demotions',0)}")
        config = s.get("template_config", {})
        if config:
            st.json(config)
