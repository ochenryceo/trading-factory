# Charlie — Scalping Research & Strategy DNAs

_Track C Research | 2026-03-22_

---

## Part A: Trader Research

### 1. Al Brooks
- **Market Focus:** ES/NQ futures. Pure price action scalper. Author of "Trading Price Action" trilogy.
- **Common Patterns:** Two-legged pullbacks, wedge reversals, breakout pullbacks, trading range breakouts/failures. Reads every bar as a signal.
- **Timeframe Logic:** Primarily 5m charts with 1h context. Does not use indicators — pure price action and bar-by-bar analysis.
- **Entry/Exit Logic:** Enter on signal bars (reversal bars at support/resistance). Uses limit orders at key levels. Targets 1-2 points on ES (equivalent 4-8 on NQ). Quick exits on failure.
- **Risk Management:** Fixed stop of 2 points ES (8 NQ). 1:1 or 2:1 R:R targets. Scalps often with 50% win rate but maintains positive expectancy through R:R and reading context.

### 2. John Grady (No BS Day Trading)
- **Market Focus:** NQ, ES futures. Order flow and tape reading scalper.
- **Common Patterns:** DOM (depth of market) reading, iceberg order detection, absorption patterns, momentum ignition. Level-to-level trading between key zones.
- **Timeframe Logic:** 1m-5m for execution, DOM/tape for real-time. Uses 15m-1h for key level identification.
- **Entry/Exit Logic:** Reads the tape for large buyer/seller activity. Enters when large resting orders absorb aggressive sellers (long) or buyers (short). Targets the next visible level on DOM.
- **Risk Management:** Tight stops (2-4 ticks). High-frequency approach: many small winners, few losers. Daily loss limit.

### 3. Mack (PATs — Price Action Trading System)
- **Market Focus:** ES/NQ futures scalper. Price action with simple support/resistance.
- **Common Patterns:** Support/resistance bounces, failed breakouts (traps), two-bar reversal patterns, VWAP bounces.
- **Timeframe Logic:** 5m primary chart, 15m for levels, 1h for bias. Simple and clean.
- **Entry/Exit Logic:** Identify key levels on 15m/1h. Wait for 5m price action at those levels (pin bars, engulfing). Enter with limit order at level. Target 2-4 points on NQ.
- **Risk Management:** 2-3 point stop on NQ. Max 3 trades per session. No adding to losers. Daily stop-loss.

### 4. Jigsaw Trading (Peter Davies)
- **Market Focus:** Futures across ES, NQ, CL. Order flow specialist using DOM and footprint analysis.
- **Common Patterns:** Absorption at key levels (large resting orders absorbing market orders), spoofing detection, aggressive vs passive flow analysis, delta divergence.
- **Timeframe Logic:** Tick charts and 1m for execution. 5m-15m for structural context. Rarely looks above 1h.
- **Entry/Exit Logic:** Reads the DOM for large resting bids/offers. Enters when aggressive flow shifts direction at key levels. Uses market orders for speed.
- **Risk Management:** Very tight stops (1-2 ticks beyond structure). Fast cut if thesis doesn't play out within 30 seconds. Scale: high frequency, small size.

### 5. Trader Dale
- **Market Focus:** ES, NQ futures. Volume Profile-based scalping and day trading.
- **Common Patterns:** Trading off Volume Profile levels — POC (Point of Control), Value Area High/Low, naked POCs from prior sessions. VWAP as dynamic support/resistance.
- **Timeframe Logic:** 5m-15m for execution. Daily/session Volume Profile for levels. VWAP for intraday anchor.
- **Entry/Exit Logic:** Enter at prior day POC or VA boundary when price reacts (reversal candle at the level). Target: next Volume Profile level. Uses VWAP as a mid-target.
- **Risk Management:** Stop beyond the Volume Profile level by 1 ATR(5m). Typically 1-2R targets. Max 4 trades per session.

---

## Part B: Strategy DNAs

### SCP-001: Level-to-Level Price Action Scalp

