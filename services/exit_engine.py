"""
Unified Exit Engine — ONE engine, used EVERYWHERE.
Backtester ✅ | Paper Trading ✅ | Future Live ✅

NO forks. NO variations. Same config, same logic, same thresholds.

Core behavior:
  5% Profit Trigger + Adaptive Trailing Exit
  When profit hits 5% → activate trailing stop
  Trail gives back max 25% of peak profit before closing

Usage:
    from services.exit_engine import ExitEngine, EXIT_CONFIG

    engine = ExitEngine(EXIT_CONFIG)
    engine.on_entry(price)
    reason = engine.update(current_price)  # returns None or exit reason string
"""

# =============================================================================
# SHARED CONFIG — ONE SOURCE OF TRUTH
# =============================================================================

EXIT_CONFIG = {
    # Profit trigger — activates trailing after target hit
    "use_profit_trigger": True,
    "profit_target": 0.05,            # 5% profit activates trailing

    # Adaptive trailing — only active AFTER target hit
    "use_trailing_after_target": True,
    "trail_after_target_pct": 0.25,   # give back max 25% of peak profit

    # Signal-based exit — strategy's own exit signal still respected
    "use_signal_exit": True,

    # Hard TP — disabled by default, use trailing instead
    "use_hard_tp": False,
    "hard_tp_pct": 0.10,              # 10% hard cap (if enabled)

    # Time exit — disabled by default
    "use_time_exit": False,
    "max_bars": 100,

    # Stop loss — optional floor protection
    "use_stop_loss": False,
    "stop_loss_pct": 0.03,            # 3% stop loss (if enabled)
}


# =============================================================================
# EXIT ENGINE — Single class, no forks
# =============================================================================

class ExitEngine:
    """
    Unified exit engine. Call on_entry() when opening, update() on every bar/tick.
    Returns exit reason string or None.
    """

    def __init__(self, config: dict = None):
        self.config = config or EXIT_CONFIG
        self.reset()

    def reset(self):
        """Reset state for new trade."""
        self.entry_price = None
        self.max_profit = 0.0
        self.max_profit_price = 0.0
        self.target_hit = False
        self.bars_held = 0
        self.direction = 1  # 1=long, -1=short

    def on_entry(self, price: float, direction: int = 1):
        """Call when entering a position."""
        self.reset()
        self.entry_price = price
        self.max_profit_price = price
        self.direction = direction

    def update(self, price: float) -> str | None:
        """
        Call on every bar/tick while in position.
        Returns: None (hold) or exit reason string.
        """
        if self.entry_price is None or self.entry_price <= 0:
            return None

        self.bars_held += 1

        # Compute current profit
        if self.direction == 1:  # long
            current_profit = (price - self.entry_price) / self.entry_price
        else:  # short
            current_profit = (self.entry_price - price) / self.entry_price

        # Track peak profit
        if current_profit > self.max_profit:
            self.max_profit = current_profit
            self.max_profit_price = price

        # --- Exit checks (priority order) ---

        # 1. Stop loss (if enabled)
        if self.config.get("use_stop_loss") and current_profit <= -self.config["stop_loss_pct"]:
            return "stop_loss"

        # 2. Hard TP (if enabled — disabled by default)
        if self.config.get("use_hard_tp") and current_profit >= self.config["hard_tp_pct"]:
            return "hard_tp"

        # 3. Profit trigger — mark target hit
        if self.config.get("use_profit_trigger"):
            if current_profit >= self.config["profit_target"]:
                self.target_hit = True

        # 4. Adaptive trailing AFTER target hit (core logic)
        if self.config.get("use_trailing_after_target") and self.target_hit:
            trail_pct = self.config["trail_after_target_pct"]
            # Exit if profit has given back more than trail_pct of peak
            if self.max_profit > 0 and current_profit < self.max_profit * (1 - trail_pct):
                return "trail_after_target"

        # 5. Time exit (if enabled)
        if self.config.get("use_time_exit") and self.bars_held >= self.config["max_bars"]:
            return "time_exit"

        return None  # hold

    def get_metrics(self, exit_price: float) -> dict:
        """Get exit metrics for logging. Call after exit."""
        if self.entry_price is None or self.entry_price <= 0:
            return {}

        # Cast to Python float to avoid numpy float32 JSON serialization issues
        exit_price = float(exit_price)
        entry = float(self.entry_price)

        if self.direction == 1:
            final_profit = (exit_price - entry) / entry
        else:
            final_profit = (entry - exit_price) / entry

        capture = (final_profit / self.max_profit) if self.max_profit > 0 else 0

        return {
            "entry_price": round(entry, 2),
            "exit_price": round(exit_price, 2),
            "max_profit_pct": round(float(self.max_profit) * 100, 2),
            "final_profit_pct": round(float(final_profit) * 100, 2),
            "profit_capture_pct": round(float(capture) * 100, 1),
            "target_hit": bool(self.target_hit),
            "bars_held": int(self.bars_held),
        }
