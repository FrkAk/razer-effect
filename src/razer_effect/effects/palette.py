"""Shared HSV palette for effects."""

from __future__ import annotations

import colorsys

import numpy as np
import numpy.typing as npt


def build_palette() -> npt.NDArray[np.float32]:
    """Build a 360-color palette from full HSV wheel (S=1, V=1).

    Returns:
        Numpy array of shape (360, 3) with float32 RGB values 0-255.
    """
    colors = np.empty((360, 3), dtype=np.float32)
    for i in range(360):
        r, g, b = colorsys.hsv_to_rgb(i / 360.0, 1.0, 1.0)
        colors[i] = (r * 255, g * 255, b * 255)
    return colors
