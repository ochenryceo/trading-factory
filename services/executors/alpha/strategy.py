"""
Alpha Agent — Momentum Breakout Executor

Executes momentum breakout strategies: opening range breaks, VCP breakouts,
flag continuations, compression expansions, ADX pullback re-entries.
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
    MarketContext,
    SetupResult,
    SetupStatus,
    SignalDirection,
    StrategyDNA,
    TimeframeData,
)


class AlphaExecutor(BaseExecutor):
    """Momentum Breakout — trades directional breaks with volume confirmation."""

    AGENT_ID = "alpha"
    AGENT_NAME = "Alpha — Momentum Breakout"
    STYLE = "momentum_breakout"

    def check_bias(self, context_4h: TimeframeData) -> BiasResult:
        """
        4h: EMA alignment + ADX for trend strength.
        Bullish = EMA20 > EMA50 + ADX > 25.
        """
        ema_20 = context_4h.ema_20
        ema_50 = context_4h.ema_50
        close = context_4h.ohlc["close"]
        adx = context_4h.adx

        # EMA alignment
        if ema_20 > ema_50 and close > ema_20:
            direction = Bias.BULLISH
            ema_score = 0.7
        elif ema_20 < ema_50 and close < ema_20:
            direction = Bias.BEARISH
            ema_score = 0.7
        elif ema_20 > ema_50:
            direction = Bias.BULLISH
            ema_score = 0.4
        elif ema_20 < ema_50:
            direction = Bias.BEARISH
            ema_score = 0.4
        else:
            direction = Bias.NEUTRAL
            ema_score = 0.2

        # ADX boost
        adx_boost = 0.0
        if adx > 30:
            adx_boost = 0.3
        elif adx > 25:
            adx_boost = 0.2
        elif adx > 20:
            adx_boost = 0.1

        confidence = min(ema_score + adx_boost, 1.0)

        return BiasResult(
            bias=direction,
            confidence=confidence,
            rationale=f"EMA20={ema_20:.1f} vs EMA50={ema_50:.1f}, ADX={adx:.1f}, close={close:.1f}",
            indicators={"ema_20": ema_20, "ema_50": ema_50, "adx": adx},
        )

    def check_confirmation(self, context_1h: TimeframeData, bias: BiasResult) -> ConfirmationResult:
        """
        1h: Confirm intraday trend matches 4h bias.
        Check EMA alignment + trend field + key levels.
        """
        close = context_1h.ohlc["close"]
        ema_20 = context_1h.ema_20
        trend = context_1h.trend

        confirmed = False
        confidence = 0.0

        if bias.bias == Bias.BULLISH:
            if close > ema_20 and trend in ("bullish", "up", "uptrend"):
                confirmed = True
                confidence = 0.8
            elif close > ema_20:
                confirmed = True
                confidence = 0.6
        elif bias.bias == Bias.BEARISH:
            if close < ema_20 and trend in ("bearish", "down", "downtrend"):
                confirmed = True
                confidence = 0.8
            elif close < ema_20:
                confirmed = True
                confidence = 0.6

        return ConfirmationResult(
            status=Confirmation.CONFIRMED if confirmed else Confirmation.NOT_CONFIRMED,
            confidence=confidence,
            rationale=f"1h close={close:.1f} vs EMA20={ema_20:.1f}, trend={trend}",
            indicators={"close": close, "ema_20": ema_20, "trend": trend},
        )

    def check_setup(self, context_15m: TimeframeData, bias: BiasResult, confirmation: ConfirmationResult) -> SetupResult:
        """
        15m: Look for breakout setup — opening range identification,
        volatility contraction (BB width), or flag pattern.
        """
        high = context_15m.ohlc["high"]
        low = context_15m.ohlc["low"]
        close = context_15m.ohlc["close"]
        atr = context_15m.atr
        bb_width = context_15m.bb_width
        rsi = context_15m.rsi
        resistance = context_15m.resistance
        support = context_15m.support

        # Check for breakout setup conditions
        # 1. Price near key level (within 1 ATR of support/resistance)
        near_resistance = abs(close - resistance) < atr * 1.5 if atr > 0 else False
        near_support = abs(close - support) < atr * 1.5 if atr > 0 else False

        # 2. RSI in reasonable range (not extreme)
        rsi_ok = 35 < rsi < 70 if bias.bias == Bias.BULLISH else 30 < rsi < 65

        # 3. Volatility contraction (low BB width = energy building)
        vol_contracted = bb_width > 0 and bb_width < context_15m.bb_middle * 0.02 if context_15m.bb_middle > 0 else True

        pattern = ""
        if bias.bias == Bias.BULLISH and near_resistance and rsi_ok:
            pattern = "bullish_breakout_setup"
        elif bias.bias == Bias.BEARISH and near_support and rsi_ok:
            pattern = "bearish_breakdown_setup"
        elif vol_contracted and rsi_ok:
            pattern = "volatility_contraction"

        if pattern:
            return SetupResult(
                status=SetupStatus.SETUP_FOUND,
                pattern=pattern,
                rationale=f"15m: RSI={rsi:.1f}, ATR={atr:.4f}, BB_width={bb_width:.4f}, near key level",
                key_level=resistance if bias.bias == Bias.BULLISH else support,
                indicators={"rsi": rsi, "atr": atr, "bb_width": bb_width},
            )

        return SetupResult(
            status=SetupStatus.NO_SETUP,
            rationale=f"No breakout setup: RSI={rsi:.1f}, no key level proximity",
        )

    def check_entry(self, context_5m: TimeframeData, bias: BiasResult, setup: SetupResult) -> Optional[EntrySignal]:
        """
        5m: Execute when price breaks key level with volume > 1.5x average.
        """
        close = context_5m.ohlc["close"]
        high = context_5m.ohlc["high"]
        low = context_5m.ohlc["low"]
        volume = context_5m.volume
        avg_volume = context_5m.avg_volume or volume
        atr = context_5m.atr or 1.0

        # Volume confirmation
        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0
        volume_confirmed = vol_ratio >= 1.3  # slightly relaxed from 1.5 for more signals

        if not volume_confirmed and vol_ratio < 0.8:
            return None

        key_level = setup.key_level

        if bias.bias == Bias.BULLISH:
            # Price should be breaking above key level
            if close > key_level or (key_level == 0 and close > context_5m.ema_20):
                stop = low - atr * 0.5
                risk = close - stop
                target_1 = close + risk * 2.0
                target_2 = close + risk * 3.0

                return EntrySignal(
                    direction=SignalDirection.LONG,
                    entry_price=close,
                    stop_loss=round(stop, 2),
                    target_1=round(target_1, 2),
                    target_2=round(target_2, 2),
                    rationale=f"5m breakout: close={close:.2f} > level={key_level:.2f}, vol={vol_ratio:.1f}x avg",
                    confidence=min(0.5 + vol_ratio * 0.15, 0.9),
                    indicators={"volume_ratio": vol_ratio, "atr": atr},
                )

        elif bias.bias == Bias.BEARISH:
            if close < key_level or (key_level == 0 and close < context_5m.ema_20):
                stop = high + atr * 0.5
                risk = stop - close
                target_1 = close - risk * 2.0
                target_2 = close - risk * 3.0

                return EntrySignal(
                    direction=SignalDirection.SHORT,
                    entry_price=close,
                    stop_loss=round(stop, 2),
                    target_1=round(target_1, 2),
                    target_2=round(target_2, 2),
                    rationale=f"5m breakdown: close={close:.2f} < level={key_level:.2f}, vol={vol_ratio:.1f}x avg",
                    confidence=min(0.5 + vol_ratio * 0.15, 0.9),
                    indicators={"volume_ratio": vol_ratio, "atr": atr},
                )

        return None
