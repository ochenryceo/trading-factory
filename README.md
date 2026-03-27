# 🏭 Trading Factory

Autonomous strategy discovery engine using evolutionary algorithms. Backtests thousands of futures strategies (NQ, GC, CL) across multiple timeframes with Darwin selection, Monte Carlo validation, ATR regime gating, and a 10-check production gate.

## Quick Start

```bash
# One command startup
docker compose up --build -d

# API available at http://localhost:8000
# API docs at http://localhost:8000/docs
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
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
- **Docker Compose** — one-click deployment

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /strategies` | List all strategies |
| `GET /strategies/{id}` | Get strategy details |
| `POST /strategies` | Create new strategy |
| `GET /backtest/{id}` | Get backtest results |
| `POST /backtest/run` | Run backtest |
| `GET /health` | Service health check |

## Core Services

### Strategy Discovery
- **Evolutionary algorithms** — genetic operators, crossover, mutation
- **Multi-timeframe backtesting** — 5m, 15m, 30m, 1h, 4h, daily
- **Darwin selection** — fitness-based survival with production gate
- **Search expansion** — ATR regime gating, conditional strategies

### Validation Pipeline
- **Monte Carlo** — 1000+ random entry permutations
- **Walk-forward testing** — rolling window validation
- **Production gate** — 10 checks across 3 stages
- **Paper trading** — NinjaTrader webhook integration

### Risk Management
- **Real-time monitoring** — drift detection, degradation alerts
- **Kill switches** — automatic strategy shutdown
- **Portfolio limits** — capital allocation, correlation checks
- **Alert system** — Discord integration for critical events

## Data Sources

- **Databento** — NQ, GC, CL futures data
- **Multi-timeframe aggregation** — OHLCV + volume profile
- **Real-time feeds** — market context, ATR regimes
- **Economic events** — news sentiment, volatility clustering

## Execution

### Paper Trading
- NinjaTrader integration via webhooks
- Real-time signal routing
- Performance tracking and validation
- Automatic promotion to live trading

### Live Trading
- Production-ready execution engine
- Risk limits and position sizing
- Real-time P&L tracking
- Compliance and audit trails

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Database
DATABASE_URL=postgresql+asyncpg://factory:your_password@localhost:5432/trading_factory

# Data provider
DATABENTO_API_KEY=your_databento_key_here

# Webhook secrets
WEBHOOK_SECRET=your_webhook_secret
NINJA_SECRET=your_ninja_secret

# Discord alerts (optional)
DISCORD_CEO_CHANNEL=your_channel_id
DISCORD_ALERTS_CHANNEL=your_channel_id
DISCORD_SYSTEM_CHANNEL=your_channel_id
```

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run database migrations
python scripts/schema.sql

# Start development server
python main.py
```

## License

MIT License - see LICENSE file for details.