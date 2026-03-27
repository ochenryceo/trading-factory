# Foxtrot — Volume/Order Flow Research & Strategy DNAs

_Track C Research | 2026-03-22_

---

## Part A: Trader Research

### 1. J. Peter Steidlmayer
- **Market Focus:** CBOT pit trader who invented Market Profile. Applied to all futures markets.
- **Common Patterns:** Market Profile / TPO (Time Price Opportunity) analysis. Identified "normal" distribution days (range-bound) vs "trend" days. Used Point of Control (POC), Value Area (VA), and Initial Balance to read market structure.
- **Timeframe Logic:** Session-based profiles. Uses initial balance (first hour) as the setup, then trades based on acceptance/rejection of value area throughout the session. Multi-day composite profiles for context.
- **Entry/Exit Logic:** Buy at Value Area Low (VAL) when price is accepted. Sell at Value Area High (VAH) when rejected. Trade breakouts from initial balance in direction of trend. POC acts as fair value magnet.
- **Risk Management:** Stops beyond value area boundaries. Small position at edge of value, add when accepted. Exit immediately if value area shifts against you.

### 2. Jim Dalton
- **Market Focus:** Market Profile practitioner across futures. Author of "Mind Over Markets" and "Markets in Profile."
- **Common Patterns:** Day type classification (normal, trend, double distribution, neutral). Value Area migration tracking. Composite profile for multi-day context. Initial balance extension as trend indicator.
- **Timeframe Logic:** Session profile for daily trading. Multi-day composite (5-20 days) for structural context. Opening type (drive, test drive, rejection, acceptance) in first 30 min sets session character.
- **Entry/Exit Logic:** Open drive = enter in drive direction immediately. Test rejection = fade the test. If price is above yesterday's value and accepted, buy. If below and accepted, sell. Target: migration to new value area.
- **Risk Management:** Stops at value area boundaries. Uses volume-at-price to determine conviction. Light at edge of value, add only when market confirms direction.

### 3. FuturesTrader71 (Convergent Trading)
- **Market Focus:** ES, NQ futures. Pioneer of Volume Profile (not just Market Profile) in retail trading.
- **Common Patterns:** Volume Profile POC as fair value. Naked (untested) POCs from prior sessions as price magnets. VPOC migration for trend confirmation. Volume nodes (high volume = support/resistance, low volume = rapid price movement).
- **Timeframe Logic:** Composite Volume Profile for 5-20 session context. Session profile for intraday. 5m-15m for execution timing.
- **Entry/Exit Logic:** Long at High Volume Nodes (HVN) that act as support. Short at HVN acting as resistance. Trade through Low Volume Nodes (LVN) expecting rapid price movement. Target: next HVN.
- **Risk Management:** Stop beyond the opposite edge of the HVN. Position size based on profile width (wider profile = wider stop = smaller position).

### 4. Bookmap/ATAS Order Flow Community
- **Market Focus:** NQ, ES, CL, GC futures using DOM heatmap and footprint charts.
- **Common Patterns:** Cumulative Volume Delta (CVD) divergence — price making highs but delta declining. Absorption patterns (large resting orders eating aggressive flow without price moving). Iceberg orders detection. Aggressive vs passive flow analysis.
- **Timeframe Logic:** Tick-by-tick for DOM/heatmap. 1m-5m for footprint analysis. 15m for structural context.
- **Entry/Exit Logic:** CVD divergence at key levels signals exhaustion → fade. Absorption at level confirms support/resistance → enter on rejection. Delta shift (aggressive flow changing direction) confirms entry. Footprint imbalance > 300% signals institutional activity.
- **Risk Management:** Very tight stops (2-4 ticks beyond absorption zone). Quick exits if delta doesn't confirm. Small size, high frequency.

