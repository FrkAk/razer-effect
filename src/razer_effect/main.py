"""CLI entry point for the razer-effect daemon."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from typing import Any

import numpy as np

from razer_effect.compositor import LayerStack, blend, build_layer_stack
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

LayerSignature = tuple[str, tuple[tuple[str, float, bool], ...]]


def _active_profile(cfg: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Resolve the active profile from a v2 config.

    Args:
        cfg: Validated v2 config dict.

    Returns:
        Tuple of (profile name, profile dict). Falls back to the first profile
        when `active_profile` is missing.
    """
    name = cfg.get("active_profile", "default")
    profiles = cfg.get("profiles", {})
    if name not in profiles and profiles:
        name = next(iter(profiles))
    return name, profiles.get(name, {"layers": [], "effect_params": {}})


def _layer_signature(cfg: dict[str, Any]) -> LayerSignature:
    """Compute a structural signature for the active profile's layer stack.

    Args:
        cfg: Current config dict.

    Returns:
        Tuple of (profile name, tuple of per-layer (effect, opacity, enabled))
        suitable for equality comparison to detect structural reloads.
    """
    name, profile = _active_profile(cfg)
    layers = profile.get("layers", [])
    sig = tuple(
        (
            str(layer.get("effect", "")),
            float(layer.get("opacity", 1.0)),
            bool(layer.get("enabled", True)),
        )
        for layer in layers
    )
    return name, sig


def _build_layer_stacks(
    cfg: dict[str, Any], handles: list[DeviceHandle]
) -> dict[str, LayerStack]:
    """Construct one LayerStack per handle from the active profile.

    Args:
        cfg: Current config dict.
        handles: Per-device handles.

    Returns:
        Mapping of `str(id(handle))` to its LayerStack.
    """
    _, profile = _active_profile(cfg)
    return {str(id(h)): build_layer_stack(h, profile, EFFECTS) for h in handles}


def _reconfigure_stacks(stacks: dict[str, LayerStack], profile: dict[str, Any]) -> None:
    """Push updated effect params into every layer's effect.

    Args:
        stacks: Mapping of handle id to LayerStack.
        profile: The active profile dict providing `effect_params`.
    """
    params = dict(profile.get("effect_params", {}))
    for stack in stacks.values():
        for layer in stack:
            layer.effect.configure(params)


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
    stacks: dict[str, LayerStack],
    signature: LayerSignature,
) -> tuple[dict[str, Any], dict[str, LayerStack], LayerSignature]:
    """Reload config from disk and apply changes across all handles.

    Rebuilds every LayerStack when the layer-stack signature changes
    (effect swap, opacity tweak, enabled toggle, profile switch). Otherwise
    reconfigures each layer's effect in place with the updated params.

    Args:
        cfg: Previous config dict.
        handles: Per-device handles.
        stacks: Current handle id -> LayerStack mapping.
        signature: Previous layer-stack signature.

    Returns:
        Tuple of (new config, new stacks, new signature).
    """
    cfg = load_config()

    while not cfg.get("running", True):
        time.sleep(1)
        cfg = load_config()

    _apply_brightness(cfg, handles)

    new_signature = _layer_signature(cfg)
    if new_signature != signature:
        stacks = _build_layer_stacks(cfg, handles)
    else:
        _, profile = _active_profile(cfg)
        _reconfigure_stacks(stacks, profile)

    return cfg, stacks, new_signature


def _convert_frame(out: np.ndarray, rgb_buf: np.ndarray) -> None:
    """Convert float32 frame to uint8 in-place with zero allocations.

    Args:
        out: Float32 source buffer of shape (rows, cols, 3). Clamped in-place.
        rgb_buf: Pre-allocated uint8 destination buffer of same shape.
    """
    np.clip(out, 0, 255, out=out)
    np.copyto(rgb_buf, out, casting="unsafe")


def _reconcile_stacks_after_rescan(
    cfg: dict[str, Any],
    handles: list[DeviceHandle],
    stacks: dict[str, LayerStack],
) -> dict[str, LayerStack]:
    """Drop stale entries from `stacks` and build new ones for new handles.

    Args:
        cfg: Current config dict.
        handles: Post-rescan handle list.
        stacks: Existing handle id -> stack mapping.

    Returns:
        A mapping that has one LayerStack per live handle.
    """
    _, profile = _active_profile(cfg)
    live_keys = {str(id(h)) for h in handles}
    reconciled: dict[str, LayerStack] = {
        k: v for k, v in stacks.items() if k in live_keys
    }
    for h in handles:
        key = str(id(h))
        if key not in reconciled:
            reconciled[key] = build_layer_stack(h, profile, EFFECTS)
    return reconciled


