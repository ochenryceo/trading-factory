# Delta — Trend Following Research & Strategy DNAs

_Track C Research | 2026-03-22_

---

## Part A: Trader Research

### 1. Richard Dennis / Turtle Traders
- **Market Focus:** Diversified futures (commodities, currencies, bonds). Founded trend following as a teachable system.
- **Common Patterns:** Donchian Channel breakouts (20-day and 55-day). Pyramiding into winning positions. Systematic, rules-based approach.
- **Timeframe Logic:** Daily for signals. Position held for weeks/months. Adapted to intraday: 4h for trend direction, 1h for channel breakouts, 15m/5m for entry timing.
- **Entry/Exit Logic:** Enter on new 20-day high (short-term system) or 55-day high (long-term). Exit on 10-day low (short) or 20-day low (long). Uses ATR for position sizing.
- **Risk Management:** Risk 2% per trade based on ATR. Pyramiding: add positions on each N/2 profit (where N = ATR). Max 4 units per market.

### 2. Bill Dunn (Dunn Capital Management)
- **Market Focus:** Managed futures across 50+ markets. Pure trend follower since 1974.
- **Common Patterns:** Moving average crossover systems. Dual momentum (absolute + relative). Long-term position trades in futures.
- **Timeframe Logic:** Weekly/daily for signals. Holds positions weeks to months. For intraday adaptation: 4h = macro trend (MA crossover), 1h = confirmation, 15m = pullback entry.
- **Entry/Exit Logic:** Enter when faster MA (20) crosses above slower MA (50). Exit on reverse crossover or trailing ATR stop. No discretion — fully systematic.
- **Risk Management:** Volatility-based position sizing (target 1% daily portfolio volatility per position). Hard drawdown limits.

### 3. Ed Seykota
- **Market Focus:** Commodities futures. Pioneer of computerized trading systems.
- **Common Patterns:** Trend identification via exponential moving averages. Breakout from consolidation. Risk management as the primary edge.
- **Timeframe Logic:** Weekly/daily signals with holding periods of weeks. Adapted: 4h for EMA trend, 1h for pullback structure, 15m setup, 5m entry.
- **Entry/Exit Logic:** Enter on pullback to EMA in established trend. Uses multiple EMAs (10, 21, 50) for trend strength assessment. Exit on EMA crossover or trailing stop.
- **Risk Management:** "Risk no more than you can afford to lose, and also risk enough so that a win is meaningful." 1-2% risk per trade. Trailing stops to protect profits.

### 4. Jerry Parker (Chesapeake Capital)
- **Market Focus:** Original Turtle Trader. Managed futures, diversified across 80+ markets.
- **Common Patterns:** Long-term trend following using Donchian breakouts with modifications. Added short-term systems for diversification.
- **Timeframe Logic:** Daily/weekly for core system. Added shorter timeframes over time. 4h for macro, 1h for intermediate, 15m/5m for timing.
- **Entry/Exit Logic:** Donchian breakout with trend filter (only trade breakouts in direction of longer-term trend). Trailing ATR stop for exits.
- **Risk Management:** 0.5-1% risk per trade. Highly diversified across markets. Max correlation limits between positions.

### 5. David Harding (Winton Group)
- **Market Focus:** Systematic CTA, managed futures. Statistical trend following with academic rigor.
- **Common Patterns:** Multi-speed trend models (fast, medium, slow trend signals combined). Statistical momentum measurement. Regime-aware trend following.
- **Timeframe Logic:** Multiple speeds of trend signals combined into a composite. All timeframes contribute to a weighted directional signal.
- **Entry/Exit Logic:** Composite signal from multiple moving average speeds. Position size proportional to signal strength. Continuous in/out rather than binary.
- **Risk Management:** Risk parity across markets. Volatility targeting. Tail risk hedging.

---

## Part B: Strategy DNAs

### TF-001: Dual EMA Crossover with Pullback Entry

