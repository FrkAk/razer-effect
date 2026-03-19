"""Rainbow wave effect sweeping across columns."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt

    from razer_effect.effects import ParamSchema

from razer_effect.effects.palette import build_palette


class Wave:
    """Rainbow hue wave sweeping left-to-right or right-to-left."""

    LABEL: ClassVar[str] = "Wave"
    STATIC: ClassVar[bool] = False
    PARAMS: ClassVar[dict[str, ParamSchema]] = {
        "wave_speed": {
            "default": 0.1,
            "min": 0.1,
            "max": 5.0,
            "step": 0.1,
            "digits": 1,
            "label": "Speed",
            "subtitle": "Wave cycles per second",
        },
        "wave_length": {
            "default": 1.0,
            "min": 0.5,
            "max": 5.0,
            "step": 0.1,
            "digits": 1,
            "label": "Wave Length",
            "subtitle": "Rainbow cycles across keyboard width",
        },
        "wave_direction": {
            "default": 1.0,
            "min": 0.0,
            "max": 1.0,
            "step": 1.0,
            "digits": 0,
            "label": "Direction",
            "subtitle": "0 = left-to-right, 1 = right-to-left",
        },
    }

    def __init__(self) -> None:
        """Initialize with empty state before setup is called."""
        self._palette = build_palette()
        self._phase = 0.0
        self._speed = 1.0
        self._direction = 0
        self._cols = 0
        self._col_offsets: npt.NDArray[np.float32] = np.empty(0, dtype=np.float32)
        self._hues: npt.NDArray[np.float32] = np.empty(0, dtype=np.float32)
        self._indices: npt.NDArray[np.int32] = np.empty(0, dtype=np.int32)
        self._col_colors: npt.NDArray[np.float32] = np.empty(0, dtype=np.float32)

    def setup(self, rows: int, cols: int, cfg: dict[str, Any]) -> None:
        """Allocate all working buffers for the given matrix size.

        Args:
            rows: Number of key rows.
            cols: Number of key columns.
            cfg: Current config dict.
        """
        self._cols = cols
        self._phase = 0.0
        self._hues = np.empty(cols, dtype=np.float32)
        self._indices = np.empty(cols, dtype=np.int32)
        self._col_colors = np.empty((cols, 3), dtype=np.float32)
        self._rebuild_offsets(cols, float(cfg.get("wave_length", 1.5)))
        self.configure(cfg)

    def configure(self, cfg: dict[str, Any]) -> None:
        """Apply updated config values.

        Args:
            cfg: Updated config dict.
        """
        self._speed = float(cfg.get("wave_speed", 1.0))
        self._direction = int(cfg.get("wave_direction", 0))
        new_length = float(cfg.get("wave_length", 1.5))
        self._rebuild_offsets(self._cols, new_length)

    def render(self, dt: float, out: npt.NDArray[np.float32]) -> None:
        """Render one frame of the rainbow wave. Zero per-frame allocations.

        Args:
            dt: Elapsed time in seconds since the last frame.
            out: Output buffer of shape (rows, cols, 3), float32. Written in-place.
        """
        self._phase = (self._phase + self._speed * dt) % 1.0

        if self._direction == 0:
            np.add(self._phase, self._col_offsets, out=self._hues)
        else:
            np.subtract(self._phase, self._col_offsets, out=self._hues)
        np.mod(self._hues, 1.0, out=self._hues)

        np.multiply(self._hues, 360.0, out=self._hues)
        np.copyto(self._indices, self._hues, casting="unsafe")
        np.mod(self._indices, 360, out=self._indices)
        np.copyto(self._col_colors, self._palette[self._indices])
        out[:] = self._col_colors[np.newaxis, :, :]

    def _rebuild_offsets(self, cols: int, wave_length: float) -> None:
        """Precompute column phase offsets.

        Args:
            cols: Number of columns.
            wave_length: Number of rainbow cycles across the keyboard.
        """
        if cols > 0:
            self._col_offsets = np.linspace(
                0, wave_length, cols, endpoint=False, dtype=np.float32
            )
