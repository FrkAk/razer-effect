"""CLI entry point for the razer-effect daemon."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from typing import Any

import numpy as np

from razer_effect.config import CONFIG_PATH, ensure_config, load_config
from razer_effect.device import find_device, write_frame
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


def _handle_config_reload(
    cfg: dict[str, Any],
    device: Any,
    effect: Any,
    active_effect_name: str,
    rows: int,
    cols: int,
) -> tuple[dict[str, Any], Any, str]:
    """Reload config from disk and apply changes.

    Handles pause/resume, brightness, effect switching, and parameter updates.

    Args:
        cfg: Previous config dict.
        device: OpenRazer device.
        effect: Current effect instance.
        active_effect_name: Registry key of the currently running effect.
        rows: Matrix row count.
        cols: Matrix column count.

    Returns:
        Tuple of (new config, possibly new effect instance, active effect name).
    """
    cfg = load_config()

    while not cfg.get("running", True):
        time.sleep(1)
        cfg = load_config()

    brightness = cfg.get("brightness")
    if brightness is not None:
        device.brightness = max(0, min(100, int(brightness)))

    new_effect_name = cfg.get("effect", "key_shuffle")
    if new_effect_name != active_effect_name:
        effect = _instantiate_effect(cfg, rows, cols)
        active_effect_name = new_effect_name
    else:
        effect.configure(cfg)

    return cfg, effect, active_effect_name


def _convert_frame(out: np.ndarray, rgb_buf: np.ndarray) -> None:
    """Convert float32 frame to uint8 in-place with zero allocations.

    Args:
        out: Float32 source buffer of shape (rows, cols, 3). Clamped in-place.
        rgb_buf: Pre-allocated uint8 destination buffer of same shape.
    """
    np.clip(out, 0, 255, out=out)
    np.copyto(rgb_buf, out, casting="unsafe")


def run_loop(device: Any, cfg: dict[str, Any]) -> None:
    """Main render loop with inotify-based config reload.

    Args:
        device: OpenRazer device with matrix support.
        cfg: Initial config dict.
    """
    adv = device.fx.advanced
    rows, cols = adv.rows, adv.cols

    active_effect_name = cfg.get("effect", "key_shuffle")
    effect = _instantiate_effect(cfg, rows, cols)
    out = np.empty((rows, cols, 3), dtype=np.float32)
    rgb_buf = np.empty((rows, cols, 3), dtype=np.uint8)

    fps = int(cfg.get("fps", 24))
    frame_delay = 1.0 / fps
    last_time = time.monotonic()
    needs_redraw = True

    watcher = ConfigWatcher(CONFIG_PATH)

    while True:
        if watcher.has_changed():
            cfg, effect, active_effect_name = _handle_config_reload(
                cfg, device, effect, active_effect_name, rows, cols
            )
            fps = int(cfg.get("fps", 24))
            frame_delay = 1.0 / fps
            last_time = time.monotonic()
            needs_redraw = True

        if effect.STATIC:
            if needs_redraw:
                effect.render(0, out)
                _convert_frame(out, rgb_buf)
                write_frame(adv, rgb_buf)
                needs_redraw = False
            watcher.wait()
            cfg, effect, active_effect_name = _handle_config_reload(
                cfg, device, effect, active_effect_name, rows, cols
            )
            fps = int(cfg.get("fps", 24))
            frame_delay = 1.0 / fps
            last_time = time.monotonic()
            needs_redraw = True
        else:
            now = time.monotonic()
            dt = now - last_time
            last_time = now

            effect.render(dt, out)
            _convert_frame(out, rgb_buf)
            write_frame(adv, rgb_buf)

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
    device = find_device()
    adv = device.fx.advanced
    print(f"Found: {device.name} ({adv.rows}x{adv.cols} matrix)")

    brightness = cfg.get("brightness")
    if brightness is not None:
        device.brightness = max(0, min(100, int(brightness)))
        print(f"Brightness set to {brightness}%")

    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    if args.loop:
        fps = cfg.get("fps", 24)
        effect_name = cfg.get("effect", "key_shuffle")
        print(f"Looping: {effect_name} @ {fps}fps (Ctrl+C to stop)")
        run_loop(device, cfg)
    else:
        from razer_effect.effects.key_shuffle import KeyShuffle

        rows, cols = adv.rows, adv.cols
        effect = KeyShuffle()
        effect.setup(rows, cols, cfg)
        rgb_buf = np.empty((rows, cols, 3), dtype=np.uint8)
        _convert_frame(effect._current.copy(), rgb_buf)
        write_frame(adv, rgb_buf)
        print("Random colors applied.")
