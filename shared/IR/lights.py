from __future__ import annotations
from dataclasses import dataclass, field

from .enums import LightType
from .animation import IRKeyframe


@dataclass
class IRLightKeyframes:
    """Decoded animation keyframes for one light animation clip.

    Mirrors the LightAnimation node: the LObj's own AOBJ carries colour
    (LITC_R/G/B/A), visibility, and cutoff tracks, while the eye/interest
    WObjectAnimations carry position tracks. A clip with every field None
    is an empty-but-present LightAnimation node (common in map archives).
    """
    name: str
    color_r: list[IRKeyframe] | None = None
    color_g: list[IRKeyframe] | None = None
    color_b: list[IRKeyframe] | None = None
    color_a: list[IRKeyframe] | None = None
    visibility: list[IRKeyframe] | None = None
    cutoff: list[IRKeyframe] | None = None
    eye_x: list[IRKeyframe] | None = None
    eye_y: list[IRKeyframe] | None = None
    eye_z: list[IRKeyframe] | None = None
    target_x: list[IRKeyframe] | None = None
    target_y: list[IRKeyframe] | None = None
    target_z: list[IRKeyframe] | None = None
    end_frame: float = 0.0
    loop: bool = False


@dataclass
class IRLight:
    """A light source in the scene."""
    name: str
    type: LightType
    color: tuple[float, float, float]
    position: tuple[float, float, float] | None = None
    target_position: tuple[float, float, float] | None = None
    brightness: float = 1.0
    animations: list[IRLightKeyframes] = field(default_factory=list)
