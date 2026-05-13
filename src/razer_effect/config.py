"""Shared config for razer-effect daemon and GUI."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when the loaded config violates the v2 schema invariants.

    Inherits from ValueError so existing handlers that catch ValueError
    keep working; new code can catch the narrower ConfigError.
    """


CONFIG_DIR = Path.home() / ".config" / "razer-effect"
CONFIG_PATH = CONFIG_DIR / "config.json"

SCHEMA_VERSION = 2
DEFAULT_PROFILE_NAME = "default"
MAX_LAYERS = 4
DEFAULT_PLUGIN_DIR = CONFIG_DIR / "effects"

GLOBAL_DEFAULTS: dict[str, Any] = {
    "version": SCHEMA_VERSION,
    "fps": 24,
    "brightness": 75,
    "running": True,
    "active_profile": DEFAULT_PROFILE_NAME,
    "hotkey": None,
    "device_overrides": {},
    "plugin_paths": [str(DEFAULT_PLUGIN_DIR)],
}

DEFAULTS: dict[str, Any] = GLOBAL_DEFAULTS
"""Deprecated legacy alias for GLOBAL_DEFAULTS; retained for transitional callers."""


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


def _default_profile() -> dict[str, Any]:
    """Build the default profile structure with one enabled layer.

    Returns:
        A profile dict with a single key_shuffle layer at full opacity and
        the matching effect parameter defaults.
    """
    return {
        "layers": [{"effect": "key_shuffle", "opacity": 1.0, "enabled": True}],
        "effect_params": _effect_defaults("key_shuffle"),
    }


def _build_defaults() -> dict[str, Any]:
    """Build complete v2 defaults with the default profile populated.

    Returns:
        Full default config dict including a single 'default' profile.
    """
    cfg = dict(GLOBAL_DEFAULTS)
    cfg["plugin_paths"] = [str(DEFAULT_PLUGIN_DIR)]
    cfg["device_overrides"] = {}
    cfg["profiles"] = {DEFAULT_PROFILE_NAME: _default_profile()}
    return cfg


def _is_v1(cfg: dict[str, Any]) -> bool:
    """Detect a v1 flat config (no `version`, top-level `effect` key).

    Args:
        cfg: Raw config dict loaded from disk.

    Returns:
        True when the dict matches the v1 flat schema.
    """
    return cfg.get("version") != SCHEMA_VERSION and "effect" in cfg


def _migrate_v1_to_v2(cfg: dict[str, Any]) -> dict[str, Any]:
    """Convert a v1 flat config to v2 layered structure.

    Args:
        cfg: v1 config dict with flat top-level effect/params keys.

    Returns:
        A v2 config dict with the v1 effect wrapped as the single default
        profile layer and the v1 params copied into effect_params.
    """
    v1_effect = cfg.get("effect", "key_shuffle")
    v1_params = {
        k: v
        for k, v in cfg.items()
        if k not in {"effect", "fps", "brightness", "running"}
    }

    migrated = dict(GLOBAL_DEFAULTS)
    migrated["plugin_paths"] = [str(DEFAULT_PLUGIN_DIR)]
    migrated["device_overrides"] = {}
    migrated["profiles"] = {
        DEFAULT_PROFILE_NAME: {
            "layers": [{"effect": v1_effect, "opacity": 1.0, "enabled": True}],
            "effect_params": v1_params,
        }
    }
    for k in ("fps", "brightness", "running"):
        if k in cfg:
            migrated[k] = cfg[k]
    return migrated


def _validate_layer(layer: Any, profile_name: str, index: int) -> dict[str, Any]:
    """Validate and normalize a single layer dict.

    Args:
        layer: Candidate layer value.
        profile_name: Name of the owning profile, used for error messages.
        index: Layer index within the profile, used for error messages.

    Returns:
        Normalized layer dict with clamped opacity and bool enabled flag.

    Raises:
        ConfigError: When the layer is not a dict or `effect` is missing/empty.
    """
    if not isinstance(layer, dict):
        raise ConfigError(f"profile {profile_name!r} layer {index} must be a dict")
    effect = layer.get("effect")
    if not isinstance(effect, str) or not effect:
        raise ConfigError(
            f"profile {profile_name!r} layer {index} missing non-empty 'effect'"
        )
    opacity = float(layer.get("opacity", 1.0))
    return {
        "effect": effect,
        "opacity": max(0.0, min(1.0, opacity)),
        "enabled": bool(layer.get("enabled", True)),
    }


