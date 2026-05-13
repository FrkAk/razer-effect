"""CLI entry point for the razer-effect daemon."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from typing import Any

import numpy as np

from razer_effect.config import CONFIG_PATH, ensure_config, load_config
from razer_effect.device import (
    DeviceHandle,
    consume_rescan_request,
    find_device,
    find_devices,
    request_rescan,
    rescan_devices,
    write_frame,
)
from razer_effect.effects import EFFECTS
from razer_effect.inotify import ConfigWatcher


def _instantiate_effect(cfg: dict[str, Any], rows: int, cols: int) -> Any:
    """Create and set up an effect instance from config.

    Args:
        cfg: Current config dict.
        rows: Matrix row count.
        cols: Matrix column count.

    Returns:
        An initialized effect instance.

    Raises:
        SystemExit: If the configured effect name is unknown.
    """
    effect_name = cfg.get("effect", "key_shuffle")
    effect_cls = EFFECTS.get(effect_name)
    if effect_cls is None:
        print(f"Unknown effect: {effect_name}", file=sys.stderr)
        sys.exit(1)

    effect = effect_cls()
    effect.setup(rows, cols, cfg)
    return effect


def _effect_allowed(effect: Any, handle: DeviceHandle) -> bool:
    """Check whether an effect opted in to rendering on the given handle.

    Args:
        effect: An effect instance.
        handle: The device handle under consideration.

    Returns:
        True when the effect's `DEVICE_CLASSES` is None (universal) or
        explicitly includes the handle's `device_class`.
    """
    classes = getattr(effect, "DEVICE_CLASSES", None)
    return classes is None or handle.device_class in classes


def _build_effects(cfg: dict[str, Any], handles: list[DeviceHandle]) -> dict[str, Any]:
    """Instantiate one effect per handle for the current config.

    Args:
        cfg: Current config dict.
        handles: Per-device handles.

    Returns:
        Mapping of handle id (`id(handle)` as string) to effect instance.
    """
    return {str(id(h)): _instantiate_effect(cfg, h.rows, h.cols) for h in handles}


def _apply_brightness(cfg: dict[str, Any], handles: list[DeviceHandle]) -> None:
    """Push the configured brightness to every handle's device.

    Args:
        cfg: Current config dict.
        handles: Per-device handles to update.
    """
    brightness = cfg.get("brightness")
    if brightness is None:
        return
    value = max(0, min(100, int(brightness)))
    for h in handles:
        h.device.brightness = value


def _handle_config_reload(
    cfg: dict[str, Any],
    handles: list[DeviceHandle],
    effects: dict[str, Any],
    active_effect_name: str,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Reload config from disk and apply changes across all handles.

    Handles pause/resume, brightness, effect switching, and parameter updates.
    On effect-name change, every handle gets a fresh effect instance sized to
    its own matrix; otherwise the existing instances are reconfigured in place.

    Args:
        cfg: Previous config dict.
        handles: Per-device handles.
        effects: Current handle id -> effect instance mapping.
        active_effect_name: Registry key of the currently running effect.

    Returns:
        Tuple of (new config, new effects mapping, active effect name).
    """
    cfg = load_config()

    while not cfg.get("running", True):
        time.sleep(1)
        cfg = load_config()

    _apply_brightness(cfg, handles)

    new_effect_name = cfg.get("effect", "key_shuffle")
    if new_effect_name != active_effect_name:
        effects = _build_effects(cfg, handles)
        active_effect_name = new_effect_name
    else:
        for effect in effects.values():
            effect.configure(cfg)

    return cfg, effects, active_effect_name


def _convert_frame(out: np.ndarray, rgb_buf: np.ndarray) -> None:
    """Convert float32 frame to uint8 in-place with zero allocations.

    Args:
        out: Float32 source buffer of shape (rows, cols, 3). Clamped in-place.
        rgb_buf: Pre-allocated uint8 destination buffer of same shape.
    """
    np.clip(out, 0, 255, out=out)
    np.copyto(rgb_buf, out, casting="unsafe")


