"""Shared layout, theme, and data-fetching utilities."""
import os
import json
import streamlit as st
import requests

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
MOCK_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "mock")

# ── Theme CSS injection ──────────────────────────────────────────────
def inject_theme():
    css_path = os.path.join(os.path.dirname(__file__), "..", "assets", "styles.css")
    if os.path.exists(css_path):
        with open(css_path) as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    # Extra inline overrides for Streamlit defaults
    st.markdown("""
    <style>
    .block-container { padding-top: 1rem !important; max-width: 100% !important; }
    header[data-testid="stHeader"] { background: #0a0a0a !important; }
    .stApp { background: #0a0a0a !important; }
    [data-testid="stSidebar"] { background: #111 !important; }
    div[data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace; }
    </style>
    """, unsafe_allow_html=True)


# ── API fetch with fallback ──────────────────────────────────────────
def fetch(endpoint: str, params: dict | None = None, fallback_file: str | None = None):
    """Fetch from FastAPI; fall back to mock JSON on failure."""
    url = f"{API_BASE}{endpoint}"
    try:
        r = requests.get(url, params=params, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        if fallback_file:
            path = os.path.join(MOCK_DIR, fallback_file)
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f)
        return None


# ── Color helpers ────────────────────────────────────────────────────
STATUS_COLORS = {
    "ACTIVE":  "#00c853",
    "WARNING": "#ffc107",
    "KILLED":  "#ff1744",
    "RETIRED": "#555555",
    "PENDING": "#888888",
}

STAGE_COLORS = {
    "IDEA":        "#888888",
    "BACKTEST":    "#888888",
    "VALIDATION":  "#ffc107",
    "PAPER":       "#2979ff",
    "DEGRADATION": "#ffc107",
    "DEPENDENCY":  "#ffc107",
    "MICRO_LIVE":  "#aa00ff",
    "FULL_LIVE":   "#ffffff",
}

MODE_EMOJI = {
    "paper": "🔵",
    "micro": "🟣",
    "full":  "⚡",
    None:    "⚪",
}

STYLE_EMOJI = {
    "momentum":       "🚀",
    "trend":          "📈",
    "mean_reversion": "🔄",
    "scalp":          "⚡",
    "news_reaction":  "📰",
    "volume_flow":    "🌊",
}

def status_color(status: str) -> str:
    return STATUS_COLORS.get(status, "#888888")

def stage_color(stage: str) -> str:
    return STAGE_COLORS.get(stage, "#888888")

def pnl_color(pnl: float) -> str:
    if pnl > 0: return "#00c853"
    if pnl < 0: return "#ff1744"
    return "#888888"

def format_pnl(v: float) -> str:
    prefix = "+" if v > 0 else ""
    return f"{prefix}${v:,.0f}"

def format_pct(v: float) -> str:
    return f"{v*100:.1f}%"

def format_sharpe(v: float) -> str:
    return f"{v:.2f}"


# ── Page header ──────────────────────────────────────────────────────
def page_header(title: str, subtitle: str = ""):
    st.markdown(f"""
    <div style="margin-bottom:16px;">
        <h1 style="margin:0;padding:0;font-size:1.6rem;color:#e0e0e0;font-weight:800;letter-spacing:-0.5px;">
            {title}
        </h1>
        <p style="margin:2px 0 0 0;color:#666;font-size:0.8rem;">{subtitle}</p>
    </div>
    """, unsafe_allow_html=True)
