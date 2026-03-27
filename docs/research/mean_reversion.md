# Bravo — Mean Reversion Research & Strategy DNAs

_Track C Research | 2026-03-22_

---

## Part A: Trader Research

### 1. Larry Connors
- **Market Focus:** US equities and index futures (S&P, NQ). Pioneer of quantitative mean reversion.
- **Common Patterns:** RSI(2) extremes — buying when 2-period RSI drops below 10, selling when it rises above 90. Cumulative RSI strategies. ConnorsRSI composite indicator.
- **Timeframe Logic:** Daily for signal generation, intraday for execution. Futures: 4h for trend bias (only trade mean reversion WITH the trend), 1h for RSI extremes, 15m for setup, 5m for precise entry.
- **Entry/Exit Logic:** Buy when RSI(2) < 10 in an uptrending market (price above 200 MA). Sell when RSI(2) > 70 or price closes above 5-period MA.
- **Risk Management:** No fixed stop-loss (relies on mean reversion probability). Position sizing based on historical win rate. Max drawdown caps.

### 2. Kevin Davey
- **Market Focus:** World Cup Trading Championship winner. Algorithmic futures trader.
- **Common Patterns:** Statistical mean reversion using Bollinger Band extremes and Z-score analysis. Identifies when price deviates > 2 standard deviations from mean.
- **Timeframe Logic:** Daily/4h for regime identification, 15m-1h for signal generation. Multi-timeframe confirmation.
- **Entry/Exit Logic:** Enter when price touches lower Bollinger Band (long) or upper (short) with RSI divergence. Exit at middle band (20 SMA) or opposing band.
- **Risk Management:** Fixed percentage risk. Monte Carlo validated position sizing. Strict drawdown limits.

### 3. Rob Carver (Systematic Trading)
- **Market Focus:** Global futures across all asset classes. Author of "Systematic Trading."
- **Common Patterns:** Statistical arbitrage and mean reversion at slow speeds (multi-day to multi-week). Uses carry and mean reversion together.
- **Timeframe Logic:** Weekly/daily for mean reversion signals on futures. Adapted for intraday: 4h for statistical mean, 1h for deviation detection.
- **Entry/Exit Logic:** Enter when price deviates > 1.5 standard deviations from rolling mean. Exit at mean. Partial entry/exit at different deviation levels.
- **Risk Management:** Volatility-targeted position sizing. Risk parity approach. Portfolio-level risk management.

### 4. Howard Bandy
- **Market Focus:** Quantitative mean reversion in futures/equities. Author of quantitative trading books.
- **Common Patterns:** Oversold bounces at support levels using composite indicators (RSI + rate of change + distance from MA). Mean reversion with structural support.
- **Timeframe Logic:** Daily for structural levels, intraday for entry. Futures: 4h support/resistance, 1h for mean identification, 15m for oversold detection, 5m entry.
- **Entry/Exit Logic:** Price at 4h support + 1h RSI < 30 + positive divergence on 15m. Enter on 5m reversal candle. Exit at VWAP or 20 EMA on 1h.
- **Risk Management:** Below support by 1 ATR stop. Risk 1% per trade. Time-based stops (exit if no mean reversion within X bars).

### 5. Cesar Alvarez
- **Market Focus:** Short-term mean reversion in ETFs and futures. Co-author of Connors Research.
- **Common Patterns:** Multi-day pullbacks in uptrending instruments. Streak-based entries (consecutive down days increase probability of reversal).
- **Timeframe Logic:** Daily for streak counting, intraday for entry timing. Futures: 4h for trend confirmation, 1h for streak/pullback analysis, 5m for entry.
- **Entry/Exit Logic:** 3+ consecutive lower closes in an uptrend. Enter on 5m bullish reversal pattern. Exit when price closes above 5-period MA on 1h.
- **Risk Management:** Time-based exits. Fixed holding period. No traditional stop (relies on probability edge).

---

## Part B: Strategy DNAs

### MR-001: RSI Extreme Bounce at Structural Support

```json
{
  "strategy_code": "MR-001",
  "style": "mean_reversion",
  "template": "MeanReversion_Template",
  "timeframe_logic": {
    "4h": "Identify key support/resistance zones. Confirm macro trend direction (above/below 200 EMA)",
    "1h": "Detect RSI(14) < 30 at or near 4h support level. VWAP position assessment",
    "15m": "Look for bullish divergence on RSI. Wait for selling pressure to dry up (volume declining)",
    "5m": "Enter on bullish engulfing or hammer candle above VWAP with RSI turning up"
  },
  "hypothesis": "Price reverses at 4h support when 1h RSI < 30 and 15m shows bullish divergence. The combination of structural support, oversold conditions, and momentum divergence creates a high-probability mean reversion setup",
  "entry_rules": "Price at 4h support zone (within 1 ATR). 1h RSI(14) < 30. 15m RSI shows bullish divergence (higher low while price makes lower low). 5m candle closes above VWAP after bullish reversal pattern",
  "exit_rules": "Target 1: 15m structure break or VWAP midpoint. Target 2: 2R. Exit if price makes new low below support on 5m close",
  "stop_loss": "Below 4h support level minus 1 ATR(4h)",
  "filters": [
    "4h trend should be up (price above 200 EMA) — trade mean reversion WITH the trend",
    "1h RSI must be < 30, not just near 30",
    "15m must show divergence (not just oversold)",
    "No major bearish news catalyst active"
  ],
  "parameter_ranges": {
    "rsi_threshold": [25, 35],
    "atr_multiplier": [0.5, 1.5],
    "target_R": [1.5, 3.0],
    "rsi_period": [10, 20],
    "support_zone_atr": [0.5, 1.5]
  },
  "expected_behavior": {
    "win_rate": "55-65%",
    "avg_RR": "1.5-2.0R",
    "best_regime": "ranging markets with clear support/resistance",
    "worst_regime": "strong trend days where support breaks"
  },
  "invalidation": "If win rate < 40% over 100 trades or max drawdown > 8%, strategy is invalid"
}
```