```json
{
  "strategy_code": "SCP-001",
  "style": "scalping",
  "template": "Scalp_Template",
  "timeframe_logic": {
    "1h": "Identify key support/resistance levels, VWAP, and prior session high/low",
    "5m": "Execute trades at key levels using price action reversal patterns (pin bars, engulfing candles, failed breakouts)"
  },
  "hypothesis": "Price reacts at key structural levels (prior day high/low, VWAP, round numbers) with high probability. Scalping these reactions with tight stops and 1-2R targets produces consistent edge when combined with reading price action quality at the level",
  "entry_rules": "Price reaches key 1h level (prior session high/low, VWAP, or round number). 5m shows reversal candle pattern at level (pin bar, engulfing, doji). Volume on reversal bar > 1.2x average. Enter on close of reversal bar or on retest of level",
  "exit_rules": "Target 1: next key level (1-2R). Target 2: VWAP if trading away from it, or next structural level. Time-based exit: 15 bars on 5m if target not hit",
  "stop_loss": "Beyond the key level by 0.5 ATR(5m). If level breaks by more than 1 ATR, immediately exit",
  "filters": [
    "Only trade at pre-identified key levels (not random support/resistance)",
    "Reversal candle must show clear rejection (long wick or engulfing body)",
    "Volume must confirm (not declining/thin market)",
    "Max 4 scalp trades per session"
  ],
  "parameter_ranges": {
    "atr_stop_buffer": [0.3, 0.8],
    "min_reversal_wick_ratio": [1.5, 3.0],
    "volume_multiplier": [1.0, 1.5],
    "max_hold_bars_5m": [10, 20],
    "target_R": [1.0, 2.0]
  },
  "expected_behavior": {
    "win_rate": "55-65%",
    "avg_RR": "1.0-1.5R",
    "best_regime": "range-bound days with clear levels",
    "worst_regime": "strong trend days where levels break without reaction"
  },
  "invalidation": "If win rate < 45% over 150 trades or if average loss exceeds average win, strategy is invalid"
}
```

### SCP-002: VWAP Bounce Scalp

```json
{
  "strategy_code": "SCP-002",
  "style": "scalping",
  "template": "Scalp_Template",
  "timeframe_logic": {
    "1h": "Determine if market is trending or ranging relative to VWAP. Note VWAP slope direction",
    "5m": "Enter on 5m price action at VWAP touch with trend confirmation and volume support"
  },
  "hypothesis": "VWAP acts as a magnet and support/resistance level for institutional order flow. When price pulls back to VWAP in a trending session, it bounces with high probability because institutions use VWAP as execution benchmark",
  "entry_rules": "1h trend established (price consistently above/below VWAP). Price pulls back to touch VWAP on 5m. 5m candle shows bounce (close back in direction of trend). Volume on bounce bar > average",
  "exit_rules": "Target: 1st standard deviation VWAP band in trend direction. Trail with 5m 8 EMA after 0.5R. Exit if price closes on wrong side of VWAP for 2 consecutive 5m bars",
  "stop_loss": "Beyond VWAP by 0.5 ATR(5m) on wrong side. Max 1 ATR from VWAP",
  "filters": [
    "VWAP slope must be in trend direction",
    "At least 1 hour of RTH data to establish VWAP",
    "Only trade first 3 VWAP touches per session (diminishing returns after that)",
    "Not within 15 minutes of major news event"
  ],
  "parameter_ranges": {
    "atr_stop_distance": [0.3, 0.8],
    "ema_trail_period": [5, 10],
    "max_vwap_touches": [2, 4],
    "target_sd_band": [1, 2],
    "min_session_minutes": [45, 90]
  },
  "expected_behavior": {
    "win_rate": "58-68%",
    "avg_RR": "1.0-1.5R",
    "best_regime": "trending days with periodic VWAP retests",
    "worst_regime": "choppy days where price oscillates around VWAP"
  },
  "invalidation": "If win rate < 48% over 120 trades or if VWAP bounces fail > 50% of the time, strategy is invalid"
}
```

### SCP-003: Failed Breakout Fade (Trap Scalp)

```json
{
  "strategy_code": "SCP-003",
  "style": "scalping",
  "template": "Scalp_Template",
  "timeframe_logic": {
    "1h": "Identify range boundaries (session high/low, prior day high/low, consolidation boundaries)",
    "5m": "Watch for breakout attempts that fail — price breaks level then quickly reverses back inside range"
  },
  "hypothesis": "Failed breakouts (traps) are among the most reliable scalping setups because they trap breakout traders on the wrong side. The subsequent reversal is fueled by their stop-outs plus new counter-trend entries, creating a momentum burst back into the range",
  "entry_rules": "1h identifies clear range boundary. Price breaks beyond boundary by 1-3 ticks on 5m. Next 5m bar(s) fail to follow through and close back inside range. Enter on close back inside range (fading the failed breakout). Volume spike on the breakout attempt confirms trapped traders",
  "exit_rules": "Target: opposite side of range or VWAP (whichever is closer). Minimum 1.5R. Time exit: 10 bars on 5m",
  "stop_loss": "Beyond the breakout extreme (the wick/high of the failed breakout) plus 0.3 ATR(5m)",
  "filters": [
    "Must be a clear, established range (minimum 1 hour of consolidation on 1h)",
    "Breakout must be a genuine attempt (not just a wick, must show momentum)",
    "Failure must be swift (within 2-3 bars of 5m)",
    "Volume on breakout attempt must be > 1.5x average (trapped liquidity)"
  ],
  "parameter_ranges": {
    "min_range_duration_1h": [3, 8],
    "breakout_overshoot_ticks": [1, 5],
    "failure_max_bars": [1, 4],
    "volume_multiplier": [1.3, 2.5],
    "target_R": [1.5, 2.5]
  },
  "expected_behavior": {
    "win_rate": "55-65%",
    "avg_RR": "1.5-2.0R",
    "best_regime": "range-bound, choppy days with clear boundaries",
    "worst_regime": "strong trend days where breakouts are real"
  },
  "invalidation": "If win rate < 42% over 100 trades or if > 50% of identified 'traps' become real breakouts, strategy is invalid"
}
```

