# Echo — News/Event Reaction Research & Strategy DNAs

_Track C Research | 2026-03-22_

---

## Part A: Trader Research

### 1. Kathy Lien
- **Market Focus:** Forex and index futures around macro events. Former JP Morgan trader.
- **Common Patterns:** Pre-positioning ahead of known catalysts (FOMC, NFP, CPI). Straddle entries around events. Post-event momentum rides.
- **Timeframe Logic:** Daily/4h for macro context and positioning expectations. 15m for pre-event setup. 5m/1m for post-event entry and stop management.
- **Entry/Exit Logic:** Analyzes consensus expectations vs actual. Positions in direction of surprise. Uses "wait for the first pullback" after initial reaction for safer entry. Avoids the first 10-30 seconds (spread widening).
- **Risk Management:** Small position sizes during news. Wider stops (2-3x normal). Reduces exposure by 50% during events. Clear max loss per event.

### 2. Boris Schlossberg
- **Market Focus:** Forex majors and NQ/ES around data releases. BK Asset Management.
- **Common Patterns:** "Fade the first move" — initial reaction is often wrong, especially on NFP. Uses the 15m close after release for directional signal. Pre-event range identification.
- **Timeframe Logic:** 1h for pre-event range. 15m for post-event directional confirmation. 5m for entry timing.
- **Entry/Exit Logic:** Mark the pre-event 1h range (1 hour before release). Wait 15 minutes after release. If price is outside range AND trending, enter in direction. If reversal back into range, fade the initial move.
- **Risk Management:** Never trade within first 2 minutes of release (liquidity issues). Wider ATR-based stops. Smaller position size (50% of normal).

### 3. News-Only Futures Traders (Community Pattern)
- **Market Focus:** NQ, ES, CL, GC on CPI, NFP, FOMC days exclusively.
- **Common Patterns:** Pre-event compression identification. Post-event directional move trading. Straddle bracket orders above/below pre-event range.
- **Timeframe Logic:** 1h pre-event for range marking. 5m post-event for trade execution. 15m for trend confirmation.
- **Entry/Exit Logic:** Wait 10-30 seconds after release for spreads to normalize. Enter in direction of dominant move once 5m candle closes outside pre-event range. Target: 1-2x the pre-event range projected.
- **Risk Management:** Risk 0.5-1% per event trade (half of normal). Max 1-2 trades per event. Daily stop applies.

### 4. CME Institutional Event Traders
- **Market Focus:** Treasury, equity index, and commodity futures around FOMC, CPI, PPI, retail sales.
- **Common Patterns:** Positioning analysis (COT data) before events. Trade the "surprise" — difference between consensus and actual. Use options straddles for non-directional exposure.
- **Timeframe Logic:** Weekly for positioning context. Daily for pre-event analysis. 5m for execution post-event.
- **Entry/Exit Logic:** Analyze crowded positioning (COT). If everyone is positioned one way, the opposite reaction to the event is more violent. Enter counter-crowd on surprise.
- **Risk Management:** Options-based risk definition. Futures with wide stops. Event-specific sizing (smaller than normal).

### 5. Edgeful Data-Driven Approach
- **Market Focus:** NQ, ES, CL futures. Statistical analysis of historical event reactions.
- **Common Patterns:** Historical pattern matching — "what does price do after hot CPI?" Uses statistical probabilities rather than prediction. Tracks first 15 min, 30 min, 1 hour post-event returns.
- **Timeframe Logic:** 15m as primary post-event analysis window. 5m for execution. 1h for trend confirmation.
- **Entry/Exit Logic:** Wait for 15m candle to close after event. If direction matches historical pattern for this type of surprise, enter. Target based on historical average move for that event type.
- **Risk Management:** Only trade high-probability historical setups (> 60% historical win rate). Smaller position size. Clear time-based exits.

---

## Part B: Strategy DNAs

### NR-001: Post-Event Range Expansion

