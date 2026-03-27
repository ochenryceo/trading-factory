"""
Charlie Agent — Scalping Executor

Executes scalp strategies: key-level reactions, VWAP bounces, failed breakouts,
momentum ignition, and volume profile (POC/VA) trades.

Scalping uses 1h + 5m only (no 4h/15m in DNA), but we adapt to the
base executor's 4-step cascade by merging logic appropriately.
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


class CharlieExecutor(BaseExecutor):
    """Scalping — quick reactions at key structural levels."""

    AGENT_ID = "charlie"
    AGENT_NAME = "Charlie — Scalping"
    STYLE = "scalping"
    MAX_CONCURRENT_TRADES = 4  # scalps allow more concurrent

    def check_bias(self, context_4h: TimeframeData) -> BiasResult:
        """
        Scalping uses 1h for bias. 4h provides general context.
        Determine if market is trending or ranging from 4h.
        """
        close = context_4h.ohlc["close"]
        ema_20 = context_4h.ema_20
        ema_50 = context_4h.ema_50
        adx = context_4h.adx

        # Scalping works in all conditions — just note the context
        if close > ema_20 > ema_50:
            direction = Bias.BULLISH
            confidence = 0.6
        elif close < ema_20 < ema_50:
            direction = Bias.BEARISH
            confidence = 0.6
        else:
            # Ranging is fine for scalping
            direction = Bias.NEUTRAL
            confidence = 0.5

        return BiasResult(
            bias=direction,
            confidence=confidence,
            rationale=f"4h context: EMA20={ema_20:.1f}, EMA50={ema_50:.1f}, ADX={adx:.1f}",
            indicators={"ema_20": ema_20, "ema_50": ema_50, "adx": adx},
        )

    def check_confirmation(self, context_1h: TimeframeData, bias: BiasResult) -> ConfirmationResult:
        """
        1h: Identify key levels (support, resistance, VWAP, POC).
        For scalping, confirmation = key levels are defined and price is near one.
        """
        close = context_1h.ohlc["close"]
        support = context_1h.support
        resistance = context_1h.resistance
        vwap = context_1h.vwap
        atr = context_1h.atr or 1.0

        # Check proximity to key levels
        near_support = abs(close - support) < atr * 2.0
        near_resistance = abs(close - resistance) < atr * 2.0
        near_vwap = abs(close - vwap) < atr * 1.5

        has_key_level = near_support or near_resistance or near_vwap
        confidence = 0.7 if has_key_level else 0.3

        return ConfirmationResult(
            status=Confirmation.CONFIRMED if has_key_level else Confirmation.NOT_CONFIRMED,
            confidence=confidence,
            rationale=(
                f"1h levels: S={support:.1f}, R={resistance:.1f}, VWAP={vwap:.1f}, "
                f"close={close:.1f}, near_level={has_key_level}"
            ),
            indicators={"support": support, "resistance": resistance, "vwap": vwap},
        )

    def check_setup(self, context_15m: TimeframeData, bias: BiasResult, confirmation: ConfirmationResult) -> SetupResult:
        """
        15m: For scalping, this refines the key level.
        Check for reversal candle patterns or failed breakout signals.
        """
        close = context_15m.ohlc["close"]
        high = context_15m.ohlc["high"]
        low = context_15m.ohlc["low"]
        open_ = context_15m.ohlc["open"]
        atr = context_15m.atr or 1.0
        volume = context_15m.volume
        avg_volume = context_15m.avg_volume or volume

        # Check for reversal candle (wick rejection)
        body = abs(close - open_)
        upper_wick = high - max(close, open_)
        lower_wick = min(close, open_) - low

        pattern = ""

        # Pin bar / hammer at level
        if body > 0 and lower_wick > body * 1.5 and bias.bias != Bias.BEARISH:
            pattern = "hammer_at_support"
        elif body > 0 and upper_wick > body * 1.5 and bias.bias != Bias.BULLISH:
            pattern = "shooting_star_at_resistance"
        # Volume spike suggesting reaction
        elif avg_volume > 0 and volume > avg_volume * 1.2:
            if close > open_:
                pattern = "volume_rejection_bullish"
            else:
                pattern = "volume_rejection_bearish"

        if pattern:
            return SetupResult(
                status=SetupStatus.SETUP_FOUND,
                pattern=pattern,
                rationale=f"15m: {pattern}, body={body:.2f}, wicks=[{lower_wick:.2f}, {upper_wick:.2f}]",
                key_level=low if "bullish" in pattern or "hammer" in pattern else high,
                indicators={"body": body, "upper_wick": upper_wick, "lower_wick": lower_wick},
            )

        return SetupResult(
            status=SetupStatus.NO_SETUP,
            rationale=f"No scalp setup: no rejection candle, vol_ratio={(volume/avg_volume if avg_volume else 0):.1f}",
        )

    def check_entry(self, context_5m: TimeframeData, bias: BiasResult, setup: SetupResult) -> Optional[EntrySignal]:
        """
        5m: Execute at key level with reversal candle and volume.
        Tight stops, 1-2R targets.
        """
        close = context_5m.ohlc["close"]
        open_ = context_5m.ohlc["open"]
        high = context_5m.ohlc["high"]
        low = context_5m.ohlc["low"]
        atr = context_5m.atr or 1.0
        volume = context_5m.volume
        avg_volume = context_5m.avg_volume or volume

        key_level = setup.key_level

        # Bullish scalp: reversal at support
        if "bullish" in setup.pattern or "hammer" in setup.pattern:
            if close > open_:  # green candle confirms
                stop = key_level - atr * 0.5
                risk = close - stop
                target_1 = close + risk * 1.5
                target_2 = close + risk * 2.0

                return EntrySignal(
                    direction=SignalDirection.LONG,
                    entry_price=close,
                    stop_loss=round(stop, 2),
                    target_1=round(target_1, 2),
                    target_2=round(target_2, 2),
                    rationale=f"5m scalp long: reversal confirmed at {key_level:.2f}",
                    confidence=0.65,
                    indicators={"volume": volume, "atr": atr},
                )

        # Bearish scalp: rejection at resistance
        if "bearish" in setup.pattern or "shooting_star" in setup.pattern:
            if close < open_:  # red candle confirms
                stop = key_level + atr * 0.5
                risk = stop - close
                target_1 = close - risk * 1.5
                target_2 = close - risk * 2.0

                return EntrySignal(
                    direction=SignalDirection.SHORT,
                    entry_price=close,
                    stop_loss=round(stop, 2),
                    target_1=round(target_1, 2),
                    target_2=round(target_2, 2),
                    rationale=f"5m scalp short: rejection confirmed at {key_level:.2f}",
                    confidence=0.65,
                    indicators={"volume": volume, "atr": atr},
                )

        return None
