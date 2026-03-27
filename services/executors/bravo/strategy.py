"""
Bravo Agent — Mean Reversion Executor

Executes mean reversion strategies: RSI divergence at support, Bollinger Band
snaps, VWAP reversion, consecutive close reversals, Z-score extremes.
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


class BravoExecutor(BaseExecutor):
    """Mean Reversion — fades extremes at structural levels."""

    AGENT_ID = "bravo"
    AGENT_NAME = "Bravo — Mean Reversion"
    STYLE = "mean_reversion"

    def check_bias(self, context_4h: TimeframeData) -> BiasResult:
        """
        4h: Identify ranging environment. ADX < 25 = range-bound (ideal).
        Also note key support/resistance and position relative to 200 EMA.
        """
        close = context_4h.ohlc["close"]
        ema_50 = context_4h.ema_50
        adx = context_4h.adx
        support = context_4h.support
        resistance = context_4h.resistance

        # Mean reversion works best in ranging markets or WITH the macro trend
        if adx < 25:
            # Ranging — look for extremes to fade
            if close < support * 1.01:
                direction = Bias.BULLISH  # At support, expect bounce
                confidence = 0.7
            elif close > resistance * 0.99:
                direction = Bias.BEARISH  # At resistance, expect rejection
                confidence = 0.7
            else:
                direction = Bias.NEUTRAL
                confidence = 0.5  # ranging, wait for extreme
        else:
            # Trending — only trade MR with the trend
            if close > ema_50:
                direction = Bias.BULLISH
                confidence = 0.5
            else:
                direction = Bias.BEARISH
                confidence = 0.5

        return BiasResult(
            bias=direction,
            confidence=confidence,
            rationale=f"ADX={adx:.1f}, close={close:.1f}, support={support:.1f}, resistance={resistance:.1f}",
            indicators={"adx": adx, "support": support, "resistance": resistance},
        )

    def check_confirmation(self, context_1h: TimeframeData, bias: BiasResult) -> ConfirmationResult:
        """
        1h: Detect RSI extremes at structural levels.
        RSI < 30 at support (long) or RSI > 70 at resistance (short).
        """
        rsi = context_1h.rsi
        close = context_1h.ohlc["close"]
        vwap = context_1h.vwap

        confirmed = False
        confidence = 0.0

        if bias.bias == Bias.BULLISH:
            # Looking for oversold conditions
            if rsi < 30:
                confirmed = True
                confidence = 0.85
            elif rsi < 40:
                confirmed = True
                confidence = 0.55
        elif bias.bias == Bias.BEARISH:
            # Looking for overbought conditions
            if rsi > 70:
                confirmed = True
                confidence = 0.85
            elif rsi > 60:
                confirmed = True
                confidence = 0.55
        elif bias.bias == Bias.NEUTRAL:
            # Neutral bias — need RSI extremes
            if rsi < 30 or rsi > 70:
                confirmed = True
                confidence = 0.7

        return ConfirmationResult(
            status=Confirmation.CONFIRMED if confirmed else Confirmation.NOT_CONFIRMED,
            confidence=confidence,
            rationale=f"1h RSI={rsi:.1f}, VWAP={vwap:.1f}, close={close:.1f}",
            indicators={"rsi": rsi, "vwap": vwap},
        )

    def check_setup(self, context_15m: TimeframeData, bias: BiasResult, confirmation: ConfirmationResult) -> SetupResult:
        """
        15m: Look for reversal signals — RSI divergence, BB band touch,
        stochastic crossover, volume drying up.
        """
        rsi = context_15m.rsi
        close = context_15m.ohlc["close"]
        bb_lower = context_15m.bb_lower
        bb_upper = context_15m.bb_upper
        bb_middle = context_15m.bb_middle
        stoch_k = context_15m.stochastic_k
        stoch_d = context_15m.stochastic_d

        pattern = ""

        if bias.bias == Bias.BULLISH or (bias.bias == Bias.NEUTRAL and confirmation.confidence > 0.5):
            # Bullish reversal setups
            if bb_lower > 0 and close <= bb_lower * 1.002:
                pattern = "bb_lower_touch"
            elif rsi < 35 and stoch_k < 20:
                pattern = "oversold_stochastic_cross"
            elif rsi < 40:
                pattern = "rsi_oversold_setup"
        elif bias.bias == Bias.BEARISH or (bias.bias == Bias.NEUTRAL and confirmation.confidence > 0.5):
            # Bearish reversal setups
            if bb_upper > 0 and close >= bb_upper * 0.998:
                pattern = "bb_upper_touch"
            elif rsi > 65 and stoch_k > 80:
                pattern = "overbought_stochastic_cross"
            elif rsi > 60:
                pattern = "rsi_overbought_setup"

        if pattern:
            return SetupResult(
                status=SetupStatus.SETUP_FOUND,
                pattern=pattern,
                rationale=f"15m reversal: {pattern}, RSI={rsi:.1f}, BB=[{bb_lower:.1f}, {bb_upper:.1f}]",
                key_level=bb_middle if bb_middle > 0 else context_15m.vwap,
                indicators={"rsi": rsi, "stoch_k": stoch_k, "stoch_d": stoch_d},
            )

        return SetupResult(
            status=SetupStatus.NO_SETUP,
            rationale=f"No reversal pattern: RSI={rsi:.1f}, no BB touch",
        )

    def check_entry(self, context_5m: TimeframeData, bias: BiasResult, setup: SetupResult) -> Optional[EntrySignal]:
        """
        5m: Enter on reversal candle — bullish engulfing above VWAP (long)
        or bearish engulfing below VWAP (short).
        """
        close = context_5m.ohlc["close"]
        open_ = context_5m.ohlc["open"]
        high = context_5m.ohlc["high"]
        low = context_5m.ohlc["low"]
        vwap = context_5m.vwap
        atr = context_5m.atr or 1.0
        rsi = context_5m.rsi

        target_level = setup.key_level  # Usually BB middle / VWAP

        # Bullish reversal entry
        if bias.bias in (Bias.BULLISH, Bias.NEUTRAL) and rsi < 45:
            # Reversal candle: close > open (green) and reclaiming levels
            if close > open_:
                stop = low - atr * 1.0
                risk = close - stop
                target_1 = target_level if target_level > close else close + risk * 1.5
                target_2 = close + risk * 2.5

                return EntrySignal(
                    direction=SignalDirection.LONG,
                    entry_price=close,
                    stop_loss=round(stop, 2),
                    target_1=round(target_1, 2),
                    target_2=round(target_2, 2),
                    rationale=f"5m bullish reversal: close={close:.2f} > open={open_:.2f}, RSI={rsi:.1f}",
                    confidence=0.65,
                    indicators={"rsi": rsi, "vwap": vwap},
                )

        # Bearish reversal entry
        if bias.bias in (Bias.BEARISH, Bias.NEUTRAL) and rsi > 55:
            if close < open_:
                stop = high + atr * 1.0
                risk = stop - close
                target_1 = target_level if target_level < close else close - risk * 1.5
                target_2 = close - risk * 2.5

                return EntrySignal(
                    direction=SignalDirection.SHORT,
                    entry_price=close,
                    stop_loss=round(stop, 2),
                    target_1=round(target_1, 2),
                    target_2=round(target_2, 2),
                    rationale=f"5m bearish reversal: close={close:.2f} < open={open_:.2f}, RSI={rsi:.1f}",
                    confidence=0.65,
                    indicators={"rsi": rsi, "vwap": vwap},
                )

        return None