def _reconcile_after_rescan(
    cfg: dict[str, Any],
    handles: list[DeviceHandle],
    effects: dict[str, Any],
) -> dict[str, Any]:
    """Drop stale entries from `effects` and instantiate any new handles.

    Args:
        cfg: Current config dict.
        handles: Post-rescan handle list.
        effects: Existing handle id -> effect mapping.

    Returns:
        A mapping that has one effect per live handle.
    """
    live_keys = {str(id(h)) for h in handles}
    reconciled: dict[str, Any] = {k: v for k, v in effects.items() if k in live_keys}
    for h in handles:
        key = str(id(h))
        if key not in reconciled:
            reconciled[key] = _instantiate_effect(cfg, h.rows, h.cols)
    return reconciled


def _render_tick(
    handles: list[DeviceHandle], effects: dict[str, Any], dt: float
) -> None:
    """Render and write one frame on every handle whose effect opted in.

    Excluded handles keep their last-written `rgb_buf` contents untouched.

    Args:
        handles: Per-device handles.
        effects: Handle id -> effect instance mapping.
        dt: Seconds elapsed since the previous tick.
    """
    for h in handles:
        effect = effects.get(str(id(h)))
        if effect is None or not _effect_allowed(effect, h):
            continue
        effect.render(dt, h.canvas)
        _convert_frame(h.canvas, h.rgb_buf)
        write_frame(h.adv, h.rgb_buf)


def run_loop(handles: list[DeviceHandle], cfg: dict[str, Any]) -> None:
    """Main render loop with inotify-based config reload and SIGHUP rescan.

    Args:
        handles: Initial list of device handles.
        cfg: Initial config dict.
    """
    active_effect_name = cfg.get("effect", "key_shuffle")
    effects = _build_effects(cfg, handles)

    fps = int(cfg.get("fps", 24))
    frame_delay = 1.0 / fps
    last_time = time.monotonic()
    needs_redraw = True

    watcher = ConfigWatcher(CONFIG_PATH)

    while True:
        if consume_rescan_request():
            handles = rescan_devices(handles)
            effects = _reconcile_after_rescan(cfg, handles, effects)
            _apply_brightness(cfg, handles)
            needs_redraw = True

        if watcher.has_changed():
            cfg, effects, active_effect_name = _handle_config_reload(
                cfg, handles, effects, active_effect_name
            )
            fps = int(cfg.get("fps", 24))
            frame_delay = 1.0 / fps
            last_time = time.monotonic()
            needs_redraw = True

        any_effect = next(iter(effects.values()), None)
        is_static = bool(getattr(any_effect, "STATIC", False)) if any_effect else False

        if is_static:
            if needs_redraw:
                _render_tick(handles, effects, 0.0)
                needs_redraw = False
            watcher.wait()
            cfg, effects, active_effect_name = _handle_config_reload(
                cfg, handles, effects, active_effect_name
            )
            fps = int(cfg.get("fps", 24))
            frame_delay = 1.0 / fps
            last_time = time.monotonic()
            needs_redraw = True
        else:
            now = time.monotonic()
            dt = now - last_time
            last_time = now

            _render_tick(handles, effects, dt)

            elapsed = time.monotonic() - now
            sleep_time = frame_delay - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)


def main() -> None:
    """CLI entry point for razer-effect."""
    parser = argparse.ArgumentParser(
        description="Per-key random RGB for Razer keyboards"
    )
    parser.add_argument(
        "--loop", action="store_true", help="continuously run the effect"
    )
    args = parser.parse_args()

    cfg = ensure_config()

    handles = find_devices()
    if not handles:
        find_device()
        return

    for h in handles:
        print(f"Found: {h.device.name} ({h.rows}x{h.cols} {h.device_class})")

    _apply_brightness(cfg, handles)
    brightness = cfg.get("brightness")
    if brightness is not None:
        print(f"Brightness set to {brightness}%")

    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGHUP, lambda *_: request_rescan())

    if args.loop:
        fps = cfg.get("fps", 24)
        effect_name = cfg.get("effect", "key_shuffle")
        print(f"Looping: {effect_name} @ {fps}fps (Ctrl+C to stop)")
        run_loop(handles, cfg)
    else:
        from razer_effect.effects.key_shuffle import KeyShuffle

        for h in handles:
            effect = KeyShuffle()
            effect.setup(h.rows, h.cols, cfg)
            _convert_frame(effect._current.copy(), h.rgb_buf)
            write_frame(h.adv, h.rgb_buf)
        print("Random colors applied.")
