"""Static uniform color effect."""

from __future__ import annotations

import colorsys
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt

    from razer_effect.effects import ParamSchema


class StaticColor:
    """Fills all keys with a single solid color from HSV."""

    LABEL: ClassVar[str] = "Static Color"
    STATIC: ClassVar[bool] = True
    PARAMS: ClassVar[dict[str, ParamSchema]] = {
        "hue": {
            "default": 120.0,
            "min": 0.0,
            "max": 360.0,
            "step": 1.0,
            "digits": 0,
            "label": "Hue",
            "subtitle": "Color hue in degrees (0-360)",
        },
        "saturation": {
            "default": 100.0,
            "min": 0.0,
            "max": 100.0,
            "step": 1.0,
            "digits": 0,
            "label": "Saturation",
            "subtitle": "Color saturation (0 = white, 100 = vivid)",
        },
        "value": {
            "default": 100.0,
            "min": 0.0,
            "max": 100.0,
            "step": 1.0,
            "digits": 0,
            "label": "Brightness",
            "subtitle": "Color brightness (0 = black, 100 = full)",
        },
    }

    def __init__(self) -> None:
        """Initialize with default red color."""
        self._color = np.array([0.0, 255.0, 0.0], dtype=np.float32)

    def setup(self, rows: int, cols: int, cfg: dict[str, Any]) -> None:
        """Allocate state for the given matrix size.

        Args:
            rows: Number of key rows.
            cols: Number of key columns.
            cfg: Current config dict.
        """
        self.configure(cfg)

    def configure(self, cfg: dict[str, Any]) -> None:
        """Recompute RGB from HSV.

        Args:
            cfg: Updated config dict.
        """
        hue = float(cfg.get("hue", 0.0))
        sat = float(cfg.get("saturation", 100.0)) / 100.0
        val = float(cfg.get("value", 100.0)) / 100.0
        r, g, b = colorsys.hsv_to_rgb(hue / 360.0, sat, val)
        self._color[0] = r * 255
        self._color[1] = g * 255
        self._color[2] = b * 255

    def render(self, dt: float, out: npt.NDArray[np.float32]) -> None:
        """Fill the entire output buffer with the static color.

        Args:
            dt: Elapsed time in seconds since the last frame (unused).
            out: Output buffer of shape (rows, cols, 3), float32. Written in-place.
        """
        out[:] = self._color
