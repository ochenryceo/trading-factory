#!/usr/bin/env python3
"""
TradingView Webhook Receiver — Auto-sync paper trades

Receives webhook POSTs from TradingView alerts, logs trades to the
production monitor, updates the dashboard, and posts to Discord.

Integrates unified ExitEngine for profit protection on all paper trades.

Run: uvicorn services.webhook_receiver:app --host 0.0.0.0 --port 8088
"""

import json
import logging
import hashlib
import hmac
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel

# Ensure project root is on path for exit_engine import
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.exit_engine import ExitEngine, EXIT_CONFIG

log = logging.getLogger("webhook_receiver")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

PROJECT = Path(__file__).resolve().parents[1]
PAPER_TRADES_PATH = PROJECT / "data" / "production" / "paper_trades.jsonl"
WEBHOOK_LOG_PATH = PROJECT / "data" / "production" / "webhook_log.jsonl"

# Simple auth token — TradingView will send this in the payload
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change_me")

app = FastAPI(title="Trading Factory Webhook Receiver")

# ── Exit Engine — Per-strategy position tracking ───────────────────────────
# One ExitEngine instance per open position, keyed by strategy name
_active_exits: dict[str, ExitEngine] = {}
EXIT_LOG_PATH = PROJECT / "data" / "paper_trading" / "exit_engine_log.jsonl"


def _log_exit_event(event: dict):
    """Log exit engine events for audit trail."""
    EXIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    event["logged_at"] = datetime.now(timezone.utc).isoformat()
    with open(EXIT_LOG_PATH, "a") as f:
        f.write(json.dumps(event, default=str) + "\n")


# ── Models ─────────────────────────────────────────────────────────────────

class TradingViewAlert(BaseModel):
    """Expected payload from TradingView webhook."""
    strategy: str = ""
    action: str = ""         # "buy" / "sell" / "close"
    ticker: str = ""
    price: float = 0.0
    time: str = ""
    interval: str = ""
    volume: float = 0.0
    # Auth
    secret: str = ""
    # Optional fields
    position_size: float = 0.0
    order_id: str = ""
    comment: str = ""


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/")
async def health():
    return {"status": "ok", "service": "webhook_receiver", "version": "1.0"}