### SCP-004: Momentum Ignition Scalp

```json
{
  "strategy_code": "SCP-004",
  "style": "scalping",
  "template": "Scalp_Template",
  "timeframe_logic": {
    "1h": "Bias direction from trend. Identify quiet consolidation zones where momentum ignition is likely",
    "5m": "Enter on sudden volume spike + price acceleration from quiet zone, riding the ignition move"
  },
  "hypothesis": "After periods of low volatility compression on the 5m chart, sudden large volume bars (3x+ average) signal institutional order flow entering the market. These ignition moves run for 3-8 bars before exhaustion, offering scalable profit if entered early",
  "entry_rules": "5m shows 5+ bars of ATR contraction (low volatility). Sudden volume bar > 3x 20-period average with directional close. 1h bias confirms direction. Enter on close of ignition bar or first pullback (within 1 bar)",
  "exit_rules": "Target: 1.5-2R or prior swing high/low on 5m. Trail with 5m 5 EMA. Exit if momentum stalls (2 consecutive doji bars)",
  "stop_loss": "Below ignition bar low (long) or above high (short). Max 1 ATR(5m)",
  "filters": [
    "Pre-ignition must show genuine compression (5+ bars below average ATR)",
    "Volume must be > 3x average — genuine institutional flow, not noise",
    "1h bias must align with ignition direction",
    "Not within 5 minutes of a known news event (distinguishes from news reaction)"
  ],
  "parameter_ranges": {
    "compression_min_bars": [4, 8],
    "volume_ignition_multiplier": [2.5, 5.0],
    "atr_compression_ratio": [0.3, 0.6],
    "ema_trail_period": [3, 8],
    "target_R": [1.5, 2.5]
  },
  "expected_behavior": {
    "win_rate": "48-58%",
    "avg_RR": "1.5-2.0R",
    "best_regime": "days with alternating compression and expansion",
    "worst_regime": "low volume days where ignition signals are noise"
  },
  "invalidation": "If win rate < 38% over 100 trades or if > 40% of ignition moves reverse within 2 bars, strategy is invalid"
}
```

### SCP-005: Volume Profile POC Rejection Scalp

```json
{
  "strategy_code": "SCP-005",
  "style": "scalping",
  "template": "Scalp_Template",
  "timeframe_logic": {
    "1h": "Map prior session POC (Point of Control), Value Area High (VAH), and Value Area Low (VAL)",
    "5m": "Enter on price reaction (rejection) at naked POC from prior sessions or at current session VAH/VAL"
  },
  "hypothesis": "Volume Profile levels (especially naked/untested POCs from prior sessions) act as magnets and reaction points. Price tends to react at these levels because they represent fair value zones where significant volume was previously transacted. Institutional algorithms target these levels",
  "entry_rules": "Price approaches prior session POC (untested) or current VAH/VAL on 5m. 5m shows rejection candle at the level (long wick, reversal pattern). Volume confirms reaction. Enter on rejection candle close",
  "exit_rules": "Target: next Volume Profile level (VAH to POC, or POC to VAL). Minimum 1R. If momentum strong, hold for 2nd level. Trail with 5m 8 EMA",
  "stop_loss": "Beyond the Volume Profile level by 0.5 ATR(5m). If price accepts (closes 2 bars beyond level), exit immediately",
  "filters": [
    "POC must be 'naked' (untested from prior session)",
    "Current session must have developed enough to have clear VA",
    "Volume must show reaction at the level (not just price touch)",
    "Max 3 VP-based scalps per session"
  ],
  "parameter_ranges": {
    "atr_stop_buffer": [0.3, 0.8],
    "ema_trail_period": [5, 10],
    "max_naked_poc_age_sessions": [1, 5],
    "acceptance_bars": [2, 3],
    "target_R": [1.0, 2.0]
  },
  "expected_behavior": {
    "win_rate": "55-65%",
    "avg_RR": "1.0-1.5R",
    "best_regime": "balanced/two-sided market days",
    "worst_regime": "strong one-directional trend days where VP levels are bulldozed"
  },
  "invalidation": "If win rate < 45% over 100 trades or if POC rejections fail > 50% of the time, strategy is invalid"
}
```