### 5. Trader Dale
- **Market Focus:** ES, NQ futures. Volume Profile-based trading system accessible to retail.
- **Common Patterns:** Prior session POC rejections. Volume cluster analysis. VWAP with deviation bands. Combining Volume Profile levels with order flow delta for confirmation.
- **Timeframe Logic:** Daily/session Volume Profile for levels. VWAP for intraday anchor. 5m for execution.
- **Entry/Exit Logic:** Enter at prior session POC or VA boundary. Confirm with 5m price action and delta direction. Target: next VP level or VWAP. VWAP + Volume Profile confluence = highest probability trades.
- **Risk Management:** Stop beyond VP level by fixed ATR amount. 1-2R targets. Max trades per session.

---

## Part B: Strategy DNAs

### VOF-001: Volume Profile Value Area Rejection

```json
{
  "strategy_code": "VOF-001",
  "style": "volume_orderflow",
  "template": "Scalp_Template",
  "timeframe_logic": {
    "1h": "Map prior session's Volume Profile: POC, VAH, VAL. Note naked (untested) POCs from prior sessions. Calculate multi-day composite POC for broader context",
    "5m": "Enter on rejection at VA boundary (VAH for shorts, VAL for longs) with delta confirmation and price action reversal"
  },
  "hypothesis": "Value Area boundaries represent zones where 70% of prior session volume occurred. Price tends to be rejected at these boundaries and revert toward POC, especially when delta (aggressive buying vs selling) confirms the rejection. These levels are algorithmically targeted by institutional execution",
  "entry_rules": "Price reaches prior session VAH or VAL on 5m. 5m shows rejection candle (long wick, reversal pattern) at VA boundary. Delta on rejection bar is negative (at VAH, short) or positive (at VAL, long). Volume > 1.5x average on rejection bar",
  "exit_rules": "Target 1: prior session POC (middle of value area). Target 2: opposite VA boundary. Trail with 5m 8 EMA after reaching POC. Time exit: 2 hours if neither target hit",
  "stop_loss": "Beyond VA boundary by 0.5 ATR(5m). If price 'accepts' beyond VA (2+ closes beyond), exit immediately",
  "filters": [
    "Prior session must have a normal distribution profile (not a trend day profile)",
    "VA boundaries must be clearly defined (not fuzzy wide zones)",
    "Delta must confirm rejection direction — no entry without delta alignment",
    "Not within 15 minutes of major news event"
  ],
  "parameter_ranges": {
    "atr_stop_buffer": [0.3, 0.8],
    "acceptance_bars": [2, 3],
    "ema_trail_period": [5, 10],
    "volume_multiplier": [1.2, 2.0],
    "max_hold_hours": [1.0, 3.0]
  },
  "expected_behavior": {
    "win_rate": "55-65%",
    "avg_RR": "1.2-2.0R",
    "best_regime": "range-bound sessions where prior session value area is tested",
    "worst_regime": "strong trend days that blow through VA levels"
  },
  "invalidation": "If win rate < 42% over 100 trades or if VA rejections fail > 50% of the time, strategy is invalid"
}
```

### VOF-002: CVD Divergence at Structure

