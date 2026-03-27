# Alpha — Momentum Breakout Research & Strategy DNAs

_Track C Research | 2026-03-22_

---

## Part A: Trader Research

### 1. Mark Minervini
- **Market Focus:** US equities, adapted principles apply to NQ futures
- **Common Patterns:** SEPA® methodology — Specific Entry Point Analysis. Buys stocks (and by extension, instruments) emerging from proper bases with volume confirmation. Looks for "volatility contraction patterns" (VCPs) before breakouts.
- **Timeframe Logic:** Daily/weekly for trend identification, intraday for entries. Translated to futures: 4h for bias, 1h for trend confirmation, 15m for setup (VCP formation), 5m for breakout entry.
- **Entry/Exit Logic:** Enter on breakout above pivot with volume surge ≥ 150% of average. Exit at trailing stop or when price closes below 10-period moving average on setup timeframe.
- **Risk Management:** Max 1-2% risk per trade. Cuts losses quickly at 7-8% from entry. Position sizing based on stop distance.

### 2. Dan Zanger
- **Market Focus:** Growth stocks, NQ-correlated instruments. Known for chart pattern breakouts.
- **Common Patterns:** Bull flags, cup-and-handle, ascending triangles. Requires volume confirmation on breakout day. Price must be above key moving averages (20, 50 EMA).
- **Timeframe Logic:** Daily for pattern formation, 15m for entry timing. For futures: 4h establishes trend, 1h shows pattern formation, 15m for setup recognition, 5m for trigger.
- **Entry/Exit Logic:** Buy the breakout of the pattern boundary with volume > 2x average. Exit on failed retest or when pattern target is met.
- **Risk Management:** Tight stops just below breakout level. Scales out at 1R, 2R, 3R targets.