```json
{
  "strategy_code": "NR-001",
  "style": "news_reaction",
  "template": "Momentum_Template",
  "timeframe_logic": {
    "4h": "Identify pre-event macro context — trend direction, key levels, and positioning",
    "1h": "Mark pre-event consolidation range (1 hour before scheduled event). Calculate range size",
    "15m": "Wait for first 15m candle to close after event. This is the directional signal",
    "5m": "Enter on 5m confirmation in direction of 15m signal with volume surge"
  },
  "hypothesis": "Scheduled macro events (CPI, NFP, FOMC) create pre-event compression that resolves into directional moves. The first 15m close after the event indicates the market's digested direction. Trading this direction with volume confirmation captures the expansion move",
  "entry_rules": "Known scheduled event (CPI, NFP, FOMC). 1h pre-event range marked. 15m candle closes outside pre-event range after release. 5m confirms with close in same direction and volume > 2x average. Enter on 5m confirmation",
  "exit_rules": "Target 1: 1x pre-event range projected from breakout. Target 2: 2x pre-event range. Trail with 5m 10 EMA. Time exit: 2 hours after entry",
  "stop_loss": "Back inside pre-event range (opposite side of breakout). Max 1x pre-event range from entry",
  "filters": [
    "Only trade Tier 1 events: CPI, NFP, FOMC, PPI, retail sales",
    "Wait minimum 10 seconds after release for spreads to normalize",
    "15m candle must CLOSE outside range, not just wick",
    "Volume on reaction > 3x average (confirms real institutional participation)"
  ],
  "parameter_ranges": {
    "pre_event_range_minutes": [30, 90],
    "wait_after_release_seconds": [10, 60],
    "volume_multiplier": [2.0, 5.0],
    "target_range_multiple": [1.0, 3.0],
    "max_hold_hours": [1.0, 4.0]
  },
  "expected_behavior": {
    "win_rate": "50-60%",
    "avg_RR": "1.5-2.5R",
    "best_regime": "surprising data releases (deviation from consensus)",
    "worst_regime": "in-line data where reaction is muted or choppy"
  },
  "invalidation": "If win rate < 40% over 50 event trades or if pre-event range expansion fails > 50% of the time, strategy is invalid"
}
```

### NR-002: Fade the Initial Reaction

```json
{
  "strategy_code": "NR-002",
  "style": "news_reaction",
  "template": "MeanReversion_Template",
  "timeframe_logic": {
    "4h": "Check macro trend and positioning. If trend is strong, initial reactions against trend often reverse",
    "1h": "Mark pre-event range. Note prior key support/resistance levels that might cap the reaction",
    "15m": "Monitor initial reaction. If price spikes to key level and shows exhaustion, prepare to fade",
    "5m": "Enter fade trade when 5m shows reversal candle at key level after initial news spike"
  },
  "hypothesis": "Initial reactions to news events are often driven by algorithmic stop-hunting and emotional retail participation. When the initial move hits a key structural level and shows exhaustion, fading the first move captures the reversion as smart money takes the other side",
  "entry_rules": "News event produces sharp initial move (> 1 ATR in first 5 minutes). Price reaches key structural level on 1h (prior support/resistance, round number). 5m shows exhaustion: reversal candle, volume spike then decline, RSI extreme. Enter fade direction on 5m reversal candle close",
  "exit_rules": "Target: pre-event price (full reversion). Partial exit at 50% reversion. Time exit: 1 hour if no reversion occurring. Exit immediately if price makes new extreme beyond key level",
  "stop_loss": "Beyond key structural level plus 1 ATR(15m). If initial spike exceeds all nearby structure, do not take the trade",
  "filters": [
    "Initial move must be sharp (> 1 ATR in 5 minutes) — slow grinds don't fade well",
    "Must hit a recognizable structural level (not just random overextension)",
    "5m exhaustion signals must be present (not just hoping for reversal)",
    "4h trend should ideally be against the initial reaction (fading WITH the macro trend)"
  ],
  "parameter_ranges": {
    "min_initial_move_atr": [1.0, 2.0],
    "exhaustion_volume_ratio": [2.0, 4.0],
    "rsi_extreme": [15, 25],
    "atr_stop_buffer": [0.5, 1.5],
    "reversion_target_pct": [50, 100]
  },
  "expected_behavior": {
    "win_rate": "45-55%",
    "avg_RR": "1.5-2.5R",
    "best_regime": "in-line data where initial reaction is positioning-driven, not fundamental",
    "worst_regime": "major surprise events where the initial reaction IS the real move"
  },
  "invalidation": "If win rate < 35% over 50 event trades or if faded moves continue to new extremes > 40% of the time, strategy is invalid"
}
```

