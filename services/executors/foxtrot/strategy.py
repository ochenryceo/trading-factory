"""
Foxtrot Agent — Volume / Order Flow Executor

Executes volume profile and order flow strategies: VA boundary reactions,
CVD divergence fades, absorption at key levels, VWAP SD band trades,
naked POC magnet plays.
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


class FoxtrotExecutor(BaseExecutor):
    """Volume/Order Flow — trades institutional footprints and VP levels."""

    AGENT_ID = "foxtrot"
    AGENT_NAME = "Foxtrot — Volume/Order Flow"
    STYLE = "volume_orderflow"

    def check_bias(self, context_4h: TimeframeData) -> BiasResult:
        """
        4h: Volume profile context — note key POC, VAH, VAL from prior sessions.
        Use trend direction as backdrop for which side of order flow to favor.
        """
        close = context_4h.ohlc["close"]
        ema_20 = context_4h.ema_20
        ema_50 = context_4h.ema_50
        poc = context_4h.poc
        vah = context_4h.vah
        val = context_4h.val

        # Determine position relative to value area
        if val > 0 and vah > 0:
            if close > vah:
                direction = Bias.BULLISH
                confidence = 0.6
                rationale_extra = "price above VAH — bullish acceptance"
            elif close < val:
                direction = Bias.BEARISH
                confidence = 0.6
                rationale_extra = "price below VAL — bearish acceptance"
            else:
                # Inside value area — look for reactions at boundaries
                distance_to_vah = vah - close
                distance_to_val = close - val

                if distance_to_val < distance_to_vah:
                    direction = Bias.BULLISH  # near VAL, expect bounce
                    confidence = 0.5
                    rationale_extra = "near VAL — potential support"
                else:
                    direction = Bias.BEARISH  # near VAH, expect rejection
                    confidence = 0.5
                    rationale_extra = "near VAH — potential resistance"
        else:
            # No VP data — fall back to EMA trend
            if close > ema_20 > ema_50:
                direction = Bias.BULLISH
                confidence = 0.5
                rationale_extra = "EMA trend up (no VP data)"
            elif close < ema_20 < ema_50:
                direction = Bias.BEARISH
                confidence = 0.5
                rationale_extra = "EMA trend down (no VP data)"
            else:
                direction = Bias.NEUTRAL
                confidence = 0.4
                rationale_extra = "no clear direction"

        return BiasResult(
            bias=direction,
            confidence=confidence,
            rationale=f"VP: POC={poc:.1f}, VAH={vah:.1f}, VAL={val:.1f}, close={close:.1f} — {rationale_extra}",
            indicators={"poc": poc, "vah": vah, "val": val},
        )

    def check_confirmation(self, context_1h: TimeframeData, bias: BiasResult) -> ConfirmationResult:
        """
        1h: Map current session VP. Confirm key levels exist.
        Check CVD direction for order flow alignment.
        """
        close = context_1h.ohlc["close"]
        vwap = context_1h.vwap
        cvd = context_1h.cvd
        delta = context_1h.delta
        poc = context_1h.poc
        vah = context_1h.vah
        val = context_1h.val
        atr = context_1h.atr or 1.0

        # Check if we're near a VP level worth trading
        near_vah = abs(close - vah) < atr * 1.5 if vah > 0 else False
        near_val = abs(close - val) < atr * 1.5 if val > 0 else False
        near_poc = abs(close - poc) < atr * 1.5 if poc > 0 else False
        near_vwap = abs(close - vwap) < atr * 1.0

        near_level = near_vah or near_val or near_poc or near_vwap

        # CVD alignment
        cvd_aligned = False
        if bias.bias == Bias.BULLISH and cvd > 0:
            cvd_aligned = True
        elif bias.bias == Bias.BEARISH and cvd < 0:
            cvd_aligned = True

        confirmed = near_level
        confidence = 0.0
        if near_level and cvd_aligned:
            confidence = 0.8
        elif near_level:
            confidence = 0.6
        elif cvd_aligned:
            confidence = 0.4

        return ConfirmationResult(
            status=Confirmation.CONFIRMED if confirmed else Confirmation.NOT_CONFIRMED,
            confidence=confidence,
            rationale=(
                f"1h VP: POC={poc:.1f}, VWAP={vwap:.1f}, CVD={cvd:.0f}, "
                f"near_level={near_level}, cvd_aligned={cvd_aligned}"
            ),
            indicators={"vwap": vwap, "cvd": cvd, "delta": delta, "near_level": near_level},
        )

    def check_setup(self, context_15m: TimeframeData, bias: BiasResult, confirmation: ConfirmationResult) -> SetupResult:
        """
        15m: Detect order flow signals — absorption, delta shift,
        volume anomaly at key level.
        """
        close = context_15m.ohlc["close"]
        high = context_15m.ohlc["high"]
        low = context_15m.ohlc["low"]
        volume = context_15m.volume
        avg_volume = context_15m.avg_volume or volume
        delta = context_15m.delta
        cvd = context_15m.cvd
        atr = context_15m.atr or 1.0

        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0
        range_size = high - low

        pattern = ""

        # Absorption: high volume but small range (passive orders absorbing)
        if vol_ratio > 1.5 and range_size < atr * 0.5:
            if bias.bias == Bias.BULLISH:
                pattern = "absorption_at_support"
            elif bias.bias == Bias.BEARISH:
                pattern = "absorption_at_resistance"
            else:
                pattern = "absorption_detected"

        # CVD divergence: price making new extreme but CVD not confirming
        elif bias.bias == Bias.BEARISH and delta > 0 and vol_ratio > 1.0:
            pattern = "cvd_divergence_bullish"  # hidden buying
        elif bias.bias == Bias.BULLISH and delta < 0 and vol_ratio > 1.0:
            pattern = "cvd_divergence_bearish"  # hidden selling

        # Volume spike at level
        elif vol_ratio > 2.0:
            if close > context_15m.ohlc["open"]:
                pattern = "volume_spike_bullish"
            else:
                pattern = "volume_spike_bearish"

        if pattern:
            return SetupResult(
                status=SetupStatus.SETUP_FOUND,
                pattern=pattern,
                rationale=(
                    f"15m order flow: {pattern}, vol={vol_ratio:.1f}x, "
                    f"delta={delta:.0f}, range={range_size:.2f}"
                ),
                key_level=close,
                indicators={"vol_ratio": vol_ratio, "delta": delta, "cvd": cvd},
            )

        return SetupResult(
            status=SetupStatus.NO_SETUP,
            rationale=f"No order flow signal: vol={vol_ratio:.1f}x, delta={delta:.0f}",
        )

    def check_entry(self, context_5m: TimeframeData, bias: BiasResult, setup: SetupResult) -> Optional[EntrySignal]:
        """
        5m: Enter on delta confirmation at key level.
        Tight stops — if order flow thesis is wrong, exit fast.
        """
        close = context_5m.ohlc["close"]
        open_ = context_5m.ohlc["open"]
        high = context_5m.ohlc["high"]
        low = context_5m.ohlc["low"]
        atr = context_5m.atr or 1.0
        delta = context_5m.delta

        # Bullish entries
        if "bullish" in setup.pattern or "support" in setup.pattern:
            # Delta should be positive or at least not strongly negative
            if delta >= 0 or close > open_:
                stop = low - atr * 0.5
                risk = close - stop
                target_1 = close + risk * 1.5
                target_2 = close + risk * 2.0

                return EntrySignal(
                    direction=SignalDirection.LONG,
                    entry_price=close,
                    stop_loss=round(stop, 2),
                    target_1=round(target_1, 2),
                    target_2=round(target_2, 2),
                    rationale=f"5m OF entry long: delta={delta:.0f}, pattern={setup.pattern}",
                    confidence=0.65,
                    indicators={"delta": delta, "atr": atr},
                )

        # Bearish entries
        if "bearish" in setup.pattern or "resistance" in setup.pattern:
            if delta <= 0 or close < open_:
                stop = high + atr * 0.5
                risk = stop - close
                target_1 = close - risk * 1.5
                target_2 = close - risk * 2.0

                return EntrySignal(
                    direction=SignalDirection.SHORT,
                    entry_price=close,
                    stop_loss=round(stop, 2),
                    target_1=round(target_1, 2),
                    target_2=round(target_2, 2),
                    rationale=f"5m OF entry short: delta={delta:.0f}, pattern={setup.pattern}",
                    confidence=0.65,
                    indicators={"delta": delta, "atr": atr},
                )

        return None