```json
{
  "strategy_code": "TF-001",
  "style": "trend_following",
  "template": "Trend_Template",
  "timeframe_logic": {
    "4h": "Primary trend: 20 EMA above 50 EMA = uptrend, below = downtrend. ADX > 20 confirms trend exists",
    "1h": "Confirm trend alignment. Price above both EMAs for longs. Look for pullback structure",
    "15m": "Wait for pullback to 1h 20 EMA zone. RSI(14) between 40-55 (pullback, not reversal)",
    "5m": "Enter on 5m reversal candle showing trend resumption. Volume should confirm"
  },
  "hypothesis": "When the 4h trend is confirmed by EMA crossover and ADX, pullbacks to the 1h 20 EMA offer high-probability trend continuation entries. The multi-timeframe alignment ensures we're trading with the dominant force",
  "entry_rules": "4h 20 EMA > 50 EMA and ADX > 20. 1h price above 20 EMA, pulls back to touch/near 20 EMA. 15m RSI(14) between 40-55. 5m bullish reversal candle with close above prior bar high",
  "exit_rules": "Trail with 1h 20 EMA. Exit on 1h close below 20 EMA. Target: next 4h swing high. Partial exits at 1R, 2R, 3R",
  "stop_loss": "Below 1h 50 EMA or below pullback low, whichever is tighter. Max 1.5 ATR(1h)",
  "filters": [
    "ADX(4h) > 20 and rising — trend must be confirmed",
    "No more than 2 pullback entries per trend leg",
    "1h pullback must not break below 50 EMA (that's trend damage, not a pullback)",
    "Not during first 30 minutes of RTH"
  ],
  "parameter_ranges": {
    "fast_ema": [15, 25],
    "slow_ema": [40, 60],
    "adx_threshold": [18, 25],
    "rsi_pullback_zone": [35, 55],
    "trailing_ema_period": [15, 25]
  },
  "expected_behavior": {
    "win_rate": "48-58%",
    "avg_RR": "2.0-3.5R",
    "best_regime": "sustained trending markets",
    "worst_regime": "choppy/ranging markets where EMAs whipsaw"
  },
  "invalidation": "If win rate < 35% over 100 trades or if trailing stops are hit > 70% of the time before 1R, strategy is invalid"
}
```

### TF-002: Donchian Channel Breakout (Modified Turtle)

```json
{
  "strategy_code": "TF-002",
  "style": "trend_following",
  "template": "Trend_Template",
  "timeframe_logic": {
    "4h": "Calculate 20-period Donchian Channel. Breakout above upper band = long signal, below lower = short",
    "1h": "Confirm breakout direction matches 50 EMA trend. Volume expansion on breakout",
    "15m": "Enter on first pullback after Donchian breakout that holds above the breakout level",
    "5m": "Precise entry on pullback bounce or continuation bar with volume"
  },
  "hypothesis": "New 20-period highs/lows on the 4h chart represent trend continuation points. The Turtle system's core insight: trends persist because markets are driven by human behavioral patterns that repeat. Modified with pullback entry for better risk:reward",
  "entry_rules": "4h closes above 20-period Donchian upper band. 1h 50 EMA aligns with breakout direction. 15m first pullback to breakout level (former resistance becomes support). 5m confirms hold with reversal candle or continuation",
  "exit_rules": "Trail with 10-period Donchian lower band (long) or upper band (short) on 4h. Partial exit at 2R. Full exit on 4h Donchian trail hit",
  "stop_loss": "10-period Donchian lower band on 1h (long) or upper band (short). Approximately 1-2 ATR(4h)",
  "filters": [
    "Previous Donchian signal must have been profitable (avoid breakout after recent failure)",
    "Volume on breakout > 1.5x 20-period average",
    "ADX(4h) > 15 (some directionality required)",
    "Not in last 2 hours of Friday session (weekend risk)"
  ],
  "parameter_ranges": {
    "donchian_entry_period": [15, 30],
    "donchian_exit_period": [8, 15],
    "ema_trend_filter": [40, 60],
    "volume_multiplier": [1.3, 2.0],
    "adx_min": [12, 20]
  },
  "expected_behavior": {
    "win_rate": "38-48%",
    "avg_RR": "2.5-5.0R",
    "best_regime": "strong trending periods with momentum",
    "worst_regime": "choppy markets producing false breakouts"
  },
  "invalidation": "If win rate < 30% over 80 trades or if average loss exceeds 1.5x expected stop size, strategy is invalid"
}
```

