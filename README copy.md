# razer-effect

Per-key random RGB with smooth fades for Razer laptops on Linux. Replicates the Razer Synapse per-key random illumination that isn't available in Polychromatic or OpenRazer's built-in effects.

Each key independently cycles through vibrant colors with smooth fade transitions — no sudden jumps. Includes a GTK4 settings app for real-time control.

Tested on **Razer Blade 14 (2025)** with Fedora. Should work on any Razer device with per-key RGB matrix support via OpenRazer.

## Prerequisites

- [OpenRazer](https://openrazer.github.io/) v3.0+ installed and daemon running
- `python3-openrazer` system package (comes with OpenRazer)
- `numpy` (comes with `python3-openrazer`)
- GTK4 + libadwaita (pre-installed on Fedora/GNOME)
- User in `plugdev` group

## Install

```bash
git clone https://github.com/FrkAk/razer-effect.git
cd razer-effect
./install.sh
```

This installs:
- `razer-effect` CLI + systemd user service (auto-starts on login)
- `razer-effect-gui` GTK settings app (available in app launcher as "Razer Effect")

## Uninstall

```bash
./uninstall.sh
```

## GUI

Launch from app launcher ("Razer Effect") or run `razer-effect-gui`.

Controls:
- **Effect** — select effect type (currently: Random Fade)
- **Fade Duration** — seconds per color transition (0.5–5.0)
- **FPS** — animation framerate (12–60)
- **Brightness** — keyboard brightness (0–100)
- **Hold Min/Max** — how long each key holds a color before changing
- **Running** — toggle the effect on/off without stopping the service

Changes apply instantly — the daemon hot-reloads settings within ~1 second.

## CLI

The service runs automatically after install. You can also run manually:

```bash
# Continuous per-key random fades
razer-effect --loop

# Set once and exit
razer-effect
```

## Service management

```bash
systemctl --user status razer-effect     # check status
systemctl --user stop razer-effect       # stop
systemctl --user start razer-effect      # start
systemctl --user restart razer-effect    # restart
systemctl --user disable razer-effect    # disable autostart
systemctl --user enable razer-effect     # re-enable autostart
```

## Config

Settings are stored in `~/.config/razer-effect/config.json` and shared between the GUI and daemon. You can also edit this file directly.

## Performance

~1.7% CPU, 45MB RSS at 24fps. Safe for indefinite runtime — no memory leaks or numeric overflow.

## How it works

Uses OpenRazer's per-key matrix API (`device.fx.advanced`) to write RGB values directly to the keyboard's LED matrix. Colors are sampled from a 360-degree HSV wheel at full saturation and brightness — the same vibrant neon look as Razer Synapse. Each key maintains its own fade timer: holds a color for 1-4 seconds, then smoothly interpolates to a new random color over 2 seconds. All math is vectorized with numpy for minimal CPU overhead.

## License

MIT
