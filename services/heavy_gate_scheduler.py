"""
Heavy Gate Scheduler — Prevents CPU spike death from concurrent MC/WF jobs.

Problem: Multiple agents hit Monte Carlo (1000 sims) + Walk-Forward simultaneously,
spiking load from ~8 to 20+ and killing the box.

Solution: File-lock based semaphore limiting concurrent heavy jobs.

Usage:
    from services.heavy_gate_scheduler import heavy_gate
    
    with heavy_gate():
        run_walk_forward()
        run_monte_carlo()
"""

import os
import time
import fcntl
import random
import logging
from pathlib import Path
from contextlib import contextmanager

log = logging.getLogger("heavy_gate")

# ── Config ──────────────────────────────────────────────────────────────────

MAX_HEAVY_JOBS = 2          # max concurrent heavy gates across all agents
LOCK_DIR = Path("/tmp/trading-factory-locks")
WAIT_POLL_INTERVAL = 2.0    # seconds between retry attempts
MAX_WAIT_TIME = 300         # max seconds to wait for a slot (5 min)

# ── Implementation ──────────────────────────────────────────────────────────

def _ensure_lock_dir():
    LOCK_DIR.mkdir(parents=True, exist_ok=True)


def _get_active_count() -> int:
    """Count how many heavy gate slots are currently held."""
    _ensure_lock_dir()
    count = 0
    for i in range(MAX_HEAVY_JOBS):
        lock_path = LOCK_DIR / f"heavy_slot_{i}.lock"
        if not lock_path.exists():
            continue
        try:
            fd = os.open(str(lock_path), os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Got the lock = slot is free
                fcntl.flock(fd, fcntl.LOCK_UN)
            except (IOError, OSError):
                # Can't lock = slot is held
                count += 1
            finally:
                os.close(fd)
        except FileNotFoundError:
            pass
    return count


def _acquire_slot() -> int:
    """Try to acquire a heavy gate slot. Returns slot index or -1."""
    _ensure_lock_dir()
    for i in range(MAX_HEAVY_JOBS):
        lock_path = LOCK_DIR / f"heavy_slot_{i}.lock"
        lock_path.touch(exist_ok=True)
        try:
            fd = os.open(str(lock_path), os.O_RDWR)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Got it — write our PID for debugging
            os.write(fd, f"{os.getpid()}\n".encode())
            return fd  # caller must keep fd open to hold lock
        except (IOError, OSError):
            try:
                os.close(fd)
            except:
                pass
            continue
    return -1


@contextmanager
def heavy_gate(agent_name: str = "unknown"):
    """
    Context manager that limits concurrent heavy gate execution.
    
    Blocks until a slot is available (up to MAX_WAIT_TIME).
    
    Usage:
        with heavy_gate("alpha"):
            result = run_walk_forward(...)
            mc_result = run_monte_carlo(...)
    """
    fd = -1
    waited = 0.0
    
    while fd == -1 and waited < MAX_WAIT_TIME:
        fd = _acquire_slot()
        if fd == -1:
            # Add jitter to prevent thundering herd
            jitter = random.uniform(0.5, WAIT_POLL_INTERVAL)
            log.debug(f"  [{agent_name}] Heavy gate full ({MAX_HEAVY_JOBS}/{MAX_HEAVY_JOBS} slots busy), waiting {jitter:.1f}s...")
            time.sleep(jitter)
            waited += jitter
    
    if fd == -1:
        log.warning(f"  [{agent_name}] Heavy gate timeout after {MAX_WAIT_TIME}s — running anyway (degraded)")
        # Run anyway rather than blocking forever — load spike is better than deadlock
        yield
        return
    
    try:
        log.debug(f"  [{agent_name}] Heavy gate acquired (slot fd={fd})")
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            log.debug(f"  [{agent_name}] Heavy gate released")
        except:
            pass
