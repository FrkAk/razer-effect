# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Python daemon + GTK4/Adwaita GUI for custom per-key RGB effects on Razer keyboards via OpenRazer. The daemon runs as a systemd user service, the GUI writes to a shared config file (`~/.config/razer-effect/config.json`), and the daemon picks up changes via inotify.

## Commands

```bash
uv run razer-effect --loop     # run daemon directly (requires Razer device)
uv run razer-effect-gui        # launch GTK4 settings app
uv run ruff format .           # format
uv run ruff check --fix .      # lint
uv run ty check                # type check
```

No test suite exists yet.

## Architecture

**Entry points** (defined in `pyproject.toml [project.scripts]`):
- `razer-effect` → `src/razer_effect/main.py:main` — daemon with render loop
- `razer-effect-gui` → `src/razer_effect/gui.py:main` — GTK4/Adwaita settings window

**Effect system** — pluggable effects follow the `Effect` protocol (`src/razer_effect/effects/__init__.py`):
- `LABEL`: display name, `PARAMS`: dict of `ParamSchema` (default/min/max/step/digits/label/subtitle)
- Methods: `setup(rows, cols, cfg)`, `configure(cfg)`, `render(dt, out)` — `out` is a `(rows, cols, 3)` float32 numpy array written in-place
- Shared HSV palette in `effects/palette.py` — used by `key_shuffle` and `wave`
- Registered effects: `key_shuffle` (per-key random fades), `static_color` (uniform hue-based color), `wave` (rainbow sweep)
- Register new effects in `_register()` in `effects/__init__.py`

**Config** (`src/razer_effect/config.py`): JSON file at `~/.config/razer-effect/config.json`. Atomic writes via tmp+rename. Global keys: `effect`, `fps`, `brightness`, `running`. Effect-specific params are flat top-level keys.

**Config watching** (`src/razer_effect/inotify.py`): Raw Linux inotify via ctypes on the config's parent directory to detect atomic renames.

**Device I/O** (`src/razer_effect/device.py`): Finds first OpenRazer device with matrix support, writes RGB frames by directly assigning to `adv.matrix._matrix` channels.

## Key Constraints

- System dependencies not on PyPI: `python3-openrazer`, `gi` (GTK4/libadwaita) — must be installed via distro package manager
- Render loop is performance-sensitive: numpy operations are in-place/zero-allocation where possible
- No new dependencies without discussion

## Self-Improvement

Update this file when changes affect information tracked here:

- New effect added → update the effect registry note in Architecture
- New entry point or command added → update Commands section
- New system dependency introduced → update Key Constraints
- Config keys added/removed → update the Config description
- Test suite added → remove "No test suite exists yet" and add test commands
- Architecture changes (new modules, changed communication patterns) → update Architecture