@app.get("/health")
async def health_check():
    """Health check for monitoring."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trades_logged": _count_trades(),
    }


@app.post("/webhook/tradingview")
async def receive_tradingview(request: Request):
    """
    Receive TradingView webhook alert.
    
    TradingView sends POST with JSON body.
    We validate, log, and forward to dashboard + Discord.
    """
    try:
        body = await request.json()
    except:
        raw = await request.body()
        try:
            body = json.loads(raw)
        except:
            raise HTTPException(400, "Invalid JSON payload")
    
    log.info(f"📥 Webhook received: {json.dumps(body, default=str)[:500]}")
    
    # Validate secret
    secret = body.get("secret", "")
    if secret != WEBHOOK_SECRET:
        log.warning(f"❌ Invalid secret: {secret}")
        raise HTTPException(403, "Invalid secret")
    
    # Parse alert
    action = body.get("action", "").lower()
    ticker = body.get("ticker", body.get("symbol", "NQ"))
    price = float(body.get("price", body.get("close", 0)))
    timestamp = body.get("time", datetime.now(timezone.utc).isoformat())
    strategy = body.get("strategy", "LOCKED_PRODUCTION_V1")
    comment = body.get("comment", "")
    interval = body.get("interval", "1D")
    
    # Build trade record
    trade = {
        "strategy_code": strategy,
        "action": action,
        "ticker": ticker,
        "price": price,
        "timestamp": timestamp,
        "interval": interval,
        "comment": comment,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "source": "tradingview_webhook",
    }
    
    # Determine trade type
    if action in ("buy", "long", "entry_long"):
        trade["direction"] = "LONG"
        trade["type"] = "ENTRY"
        log.info(f"🟢 LONG ENTRY: {ticker} @ {price} — {strategy}")
    elif action in ("sell", "short", "entry_short"):
        trade["direction"] = "SHORT"
        trade["type"] = "ENTRY"
        log.info(f"🔴 SHORT ENTRY: {ticker} @ {price} — {strategy}")
    elif action in ("close", "exit", "close_long", "close_short"):
        trade["type"] = "EXIT"
        log.info(f"⬜ EXIT: {ticker} @ {price} — {strategy} ({comment})")
    else:
        trade["type"] = "UNKNOWN"
        log.warning(f"⚠️ Unknown action: {action}")
    
    # Persist trade
    _log_trade(trade)
    
    # Log raw webhook
    _log_webhook(body)
    
    return {
        "status": "ok",
        "trade": trade,
        "message": f"Trade logged: {action} {ticker} @ {price}"
    }


# ── Persistence ────────────────────────────────────────────────────────────

def _log_trade(trade: dict):
    """Append trade to paper trades log."""
    PAPER_TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PAPER_TRADES_PATH, "a") as f:
        f.write(json.dumps(trade, default=str) + "\n")


def _log_webhook(payload: dict):
    """Log raw webhook payload."""
    WEBHOOK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    with open(WEBHOOK_LOG_PATH, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _count_trades() -> int:
    """Count logged trades."""
    if not PAPER_TRADES_PATH.exists():
        return 0
    with open(PAPER_TRADES_PATH) as f:
        return sum(1 for _ in f)


# ── Get trades (for dashboard) ────────────────────────────────────────────

@app.get("/trades")
async def get_trades(strategy: Optional[str] = None, limit: int = 50):
    """Get paper trades for dashboard display."""
    trades = []
    if PAPER_TRADES_PATH.exists():
        with open(PAPER_TRADES_PATH) as f:
            for line in f:
                try:
                    t = json.loads(line.strip())
                    if strategy is None or t.get("strategy_code") == strategy:
                        trades.append(t)
                except:
                    continue
    
    return {"trades": trades[-limit:], "total": len(trades)}


@app.get("/trades/summary")
async def trades_summary():
    """Summary stats for dashboard."""
    trades = []
    if PAPER_TRADES_PATH.exists():
        with open(PAPER_TRADES_PATH) as f:
            for line in f:
                try:
                    trades.append(json.loads(line.strip()))
                except:
                    continue
    
    entries = [t for t in trades if t.get("type") == "ENTRY"]
    exits = [t for t in trades if t.get("type") == "EXIT"]
    
    return {
        "total_signals": len(trades),
        "entries": len(entries),
        "exits": len(exits),
        "last_trade": trades[-1] if trades else None,
        "strategies": list(set(t.get("strategy_code", "") for t in trades)),
    }


# ── NinjaTrader Auto-Sync ──────────────────────────────────────────────────

NINJA_TRADES_PATH = PROJECT / "data" / "paper_trading" / "trades.json"
NINJA_SECRET = os.getenv("NINJA_SECRET", "change_me")


class NinjaTradePayload(BaseModel):
    secret: str
    strategy: str
    instrument: str
    direction: str  # "Long" or "Short"
    entry_price: float
    exit_price: float = 0
    quantity: int = 1
    pnl: float = 0
    action: str = "entry"  # "entry" or "exit"
    timestamp: str = ""
    order_id: str = ""


def _get_session(hour: int) -> str:
    """Determine trading session from UTC hour."""
    if 0 <= hour < 8:
        return "Asia"
    elif 8 <= hour < 13:
        return "London"
    else:
        return "NY"


def _load_ninja_trades():
    """Load existing trades."""
    if NINJA_TRADES_PATH.exists():
        try:
            with open(NINJA_TRADES_PATH) as f:
                return json.load(f)
        except:
            return []
    return []


def _save_ninja_trades(trades):
    """Save trades."""
    NINJA_TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(NINJA_TRADES_PATH, "w") as f:
        json.dump(trades, f, indent=2, default=str)


@app.post("/ninja/trade")
async def ninja_trade(payload: NinjaTradePayload):
    """Receive trade from NinjaTrader addon."""
    if payload.secret != NINJA_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    ts = payload.timestamp or datetime.now(timezone.utc).isoformat()
    hour = int(ts[11:13]) if len(ts) > 13 else 12

    trade = {
        "id": f"NT-{payload.strategy}-{payload.order_id or int(datetime.now(timezone.utc).timestamp())}",
        "system": payload.strategy,
        "instrument": payload.instrument,
        "direction": payload.direction,
        "entry_price": payload.entry_price,
        "exit_price": payload.exit_price,
        "pnl_dollars": payload.pnl,
        "quantity": payload.quantity,
        "action": payload.action,
        "timestamp": ts,
        "session": _get_session(hour),
        "day_of_week": datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%A") if ts else "",
        "source": "ninjatrader",
    }

    # ── Exit Engine Integration ──────────────────────────────────────
    exit_info = {}
    strat_key = payload.strategy

    if payload.action == "entry":
        # Start tracking this position with exit engine
        direction = 1 if payload.direction.lower() == "long" else -1
        engine = ExitEngine(EXIT_CONFIG)
        engine.on_entry(payload.entry_price, direction=direction)
        _active_exits[strat_key] = engine
        exit_info = {"exit_engine": "activated", "entry_price": payload.entry_price}
        log.info(f"🛡️ Exit engine activated for {strat_key} @ {payload.entry_price}")
        _log_exit_event({
            "event": "engine_activated",
            "strategy": strat_key,
            "direction": payload.direction,
            "entry_price": payload.entry_price,
        })

    elif payload.action == "exit":
        # Get exit engine metrics before closing
        if strat_key in _active_exits:
            engine = _active_exits[strat_key]
            exit_info = engine.get_metrics(payload.exit_price)
            exit_info["exit_engine"] = "closed"
            _log_exit_event({
                "event": "engine_closed",
                "strategy": strat_key,
                "exit_price": payload.exit_price,
                "metrics": exit_info,
            })
            del _active_exits[strat_key]
            log.info(f"🛡️ Exit engine closed for {strat_key}: capture={exit_info.get('profit_capture_pct', 0)}%")

    trade["exit_engine"] = exit_info
    # ── End Exit Engine ────────────────────────────────────────────

    trades = _load_ninja_trades()
    trades.append(trade)
    _save_ninja_trades(trades)

    log.info(f"NT TRADE: {payload.strategy} {payload.action} {payload.direction} {payload.instrument} @ {payload.entry_price} PnL={payload.pnl}")

    # Fire central alert for first live trade
    try:
        from services.central_alerts import alert_live_trade
        alert_live_trade(payload.strategy, payload.direction, payload.entry_price, payload.action)
    except Exception:
        pass

    return {"status": "ok", "trade_id": trade["id"], "exit_engine": exit_info}


class NinjaPriceUpdate(BaseModel):
    secret: str
    strategy: str
    instrument: str
    price: float
    timestamp: str = ""


@app.post("/ninja/price_update")
async def ninja_price_update(payload: NinjaPriceUpdate):
    """
    Receive price update from NinjaTrader on each bar close.
    Exit engine checks if profit protection should trigger.
    Returns exit signal if trailing stop hit.
    """
    if payload.secret != NINJA_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    strat_key = payload.strategy
    if strat_key not in _active_exits:
        return {"status": "ok", "action": "none", "reason": "no_active_position"}

    engine = _active_exits[strat_key]
    exit_reason = engine.update(payload.price)

    if exit_reason:
        # Exit engine says close the trade
        metrics = engine.get_metrics(payload.price)
        log.info(
            f"🚨 EXIT ENGINE TRIGGER: {strat_key} @ {payload.price} | "
            f"reason={exit_reason} | capture={metrics.get('profit_capture_pct', 0)}%"
        )
        _log_exit_event({
            "event": "exit_triggered",
            "strategy": strat_key,
            "price": payload.price,
            "reason": exit_reason,
            "metrics": metrics,
        })
        # Don't remove from _active_exits yet — wait for the actual exit trade to confirm
        return {
            "status": "exit",
            "action": "close",
            "reason": exit_reason,
            "price": payload.price,
            "metrics": metrics,
        }

    # No exit — report current state
    current_profit = (payload.price - engine.entry_price) / engine.entry_price
    if engine.direction == -1:
        current_profit = (engine.entry_price - payload.price) / engine.entry_price

    return {
        "status": "ok",
        "action": "hold",
        "current_profit_pct": round(current_profit * 100, 2),
        "max_profit_pct": round(engine.max_profit * 100, 2),
        "target_hit": engine.target_hit,
    }


@app.get("/ninja/exit_status")
async def ninja_exit_status():
    """Check active exit engine positions."""
    positions = {}
    for strat, engine in _active_exits.items():
        positions[strat] = {
            "entry_price": engine.entry_price,
            "max_profit_pct": round(engine.max_profit * 100, 2),
            "target_hit": engine.target_hit,
            "bars_held": engine.bars_held,
            "direction": "long" if engine.direction == 1 else "short",
        }
    return {"active_positions": positions, "count": len(positions)}


# ── Signal Queue — External signal engine → NinjaTrader executor ────────────

SIGNAL_QUEUE_PATH = PROJECT / "data" / "paper_trading" / "signal_queue.json"
SIGNAL_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)

def _load_signal_queue() -> list:
    if SIGNAL_QUEUE_PATH.exists():
        try:
            return json.load(open(SIGNAL_QUEUE_PATH))
        except:
            return []
    return []

def _save_signal_queue(queue: list):
    with open(SIGNAL_QUEUE_PATH, "w") as f:
        json.dump(queue, f, indent=2, default=str)


# ── Kill Switch ─────────────────────────────────────────────────────────────

KILL_SWITCH_PATH = PROJECT / "data" / "paper_trading" / "kill_switch.json"

def _is_system_disabled() -> bool:
    if KILL_SWITCH_PATH.exists():
        try:
            ks = json.load(open(KILL_SWITCH_PATH))
            return ks.get("disabled", False)
        except:
            pass
    return False


@app.post("/signals/kill")
async def toggle_kill_switch(request: Request):
    """Enable/disable kill switch. When disabled=true, all signals are rejected."""
    body = await request.json()
    if body.get("secret", "") != NINJA_SECRET:
        raise HTTPException(403, "Invalid secret")
    
    disabled = body.get("disabled", True)
    with open(KILL_SWITCH_PATH, "w") as f:
        json.dump({"disabled": disabled, "toggled_at": datetime.now(timezone.utc).isoformat()}, f)
    
    state = "DISABLED" if disabled else "ENABLED"
    log.warning(f"🚨 Kill switch {state}")
    return {"status": "ok", "system_disabled": disabled}


@app.get("/signals/kill")
async def kill_switch_status():
    """Check kill switch state."""
    return {"disabled": _is_system_disabled()}


# ── Instrument Mapping ─────────────────────────────────────────────────────

INSTRUMENT_MAP = {
    "NQ": "NQ 06-26",
    "GC": "GC 06-26",
    "CL": "CL 05-26",
}

def _map_instrument(symbol: str) -> str:
    """Map generic symbol to NinjaTrader contract."""
    return INSTRUMENT_MAP.get(symbol.upper(), symbol)


# ── Idempotency + Dedup ───────────────────────────────────────────────────

_seen_signal_ids: set = set()
SIGNAL_LOG_PATH = PROJECT / "data" / "paper_trading" / "signal_log.jsonl"

def _log_signal(signal: dict, status: str, reason: str = ""):
    """Append every signal to audit log."""
    SIGNAL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {**signal, "log_status": status, "reason": reason, "logged_at": datetime.now(timezone.utc).isoformat()}
    with open(SIGNAL_LOG_PATH, "a") as f:
        f.write(json.dumps(entry, separators=(",", ":"), default=str) + "\n")


# ── Active positions tracking (for safety checks) ─────────────────────────

_signal_positions: dict = {}  # {strategy: "LONG"|"SHORT"|"FLAT"}


@app.post("/signals/submit")
async def submit_signal(request: Request):
    """
    Submit a trading signal from the backtester/signal engine.
    NinjaTrader PaperExecutor polls /signals/pending and executes these.
    
    Required fields: secret, strategy, action, instrument
    Valid actions: BUY, SELL, EXIT, FLAT
    """
    body = await request.json()
    
    # Auth
    secret = body.get("secret", "")
    if secret != NINJA_SECRET:
        raise HTTPException(403, "Invalid secret")
    
    # Kill switch
    if _is_system_disabled():
        _log_signal(body, "REJECTED", "kill_switch_active")
        return {"status": "rejected", "reason": "System disabled via kill switch"}
    
    # Required field validation
    required = ["strategy", "action", "instrument"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        _log_signal(body, "REJECTED", f"missing_fields: {missing}")
        raise HTTPException(400, f"Missing required fields: {missing}")
    
    action = body.get("action", "").upper()
    valid_actions = {"BUY", "SELL", "EXIT", "FLAT", "CLOSE"}
    if action not in valid_actions:
        _log_signal(body, "REJECTED", f"invalid_action: {action}")
        raise HTTPException(400, f"Invalid action: {action}. Must be one of {valid_actions}")
    
    strategy = body.get("strategy", "")
    instrument = body.get("instrument", "").upper()
    
    # Idempotency — reject duplicate signal IDs
    client_id = body.get("signal_id", "")
    if client_id and client_id in _seen_signal_ids:
        _log_signal(body, "DUPLICATE", f"signal_id already seen: {client_id}")
        return {"status": "duplicate", "reason": f"Signal {client_id} already processed"}
    
    # Position safety check
    current_pos = _signal_positions.get(strategy, "FLAT")
    if action == "BUY" and current_pos == "LONG":
        _log_signal(body, "SKIPPED", "already_long")
        return {"status": "skipped", "reason": f"{strategy} already LONG"}
    if action == "SELL" and current_pos == "SHORT":
        _log_signal(body, "SKIPPED", "already_short")
        return {"status": "skipped", "reason": f"{strategy} already SHORT"}
    if action in ("EXIT", "FLAT", "CLOSE") and current_pos == "FLAT":
        _log_signal(body, "SKIPPED", "already_flat")
        return {"status": "skipped", "reason": f"{strategy} already FLAT"}
    
    # Build signal
    signal_id = client_id or f"SIG-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    
    signal = {
        "id": signal_id,
        "strategy": strategy,
        "action": action,
        "instrument": instrument,
        "nt_instrument": _map_instrument(instrument),
        "price": body.get("price", 0),
        "quantity": max(body.get("quantity", 1), 1),
        "timestamp": body.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    
    # Track position state
    if action == "BUY":
        _signal_positions[strategy] = "LONG"
    elif action == "SELL":
        _signal_positions[strategy] = "SHORT"
    elif action in ("EXIT", "FLAT", "CLOSE"):
        _signal_positions[strategy] = "FLAT"
    
    # Track for idempotency
    _seen_signal_ids.add(signal_id)
    
    # Queue it
    queue = _load_signal_queue()
    queue.append(signal)
    _save_signal_queue(queue)
    
    # Log
    _log_signal(signal, "QUEUED")
    log.info(f"📤 Signal queued: {signal['action']} {signal['instrument']} ({signal['nt_instrument']}) for {signal['strategy']} (id={signal_id})")
    
    return {"status": "ok", "signal_id": signal_id, "nt_instrument": signal["nt_instrument"]}


@app.get("/signals/pending")
async def get_pending_signals(secret: str = ""):
    """
    Get pending signals for NinjaTrader PaperExecutor to poll.
    Returns only signals with status=pending.
    """
    if secret != NINJA_SECRET:
        raise HTTPException(403, "Invalid secret")
    
    queue = _load_signal_queue()
    pending = [s for s in queue if s.get("status") == "pending"]
    
    return {"signals": pending}


@app.post("/signals/ack")
async def ack_signal(request: Request):
    """
    Acknowledge a signal as received/executed by NinjaTrader.
    Removes it from the pending queue.
    """
    body = await request.json()
    
    secret = body.get("secret", "")
    if secret != NINJA_SECRET:
        raise HTTPException(403, "Invalid secret")
    
    signal_id = body.get("signal_id", "")
    
    queue = _load_signal_queue()
    for s in queue:
        if s.get("id") == signal_id:
            s["status"] = "acknowledged"
            s["acked_at"] = datetime.now(timezone.utc).isoformat()
    _save_signal_queue(queue)
    
    log.info(f"✅ Signal acknowledged: {signal_id}")
    
    return {"status": "ok", "signal_id": signal_id}


@app.get("/signals/status")
async def signal_queue_status():
    """Get signal queue status."""
    queue = _load_signal_queue()
    pending = [s for s in queue if s.get("status") == "pending"]
    acked = [s for s in queue if s.get("status") == "acknowledged"]
    return {
        "total": len(queue),
        "pending": len(pending),
        "acknowledged": len(acked),
        "signals": queue[-10:],
    }


@app.get("/ninja/status")
async def ninja_status():
    """Check NinjaTrader sync status."""
    trades = _load_ninja_trades()
    return {
        "status": "ok",
        "total_trades": len(trades),
        "last_trade": trades[-1] if trades else None,
    }