```json
{
  "strategy_code": "VOF-002",
  "style": "volume_orderflow",
  "template": "Scalp_Template",
  "timeframe_logic": {
    "1h": "Identify key structural levels (prior highs/lows, VP POCs, VWAP bands). Note CVD trend direction",
    "5m": "Enter when price makes new high/low at structure BUT CVD diverges (fails to confirm). Fade the move"
  },
  "hypothesis": "When price makes a new extreme at a structural level but Cumulative Volume Delta diverges (price up, delta down = bearish divergence), it signals that aggressive buying is exhausted. The move is running on fumes and likely to reverse. This is an early warning that institutional flow has shifted",
  "entry_rules": "Price reaches key 1h structural level. Price makes new 5m high (at resistance) or low (at support). CVD diverges: new price high but CVD lower than prior price high's CVD (bearish divergence) or vice versa. 5m shows stalling/reversal candle. Enter fade direction",
  "exit_rules": "Target: VWAP or prior swing point in reversion direction. Trail with 5m 8 EMA. Time exit: 1 hour if target not reached. Exit if price makes new extreme WITH CVD confirmation (divergence resolved)",
  "stop_loss": "Beyond the new extreme (the divergent high/low) plus 0.3 ATR(5m)",
  "filters": [
    "Divergence must be clear — at least 2 CVD readings showing divergence",
    "Must be at a recognizable structural level (not random price points)",
    "Volume must not be declining to nothing (needs participation to trade)",
    "Not during the first or last 15 minutes of RTH session"
  ],
  "parameter_ranges": {
    "min_divergence_readings": [2, 4],
    "atr_stop_buffer": [0.2, 0.5],
    "ema_trail_period": [5, 10],
    "max_hold_minutes": [30, 90],
    "target_R": [1.5, 2.5]
  },
  "expected_behavior": {
    "win_rate": "50-60%",
    "avg_RR": "1.5-2.0R",
    "best_regime": "two-sided markets at key inflection points",
    "worst_regime": "strong trend days where divergence is persistent before final resolution"
  },
  "invalidation": "If win rate < 40% over 80 trades or if CVD divergences resolve in trend direction > 50% of the time, strategy is invalid"
}
```

### VOF-003: Delta Absorption Confirmation

```json
{
  "strategy_code": "VOF-003",
  "style": "volume_orderflow",
  "template": "Scalp_Template",
  "timeframe_logic": {
    "1h": "Identify key support/resistance levels using Volume Profile HVN/LVN and prior session levels",
    "5m": "Enter when absorption is detected at key level: large resting orders absorb aggressive sellers/buyers without price moving"
  },
  "hypothesis": "Absorption occurs when large passive orders (limit orders) absorb aggressive market orders without allowing price to move. This indicates institutional commitment to a level and high probability of a reaction (bounce or reversal) from that level",
  "entry_rules": "Price at key 1h level (VP HVN, prior POC, session VA boundary). 5m shows absorption: high volume traded at level but price doesn't move through (delta on bar is disproportionate to price movement). Footprint imbalance > 200% at level. Enter in direction of expected reaction after absorption confirmed",
  "exit_rules": "Target: next VP level (HVN or POC). Trail with 5m 5 EMA. Exit if level breaks despite absorption (institutional order exhausted). Minimum 1R target",
  "stop_loss": "Beyond the absorption zone by 0.3 ATR(5m). Very tight stops — if absorption fails, thesis is wrong",
  "filters": [
    "Absorption must be genuine: volume at level > 2x average but price range compressed",
    "Must be at a pre-identified structural level (not random)",
    "Footprint imbalance must confirm (bid/ask volume heavily one-sided at level)",
    "Max 3 absorption trades per session"
  ],
  "parameter_ranges": {
    "min_absorption_volume_ratio": [1.5, 3.0],
    "footprint_imbalance_pct": [150, 400],
    "atr_stop_buffer": [0.2, 0.5],
    "ema_trail_period": [3, 8],
    "target_R": [1.0, 2.0]
  },
  "expected_behavior": {
    "win_rate": "58-68%",
    "avg_RR": "1.0-1.5R",
    "best_regime": "two-sided markets with institutional level defense",
    "worst_regime": "trend days where institutional orders get overwhelmed"
  },
  "invalidation": "If win rate < 45% over 100 trades or if absorption zones fail > 40% of the time, strategy is invalid"
}
```

### VOF-004: VWAP Standard Deviation Band Trade