### NR-003: FOMC Drift Strategy

```json
{
  "strategy_code": "NR-003",
  "style": "news_reaction",
  "template": "Trend_Template",
  "timeframe_logic": {
    "4h": "Analyze pre-FOMC trend. Historically, markets tend to drift in direction of pre-FOMC trend post-announcement",
    "1h": "Mark FOMC announcement range (first 30 min after 2 PM ET). Note initial direction",
    "15m": "After initial volatility subsides (30-45 min post), identify the trend direction on 15m",
    "5m": "Enter on first pullback in the post-FOMC direction with declining volatility"
  },
  "hypothesis": "FOMC announcements create a characteristic pattern: initial two-way whipsaw (first 30 min), followed by a directional drift that often persists for 24-48 hours. Trading the drift rather than the initial reaction avoids whipsaw and captures the sustainable move",
  "entry_rules": "FOMC announcement at 2 PM ET. Wait 30-45 minutes for initial whipsaw to settle. Identify 15m trend direction post-settlement. Enter on first 5m pullback in the drift direction. Volume should be declining from spike (normalizing)",
  "exit_rules": "Hold for FOMC drift — target next day continuation. Trail with 1h 20 EMA. Partial exit at 1R, hold remainder for 24-hour drift. Exit next session open if still profitable",
  "stop_loss": "Below post-settlement swing low (long) or above swing high (short). Approximately 1.5 ATR(15m). Wide stop for news volatility",
  "filters": [
    "Only trade 8 FOMC meetings per year — pure event strategy",
    "Must wait minimum 30 minutes post-announcement",
    "Initial whipsaw must show clear resolution on 15m (not still two-way)",
    "4h pre-FOMC trend alignment increases probability"
  ],
  "parameter_ranges": {
    "post_fomc_wait_minutes": [30, 60],
    "atr_stop_multiplier": [1.0, 2.0],
    "drift_hold_hours": [12, 36],
    "ema_trail_period": [15, 25],
    "target_R": [2.0, 4.0]
  },
  "expected_behavior": {
    "win_rate": "55-65%",
    "avg_RR": "2.0-3.0R",
    "best_regime": "FOMC meetings with clear policy direction change",
    "worst_regime": "FOMC meetings with no change and mixed dot plot signals"
  },
  "invalidation": "If win rate < 40% over 20 FOMC events (2.5 years of data) or if drift fails to materialize in > 50% of meetings, strategy is invalid"
}
```

### NR-004: CPI Surprise Momentum