### 3. Kristjan Kullamägi (Qullamaggie)
- **Market Focus:** US equities momentum, directly applicable to NQ futures momentum.
- **Common Patterns:** Breakout of multi-day range with volume expansion. "Episodic pivots" — gap-ups on catalysts. First pullback after strong initial breakout.
- **Timeframe Logic:** Daily for identifying range, 5m for entry execution. Futures translation: 4h for macro trend, 1h for range identification, 15m for setup, 5m for trigger.
- **Entry/Exit Logic:** Enter as price clears range high with volume. Uses time-based stops (if trade doesn't work within 2-3 bars, cut it). Holds winners for multiple R.
- **Risk Management:** Risk 0.5-1% per trade. Very quick to cut losers. Lets winners run with trailing stops.

### 4. Linda Bradford Raschke
- **Market Focus:** S&P/NQ futures, commodities. Active futures trader for 30+ years.
- **Common Patterns:** "Holy Grail" setup (pullback to 20 EMA in trending market then breakout), opening range breakouts, momentum thrust patterns.
- **Timeframe Logic:** Uses 15m-60m charts for setup identification, 5m for entries. Aligns with higher timeframe ADX for trend strength.
- **Entry/Exit Logic:** ADX > 30 confirms trend. Wait for pullback to 20 EMA on 15m. Enter on breakout above pullback high. Exit at prior swing high or 2R target.
- **Risk Management:** Fixed R risk model. Stop below pullback low. 1-2R targets. Max daily loss limit.

### 5. Oliver Kell
- **Market Focus:** US Champion Trader 2020. Growth momentum, applicable to NQ.
- **Common Patterns:** Power plays — stocks/instruments making new highs with accelerating volume. Buys continuation after initial breakout confirmation.
- **Timeframe Logic:** Weekly/daily for trend, intraday for execution. Futures: 4h for macro, 1h confirmation, 15m setup, 5m execution.
- **Entry/Exit Logic:** Enter on first constructive pullback after breakout. Volume should confirm. Adds to winners on subsequent breakouts.
- **Risk Management:** Initial risk 5-7% from entry. Scales in. Trailing stop on 10 EMA or 21 EMA.

---

## Part B: Strategy DNAs

### MOM-001: Opening Range Breakout with Trend Alignment

```json
{
  "strategy_code": "MOM-001",
  "style": "momentum_breakout",
  "template": "Momentum_Template",
  "timeframe_logic": {
    "4h": "Determine macro trend direction using 20/50 EMA alignment and ADX > 25",
    "1h": "Confirm intraday trend matches 4h bias. Identify key support/resistance levels",
    "15m": "Identify opening range (first 30-45 min). Mark high/low boundaries",
    "5m": "Execute breakout entry when price clears opening range with volume > 150% average"
  },
  "hypothesis": "When macro trend (4h) is aligned with intraday trend (1h), and price breaks the opening range on the 15m with volume confirmation on 5m, a momentum continuation move follows 55-65% of the time",
  "entry_rules": "4h EMA20 > EMA50 (long bias) or EMA20 < EMA50 (short bias). 1h trend confirms same direction. Price breaks 15m opening range high (long) or low (short). 5m candle closes beyond range with volume > 1.5x 20-period average volume",
  "exit_rules": "Take profit at 2R target or prior 1h swing level. Trail stop to breakeven after 1R. Exit if price reverses back inside opening range on 5m close",
  "stop_loss": "Below opening range low (long) or above opening range high (short), minus 0.5 ATR(15m) buffer",
  "filters": [
    "ADX(4h) > 25 — must be trending, not ranging",
    "Volume on breakout bar > 1.5x 20-period average",
    "No major news event within 30 minutes",
    "Time filter: first 3 hours of RTH session only"
  ],
  "parameter_ranges": {
    "opening_range_minutes": [30, 60],
    "volume_multiplier": [1.3, 2.0],
    "adx_threshold": [20, 30],
    "atr_buffer": [0.3, 0.8],
    "target_R": [1.5, 3.0]
  },
  "expected_behavior": {
    "win_rate": "50-60%",
    "avg_RR": "1.5-2.5R",
    "best_regime": "trending days with clear directional bias",
    "worst_regime": "choppy/ranging days, FOMC days"
  },
  "invalidation": "If win rate < 40% over 100 trades or average R:R drops below 1.2, strategy is invalid"
}
```

### MOM-002: Volatility Contraction Pattern (VCP) Breakout

```json
{
  "strategy_code": "MOM-002",
  "style": "momentum_breakout",
  "template": "Momentum_Template",
  "timeframe_logic": {
    "4h": "Confirm instrument is in uptrend — price above 50 EMA, higher highs/higher lows",
    "1h": "Identify consolidation zone with contracting range (each swing smaller than last)",
    "15m": "Measure volatility contraction — Bollinger Band width decreasing for 8+ bars",
    "5m": "Enter on breakout above contraction range with volume spike"
  },
  "hypothesis": "When price consolidates in a tightening range (VCP) within a 4h uptrend, the breakout from the final contraction produces a momentum thrust as trapped sellers and new buyers create directional pressure",
  "entry_rules": "4h trend up (price > 50 EMA). 1h shows 2-4 contractions (each range smaller). 15m Bollinger Band width at 20-period low. 5m candle closes above contraction high with volume > 2x average",
  "exit_rules": "Target 1: 1.5R (scale out 50%). Target 2: measured move (contraction range projected from breakout). Trail remaining with 15m 10 EMA",
  "stop_loss": "Below the final contraction low, minus 0.5 ATR(15m)",
  "filters": [
    "Minimum 3 contractions visible on 1h chart",
    "Bollinger Band width at or near 20-bar low on 15m",
    "Volume declining during contraction, expanding on breakout",
    "4h RSI between 40-70 (not overbought)"
  ],
  "parameter_ranges": {
    "min_contractions": [2, 4],
    "bb_period": [15, 25],
    "volume_breakout_multiplier": [1.5, 3.0],
    "ema_trail_period": [8, 15],
    "rsi_max": [65, 75]
  },
  "expected_behavior": {
    "win_rate": "45-55%",
    "avg_RR": "2.0-3.5R",
    "best_regime": "trending markets with periodic consolidations",
    "worst_regime": "extended ranging markets with false breakouts"
  },
  "invalidation": "If win rate < 35% over 100 trades or max drawdown exceeds 8%, strategy is invalid"
}
```

### MOM-003: Flag/Pennant Continuation Breakout

```json
{
  "strategy_code": "MOM-003",
  "style": "momentum_breakout",
  "template": "Momentum_Template",
  "timeframe_logic": {
    "4h": "Identify strong impulsive move (flagpole) — ATR expansion, directional momentum",
    "1h": "Observe consolidation after impulse forming bull/bear flag or pennant pattern",
    "15m": "Pattern boundaries clearly defined. Wait for breakout setup with declining volume",
    "5m": "Enter on breakout of flag boundary with volume confirmation"
  },
  "hypothesis": "After a strong impulsive move, a flag/pennant consolidation represents a pause, not a reversal. Breakout in the direction of the original impulse continues the trend with a measured move target equal to the flagpole height",
  "entry_rules": "4h shows impulse move > 2 ATR. 1h flag/pennant forms with 3-8 bars. Volume declines during flag. 5m breakout above flag high (long) with volume > 1.5x average. RSI(15m) > 50 for longs",
  "exit_rules": "Target 1: 1.5R. Target 2: flagpole height projected from breakout point. Trail with 15m 8 EMA after 1R",
  "stop_loss": "Below flag low (long) or above flag high (short), plus 0.3 ATR(15m) buffer",
  "filters": [
    "Flagpole must be > 2x ATR(4h) — strong impulse required",
    "Flag duration: 3-8 candles on 1h (not too long or pattern loses energy)",
    "Volume must decline during flag formation",
    "Flag retracement < 50% of flagpole (shallow pullback)"
  ],
  "parameter_ranges": {
    "flagpole_atr_multiple": [1.5, 3.0],
    "flag_max_bars": [5, 12],
    "max_retracement_pct": [38.2, 50.0],
    "volume_decline_threshold": [0.5, 0.8],
    "target_R": [1.5, 3.0]
  },
  "expected_behavior": {
    "win_rate": "50-58%",
    "avg_RR": "1.8-2.5R",
    "best_regime": "strong trending days with momentum continuation",
    "worst_regime": "reversal days, end-of-trend exhaustion"
  },
  "invalidation": "If win rate < 38% over 100 trades or if > 60% of flags fail to reach 1R, strategy is invalid"
}
```

### MOM-004: Range Expansion Breakout (Multi-Day)

```json
{
  "strategy_code": "MOM-004",
  "style": "momentum_breakout",
  "template": "Momentum_Template",
  "timeframe_logic": {
    "4h": "Identify multi-day compression — 3+ days of narrowing range (inside bars or NR7)",
    "1h": "Mark the compression range boundaries from the tightest day",
    "15m": "Monitor for range expansion — first candle that exceeds prior day range by > 50%",
    "5m": "Enter on confirmed breakout direction with volume and momentum confirmation"
  },
  "hypothesis": "Multi-day range compression (NR4/NR7 or inside day sequences) precedes directional expansion. The longer the compression, the stronger the eventual breakout move, as orders accumulate above and below the range",
  "entry_rules": "4h shows 3+ consecutive narrowing ranges. 1h marks the breakout level. 15m range bar exceeds prior session range. 5m confirms direction with close beyond level and volume > 2x average",
  "exit_rules": "Target: average true range of the 3 prior full-range days projected from breakout. Trail with 1h 10 EMA. Exit if price returns inside compression range",
  "stop_loss": "Opposite side of compression range, or midpoint of range if range is wide (> 2 ATR)",
  "filters": [
    "Minimum 3 days of narrowing range on 4h chart",
    "Breakout volume > 2x 20-day average volume",
    "4h trend direction matches breakout direction for highest probability",
    "Not within 2 hours of major news event"
  ],
  "parameter_ranges": {
    "min_compression_days": [3, 7],
    "volume_multiplier": [1.5, 3.0],
    "atr_target_days": [3, 5],
    "ema_trail_period": [8, 15],
    "range_return_exit_bars": [2, 5]
  },
  "expected_behavior": {
    "win_rate": "45-55%",
    "avg_RR": "2.0-4.0R",
    "best_regime": "post-compression breakout environments, earnings seasons for NQ",
    "worst_regime": "low volatility grind with no catalyst for expansion"
  },
  "invalidation": "If win rate < 35% over 80 trades or if average holding time exceeds 2 sessions without profit, strategy is invalid"
}
```

### MOM-005: Momentum Thrust with ADX Confirmation (Raschke-Style)

```json
{
  "strategy_code": "MOM-005",
  "style": "momentum_breakout",
  "template": "Momentum_Template",
  "timeframe_logic": {
    "4h": "ADX rising and > 30, confirming strong trend. DI+ > DI- (long) or DI- > DI+ (short)",
    "1h": "Price above 20 EMA. Look for pullback to 20 EMA ('Holy Grail' setup)",
    "15m": "Pullback touches or penetrates 20 EMA on 1h equivalent. RSI dips to 40-50 zone",
    "5m": "Enter on first 5m candle that closes above pullback high with expanding volume"
  },
  "hypothesis": "In a strong trend (ADX > 30), pullbacks to the 20 EMA offer high-probability re-entry points. The ADX filter ensures we only trade in trending environments, filtering out choppy conditions that produce false signals",
  "entry_rules": "4h ADX > 30 with correct DI alignment. 1h shows pullback to 20 EMA after trend move. 15m RSI between 40-55 (not oversold, just pulled back). 5m breakout above pullback high with volume confirmation",
  "exit_rules": "Target 1: prior 1h swing high/low. Target 2: 2.5R. Trail with 5m 20 EMA after 1R achieved",
  "stop_loss": "Below 1h 20 EMA, minus 0.5 ATR(1h)",
  "filters": [
    "ADX(4h) > 30 and rising — strong trend required",
    "Pullback must touch 20 EMA on 1h (not overshoot by > 1 ATR)",
    "RSI(15m) must not go below 30 — that indicates trend damage, not a pullback",
    "No more than 2 pullback entries per trend leg"
  ],
  "parameter_ranges": {
    "adx_threshold": [25, 35],
    "ema_period": [15, 25],
    "rsi_pullback_zone": [35, 55],
    "atr_stop_buffer": [0.3, 0.8],
    "target_R": [1.5, 3.0]
  },
  "expected_behavior": {
    "win_rate": "52-62%",
    "avg_RR": "1.5-2.5R",
    "best_regime": "strong trending markets with periodic pullbacks",
    "worst_regime": "ranging/choppy markets where ADX stays below 25"
  },
  "invalidation": "If win rate < 40% over 100 trades or if ADX filter produces fewer than 3 setups per month, strategy is invalid"
}
```