def _render_tick(
    handles: list[DeviceHandle],
    stacks: dict[str, LayerStack],
    dt: float,
) -> None:
    """Composite and write one frame on every handle with active layers.

    Handles whose stack produced no active contribution keep their last
    `rgb_buf` contents on hardware.

    Args:
        handles: Per-device handles.
        stacks: Handle id -> LayerStack mapping.
        dt: Seconds elapsed since the previous tick.
    """
    for h in handles:
        stack = stacks.get(str(id(h)))
        if stack is None:
            continue
        drew = blend(h.canvas, stack, dt, h.device_class)
        if not drew:
            continue
        _convert_frame(h.canvas, h.rgb_buf)
        write_frame(h.adv, h.rgb_buf)


def _all_static(handles: list[DeviceHandle], stacks: dict[str, LayerStack]) -> bool:
    """Check whether every handle's stack is fully static.

    Args:
        handles: Per-device handles.
        stacks: Handle id -> LayerStack mapping.

    Returns:
        True iff at least one handle has active layers and every active layer
        across every handle is STATIC.
    """
    any_active = False
    for h in handles:
        stack = stacks.get(str(id(h)))
        if stack is None:
            continue
        if stack.is_all_static(h.device_class):
            any_active = True
            continue
        for _ in stack.active(h.device_class):
            return False
    return any_active


def run_loop(handles: list[DeviceHandle], cfg: dict[str, Any]) -> None:
    """Main render loop with inotify-based config reload and SIGHUP rescan.

    Args:
        handles: Initial list of device handles.
        cfg: Initial config dict.
    """
    stacks = _build_layer_stacks(cfg, handles)
    signature = _layer_signature(cfg)

    fps = int(cfg.get("fps", 24))
    frame_delay = 1.0 / fps
    last_time = time.monotonic()
    needs_redraw = True

    watcher = ConfigWatcher(CONFIG_PATH)

    while True:
        if consume_rescan_request():
            handles = rescan_devices(handles)
            stacks = _reconcile_stacks_after_rescan(cfg, handles, stacks)
            _apply_brightness(cfg, handles)
            needs_redraw = True

        if watcher.has_changed():
            cfg, stacks, signature = _handle_config_reload(
                cfg, handles, stacks, signature
            )
            fps = int(cfg.get("fps", 24))
            frame_delay = 1.0 / fps
            last_time = time.monotonic()
            needs_redraw = True

        if _all_static(handles, stacks):
            if needs_redraw:
                _render_tick(handles, stacks, 0.0)
                needs_redraw = False
            watcher.wait()
            cfg, stacks, signature = _handle_config_reload(
                cfg, handles, stacks, signature
            )
            fps = int(cfg.get("fps", 24))
            frame_delay = 1.0 / fps
            last_time = time.monotonic()
            needs_redraw = True
        else:
            now = time.monotonic()
            dt = now - last_time
            last_time = now

            _render_tick(handles, stacks, dt)

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
        profile_name, profile = _active_profile(cfg)
        layer_count = len(profile.get("layers", []))
        print(
            f"Looping: profile={profile_name!r} layers={layer_count} "
            f"@ {fps}fps (Ctrl+C to stop)"
        )
        run_loop(handles, cfg)
    else:
        _, profile = _active_profile(cfg)
        params = dict(profile.get("effect_params", {}))
        layers = profile.get("layers", [])
        first_name = layers[0]["effect"] if layers else "key_shuffle"
        effect_cls = EFFECTS.get(first_name) or EFFECTS["key_shuffle"]
        for h in handles:
            effect = effect_cls()
            effect.setup(h.rows, h.cols, params)
            scratch = np.empty((h.rows, h.cols, 3), dtype=np.float32)
            effect.render(0.0, scratch)
            _convert_frame(scratch, h.rgb_buf)
            write_frame(h.adv, h.rgb_buf)
        print("Random colors applied.")