### TF-003: Multi-Speed Momentum Composite

```json
{
  "strategy_code": "TF-003",
  "style": "trend_following",
  "template": "Trend_Template",
  "timeframe_logic": {
    "4h": "Slow momentum: 50 EMA direction + MACD(26,52,9) signal. Weight: 40%",
    "1h": "Medium momentum: 20 EMA direction + MACD(12,26,9) signal. Weight: 35%",
    "15m": "Fast momentum: 10 EMA direction + RSI(14) > 50. Weight: 15%",
    "5m": "Entry timing: enter when composite score > 0.7 (strong alignment) on 5m trigger bar"
  },
  "hypothesis": "Combining multiple speeds of trend signals (slow, medium, fast) into a composite score produces more robust trend identification than any single indicator. When all speeds align (score > 0.7), the probability of trend continuation is highest",
  "entry_rules": "Composite momentum score: (4h_signal * 0.40) + (1h_signal * 0.35) + (15m_signal * 0.15) + (5m_signal * 0.10). Each signal = +1 (bullish), 0 (neutral), -1 (bearish). Enter long when score > 0.7, short when < -0.7",
  "exit_rules": "Exit when composite score drops below 0.3 (long) or rises above -0.3 (short). Trail with 1h 20 EMA. Partial exit at each R level",
  "stop_loss": "Below most recent 1h swing low (long) or above swing high (short). Max 2 ATR(1h)",
  "filters": [
    "Composite score must exceed 0.7 — no entry on moderate alignment",
    "4h must be aligned (heaviest weight) — never trade against 4h momentum",
    "Minimum 3 of 4 timeframes must agree in direction",
    "Score must have been < 0.3 within last 20 bars (fresh signal, not stale)"
  ],
  "parameter_ranges": {
    "slow_ema": [40, 60],
    "medium_ema": [15, 25],
    "fast_ema": [8, 15],
    "composite_threshold": [0.6, 0.8],
    "weight_4h": [0.35, 0.45],
    "weight_1h": [0.30, 0.40]
  },
  "expected_behavior": {
    "win_rate": "45-55%",
    "avg_RR": "2.0-3.0R",
    "best_regime": "strong multi-timeframe aligned trends",
    "worst_regime": "mixed-signal markets where timeframes conflict"
  },
  "invalidation": "If win rate < 35% over 100 trades or if composite signals whipsaw > 5 times in 24 hours, strategy is invalid"
}
```

### TF-004: Trend Continuation after Structural Pullback

