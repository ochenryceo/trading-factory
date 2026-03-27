# 🏭 Trading Factory

Multi-agent strategy factory and trading operations platform for futures trading (NQ, GC, CL).

## Quick Start

```bash
# One command startup
docker compose up --build -d

# API available at http://localhost:8000
# Dashboard available at http://localhost:8501
# API docs at http://localhost:8000/docs
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Streamlit Dashboard                 │
│            (Visual Command Center)                   │
├─────────────────────────────────────────────────────┤
│                   FastAPI Backend                     │
│            (REST API + Business Logic)               │
├───────────────────┬─────────────────────────────────┤
│    PostgreSQL 16  │         Redis 7                  │
│  (Durable State)  │   (Cache + Events)              │
└───────────────────┴─────────────────────────────────┘
```

## Pipeline Stages

Every strategy must pass through all 8 stages — no skipping:

```
IDEA → BACKTEST → VALIDATION → PAPER → DEGRADATION → DEPENDENCY → MICRO LIVE → FULL LIVE
```

## Stack

- **Python 3.11+**, FastAPI, SQLAlchemy 2.0 (async), asyncpg
- **PostgreSQL 16** — 8 tables for full lifecycle tracking
- **Redis 7** — caching and event streaming
- **Streamlit** — visual operations console
- **Docker Compose** — one-click deployment

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /strategies` | All strategies with metrics |
| `GET /strategies/{id}` | Full strategy detail |
| `GET /pipeline` | Grouped by stage (Kanban) |
| `GET /metrics/summary` | Dashboard totals |
| `GET /events/kill-feed` | Kills, failures, risk events |
| `GET /risk/state` | Global risk posture |
| `GET /research/styles` | Trader inspirations by style |
| `GET /audit` | Filtered audit history |
| `GET /live-ops` | Active signals and live activity |

## Database Tables

1. **strategies** — core identity and lifecycle state
2. **strategy_metrics** — performance by stage and date
3. **strategy_history** — immutable stage transition ledger
4. **audit_log** — every system event
5. **trade_explanations** — why trades won or lost
6. **research_sources** — trader inspiration
7. **strategy_research_links** — strategy ↔ research mapping
8. **overrides** — override attempts and approvals

## Seed Data

On first startup, the API service automatically seeds 25 realistic mock strategies across all pipeline stages with metrics, trade explanations, research sources, audit logs, and override examples.

## Development

```bash
# Run locally (without Docker)
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://factory:your_password_here@localhost:5432/trading_factory
python scripts/seed.py
uvicorn main:app --reload --port 8000
```

## Environment Variables

See `.env` for all configuration. Key variables:
- `DATABASE_URL` — PostgreSQL async connection string
- `REDIS_URL` — Redis connection
- `DATABENTO_API_KEY` — Market data API key
