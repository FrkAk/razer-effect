"""Device discovery and frame I/O for OpenRazer keyboards."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from openrazer.client import DeviceManager

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt


def find_device() -> Any:
    """Find the first Razer device with per-key matrix support.

    Returns:
        The first OpenRazer device that supports advanced matrix lighting.

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


def write_frame(adv: Any, rgb: npt.NDArray[np.uint8]) -> None:
    """Write a pre-converted (rows, cols, 3) uint8 array to the device matrix.

    Args:
        adv: The device's advanced FX object.
        rgb: Numpy array of shape (rows, cols, 3) with uint8 RGB values.
    """
    adv.matrix._matrix[0] = rgb[:, :, 0]
    adv.matrix._matrix[1] = rgb[:, :, 1]
    adv.matrix._matrix[2] = rgb[:, :, 2]
    adv.draw()
