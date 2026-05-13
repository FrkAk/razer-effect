"""Device discovery and frame I/O for OpenRazer matrix devices."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from openrazer.client import DeviceManager

if TYPE_CHECKING:
    import numpy.typing as npt


DEVICE_CLASS_MAP: dict[str, str] = {
    "keyboard": "keyboard",
    "mouse": "mouse",
    "mousepad": "mat",
    "mug": "other",
    "headset": "other",
    "accessory": "other",
}


@dataclass
class DeviceHandle:
    """One enumerated OpenRazer device with its allocated render buffers.

    Attributes:
        device: The OpenRazer device object.
        adv: The device's advanced FX object exposing the matrix.
        rows: Matrix row count.
        cols: Matrix column count.
        device_class: One of 'keyboard', 'mouse', 'mat', 'other'.
        canvas: Pre-allocated float32 (rows, cols, 3) effect-render buffer.
        rgb_buf: Pre-allocated uint8 (rows, cols, 3) hardware-write buffer.
    """

    device: Any
    adv: Any
    rows: int
    cols: int
    device_class: str
    canvas: np.ndarray
    rgb_buf: np.ndarray


def _classify(device: Any) -> str:
    """Map an OpenRazer device's `type` to a canonical class label.

    Args:
        device: An OpenRazer device object exposing a `type` attribute.

    Returns:
        One of 'keyboard', 'mouse', 'mat', 'other'. Unknown types fall
        back to 'other'.
    """
    raw = getattr(device, "type", "") or ""
    return DEVICE_CLASS_MAP.get(raw.lower(), "other")


def find_devices() -> list[DeviceHandle]:
    """Enumerate every OpenRazer device with per-key matrix support.

    Allocates per-device float32 and uint8 buffers so render and write paths
    stay zero-allocation. Devices that advertise advanced FX but report a
    zero-sized matrix are skipped with a stderr warning.

    Returns:
        List of `DeviceHandle` for each matrix-capable device, in the order
        reported by `DeviceManager.devices`.
    """
    manager = DeviceManager()
    manager.sync_effects = False

    handles: list[DeviceHandle] = []
    for device in manager.devices:
        if not device.fx.advanced:
            continue
        adv = device.fx.advanced
        rows = int(getattr(adv, "rows", 0) or 0)
        cols = int(getattr(adv, "cols", 0) or 0)
        if rows <= 0 or cols <= 0:
            name = getattr(device, "name", repr(device))
            print(
                f"razer-effect: device {name!r} reports zero-sized matrix "
                f"({rows}x{cols}); skipping",
                file=sys.stderr,
            )
            continue
        handles.append(
            DeviceHandle(
                device=device,
                adv=adv,
                rows=rows,
                cols=cols,
                device_class=_classify(device),
                canvas=np.empty((rows, cols, 3), dtype=np.float32),
                rgb_buf=np.empty((rows, cols, 3), dtype=np.uint8),
            )
        )
    return handles


def find_device() -> Any:
    """Find a single Razer device for legacy single-device callers.

    Preserves v1 behaviour: prefers the first enumerated keyboard, otherwise
    returns the first matrix-capable device. Exits the process if none are
    available.

    Returns:
        The OpenRazer device object backing the first available handle.

    Raises:
        SystemExit: If no matrix-capable device is found.
    """
    handles = find_devices()
    if not handles:
        print("No Razer device with per-key matrix support found.", file=sys.stderr)
        sys.exit(1)
    keyboards = [h for h in handles if h.device_class == "keyboard"]
    return (keyboards[0] if keyboards else handles[0]).device


_rescan_flag = False


def request_rescan() -> None:
    """Mark the rescan flag so the next tick re-enumerates devices.

    Safe to call from a signal handler — only toggles a module-level bool.
    """
    global _rescan_flag
    _rescan_flag = True


def consume_rescan_request() -> bool:
    """Read-and-clear the rescan flag.

    Returns:
        True if a rescan was requested since the last call; False otherwise.
    """
    global _rescan_flag
    flag = _rescan_flag
    _rescan_flag = False
    return flag


def _device_key(device: Any) -> str:
    """Compute a stable identity key for a device across rescans.

    Args:
        device: OpenRazer device object.

    Returns:
        The device serial when available, else the device name, else its repr.
    """
    return getattr(device, "serial", None) or getattr(device, "name", repr(device))


def rescan_devices(existing: list[DeviceHandle]) -> list[DeviceHandle]:
    """Refresh the device list while preserving handles for unchanged devices.

    Devices identified by the same key as an existing handle keep their
    buffers (and any effect state keyed on them by the caller). New devices
    receive freshly allocated handles. Disconnected devices are dropped.

    Args:
        existing: The current list of handles.

    Returns:
        A new list reflecting the live device set, preserving existing
        handle identity wherever possible.
    """
    existing_by_key = {_device_key(h.device): h for h in existing}
    fresh = find_devices()
    result: list[DeviceHandle] = []
    for h in fresh:
        prior = existing_by_key.get(_device_key(h.device))
        result.append(prior if prior is not None else h)
    return result


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
