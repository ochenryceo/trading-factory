import os
"""
Databento API Key Rotation — Auto-switches when credits are low.

Usage:
    from services.feed.key_rotation import get_client

    client = get_client()  # returns a databento.Historical with the best available key
"""

import json
import logging
from pathlib import Path
from typing import Optional

import databento as db

log = logging.getLogger("key_rotation")

KEYS_PATH = Path(__file__).parent / "api_keys.json"

_current_index = 0


def _load_keys():
    """Load API keys from config."""
    if not KEYS_PATH.exists():
        return []
    with open(KEYS_PATH) as f:
        data = json.load(f)
    return [k for k in data.get("databento", []) if k.get("active", True)]


def get_client() -> db.Historical:
    """
    Get a Databento client, rotating keys if one fails.
    Tries current key first, rotates to next on auth/credit failure.
    """
    global _current_index
    keys = _load_keys()
    
    if not keys:
        # Fallback to env/hardcoded
        return db.Historical(key=os.getenv("DATABENTO_API_KEY", ""))
    
    # Try current key first, then rotate
    for attempt in range(len(keys)):
        idx = (_current_index + attempt) % len(keys)
        key_entry = keys[idx]
        key = key_entry["key"]
        label = key_entry.get("label", f"key_{idx}")
        
        try:
            client = db.Historical(key=key)
            # Quick validation — try a cheap metadata call
            client.metadata.list_datasets()
            _current_index = idx
            log.debug(f"Using Databento key: {label}")
            return client
        except Exception as e:
            err = str(e).lower()
            if "credit" in err or "unauthorized" in err or "403" in err or "402" in err:
                log.warning(f"Key '{label}' exhausted or unauthorized, rotating...")
                continue
            else:
                # Non-credit error — key is probably fine, just a transient issue
                _current_index = idx
                return db.Historical(key=key)
    
    # All keys failed — return last one anyway
    log.error("All Databento keys failed rotation — using last key")
    return db.Historical(key=keys[-1]["key"])


def get_all_keys():
    """Return all active keys (for balance checking)."""
    return _load_keys()
