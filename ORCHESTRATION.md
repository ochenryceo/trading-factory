# Orchestration Directive — Distributed Quantitative Trading System

_CEO Directive. Non-negotiable. Code-enforced._

## Architecture

| Layer | Machine A (Control) | Machine B (Compute) |
|---|---|---|
| **CPU** | Orchestration, API, validation | Strategy generation, agent coordination |
| **RAM** | Dashboard, monitoring state | Market data (24.8M bars), indicators |
| **GPU** | — | Backtesting, parameter sweeps, Ollama |

## Resource Rules

### CPU MUST:
- Handle all decision-making and validation logic (Directives 001–007)
- Schedule and prioritize agent workloads
- NEVER be blocked by long-running computations

### RAM MUST:
- Keep frequently used datasets in memory
- Avoid reloading data from disk repeatedly
- Maintain efficient usage (<80%)

### GPU MUST:
- Execute all heavy numerical workloads
- Be kept saturated but not overloaded

## Early Termination Rule
If a strategy fails early indicators after initial trades:
- Sharpe < -0.5 → **kill immediately**
- Win rate < 25% → **kill immediately**
- Max drawdown > 20% → **kill immediately**
- Negative expectancy → **kill immediately**

Conserve compute for promising candidates.

## Cluster-Aware Scheduling
Strategies grouped by: asset × timeframe × style

- **Underexplored clusters** → 2x compute allocation
- **Promising clusters** (pass rate >15%, Sharpe >1) → 1.8x allocation
- **Saturated clusters** (no new discoveries) → 0.2x allocation

## Implementation
- `services/orchestrator.py` — core orchestration logic
- `services/parallel_backtester.py` — 6 agents with early termination
- Cluster state tracked in `data/cluster_state.json`