```json
{
  "strategy_code": "TF-004",
  "style": "trend_following",
  "template": "Trend_Template",
  "timeframe_logic": {
    "4h": "Established trend with higher highs/higher lows (uptrend) or lower highs/lower lows (downtrend)",
    "1h": "Pullback forms — price retraces to 38.2%-61.8% Fibonacci of prior 4h impulse leg",
    "15m": "Structure forms at Fib level (double bottom, ascending triangle, bullish engulfing)",
    "5m": "Enter on breakout of 15m structure with volume confirmation"
  },
  "hypothesis": "In established trends, Fibonacci retracement levels (38.2-61.8%) act as institutional re-entry zones. When price builds structure (consolidation) at a Fib level and breaks out, the trend resumes with force as sidelined participants re-enter",
  "entry_rules": "4h shows clear trend structure. 1h pullback reaches 38.2-61.8% Fib zone of prior impulse. 15m builds consolidation/structure at Fib level (minimum 4 bars). 5m breaks out of structure with volume > 1.5x average",
  "exit_rules": "Target 1: prior 4h swing extreme (100% extension). Target 2: 161.8% Fibonacci extension. Trail with 1h 20 EMA after 1R",
  "stop_loss": "Below 61.8% Fibonacci level (long) or above (short), plus 1 ATR(1h) buffer. If price breaks 78.6% Fib, trend thesis is invalidated",
  "filters": [
    "Must be an established trend — minimum 2 impulse legs visible on 4h",
    "Pullback must reach at least 38.2% — shallow pullbacks don't qualify",
    "Pullback must not exceed 78.6% — that invalidates the trend",
    "15m structure must form (minimum 4 bars consolidation, not V-reversal)"
  ],
  "parameter_ranges": {
    "fib_entry_zone": [0.382, 0.618],
    "fib_invalidation": [0.718, 0.886],
    "structure_min_bars_15m": [3, 8],
    "volume_multiplier": [1.3, 2.0],
    "extension_target": [1.0, 1.618]
  },
  "expected_behavior": {
    "win_rate": "48-58%",
    "avg_RR": "2.0-3.0R",
    "best_regime": "strong trending markets with healthy pullbacks",
    "worst_regime": "V-shaped reversals, markets without clean pullback structure"
  },
  "invalidation": "If win rate < 38% over 80 trades or if Fib levels consistently fail to hold (> 60% break 78.6%), strategy is invalid"
}
```

### TF-005: ATR Trailing Trend Ride

```json
{
  "strategy_code": "TF-005",
  "style": "trend_following",
  "template": "Trend_Template",
  "timeframe_logic": {
    "4h": "Identify trend direction using 50 EMA slope and price position relative to it",
    "1h": "Set ATR trailing stop at 2x ATR below price (long) or above (short). Use Chandelier Exit method",
    "15m": "Monitor trend health — ADX, volume trend, momentum indicators",
    "5m": "Enter on trend resumption signal after ATR trailing stop reset following a pullback"
  },
  "hypothesis": "ATR-based trailing stops adapt to current market volatility, allowing wide stops in volatile markets and tight stops in calm markets. This volatility-adaptive approach captures more trend profit than fixed stops while managing risk dynamically",
  "entry_rules": "4h EMA(50) sloping in trend direction. 1h price above EMA(50). Enter on 5m when price moves above prior 1h swing high (long) with ATR trailing stop set at 2x ATR(1h) below entry",
  "exit_rules": "Exit ONLY when 1h ATR trailing stop is hit. No profit target — let trends run. Re-enter if price makes new high/low after trailing stop exit",
  "stop_loss": "Initial: 2x ATR(1h) from entry. Trailing: moves up with price, never moves down. Chandelier exit logic",
  "filters": [
    "4h must show clear trend (EMA sloping, ADX > 20)",
    "1h ATR must be stable or expanding (not collapsing — that suggests trend ending)",
    "Volume must be positive on trend days",
    "Max 1 re-entry per 4h trend leg after trailing stop hit"
  ],
  "parameter_ranges": {
    "atr_multiplier": [1.5, 3.0],
    "atr_period": [10, 20],
    "ema_trend_period": [40, 60],
    "adx_threshold": [18, 25],
    "max_reentries": [1, 3]
  },
  "expected_behavior": {
    "win_rate": "40-50%",
    "avg_RR": "3.0-6.0R",
    "best_regime": "extended trends with moderate volatility",
    "worst_regime": "choppy markets that trigger trailing stops repeatedly"
  },
  "invalidation": "If win rate < 30% over 80 trades or if average winning trade doesn't exceed 2.5R, strategy is invalid"
}
```