### MR-002: Bollinger Band Snap-Back

```json
{
  "strategy_code": "MR-002",
  "style": "mean_reversion",
  "template": "MeanReversion_Template",
  "timeframe_logic": {
    "4h": "Determine if market is in range-bound regime (ADX < 25, Bollinger Band width stable)",
    "1h": "Price touches or pierces outer Bollinger Band (20,2). Note distance from 20 SMA",
    "15m": "Wait for reversal candle pattern at band extreme. Volume spike indicates capitulation",
    "5m": "Enter on first 5m close back inside Bollinger Band with declining momentum"
  },
  "hypothesis": "When price touches the outer Bollinger Band in a range-bound market, it reverts to the 20 SMA (middle band) 70-80% of the time. The snap-back is strongest when combined with volume capitulation and reversal candle patterns",
  "entry_rules": "4h ADX < 25 (ranging). 1h price closes beyond 2 SD Bollinger Band. 15m shows reversal candle (engulfing, pin bar, doji). 5m first candle back inside band with volume > 1.5x average (capitulation)",
  "exit_rules": "Target 1: 20 SMA (middle band) on 1h. Target 2: opposite Bollinger Band (if momentum strong). Trail with 15m 10 EMA after reaching middle band",
  "stop_loss": "Beyond the extreme point (wick) of the band touch, plus 0.5 ATR(1h)",
  "filters": [
    "ADX(4h) < 25 — must be range-bound, not trending",
    "Price must close beyond the band, not just touch it",
    "No earnings/FOMC within 4 hours",
    "Band width must not be expanding rapidly (not a volatility breakout)"
  ],
  "parameter_ranges": {
    "bb_period": [15, 25],
    "bb_std_dev": [1.8, 2.5],
    "adx_max": [20, 28],
    "volume_multiplier": [1.2, 2.0],
    "target_R": [1.5, 2.5]
  },
  "expected_behavior": {
    "win_rate": "60-70%",
    "avg_RR": "1.2-1.8R",
    "best_regime": "range-bound, mean-reverting markets",
    "worst_regime": "trending breakout days where bands expand"
  },
  "invalidation": "If win rate < 45% over 100 trades or if strategy loses money in 3 consecutive weeks, strategy is invalid"
}
```

### MR-003: VWAP Reversion from Extremes

```json
{
  "strategy_code": "MR-003",
  "style": "mean_reversion",
  "template": "MeanReversion_Template",
  "timeframe_logic": {
    "4h": "Identify session VWAP and standard deviation bands. Note prior session's value area",
    "1h": "Price deviates > 2 standard deviations from session VWAP",
    "15m": "RSI(14) shows extreme (< 25 or > 75). Watch for reversal momentum shift",
    "5m": "Enter on 5m close crossing back toward VWAP with volume confirmation"
  },
  "hypothesis": "Price that deviates > 2 standard deviations from session VWAP tends to revert to VWAP, especially during the middle of the session when mean-reverting behavior is strongest. The reversion is a statistical tendency amplified by algorithmic execution targeting VWAP",
  "entry_rules": "Price > 2 SD from session VWAP. 1h RSI at extreme (< 25 long / > 75 short). 15m shows momentum reversal (MACD histogram changing direction). 5m candle closes crossing back toward VWAP",
  "exit_rules": "Primary target: session VWAP. Secondary target: 1 SD band on opposite side. Time-based exit: if no VWAP tag within 2 hours, exit at market",
  "stop_loss": "Beyond the 3 SD band from VWAP, or the session extreme, whichever is tighter",
  "filters": [
    "Only trade VWAP reversion in mid-session (10:30 AM - 2:30 PM ET)",
    "Not during major news release windows",
    "Session must have established a clear VWAP with > 1 hour of data",
    "Volume must be above average for the session (not a thin holiday market)"
  ],
  "parameter_ranges": {
    "vwap_deviation_entry": [1.8, 2.5],
    "vwap_deviation_stop": [2.5, 3.5],
    "rsi_extreme": [20, 30],
    "max_hold_hours": [1.5, 3.0],
    "target_levels": ["vwap", "1sd_opposite"]
  },
  "expected_behavior": {
    "win_rate": "58-68%",
    "avg_RR": "1.2-2.0R",
    "best_regime": "normal trading days with established VWAP, mid-session",
    "worst_regime": "trending days where VWAP never gets retested, news-driven sessions"
  },
  "invalidation": "If win rate < 42% over 80 trades or if average R:R drops below 1.0, strategy is invalid"
}
```

