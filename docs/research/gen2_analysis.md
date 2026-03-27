# Generation 2 Strategy DNA Analysis

**Date:** 2026-03-22  
**Author:** R&D Department  
**Status:** COMPLETE — 24 Gen 2 strategies produced

---

## Executive Summary

Gen 1 strategies averaged **38.8% confidence** with **zero IMMEDIATE queue** placements. Every single strategy lost money in fast validation. The root cause is clear: **Gen 1 strategies had no regime awareness** — they traded the same signals in trending, ranging, choppy, and volatile markets indiscriminately, destroying edge through signal dilution.

Gen 2 introduces **5 systemic fixes** that address every identified failure mode. Expected confidence improvement: **55-70%** average (vs 38.8%).

---

## What Was Wrong With Gen 1

### 1. No Regime Filtering — The #1 Killer

Every Gen 1 strategy traded in ALL market conditions. A momentum breakout strategy (MOM-001) would fire in choppy ranges. A mean reversion strategy (MR-001) would fade moves in strong trends. This is the equivalent of using a hammer on screws.

**Evidence:**
- MOM strategies: 32.7% win rate in fast validation — they were firing in ranging markets where breakouts fail
- MR strategies: -$3,700 avg PnL — they were fading moves in trending markets where mean reversion fails
- TF strategies: 23.8-26.7% win rate — too many signals in choppy conditions

### 2. Weak Exits Destroyed Expectancy

Gen 1 used simple "5m signal exit" for almost every strategy. This is catastrophically inadequate:
- **No trailing stops** — gave back large winning moves
- **No breakeven protection** — let 1R winners become losers
- **No time limits** — held dead trades indefinitely
- **No structure-based exits** — ignored market information

**Evidence from backtest:**
- MOM-001: avg_win 6.1% vs avg_loss 4.3% — only 1.4R ratio despite targeting 2-3R
- SCP-002: largest_loss -11.3% vs largest_win 6.0% — asymmetry is BACKWARDS
- MR-001: avg_win 2.9% vs avg_loss 6.3% — losses 2x wins

### 3. No Signal Strength Filtering

Gen 1 took every signal regardless of quality. A weak RSI touch at 31 was treated the same as a deep RSI plunge to 18 with divergence and volume capitulation.

### 4. No Volume/Liquidity Gate

Gen 1 VOF strategies were the worst performers (-$7,882 to -$8,442 in fast validation). They attempted order flow analysis without checking if institutional volume was present. In thin markets, order flow signals are noise.

### 5. No Asymmetric Risk/Reward Design

Gen 1 strategies averaged ~1.4R on wins with losses often exceeding wins. The payoff profile was nearly symmetric, requiring >50% win rate to be profitable — and most strategies couldn't achieve that.

---

## What Changed in Gen 2

### Fix 1: Regime Awareness (EVERY strategy)

Every Gen 2 DNA includes a `regime_filter` with:
- ADX threshold for trend strength gating
- Volatility range constraints
- Explicit enabled/disabled regimes

**Regime specialization:**
| Style | Regime Gate | ADX Requirement |
|-------|-----------|----------------|
| Alpha (Momentum) | Trending only | ADX > 25 |
| Bravo (Mean Reversion) | Ranging only | ADX < 20-22 |
| Charlie (Scalping) | Low volatility | ATR < 1.2x avg |
| Delta (Trend Following) | Strong trends | ADX > 25-30 |
| Echo (News Reaction) | Event-driven | Surprise > 0.15% |
| Foxtrot (Volume/OF) | High volume | Volume > 1.5x avg |

### Fix 2: Advanced Exit System

Every Gen 2 DNA includes structured `exit_rules`:
- **Primary:** ATR trailing stop (adapts to volatility)
- **Secondary:** Structure break / target level
- **Time limit:** Prevents dead-money trades
- **Breakeven trigger:** Moves stop to entry at 0.8-1.0R
- **Partial scaling:** Locks profits at 1R, 2R milestones

### Fix 3: Signal Strength Filtering

Every Gen 2 DNA requires:
- Minimum signal strength score (0.6-0.7)
- 2-3 confirming indicators (not just one)
- Volume confirmation mandatory
- Delta/order flow confirmation where applicable

### Fix 4: Asymmetric Risk/Reward

Every Gen 2 DNA targets:
- Minimum 2.0R (most target 2.5-4.0R)
- ATR-based stops (tight: 0.6-1.5 ATR)
- Trailing exits to capture extended moves
- Breakeven protection to eliminate give-back

### Fix 5: Volume/Participation Gates (VOF strategies)

VOF Gen 2 strategies require session volume > 1.5x 20-day average before trading. This ensures:
- Institutional participation (signals are meaningful)
- Better fills (tighter spreads)
- Stronger level defense (more capital defending levels)

---

## Expected Impact on Confidence Scores

### Confidence Score Drivers
The confidence formula weighs: win_rate, PnL, drawdown, Sharpe ratio, and trade count.

### Gen 1 → Gen 2 Expected Improvements

