# razer-effect

Custom RGB lighting effects for Razer keyboards on Linux. Pluggable effect system with a GTK4 settings app for real-time control.

Works on any Razer device with per-key RGB matrix support via [OpenRazer](https://openrazer.github.io/).

## Effects

| Effect | Description |
|---|---|
| Static Color | Uniform solid color across all keys with color wheel picker (HSV) |
| Wave | Rainbow hue wave sweeping across the keyboard |
| Key Shuffle | Each key independently cycles through random colors with smooth fade transitions |

## Prerequisites

### 1. Install OpenRazer

Follow the instructions for your distro at [openrazer.github.io/#download](https://openrazer.github.io/#download).

### 2. Add your user to the plugdev group

```bash
sudo gpasswd -a $USER plugdev
```

Log out and back in for the group change to take effect.

### 3. GTK4 + libadwaita

Pre-installed on Fedora/GNOME. On other distros, install `gtk4` and `libadwaita` via your package manager.

## Install

```bash
git clone https://github.com/FrkAk/razer-effect.git
cd razer-effect
./install.sh
```

This sets up the `razer-effect` daemon as a systemd user service (auto-starts on login) and installs the `razer-effect-gui` settings app.

To uninstall: `./uninstall.sh`

## Usage

The daemon starts automatically after install. Launch the settings app from your app launcher ("Razer Effect") or run `razer-effect-gui`. Changes apply instantly.

```bash
systemctl --user status razer-effect    # check status
systemctl --user restart razer-effect   # restart
```

Settings are stored in `~/.config/razer-effect/config.json` and shared between the GUI and daemon.

## License

MIT