### MR-004: Consecutive Close Streak Reversal (Connors-Style)

```json
{
  "strategy_code": "MR-004",
  "style": "mean_reversion",
  "template": "MeanReversion_Template",
  "timeframe_logic": {
    "4h": "Confirm macro trend is up (price above 50 EMA) — only trade mean reversion WITH trend",
    "1h": "Count consecutive lower closes. 3+ consecutive lower 1h closes triggers setup watch",
    "15m": "On the 3rd+ consecutive lower close, check RSI(2) < 10 on 15m for extreme oversold",
    "5m": "Enter on first 5m bar that closes above the prior 5m bar's high (reversal candle)"
  },
  "hypothesis": "After 3+ consecutive lower closes on 1h in an uptrending market, the probability of an up-close on the next bar exceeds 65%. The RSI(2) < 10 filter further increases edge by ensuring genuine oversold conditions",
  "entry_rules": "4h price above 50 EMA. 1h has 3+ consecutive lower closes. 15m RSI(2) < 10. 5m produces first higher close after the streak",
  "exit_rules": "Exit when 1h RSI(2) > 70 or when price closes above 1h 5-period SMA. Time-based exit: 5 bars on 1h if neither target hit",
  "stop_loss": "Below the lowest low of the consecutive close streak, minus 0.5 ATR(1h)",
  "filters": [
    "4h trend must be up (above 50 EMA) — never trade streak reversal against the trend",
    "Minimum 3 consecutive lower closes on 1h",
    "RSI(2) on 15m must be < 10 (true extreme)",
    "Not during last hour of RTH session"
  ],
  "parameter_ranges": {
    "min_consecutive_closes": [3, 5],
    "rsi2_threshold": [5, 15],
    "exit_rsi2": [60, 80],
    "sma_exit_period": [3, 7],
    "max_hold_bars_1h": [3, 8]
  },
  "expected_behavior": {
    "win_rate": "65-75%",
    "avg_RR": "0.8-1.5R",
    "best_regime": "uptrending markets with short-term pullbacks",
    "worst_regime": "trend reversals where pullbacks become new downtrends"
  },
  "invalidation": "If win rate < 50% over 100 trades, strategy is invalid — edge depends on high win rate with moderate R:R"
}
```

### MR-005: Z-Score Mean Reversion at Key Levels

```json
{
  "strategy_code": "MR-005",
  "style": "mean_reversion",
  "template": "MeanReversion_Template",
  "timeframe_logic": {
    "4h": "Calculate 50-period rolling mean and standard deviation. Identify key structural levels",
    "1h": "Compute Z-score (current price deviation from mean / std dev). Flag when |Z| > 2.0",
    "15m": "Watch for reversal signals at Z-score extreme — stochastic crossover, volume shift",
    "5m": "Enter on 5m confirmation: close crossing back toward zero Z-score direction"
  },
  "hypothesis": "Z-scores > 2.0 or < -2.0 on the 1h timeframe represent statistically significant deviations. In non-trending markets, these extremes revert to the mean 80%+ of the time. Structural support/resistance on 4h increases the probability",
  "entry_rules": "1h Z-score > 2.0 (short) or < -2.0 (long). 4h structural level within 1 ATR confirms zone. 15m stochastic crosses from overbought/oversold zone. 5m candle confirms direction change",
  "exit_rules": "Exit at Z-score = 0 (mean). Partial exit at Z-score = 1.0 (halfway). Time-based exit after 8 hours if Z-score hasn't returned to 1.0",
  "stop_loss": "Z-score = 3.0 level, or 4h structure break, whichever is closer",
  "filters": [
    "ADX(4h) < 30 — avoid strong trends where Z-score extremes persist",
    "Z-score must reach 2.0, not just approach it",
    "Structural level on 4h must exist within 1 ATR of entry",
    "No FOMC/CPI/NFP within 4 hours"
  ],
  "parameter_ranges": {
    "z_score_entry": [1.8, 2.5],
    "z_score_stop": [2.5, 3.5],
    "rolling_period": [30, 70],
    "stochastic_period": [10, 20],
    "max_hold_hours": [4, 12]
  },
  "expected_behavior": {
    "win_rate": "60-70%",
    "avg_RR": "1.0-1.8R",
    "best_regime": "range-bound markets with clear statistical mean",
    "worst_regime": "regime shifts, trending markets where mean moves"
  },
  "invalidation": "If win rate < 45% over 80 trades or if Z-score extremes persist beyond stop in > 30% of trades, strategy is invalid"
}
```