| Style | Gen 1 Avg Confidence | Expected Gen 2 | Change | Why |
|-------|---------------------|----------------|--------|-----|
| **Momentum (MOM)** | 38.5% | 58-65% | +20-27pp | ADX gate eliminates 60% of false breakouts |
| **Mean Reversion (MR)** | 36.0% | 62-70% | +26-34pp | ADX < 20 prevents fading trends (biggest killer) |
| **Scalping (SCP)** | 42.6% | 55-62% | +12-19pp | Low-vol filter + tighter stops reduce damage |
| **Trend Following (TF)** | 44.3% | 55-65% | +11-21pp | ADX > 30 (vs 20) eliminates choppy whipsaws |
| **News Reaction (NR)** | 35.4% | 52-60% | +17-25pp | Surprise filter + pullback entry = better RR |
| **Volume/OF (VOF)** | 36.3% | 58-68% | +22-32pp | Volume gate + regime filter = biggest improvement |

### Overall Expected
- **Gen 1 Average:** 38.8%
- **Gen 2 Expected Average:** 58-65%
- **Improvement:** +20-27 percentage points

### Which Styles Should Improve Most

1. **VOF (Volume/Order Flow)** — Biggest expected improvement (+22-32pp)
   - Gen 1 was the worst performer (-$7,882 to -$8,442 PnL)
   - Adding volume > 1.5x gate + ADX < 25 for range strategies should fix the core issue
   - VOF strategies were trying to read order flow in thin markets and trending conditions

2. **Mean Reversion (MR)** — Second biggest improvement (+26-34pp)
   - Gen 1 MR was fading moves in trends (fatal)
   - ADX < 20 gate ensures only ranging markets
   - Triple confirmation (RSI + divergence + delta) raises signal quality

3. **Momentum (MOM)** — Significant improvement (+20-27pp)
   - ADX > 25 gate prevents false breakouts in ranges
   - ATR trailing exit captures the big moves Gen 1 left on the table
   - VCP pattern (MOM-G2-002) targets 4R — single winners can carry the portfolio

4. **News Reaction (NR)** — Moderate improvement (+17-25pp)
   - Surprise deviation filter (> 0.15%) eliminates in-line data trades
   - Pullback entry vs spike chase = fundamentally better RR
   - FOMC drift strategy has historical edge of 55-65% WR

5. **Trend Following (TF)** — Moderate improvement (+11-21pp)
   - ADX > 30 (vs Gen 1's > 20) = much fewer but higher quality signals
   - Chandelier/ATR trailing exits let winners run (Gen 1 capped at fixed targets)
   - Partial scaling locks profits

6. **Scalping (SCP)** — Moderate improvement (+12-19pp)
   - Low-vol regime filter prevents scalping in volatile sessions
   - Ultra-tight stops (0.6-0.8 ATR) limit per-trade damage
   - Failed breakout trap strategy (SCP-G2-002) has built-in edge in ranging markets

---

## Strategy Count Summary

| Style | Gen 1 | Gen 2 | Total |
|-------|-------|-------|-------|
| Momentum | 5 | 4 | 9 |
| Mean Reversion | 5 | 4 | 9 |
| Scalping | 5 | 4 | 9 |
| Trend Following | 5 | 4 | 9 |
| News Reaction | 5 | 4 | 9 |
| Volume/Order Flow | 5 | 4 | 9 |
| **Total** | **30** | **24** | **54** |

---

## Key Gen 2 Strategy Highlights

### Highest Expected Win Rate
- **MR-G2-004** (Z-score extreme reversion): 62-72% WR, 2.0-2.5R
- **VOF-G2-003** (Absorption detection): 60-70% WR, 2.0-2.5R
- **MR-G2-002** (BB snap-back): 60-70% WR, 2.0-2.5R

### Highest Expected Asymmetry
- **TF-G2-002** (Donchian + Chandelier): 38-48% WR but 3.0-5.0R
- **MOM-G2-002** (VCP breakout): 42-52% WR but 2.5-4.0R
- **NR-G2-003** (FOMC drift): 55-65% WR and 2.5-4.0R

### Best Risk Management
- **VOF-G2-003** (Absorption): 0.6 ATR stop + breakeven at 0.6R
- **SCP-G2-003** (Ignition): 0.8 ATR stop + 8-bar time limit
- **All Gen 2**: Breakeven triggers at 0.6-1.0R

---

## Risk Assessment

### What Could Still Go Wrong
1. **Regime detection accuracy** — If ADX/ATR misclassify the regime, wrong strategies will fire
2. **Over-filtering** — Some Gen 2 strategies might trade too rarely (especially MOM-G2-003 with ADX > 30)
3. **Look-ahead bias** — Gen 2 was designed looking at Gen 1 failures; real forward performance is the true test
4. **Correlation** — Multiple strategies might fire on the same setups, concentrating risk

### Mitigation
- Run Gen 2 through the same fast validation pipeline
- Monitor trade frequency — if a strategy averages < 5 trades/month, consider relaxing filters
- Diversify across styles so correlated entries are limited
- Set portfolio-level max exposure across all active strategies

---

## Next Steps

1. **Run fast validation** on all 24 Gen 2 strategies
2. **Compare** Gen 2 validation results to Gen 1 baseline
3. **Promote** top performers (confidence > 60%) to BATCH/IMMEDIATE queue
4. **Retire** Gen 1 strategies that Gen 2 directly replaces
5. **Iterate** — Gen 3 should focus on the weakest Gen 2 performers

---

*R&D Department — Generation 2 Analysis Complete*
