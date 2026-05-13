"""Layered composition of per-key RGB effects.

Provides the data structures and blend math that turn multiple `Effect`
instances into a single (rows, cols, 3) float32 canvas. Each handle owns one
`LayerStack` capped at `MAX_LAYERS`; `blend` walks the stack bottom-to-top and
alpha-composites in place using pre-allocated buffers.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from razer_effect.config import MAX_LAYERS

if TYPE_CHECKING:
    from collections.abc import Iterator

    import numpy.typing as npt

    from razer_effect.device import DeviceHandle


@dataclass
class Layer:
    """One slot of the layered render stack.

    Attributes:
        effect: An initialized effect instance (already `setup` on this slot).
        effect_name: Registry key of the effect; used for reload diffing.
        opacity: Alpha in [0.0, 1.0]; clamped at construction.
        enabled: When False the layer is skipped during blend.
        scratch: Pre-allocated (rows, cols, 3) float32 buffer the effect
            renders into. Owned by the layer for the lifetime of the stack so
            blend operates with zero per-tick allocations.
    """

    effect: Any
    effect_name: str
    opacity: float
    enabled: bool
    scratch: npt.NDArray[np.float32] = field(repr=False)

    def __post_init__(self) -> None:
        """Clamp opacity into [0.0, 1.0] as defense-in-depth.

        Returns:
            None.
        """
        self.opacity = max(0.0, min(1.0, float(self.opacity)))


class LayerStack:
    """Per-handle stack of Layers bounded by `MAX_LAYERS`.

    Owns a single `_blend_tmp` scratch buffer reused on every blend so the
    composite path stays allocation-free.
    """

    def __init__(self, rows: int, cols: int) -> None:
        """Allocate the per-stack scratch buffer for a given matrix shape.

        Args:
            rows: Matrix row count.
            cols: Matrix column count.
        """
        self.rows = rows
        self.cols = cols
        self.layers: list[Layer] = []
        self._blend_tmp: npt.NDArray[np.float32] = np.empty(
            (rows, cols, 3), dtype=np.float32
        )

    def append(self, layer: Layer) -> None:
        """Append a layer to the stack.

        Args:
            layer: The Layer to add at the top of the stack.

        Raises:
            ValueError: If the stack already holds `MAX_LAYERS` layers. The
                cap is documented in `razer_effect.config.MAX_LAYERS` and is
                fixed at 4 for v2.
        """
        if len(self.layers) >= MAX_LAYERS:
            raise ValueError(f"LayerStack cannot exceed MAX_LAYERS={MAX_LAYERS} layers")
        self.layers.append(layer)

    def clear(self) -> None:
        """Drop every layer reference; the `_blend_tmp` buffer is retained."""
        self.layers.clear()

    def __len__(self) -> int:
        """Return the number of layers in the stack."""
        return len(self.layers)

    def __iter__(self) -> Iterator[Layer]:
        """Iterate over layers bottom-to-top."""
        return iter(self.layers)

    def __getitem__(self, index: int) -> Layer:
        """Index into the stack.

        Args:
            index: Position in the stack (0 is bottom).

        Returns:
            The Layer at that index.
        """
        return self.layers[index]

    def active(self, device_class: str) -> Iterator[Layer]:
        """Yield layers eligible to render on the given device class.

        Args:
            device_class: One of 'keyboard', 'mouse', 'mat', 'other'.

        Returns:
            Iterator over enabled layers whose effect's `DEVICE_CLASSES` is
            None or contains `device_class`.
        """
        for layer in self.layers:
            if not layer.enabled:
                continue
            classes = getattr(layer.effect, "DEVICE_CLASSES", None)
            if classes is None or device_class in classes:
                yield layer

    def is_all_static(self, device_class: str) -> bool:
        """Check whether every active layer is marked STATIC.

        Args:
            device_class: Device class to filter active layers by.

        Returns:
            True iff at least one active layer exists and all of them are
            STATIC. An empty active set returns False so the loop ticks at
            fps and eventually rebuilds if the config changes.
        """
        any_active = False
        for layer in self.active(device_class):
            any_active = True
            if not getattr(layer.effect, "STATIC", False):
                return False
        return any_active


def blend(
    canvas: npt.NDArray[np.float32],
    stack: LayerStack,
    dt: float,
    device_class: str,
) -> bool:
    """Composite a `LayerStack` into `canvas` in place.

    Walks active layers bottom-to-top. The first active layer is copied into
    `canvas` scaled by its opacity; each subsequent layer is src-over blended:
    `canvas = canvas * (1 - opacity) + scratch * opacity`. All math runs
    in-place via `np.multiply(..., out=...)` and `np.add(..., out=...)` so no
    per-tick allocations occur. When no active layer remains the canvas is
    zeroed.

    Args:
        canvas: Destination buffer of shape (rows, cols, 3), float32.
        stack: The handle's LayerStack.
        dt: Seconds since the previous tick.
        device_class: Handle device class used to filter active layers.

    Returns:
        True if at least one active layer contributed to the canvas; False
        when no layer was eligible (caller may skip the device write).
    """
    drew = False
    for layer in stack.active(device_class):
        layer.effect.render(dt, layer.scratch)
        if not drew:
            if layer.opacity >= 1.0:
                np.copyto(canvas, layer.scratch)
            else:
                np.multiply(layer.scratch, layer.opacity, out=canvas)
            drew = True
            continue

        if layer.opacity <= 0.0:
            continue
        if layer.opacity >= 1.0:
            np.copyto(canvas, layer.scratch)
            continue
        np.multiply(layer.scratch, layer.opacity, out=stack._blend_tmp)
        np.multiply(canvas, 1.0 - layer.opacity, out=canvas)
        np.add(canvas, stack._blend_tmp, out=canvas)

    if not drew:
        canvas.fill(0.0)
    return drew


def build_layer_stack(
    handle: DeviceHandle,
    profile: dict[str, Any],
    effect_registry: dict[str, type],
) -> LayerStack:
    """Construct a `LayerStack` for a handle from one v2 profile dict.

    Iterates over `profile['layers']`, instantiates each known effect,
    calls `effect.setup(handle.rows, handle.cols, params)` where `params`
    is the merged `profile['effect_params']` (so existing flat-keyed effect
    params keep working). Unknown effect names are logged to stderr and
    skipped.

    Args:
        handle: The DeviceHandle whose canvas this stack will composite into.
        profile: One entry from `cfg['profiles']` containing 'layers' and
            'effect_params'.
        effect_registry: Mapping of effect names to classes (`EFFECTS`).

    Returns:
        A populated LayerStack. Empty if the profile has zero recognizable
        enabled layers.
    """
    stack = LayerStack(handle.rows, handle.cols)
    params = dict(profile.get("effect_params", {}))
    for entry in profile.get("layers", []):
        name = entry.get("effect")
        effect_cls = effect_registry.get(name)
        if effect_cls is None:
            print(
                f"razer-effect: unknown effect {name!r} in profile; skipping layer",
                file=sys.stderr,
            )
            continue
        effect = effect_cls()
        effect.setup(handle.rows, handle.cols, params)
        scratch = np.empty((handle.rows, handle.cols, 3), dtype=np.float32)
        stack.append(
            Layer(
                effect=effect,
                effect_name=name,
                opacity=float(entry.get("opacity", 1.0)),
                enabled=bool(entry.get("enabled", True)),
                scratch=scratch,
            )
        )
    return stack
