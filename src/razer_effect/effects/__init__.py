"""Effect registry and protocol definition."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Protocol, TypedDict

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt


class ParamSchema(TypedDict):
    """Schema for a single effect parameter."""

    default: float
    min: float
    max: float
    step: float
    digits: int
    label: str
    subtitle: str


class Effect(Protocol):
    """Structural protocol that all effects must satisfy."""

    LABEL: ClassVar[str]
    PARAMS: ClassVar[dict[str, ParamSchema]]
    STATIC: ClassVar[bool]
    DEVICE_CLASSES: ClassVar[frozenset[str] | None] = None

    def setup(self, rows: int, cols: int, cfg: dict[str, Any]) -> None:
        """Allocate buffers and initialize state for given matrix dimensions.

        Args:
            rows: Number of key rows.
            cols: Number of key columns.
            cfg: Current config dict.
        """
        ...

    def configure(self, cfg: dict[str, Any]) -> None:
        """Apply updated config values without reallocating buffers.

        Args:
            cfg: Updated config dict.
        """
        ...

    def render(self, dt: float, out: npt.NDArray[np.float32]) -> None:
        """Write one frame of RGB data into the output buffer in-place.

        Args:
            dt: Elapsed time in seconds since the last frame.
            out: Numpy array of shape (rows, cols, 3), float32. Write into this.
        """
        ...


def _register() -> dict[str, type[Effect]]:
    """Build the effect registry (built-ins + validated user plugins).

    ``plugin_paths`` is read from ``CONFIG_PATH`` directly via ``json.load``
    rather than ``load_config()`` because ``config._effect_defaults`` already
    imports this module; a ``load_config`` call from here would re-enter
    ``config`` during module initialization.

    Returns:
        Mapping of effect names to their implementing classes. Plugins are
        merged in after built-ins, so a plugin keyed identically to a
        built-in overrides it (with a stderr warning from ``load_plugins``).
    """
    import json
    from pathlib import Path

    from razer_effect.config import CONFIG_PATH, DEFAULT_PLUGIN_DIR
    from razer_effect.effects.key_shuffle import KeyShuffle
    from razer_effect.effects.static_color import StaticColor
    from razer_effect.effects.wave import Wave
    from razer_effect.plugins import load_plugins

    builtin: dict[str, type[Effect]] = {
        "key_shuffle": KeyShuffle,
        "static_color": StaticColor,
        "wave": Wave,
    }

    plugin_paths: list[Path] = [DEFAULT_PLUGIN_DIR]
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        configured = raw.get("plugin_paths")
        if isinstance(configured, list) and configured:
            plugin_paths = [Path(p) for p in configured if isinstance(p, str)]
    except (FileNotFoundError, ValueError, OSError):
        pass

    builtin.update(load_plugins(plugin_paths))
    return builtin


EFFECTS: dict[str, type[Effect]] = _register()
