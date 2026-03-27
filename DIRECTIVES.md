# CEO Directives — Trading Factory

_These are permanent system rules. Non-negotiable. Code-enforced where possible._

---

## Directive 001 — Final Validation Protocol (2026-03-23)

Every strategy must pass Gate 4 (Multi-Axis Degradation) + Gate 5 (Dependency Test) before paper trading. Code-enforced. No manual override except Jordan.

- `if not degradation_passed or not dependency_passed: block_paper_trading()`
- Decision tags: READY_FOR_PAPER / REQUIRES_HARDENING / REJECTED_POST_DARWIN

## Directive 002 — No Single-Indicator Edges (2026-03-23)

**ADX (or any single indicator) must NEVER be both the gatekeeper AND the edge.**

A regime filter is a safety net — it tells you WHEN to trade. The entry logic must carry the edge independently. If removing the regime filter collapses the strategy, you don't have an edge — you have a filter pretending to be one.

**Rule:** If any single indicator removal causes >40% performance drop, the strategy is tagged FRAGILE and rejected. The edge must be distributed across multiple independent signals.

## Directive 003 — Robust Edge > Precise Configuration (2026-03-23)

**If ±10-20% parameter shift breaks a strategy, it's curve-fitted — not robust.**

A real market edge works across a RANGE of parameters. A precise configuration that only works at exact values found an artifact in historical noise, not a market inefficiency.

**Rule:** Parameter degradation at ±20% must not cause equity curve collapse or >50% drawdown increase. Strategies that only work at specific parameter values are rejected as overfitted.

**What we want:** Strategies where the LOGIC is the edge (structure, context, alignment) — not the exact number plugged into an indicator.

## Directive 004 — Suspicion Filter: Too Good = Suspicious (2026-03-23)

**If it looks too good, it probably is.**

Any strategy matching these criteria gets flagged `SUSPICIOUS_EDGE`:
- Win rate > 85% AND drawdown < 1% → `TOO_GOOD_TO_BE_TRUE`
- Win rate > 85% alone → `HIGH_WR`
- Drawdown < 1% with 20+ trades → `ULTRA_LOW_DD`
- Sharpe > 4.0 → `EXTREME_SHARPE`
- Average loss > 3x average win → `HIDDEN_TAIL_RISK` (tiny wins, big losses)
- Largest single loss > 50% of total PnL → `SINGLE_LOSS_WIPEOUT`

**Rule:** Don't kill suspicious strategies early. Let them pass through the full pipeline. Degradation and dependency tests will expose fakes. But flag them so they get extra scrutiny before paper trading.

**Realistic winner profile:**
- 🟢 Sharpe 1–2, DD 3–10%, WR 50–70% → strong and believable
- 🟡 Sharpe 2–4, WR 70–85% → investigate deeply
- 🔴 Sharpe >4, WR >85%, DD <1% → suspicious until proven otherwise

## Directive 005 — Realistic Performance Bands (2026-03-23)

**Prioritize strategies in the realistic zone:**
- Sharpe: **1.0–2.5** (sweet spot)
- Win Rate: **50–70%** (sustainable)
- Max Drawdown: **3–10%** (controlled risk)
- Profit Factor: **1.3–3.0** (edge without fantasy)

Strategies outside these bands CAN proceed but get flagged for extra validation.

## Directive 006 — Time Consistency Check (2026-03-23)

**An edge that only worked in one period isn't an edge — it's luck.**

Split trades into quarterly periods and check:
1. **Performance variance (CV):** If coefficient of variation > 2.0 → `REGIME_DEPENDENT_EDGE`
2. **No losing periods:** If ALL periods are profitable with 4+ periods → `NO_LOSING_PERIODS` (suspicious)
3. **Golden period:** If one period carries >60% of total PnL → `GOLDEN_PERIOD` (temporal edge)
4. **Win rate consistency:** If WR spread > 40pp across periods → `INCONSISTENT_WR`

A real edge performs consistently across time. Not perfectly — but consistently. A strategy that crushed 2020 and broke even everywhere else is trading the pandemic, not the market.

## Directive 007 — Equity Curve Smoothness Check (2026-03-23)

**Growth should be steady, not spiky.**

Analyze the equity curve for:
1. **R² linearity:** If equity curve R² < 0.5 → `UNSTABLE_GROWTH` (erratic, not steady)
2. **Volatility spikes:** If return volatility ratio > 4x → `VOLATILITY_SPIKES` (growth in bursts)
3. **Long stalls:** If equity underwater >50% of time → `LONG_STALL` (stalled, not growing)
4. **Burst dependency:** If top 10% of trades = >60% of gains → `BURST_DEPENDENT` (needs big hits)

A smooth equity curve means the edge is consistent trade-to-trade. A spiky curve means you're dependent on catching the right moment — which is luck, not edge.

## Directive 008 — Compute Allocation Policy (2026-03-23)

**Style weights (fixed allocation):**
- Volume Orderflow: 40%
- Scalping: 30%
- Mean Reversion: 15%
- Momentum Breakout: 10%
- Trend Following: 3%
- News Reaction: 2%

**Revival Trigger:** If a deprioritized style shows improvement (discoveries > 0 after being near-zero), automatically increase compute allocation.

**Edge Mapping:** Track Style × Timeframe × Asset scores. The edge is NOT "volume orderflow is good" — the edge is "GC + 5m + volume_orderflow = HIGH". Precision matters.

**Cluster Stability:** Before deploying new paper trades, verify dominant clusters persist over multiple brain cycles (minimum hours). Don't chase single-cycle spikes.

---

_"We don't deploy hope — we deploy proof. And proof means it works when the numbers shift."_
