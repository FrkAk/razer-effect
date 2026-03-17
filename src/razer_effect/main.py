"""Per-key random RGB effects for Razer keyboards via OpenRazer."""

import argparse
import signal
import sys
import time

import numpy as np
from openrazer.client import DeviceManager

from razer_effect.config import CONFIG_PATH, ensure_config, load_config


def _build_palette():
    """Build a 360-color palette from full HSV wheel (S=1, V=1).

    Returns:
        numpy array of shape (360, 3) with float32 RGB values 0-255.
    """
    import colorsys

    colors = np.empty((360, 3), dtype=np.float32)
    for i in range(360):
        r, g, b = colorsys.hsv_to_rgb(i / 360.0, 1.0, 1.0)
        colors[i] = (r * 255, g * 255, b * 255)
    return colors


PALETTE = _build_palette()


def find_device():
    """Find the first Razer keyboard/laptop device with matrix support.

    Returns:
        The first device that supports advanced matrix lighting.

    Raises:
        SystemExit: If no compatible device is found.
    """
    manager = DeviceManager()
    manager.sync_effects = False

    for device in manager.devices:
        if device.fx.advanced:
            return device

    print("No Razer device with per-key matrix support found.", file=sys.stderr)
    sys.exit(1)


def write_frame(adv, colors):
    """Write a (rows, cols, 3) float array to the device matrix and draw.

    Args:
        adv: The device's advanced FX object.
        colors: numpy array (rows, cols, 3) of RGB float values.
    """
    rgb = np.clip(colors, 0, 255).astype(np.uint8)
    adv.matrix._matrix[0] = rgb[:, :, 0]
    adv.matrix._matrix[1] = rgb[:, :, 1]
    adv.matrix._matrix[2] = rgb[:, :, 2]
    adv.draw()


def random_colors(rows, cols):
    """Generate a rows x cols grid of random palette colors as float32 array.

    Args:
        rows: Number of rows.
        cols: Number of columns.

    Returns:
        numpy array of shape (rows, cols, 3) with float32 RGB values.
    """
    return PALETTE[np.random.randint(0, len(PALETTE), size=(rows, cols))]


def _config_mtime():
    """Get config file modification time, or 0 if missing.

    Returns:
        Modification time as float, or 0.
    """
    try:
        return CONFIG_PATH.stat().st_mtime
    except OSError:
        return 0


def fade_loop(device, cfg):
    """Continuously cycle per-key random colors with independent staggered fades.

    Uses a single timer array: negative = holding, positive = fade progress (0-1).
    Timer advance is branchless via signbit. Resets checked every few frames.
    Hot-reloads config from disk when file changes.

    Args:
        device: An OpenRazer device with advanced matrix support.
        cfg: Initial config dict.
    """
    adv = device.fx.advanced
    rows, cols = adv.rows, adv.cols
    palette_len = len(PALETTE)

    fade_duration = cfg["fade_duration"]
    fade_fps = cfg["fade_fps"]
    hold_min = cfg["hold_min"]
    hold_max = cfg["hold_max"]
    frame_delay = 1.0 / fade_fps
    fade_step = frame_delay / fade_duration
    step_diff = frame_delay - fade_step

    current = random_colors(rows, cols)
    target = random_colors(rows, cols)
    timer = -np.random.uniform(0, hold_max, size=(rows, cols)).astype(np.float32)

    t_3d = np.empty((rows, cols, 1), dtype=np.float32)
    display = np.empty((rows, cols, 3), dtype=np.float32)
    step_arr = np.empty((rows, cols), dtype=np.float32)

    write_frame(adv, current)

    reset_interval = max(1, fade_fps // 4)
    frame_count = 0
    config_check_frames = fade_fps
    config_frame_count = 0
    last_mtime = _config_mtime()

    while True:
        # Config hot-reload check (~1/second)
        config_frame_count = (config_frame_count + 1) % config_check_frames
        if config_frame_count == 0:
            mtime = _config_mtime()
            if mtime != last_mtime:
                last_mtime = mtime
                cfg = load_config()

                # Pause loop if running=false
                while not cfg.get("running", True):
                    time.sleep(1)
                    new_mt = _config_mtime()
                    if new_mt != last_mtime:
                        last_mtime = new_mt
                        cfg = load_config()

                # Apply changed values
                if cfg["brightness"] is not None:
                    device.brightness = max(0, min(100, cfg["brightness"]))

                fade_duration = cfg["fade_duration"]
                fade_fps = cfg["fade_fps"]
                hold_min = cfg["hold_min"]
                hold_max = cfg["hold_max"]
                frame_delay = 1.0 / fade_fps
                fade_step = frame_delay / fade_duration
                step_diff = frame_delay - fade_step
                reset_interval = max(1, fade_fps // 4)
                config_check_frames = fade_fps

        start = time.monotonic()

        # Branchless timer advance
        np.signbit(timer, out=step_arr)
        timer += step_arr * step_diff + fade_step

        # Check for completed fades every few frames
        frame_count = (frame_count + 1) % reset_interval
        if frame_count == 0:
            reset_mask = timer >= 1.0
            if reset_mask.any():
                current[reset_mask] = target[reset_mask]
                n = int(reset_mask.sum())
                target[reset_mask] = PALETTE[
                    np.random.randint(0, palette_len, size=n)
                ]
                timer[reset_mask] = -np.random.uniform(hold_min, hold_max, size=n)

        # Lerp: clamp timer to 0-1 for blending
        np.clip(timer, 0.0, 1.0, out=t_3d[:, :, 0])
        np.subtract(target, current, out=display)
        display *= t_3d
        display += current
        write_frame(adv, display)

        elapsed = time.monotonic() - start
        sleep_time = frame_delay - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)


def main():
    """CLI entry point for razer-effect."""
    parser = argparse.ArgumentParser(description="Per-key random RGB for Razer keyboards")
    parser.add_argument("--loop", action="store_true", help="continuously randomize with smooth fades")
    args = parser.parse_args()

    cfg = ensure_config()

    device = find_device()
    adv = device.fx.advanced
    print(f"Found: {device.name} ({adv.rows}x{adv.cols} matrix)")

    if cfg["brightness"] is not None:
        device.brightness = max(0, min(100, cfg["brightness"]))
        print(f"Brightness set to {cfg['brightness']}%")

    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    if args.loop:
        print(f"Looping: {cfg['fade_duration']}s fade @ {cfg['fade_fps']}fps (Ctrl+C to stop)")
        fade_loop(device, cfg)
    else:
        rows, cols = adv.rows, adv.cols
        write_frame(adv, random_colors(rows, cols))
        print("Random colors applied.")
