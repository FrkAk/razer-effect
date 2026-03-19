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
    """Build the effect registry.

    Returns:
        Mapping of effect names to their implementing classes.
    """
    from razer_effect.effects.key_shuffle import KeyShuffle
    from razer_effect.effects.static_color import StaticColor
    from razer_effect.effects.wave import Wave

    return {
        "key_shuffle": KeyShuffle,
        "static_color": StaticColor,
        "wave": Wave,
    }


EFFECTS: dict[str, type[Effect]] = _register()