```json
{
  "strategy_code": "VOF-004",
  "style": "volume_orderflow",
  "template": "Scalp_Template",
  "timeframe_logic": {
    "1h": "Calculate session VWAP and 1 SD, 2 SD, 3 SD bands. Determine day type (trend/range) from profile development",
    "5m": "Enter on reaction at VWAP SD bands with order flow confirmation (delta shift or absorption)"
  },
  "hypothesis": "VWAP standard deviation bands represent statistical boundaries where institutional algorithms execute. The 1 SD band captures ~68% of volume, 2 SD ~95%. Price reactions at these bands, confirmed by order flow shifts, offer high-probability scalp entries because algos cluster execution around VWAP",
  "entry_rules": "Price reaches VWAP 2 SD band on 5m. Order flow shows reaction: delta shifts direction OR absorption detected at band. 5m reversal candle at band level. Enter in mean-reversion direction (toward VWAP) from 2 SD band",
  "exit_rules": "Target 1: VWAP 1 SD band. Target 2: VWAP (full reversion). Trail with 5m 8 EMA. Time exit: 1.5 hours if target not reached",
  "stop_loss": "Beyond VWAP 2.5 SD band. If price reaches 3 SD, exit immediately",
  "filters": [
    "Session VWAP must have > 1 hour of data to be meaningful",
    "Only trade 2 SD bands (1 SD too common, 3 SD too rare)",
    "Delta must show reaction at the band (not just price touch)",
    "Range day profile preferred (trend days continuously press through bands)"
  ],
  "parameter_ranges": {
    "sd_entry_band": [1.8, 2.2],
    "sd_stop_band": [2.3, 3.0],
    "ema_trail_period": [5, 10],
    "max_hold_minutes": [30, 120],
    "target_levels": ["1sd", "vwap"]
  },
  "expected_behavior": {
    "win_rate": "55-65%",
    "avg_RR": "1.2-2.0R",
    "best_regime": "normal distribution days with VWAP as fair value",
    "worst_regime": "trend days where price establishes new value away from VWAP"
  },
  "invalidation": "If win rate < 42% over 100 trades or if 2 SD bands fail to produce reaction > 50% of the time, strategy is invalid"
}
```

### VOF-005: Naked POC Magnet Trade

```json
{
  "strategy_code": "VOF-005",
  "style": "volume_orderflow",
  "template": "Momentum_Template",
  "timeframe_logic": {
    "4h": "Identify naked (untested) POCs from prior sessions — these act as price magnets",
    "1h": "Price trending toward a naked POC. Confirm momentum direction and volume increasing",
    "15m": "Setup: price within 1 ATR of naked POC with momentum aligned. No contrary structure between price and target",
    "5m": "Enter on 5m continuation bar in direction of naked POC with volume confirmation"
  },
  "hypothesis": "Naked POCs (untested Point of Control levels from prior sessions) act as price magnets because they represent unfilled institutional orders and fair value zones that the market hasn't accepted. Price is drawn to these levels to test and fill the orders, creating a directional trade toward the POC",
  "entry_rules": "Naked POC identified from prior session (not yet tested by current session). Price trending toward POC on 1h. No major structural obstacle between current price and POC. 5m shows momentum bar toward POC with volume. Enter in direction of POC",
  "exit_rules": "Primary target: naked POC level (touch/fill). Secondary: through POC to next VP level if momentum persists. Trail with 5m 10 EMA. Exit if momentum stalls (3 consecutive doji bars)",
  "stop_loss": "Below most recent 5m swing (against direction of POC). Max 1 ATR(15m)",
  "filters": [
    "POC must be genuinely naked — untested in the current or intervening sessions",
    "Path to POC must be relatively clear (no massive HVN blocking the way)",
    "Price must be trending toward POC (not ranging or moving away)",
    "POC should be within reasonable distance (< 3 ATR on 1h)"
  ],
  "parameter_ranges": {
    "max_poc_distance_atr": [1.0, 3.0],
    "max_poc_age_sessions": [1, 10],
    "ema_trail_period": [8, 15],
    "volume_confirmation": [1.0, 1.5],
    "atr_stop_multiplier": [0.5, 1.5]
  },
  "expected_behavior": {
    "win_rate": "55-65%",
    "avg_RR": "1.0-2.0R",
    "best_regime": "sessions where prior value areas are being revisited",
    "worst_regime": "strong trending days that ignore prior value entirely"
  },
  "invalidation": "If win rate < 42% over 80 trades or if naked POCs are not tested within 5 sessions > 50% of the time, strategy is invalid"
}
```
