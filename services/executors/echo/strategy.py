"""
Echo Agent — News Reaction Executor

Executes news/event-driven strategies: post-event breakouts, news spike fades,
FOMC drift trades, CPI surprise momentum, compression-expansion straddles.
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


class EchoExecutor(BaseExecutor):
    """News Reaction — trades macro event catalysts and their aftermath."""

    AGENT_ID = "echo"
    AGENT_NAME = "Echo — News Reaction"
    STYLE = "news_reaction"

    def check_bias(self, context_4h: TimeframeData) -> BiasResult:
        """
        4h: Pre-event macro context — trend direction, positioning, key levels.
        For news strategies, the 4h trend tells us what to expect from reactions.
        """
        ema_20 = context_4h.ema_20
        ema_50 = context_4h.ema_50
        close = context_4h.ohlc["close"]
        atr = context_4h.atr
        adx = context_4h.adx

        # Pre-event context: trending markets react differently than ranging
        if close > ema_20 > ema_50:
            direction = Bias.BULLISH
            confidence = 0.6
        elif close < ema_20 < ema_50:
            direction = Bias.BEARISH
            confidence = 0.6
        else:
            direction = Bias.NEUTRAL
            confidence = 0.5

        # Higher ATR = more volatile = news reactions amplified
        # ADX shows if market is already trending (reactions may extend trend)

        return BiasResult(
            bias=direction,
            confidence=confidence,
            rationale=f"Pre-event: EMA20={ema_20:.1f}, EMA50={ema_50:.1f}, ATR={atr:.2f}, ADX={adx:.1f}",
            indicators={"ema_20": ema_20, "ema_50": ema_50, "atr": atr, "adx": adx},
        )

    def check_confirmation(self, context_1h: TimeframeData, bias: BiasResult) -> ConfirmationResult:
        """
        1h: Mark pre-event range and compression.
        Look for BB width contraction = energy building for event.
        """
        close = context_1h.ohlc["close"]
        high = context_1h.ohlc["high"]
        low = context_1h.ohlc["low"]
        bb_width = context_1h.bb_width
        bb_middle = context_1h.bb_middle
        atr = context_1h.atr or 1.0
        support = context_1h.support
        resistance = context_1h.resistance

        # Pre-event compression: narrow range + declining BB width
        range_size = high - low
        range_vs_atr = range_size / atr if atr > 0 else 1.0

        # Compressed = good for news trades (energy stored)
        compressed = range_vs_atr < 1.5

        # Check if we have clear boundaries to mark
        has_range = support > 0 and resistance > 0 and resistance > support

        confirmed = compressed or has_range
        confidence = 0.0
        if compressed and has_range:
            confidence = 0.8
        elif compressed:
            confidence = 0.65
        elif has_range:
            confidence = 0.55

        return ConfirmationResult(
            status=Confirmation.CONFIRMED if confirmed else Confirmation.NOT_CONFIRMED,
            confidence=confidence,
            rationale=(
                f"1h pre-event: range={range_size:.1f}, ATR={atr:.2f}, "
                f"compressed={compressed}, BB_width={bb_width:.4f}"
            ),
            indicators={
                "range_size": range_size,
                "bb_width": bb_width,
                "compressed": compressed,
                "support": support,
                "resistance": resistance,
            },
        )

    def check_setup(self, context_15m: TimeframeData, bias: BiasResult, confirmation: ConfirmationResult) -> SetupResult:
        """
        15m: First candle direction after event = signal direction.
        Check for directional close outside pre-event range with volume surge.
        """
        close = context_15m.ohlc["close"]
        open_ = context_15m.ohlc["open"]
        high = context_15m.ohlc["high"]
        low = context_15m.ohlc["low"]
        volume = context_15m.volume
        avg_volume = context_15m.avg_volume or volume
        rsi = context_15m.rsi
        atr = context_15m.atr or 1.0

        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0

        # Large directional candle = event reaction
        candle_size = abs(close - open_)
        large_candle = candle_size > atr * 0.8

        # Volume surge = event volume
        volume_surge = vol_ratio > 1.5

        pattern = ""

        if large_candle and volume_surge:
            if close > open_:
                pattern = "bullish_event_reaction"
            else:
                pattern = "bearish_event_reaction"
        elif large_candle:
            if close > open_ and rsi > 55:
                pattern = "directional_thrust_up"
            elif close < open_ and rsi < 45:
                pattern = "directional_thrust_down"

        if pattern:
            # Determine if fading or following
            # If reaction is against 4h trend, we might fade it
            key_level = close  # breakout level for follow-through

            return SetupResult(
                status=SetupStatus.SETUP_FOUND,
                pattern=pattern,
                rationale=(
                    f"15m event: {pattern}, candle={candle_size:.2f}, "
                    f"vol={vol_ratio:.1f}x, RSI={rsi:.1f}"
                ),
                key_level=key_level,
                indicators={"vol_ratio": vol_ratio, "candle_size": candle_size, "rsi": rsi},
            )

        return SetupResult(
            status=SetupStatus.NO_SETUP,
            rationale=f"No event reaction: candle={candle_size:.2f}, vol={vol_ratio:.1f}x — muted response",
        )

    def check_entry(self, context_5m: TimeframeData, bias: BiasResult, setup: SetupResult) -> Optional[EntrySignal]:
        """
        5m: Enter on confirmation / first pullback after event reaction.
        """
        close = context_5m.ohlc["close"]
        open_ = context_5m.ohlc["open"]
        high = context_5m.ohlc["high"]
        low = context_5m.ohlc["low"]
        atr = context_5m.atr or 1.0
        volume = context_5m.volume
        avg_volume = context_5m.avg_volume or volume

        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0

        if "bullish" in setup.pattern or "up" in setup.pattern:
            # Follow bullish event reaction
            if close > open_ or vol_ratio > 1.3:
                stop = low - atr * 1.0
                risk = close - stop
                target_1 = close + risk * 1.5
                target_2 = close + risk * 2.5

                return EntrySignal(
                    direction=SignalDirection.LONG,
                    entry_price=close,
                    stop_loss=round(stop, 2),
                    target_1=round(target_1, 2),
                    target_2=round(target_2, 2),
                    rationale=f"5m event follow-through long: vol={vol_ratio:.1f}x",
                    confidence=0.6 + min(vol_ratio * 0.05, 0.2),
                    indicators={"vol_ratio": vol_ratio, "atr": atr},
                )

        if "bearish" in setup.pattern or "down" in setup.pattern:
            if close < open_ or vol_ratio > 1.3:
                stop = high + atr * 1.0
                risk = stop - close
                target_1 = close - risk * 1.5
                target_2 = close - risk * 2.5

                return EntrySignal(
                    direction=SignalDirection.SHORT,
                    entry_price=close,
                    stop_loss=round(stop, 2),
                    target_1=round(target_1, 2),
                    target_2=round(target_2, 2),
                    rationale=f"5m event follow-through short: vol={vol_ratio:.1f}x",
                    confidence=0.6 + min(vol_ratio * 0.05, 0.2),
                    indicators={"vol_ratio": vol_ratio, "atr": atr},
                )

        return None
