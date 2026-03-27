"""
Delta Agent — Trend Following Executor

Executes trend following strategies: EMA pullback entries, Donchian breakouts,
composite momentum scores, Fibonacci retracements, ATR trailing systems.
"""
from __future__ import annotations

from typing import Optional

from ..base_executor import (
    BaseExecutor,
    Bias,
    BiasResult,
    Confirmation,
    ConfirmationResult,
    EntrySignal,
    SetupResult,
    SetupStatus,
    SignalDirection,
    StrategyDNA,
    TimeframeData,
)


class DeltaExecutor(BaseExecutor):
    """Trend Following — rides established trends with trailing stops."""

    AGENT_ID = "delta"
    AGENT_NAME = "Delta — Trend Following"
    STYLE = "trend_following"
    MIN_COMPOSITE_CONFIDENCE = 0.45  # trend following has lower win rate, higher RR

    def check_bias(self, context_4h: TimeframeData) -> BiasResult:
        """
        4h: Primary trend via EMA crossover + ADX confirmation.
        20 EMA > 50 EMA = uptrend. ADX > 20 confirms.
        """
        ema_20 = context_4h.ema_20
        ema_50 = context_4h.ema_50
        close = context_4h.ohlc["close"]
        adx = context_4h.adx
        macd = context_4h.macd
        macd_signal = context_4h.macd_signal

        # EMA crossover direction
        if ema_20 > ema_50:
            direction = Bias.BULLISH
            ema_score = 0.6
        elif ema_20 < ema_50:
            direction = Bias.BEARISH
            ema_score = 0.6
        else:
            direction = Bias.NEUTRAL
            ema_score = 0.2

        # Price position relative to EMAs
        if direction == Bias.BULLISH and close > ema_20:
            ema_score += 0.1
        elif direction == Bias.BEARISH and close < ema_20:
            ema_score += 0.1

        # ADX strength
        adx_boost = 0.0
        if adx > 25:
            adx_boost = 0.2
        elif adx > 20:
            adx_boost = 0.1

        # MACD alignment
        macd_boost = 0.1 if (direction == Bias.BULLISH and macd > macd_signal) or \
                            (direction == Bias.BEARISH and macd < macd_signal) else 0.0

        confidence = min(ema_score + adx_boost + macd_boost, 1.0)

        return BiasResult(
            bias=direction,
            confidence=confidence,
            rationale=f"EMA20={ema_20:.1f} vs EMA50={ema_50:.1f}, ADX={adx:.1f}, MACD={macd:.2f}",
            indicators={"ema_20": ema_20, "ema_50": ema_50, "adx": adx, "macd": macd},
        )

    def check_confirmation(self, context_1h: TimeframeData, bias: BiasResult) -> ConfirmationResult:
        """
        1h: Confirm trend alignment and identify pullback structure.
        Price above both EMAs for longs. Check for pullback to EMA zone.
        """
        close = context_1h.ohlc["close"]
        ema_20 = context_1h.ema_20
        ema_50 = context_1h.ema_50
        rsi = context_1h.rsi
        atr = context_1h.atr or 1.0

        confirmed = False
        confidence = 0.0

        if bias.bias == Bias.BULLISH:
            # Price above both EMAs, pulling back toward 20 EMA
            if close > ema_50:
                confirmed = True
                # Pullback to 20 EMA zone = best entry
                distance_to_ema20 = abs(close - ema_20)
                if distance_to_ema20 < atr * 1.0:
                    confidence = 0.8  # ideal pullback zone
                elif close > ema_20:
                    confidence = 0.55  # trending but not pulled back yet
                else:
                    confidence = 0.4  # below 20 EMA but above 50 = deep pullback

        elif bias.bias == Bias.BEARISH:
            if close < ema_50:
                confirmed = True
                distance_to_ema20 = abs(close - ema_20)
                if distance_to_ema20 < atr * 1.0:
                    confidence = 0.8
                elif close < ema_20:
                    confidence = 0.55
                else:
                    confidence = 0.4

        return ConfirmationResult(
            status=Confirmation.CONFIRMED if confirmed else Confirmation.NOT_CONFIRMED,
            confidence=confidence,
            rationale=f"1h: close={close:.1f}, EMA20={ema_20:.1f}, EMA50={ema_50:.1f}, RSI={rsi:.1f}",
            indicators={"close": close, "ema_20": ema_20, "ema_50": ema_50, "rsi": rsi},
        )

    def check_setup(self, context_15m: TimeframeData, bias: BiasResult, confirmation: ConfirmationResult) -> SetupResult:
        """
        15m: Wait for pullback to 1h 20 EMA zone. RSI between 40-55.
        Look for structure forming (Fib zone, consolidation).
        """
        rsi = context_15m.rsi
        close = context_15m.ohlc["close"]
        ema_20 = context_15m.ema_20
        atr = context_15m.atr or 1.0
        stoch_k = context_15m.stochastic_k

        pattern = ""

        if bias.bias == Bias.BULLISH:
            # RSI pullback zone (not oversold, just pulled back)
            if 35 <= rsi <= 60:
                # Near 15m EMA (proxy for 1h EMA pullback zone)
                if abs(close - ema_20) < atr * 1.5:
                    pattern = "pullback_to_ema_zone"
                elif stoch_k < 40:
                    pattern = "stochastic_pullback"
        elif bias.bias == Bias.BEARISH:
            if 40 <= rsi <= 65:
                if abs(close - ema_20) < atr * 1.5:
                    pattern = "pullback_to_ema_zone"
                elif stoch_k > 60:
                    pattern = "stochastic_pullback"

        if pattern:
            return SetupResult(
                status=SetupStatus.SETUP_FOUND,
                pattern=pattern,
                rationale=f"15m trend pullback: {pattern}, RSI={rsi:.1f}, near EMA20={ema_20:.1f}",
                key_level=ema_20,
                indicators={"rsi": rsi, "stoch_k": stoch_k, "ema_20": ema_20},
            )

        return SetupResult(
            status=SetupStatus.NO_SETUP,
            rationale=f"No pullback setup: RSI={rsi:.1f} outside zone or not near EMA",
        )

    def check_entry(self, context_5m: TimeframeData, bias: BiasResult, setup: SetupResult) -> Optional[EntrySignal]:
        """
        5m: Enter on reversal candle showing trend resumption with volume.
        """
        close = context_5m.ohlc["close"]
        open_ = context_5m.ohlc["open"]
        high = context_5m.ohlc["high"]
        low = context_5m.ohlc["low"]
        atr = context_5m.atr or 1.0
        ema_20 = context_5m.ema_20

        if bias.bias == Bias.BULLISH:
            # Bullish resumption: green candle, closing above 5m EMA
            if close > open_ and close > ema_20:
                # Trend following uses wider stops, bigger targets
                stop = low - atr * 1.5
                risk = close - stop
                target_1 = close + risk * 2.0
                target_2 = close + risk * 3.5

                return EntrySignal(
                    direction=SignalDirection.LONG,
                    entry_price=close,
                    stop_loss=round(stop, 2),
                    target_1=round(target_1, 2),
                    target_2=round(target_2, 2),
                    rationale=f"5m trend resumption long: close={close:.2f} > EMA20={ema_20:.2f}",
                    confidence=0.6,
                    indicators={"ema_20": ema_20, "atr": atr},
                )

        elif bias.bias == Bias.BEARISH:
            if close < open_ and close < ema_20:
                stop = high + atr * 1.5
                risk = stop - close
                target_1 = close - risk * 2.0
                target_2 = close - risk * 3.5

                return EntrySignal(
                    direction=SignalDirection.SHORT,
                    entry_price=close,
                    stop_loss=round(stop, 2),
                    target_1=round(target_1, 2),
                    target_2=round(target_2, 2),
                    rationale=f"5m trend resumption short: close={close:.2f} < EMA20={ema_20:.2f}",
                    confidence=0.6,
                    indicators={"ema_20": ema_20, "atr": atr},
                )

        return None
