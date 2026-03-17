"""Shared config for razer-effect daemon and GUI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "razer-effect"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS: dict[str, Any] = {
    "effect": "key_shuffle",
    "fps": 24,
    "brightness": 75,
    "running": True,
}


def _effect_defaults(effect_name: str) -> dict[str, Any]:
    """Get default values for the given effect's parameters.

    Args:
        effect_name: Effect registry key.

    Returns:
        Dict of parameter defaults, empty if effect is unknown.
    """
    from razer_effect.effects import EFFECTS

    effect_cls = EFFECTS.get(effect_name)
    if effect_cls is None:
        return {}
    return {name: schema["default"] for name, schema in effect_cls.PARAMS.items()}


def load_config() -> dict[str, Any]:
    """Load config from disk, merging with defaults for missing keys.

    Returns:
        Config dict with all keys guaranteed present.
    """
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return _build_defaults()

    merged = {**_build_defaults(), **cfg}
    return _validate(merged)


def _build_defaults() -> dict[str, Any]:
    """Build complete defaults including active effect parameters.

    Returns:
        Full default config dict.
    """
    effect_name = DEFAULTS["effect"]
    return {**DEFAULTS, **_effect_defaults(effect_name)}


def _validate(cfg: dict[str, Any]) -> dict[str, Any]:
    """Validate and clamp config values using global rules and effect PARAMS.

    Args:
        cfg: Config dict.

    Returns:
        Config dict with values clamped to valid ranges.
    """
    cfg["fps"] = max(1, min(60, int(cfg["fps"])))
    if cfg.get("brightness") is not None:
        cfg["brightness"] = max(0, min(100, int(cfg["brightness"])))

    from razer_effect.effects import EFFECTS

    effect_cls = EFFECTS.get(cfg.get("effect", "key_shuffle"))
    if effect_cls is None:
        return cfg

    for name, schema in effect_cls.PARAMS.items():
        if name in cfg:
            val = float(cfg[name])
            cfg[name] = max(schema["min"], min(schema["max"], val))

    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    """Atomically write config to disk.

    Args:
        cfg: Config dict to save.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def ensure_config() -> dict[str, Any]:
    """Create config file with defaults if it doesn't exist.

    Returns:
        Current config dict.
    """
    if not CONFIG_PATH.exists():
        defaults = _build_defaults()
        save_config(defaults)
        return defaults
    return load_config()
