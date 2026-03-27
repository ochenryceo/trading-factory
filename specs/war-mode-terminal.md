# Live Capital War Mode Terminal — Build Spec

**Status:** SAVED — Build after first 🏆 PRODUCTION READY
**Date:** 2026-03-26

## Trigger
Only build when: a strategy passes Production Gate (all 10 checks, score ≥ 0.85)

## Layout
```
┌──────────────────────────────────────────────────────────────┐
│ ① GLOBAL COMMAND BAR (PnL + Risk + Survival)                │
├───────────────┬───────────────────────────────┬──────────────┤
│ ② CAPITAL     │ ③ LIVE BATTLEFIELD            │ ④ RISK CORE  │
│ ALLOCATION    │ (PnL + Trades + Execution)    │ (Kill Logic) │
├───────────────┼───────────────┬───────────────┼──────────────┤
│ ⑤ STRATEGY    │ ⑥ DRIFT       │ ⑦ PROP MODE   │ ⑧ ALERT LOG  │
│ PERFORMANCE   │ MONITOR       │ (Constraints) │ (Critical)   │
└───────────────┴───────────────┴───────────────┴──────────────┘
```

## Panels

### ① Global Command Bar
- NET PnL (huge, color-coded green/red)
- Today PnL
- Max DD vs limit (always visible)
- Portfolio scale multiplier
- Risk status badge
- System mode: LIVE CAPITAL

### ② Capital Allocation
- Per-asset allocation % (NQ/CL/GC)
- Cash reserve %
- Top strategy + weight
- Adjustments: drift/correlation/prop pressure penalties

### ③ Live Battlefield (hero, center)
- Active positions with live PnL
- Entry/exit status, trailing stops
- Execution quality: slippage, missed trades, latency, score

### ④ Risk Core
- Portfolio DD vs limit (10%)
- Daily DD vs limit (5%)
- Kill switch status (OFF/ON)
- Correlation risk level
- System risk assessment

### ⑤ Strategy Performance (Expected vs Live)
- Per-strategy: expected Sharpe vs live Sharpe
- Expected WR vs live WR
- Expected DD vs live DD
- Color-coded match indicators (✅/⚠️/❌)

### ⑥ Drift Monitor
- Per-strategy drift status (OK/REDUCE/SEVERE/KILL)
- Weight multipliers
- Portfolio-level drift

### ⑦ Prop Mode
- Balance + target + current %
- Daily DD / Total DD vs limits
- Phase (Challenge/Funded)
- Pressure scale with reason

### ⑧ Alert Log
- Trade opened/closed
- Drift detected/weight reduced
- Profit locked
- DD warnings
- Strategy killed
- Target hit

### Decision Engine (overlay/panel)
- Current action being taken
- Reason (which signals triggered it)
- Confidence level

## Design Principles
- Every pixel answers: "Are we making money safely?"
- PnL and DD are top-level, always visible
- No clutter — justify every element
- Auto-updating, read-only, no user controls
- Color system: green=profit, red=drawdown, yellow=warning

## Data Sources
- webhook-receiver: /trades, /trades/summary, /ninja/status
- drift_status.json
- brain_portfolio.json
- prop_status.json
- production_gate_state.json
- control_state.json

## Prerequisites
- Production Gate approval (strategy passes all 10 checks)
- Capital Allocator module built (position sizing + scaling)
- Paper trading validated (30-day observation)
