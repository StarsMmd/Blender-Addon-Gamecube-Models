from __future__ import annotations
from dataclasses import dataclass

from .enums import LightType


@dataclass
class IRLight:
    """A light source in the scene."""
    name: str
    type: LightType
    color: tuple[float, float, float]
    position: tuple[float, float, float] | None = None
    target_position: tuple[float, float, float] | None = None
    coordinate_rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