def _validate_profile(name: str, profile: Any) -> dict[str, Any]:
    """Validate and normalize a single profile dict.

    Args:
        name: Profile name (for error messages).
        profile: Candidate profile value.

    Returns:
        Normalized profile with validated layers and clamped effect_params.

    Raises:
        ConfigError: When required keys are missing or have the wrong type.
    """
    from razer_effect.effects import EFFECTS

    if not isinstance(profile, dict):
        raise ConfigError(f"profile {name!r} must be a dict")

    layers = profile.get("layers")
    if not isinstance(layers, list) or len(layers) < 1:
        raise ConfigError(f"profile {name!r} 'layers' must be a non-empty list")

    if len(layers) > MAX_LAYERS:
        print(
            f"razer-effect: profile {name!r} has {len(layers)} layers; "
            f"truncating to MAX_LAYERS={MAX_LAYERS}",
            file=sys.stderr,
        )
        layers = layers[:MAX_LAYERS]

    validated_layers = [
        _validate_layer(layer, name, i) for i, layer in enumerate(layers)
    ]

    for layer in validated_layers:
        if layer["effect"] not in EFFECTS:
            print(
                f"razer-effect: profile {name!r} references unknown effect "
                f"{layer['effect']!r}; plugin loader may resolve it later",
                file=sys.stderr,
            )

    effect_params = profile.get("effect_params", {})
    if not isinstance(effect_params, dict):
        raise ConfigError(f"profile {name!r} 'effect_params' must be a dict")

    primary_effect = validated_layers[0]["effect"]
    effect_cls = EFFECTS.get(primary_effect) or EFFECTS.get("key_shuffle")
    if effect_cls is not None:
        for param_name, schema in effect_cls.PARAMS.items():
            if param_name in effect_params:
                val = float(effect_params[param_name])
                effect_params[param_name] = max(schema["min"], min(schema["max"], val))

    return {"layers": validated_layers, "effect_params": effect_params}


def _validate(cfg: dict[str, Any]) -> dict[str, Any]:
    """Validate and clamp the v2 config in place.

    Args:
        cfg: Config dict (already merged with defaults).

    Returns:
        Config dict with values clamped to valid ranges and profiles normalized.

    Raises:
        ConfigError: When required v2 invariants are violated.
    """
    cfg["fps"] = max(1, min(60, int(cfg["fps"])))
    if cfg.get("brightness") is not None:
        cfg["brightness"] = max(0, min(100, int(cfg["brightness"])))

    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ConfigError("profiles must be a non-empty dict")

    active_profile = cfg.get("active_profile")
    if not isinstance(active_profile, str) or active_profile not in profiles:
        raise ConfigError(f"active_profile {active_profile!r} not in profiles")

    cfg["profiles"] = {
        name: _validate_profile(name, profile) for name, profile in profiles.items()
    }

    plugin_paths = cfg.get("plugin_paths")
    if plugin_paths is None:
        cfg["plugin_paths"] = [str(DEFAULT_PLUGIN_DIR)]
    elif not isinstance(plugin_paths, list) or not all(
        isinstance(p, str) for p in plugin_paths
    ):
        raise ConfigError("plugin_paths must be a list of strings")

    device_overrides = cfg.get("device_overrides")
    if device_overrides is None:
        cfg["device_overrides"] = {}
    elif not isinstance(device_overrides, dict):
        raise ConfigError("device_overrides must be a dict")

    hotkey = cfg.get("hotkey")
    if hotkey is not None and not isinstance(hotkey, str):
        raise ConfigError("hotkey must be a string or null")

    return cfg


def load_config() -> dict[str, Any]:
    """Load config from disk, migrating v1 and merging v2 defaults.

    Returns:
        Validated v2 config dict with all keys guaranteed present.

    Raises:
        ConfigError: When the on-disk config violates the v2 schema.
    """
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return _build_defaults()

    if _is_v1(cfg):
        cfg = _migrate_v1_to_v2(cfg)

    merged = {**_build_defaults(), **cfg}
    if "profiles" not in cfg:
        merged["profiles"] = {DEFAULT_PROFILE_NAME: _default_profile()}
    return _validate(merged)


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
