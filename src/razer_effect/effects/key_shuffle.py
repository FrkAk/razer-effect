"""Per-key random color cycling with smooth staggered fades."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from razer_effect.effects import ParamSchema

from razer_effect.effects.palette import build_palette


class KeyShuffle:
    """Per-key random color cycling with independent staggered fades.

    Each key holds a random color for a configurable duration, then smoothly
    fades to a new random color. Timer advance is branchless via np.signbit.
    """

    LABEL: ClassVar[str] = "Key Shuffle"
    STATIC: ClassVar[bool] = False
    PARAMS: ClassVar[dict[str, ParamSchema]] = {
        "fade_duration": {
            "default": 2.0,
            "min": 0.5,
            "max": 5.0,
            "step": 0.1,
            "digits": 1,
            "label": "Fade Duration",
            "subtitle": "Seconds per fade transition",
        },
        "hold_min": {
            "default": 1.0,
            "min": 0.5,
            "max": 10.0,
            "step": 0.1,
            "digits": 1,
            "label": "Hold Min",
            "subtitle": "Minimum seconds before color change",
        },
        "hold_max": {
            "default": 4.0,
            "min": 0.5,
            "max": 10.0,
            "step": 0.1,
            "digits": 1,
            "label": "Hold Max",
            "subtitle": "Maximum seconds before color change",
        },
    }

    def __init__(self) -> None:
        """Initialize with empty state before setup is called."""
        self._palette = build_palette()
        self._rows = 0
        self._cols = 0
        self._fade_duration = 2.0
        self._hold_min = 1.0
        self._hold_max = 4.0
        self._current: npt.NDArray[np.float32] = np.empty(0, dtype=np.float32)
        self._target: npt.NDArray[np.float32] = np.empty(0, dtype=np.float32)
        self._timer: npt.NDArray[np.float32] = np.empty(0, dtype=np.float32)
        self._t_3d: npt.NDArray[np.float32] = np.empty(0, dtype=np.float32)
        self._step_arr: npt.NDArray[np.float32] = np.empty(0, dtype=np.float32)
        self._frame_count = 0
        self._reset_interval = 6

    def setup(self, rows: int, cols: int, cfg: dict[str, Any]) -> None:
        """Allocate all working buffers for the given matrix size.

        Args:
            rows: Number of key rows.
            cols: Number of key columns.
            cfg: Current config dict.
        """
        self._rows = rows
        self._cols = cols
        self._current = self._random_colors(rows, cols)
        self._target = self._random_colors(rows, cols)
        self._timer = -np.random.uniform(0, 4.0, size=(rows, cols)).astype(np.float32)
        self._t_3d = np.empty((rows, cols, 1), dtype=np.float32)
        self._step_arr = np.empty((rows, cols), dtype=np.float32)
        self._frame_count = 0
        self.configure(cfg)

    def configure(self, cfg: dict[str, Any]) -> None:
        """Apply changed config values without reallocating buffers.

        Args:
            cfg: Updated config dict.
        """
        self._fade_duration = float(cfg.get("fade_duration", 2.0))
        self._hold_min = float(cfg.get("hold_min", 1.0))
        self._hold_max = float(cfg.get("hold_max", 4.0))
        fps = int(cfg.get("fps", 24))
        self._reset_interval = max(1, fps // 4)

    def render(self, dt: float, out: npt.NDArray[np.float32]) -> None:
        """Render one frame of the key shuffle effect.

        Uses branchless timer advance: negative timer = holding, positive = fading.
        Resets completed fades every few frames to amortize the cost.

        Args:
            dt: Elapsed time in seconds since the last frame.
            out: Output buffer of shape (rows, cols, 3), float32. Written in-place.
        """
        fade_step = dt / self._fade_duration
        np.signbit(self._timer, out=self._step_arr)
        np.multiply(self._step_arr, dt - fade_step, out=self._step_arr)
        self._step_arr += fade_step
        self._timer += self._step_arr

        self._frame_count = (self._frame_count + 1) % self._reset_interval
        if self._frame_count == 0:
            self._reset_completed_fades()

        np.clip(self._timer, 0.0, 1.0, out=self._t_3d[:, :, 0])
        np.subtract(self._target, self._current, out=out)
        out *= self._t_3d
        out += self._current

    def _random_colors(self, rows: int, cols: int) -> npt.NDArray[np.float32]:
        """Generate a grid of random palette colors.

        Args:
            rows: Number of rows.
            cols: Number of columns.

        Returns:
            Numpy array of shape (rows, cols, 3) with float32 RGB values.
        """
        indices = np.random.randint(0, len(self._palette), size=(rows, cols))
        return self._palette[indices]

    def _reset_completed_fades(self) -> None:
        """Reset keys that have finished fading to new random targets.

        Finds all keys with timer >= 1.0, snaps their current color to target,
        picks new random targets, and assigns new hold durations.
        """
        reset_mask = self._timer >= 1.0
        if not reset_mask.any():
            return

        self._current[reset_mask] = self._target[reset_mask]
        n = int(reset_mask.sum())
        self._target[reset_mask] = self._palette[
            np.random.randint(0, len(self._palette), size=n)
        ]
        self._timer[reset_mask] = -np.random.uniform(
            self._hold_min, self._hold_max, size=n
        )