```json
{
  "strategy_code": "NR-004",
  "style": "news_reaction",
  "template": "Momentum_Template",
  "timeframe_logic": {
    "4h": "Pre-CPI: note market expectations (consensus estimate). Check 4h trend for alignment",
    "1h": "Mark pre-CPI range (1 hour before 8:30 AM ET). Note key support/resistance above and below",
    "15m": "First 15m close after CPI release determines direction. Measure deviation from consensus",
    "5m": "Enter on 5m pullback after initial thrust, in direction of surprise"
  },
  "hypothesis": "CPI surprises (actual vs consensus) create directional moves that persist for 2-4 hours. A hot CPI (higher than expected) is bearish for NQ/bonds, bullish for GC. A cool CPI is the opposite. The first pullback after the initial reaction offers the best risk:reward entry",
  "entry_rules": "CPI data released at 8:30 AM ET. Surprise = actual deviation from consensus > 0.1%. Wait for 15m close to confirm direction. Enter on first 5m pullback (retracement of 20-40% of initial move). Volume > 2x average on both reaction and pullback",
  "exit_rules": "Target: next major structural level on 1h in direction of move. Trail with 15m 10 EMA. Time exit: 4 hours after CPI release",
  "stop_loss": "Below pullback low plus 0.5 ATR(15m). Max 1R = size of initial pullback",
  "filters": [
    "CPI surprise must be > 0.1% from consensus — in-line prints don't trend",
    "Must wait for first pullback, not chase the initial spike",
    "Direction must match logical market response (hot CPI = bearish equities, etc.)",
    "Not on the same day as FOMC meeting (conflicting catalysts)"
  ],
  "parameter_ranges": {
    "min_surprise_deviation": [0.1, 0.3],
    "pullback_retracement_pct": [20, 50],
    "volume_multiplier": [1.5, 3.0],
    "max_hold_hours": [2.0, 6.0],
    "ema_trail_period": [8, 15]
  },
  "expected_behavior": {
    "win_rate": "52-62%",
    "avg_RR": "1.5-2.5R",
    "best_regime": "significant CPI surprises (> 0.2% deviation)",
    "worst_regime": "in-line or ambiguous CPI prints"
  },
  "invalidation": "If win rate < 40% over 30 CPI events (2.5 years) or if surprise direction doesn't produce expected market response > 40% of time, strategy is invalid"
}
```

### NR-005: Pre-Event Compression Straddle

```json
{
  "strategy_code": "NR-005",
  "style": "news_reaction",
  "template": "Momentum_Template",
  "timeframe_logic": {
    "4h": "Note pre-event trend and key levels. Identify if market has compressed into event",
    "1h": "Measure pre-event compression — Bollinger Band width shrinking, ATR declining for 3+ bars",
    "15m": "Set breakout levels at pre-event range high and low (bracket). Prepare for expansion",
    "5m": "Enter whichever direction breaks first after event, with volume confirmation"
  },
  "hypothesis": "Markets compress before major events (options dealers hedging, participants reducing risk). This compression stores energy that is released upon the event, regardless of direction. Trading the expansion from compression, not predicting direction, is the edge",
  "entry_rules": "Pre-event compression detected: 1h Bollinger Band width at 20-bar low AND ATR declining for 3+ bars. Bracket orders set at pre-event range high + 2 ticks and low - 2 ticks. Enter whichever side fills first after event. 5m volume must be > 3x average to confirm",
  "exit_rules": "Target: 1.5-2x the compression range projected from breakout. Trail with 5m 10 EMA. Cancel unfilled side immediately when one side fills. Time exit: 2 hours post-event",
  "stop_loss": "Opposite side of compression range (the unfilled bracket level). If range is very tight, use 1 ATR(1h) minimum",
  "filters": [
    "Compression must be genuine: BB width at 20-bar low on 1h",
    "Must be a Tier 1 scheduled event (CPI, NFP, FOMC, PPI)",
    "Volume pre-event should be declining (confirming compression)",
    "Minimum 3 bars of ATR decline on 1h before event"
  ],
  "parameter_ranges": {
    "bb_width_percentile": [5, 20],
    "atr_decline_bars": [3, 6],
    "bracket_buffer_ticks": [1, 5],
    "target_range_multiple": [1.5, 3.0],
    "max_hold_hours": [1.0, 4.0]
  },
  "expected_behavior": {
    "win_rate": "48-58%",
    "avg_RR": "1.5-3.0R",
    "best_regime": "well-compressed markets before high-impact events",
    "worst_regime": "events that produce two-way whipsaw without clear direction"
  },
  "invalidation": "If win rate < 38% over 50 event trades or if compression-to-expansion ratio < 1.5x more than 50% of the time, strategy is invalid"
}
```
