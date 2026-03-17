"""Shared config for razer-effect daemon and GUI."""

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "razer-effect"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "effect": "random_fade",
    "fade_duration": 2.0,
    "fade_fps": 24,
    "brightness": 75,
    "hold_min": 1.0,
    "hold_max": 4.0,
    "running": True,
}


def load_config():
    """Load config from disk, merging with defaults for missing keys.

    Returns:
        Config dict with all keys guaranteed present.
    """
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULTS)
    merged = {**DEFAULTS, **cfg}
    return _validate(merged)


def _validate(cfg):
    """Clamp config values to safe ranges.

    Args:
        cfg: Config dict.

    Returns:
        Config dict with values clamped to valid ranges.
    """
    cfg["fade_duration"] = max(0.1, float(cfg["fade_duration"]))
    cfg["fade_fps"] = max(1, min(60, int(cfg["fade_fps"])))
    cfg["hold_min"] = max(0.1, float(cfg["hold_min"]))
    cfg["hold_max"] = max(cfg["hold_min"], float(cfg["hold_max"]))
    if cfg["brightness"] is not None:
        cfg["brightness"] = max(0, min(100, int(cfg["brightness"])))
    return cfg


def save_config(cfg):
    """Atomically write config to disk.

    Args:
        cfg: Config dict to save.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def ensure_config():
    """Create config file with defaults if it doesn't exist.

    Returns:
        Current config dict.
    """
    if not CONFIG_PATH.exists():
        save_config(DEFAULTS)
        return dict(DEFAULTS)
    return load_config()
