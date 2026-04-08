from __future__ import annotations
from dataclasses import dataclass, field

from .animation import IRKeyframe
from .enums import CameraProjection


@dataclass
class IRCameraKeyframes:
    """Decoded animation keyframes for one camera animation clip."""
    name: str
    eye_x: list[IRKeyframe] | None = None
    eye_y: list[IRKeyframe] | None = None
    eye_z: list[IRKeyframe] | None = None
    target_x: list[IRKeyframe] | None = None
    target_y: list[IRKeyframe] | None = None
    target_z: list[IRKeyframe] | None = None
    roll: list[IRKeyframe] | None = None
    fov: list[IRKeyframe] | None = None
    near: list[IRKeyframe] | None = None
    far: list[IRKeyframe] | None = None
    end_frame: float = 0.0
    loop: bool = False


@dataclass
class IRCamera:
    """A camera in the scene."""
    name: str
    projection: CameraProjection
    position: tuple[float, float, float] | None = None
    target_position: tuple[float, float, float] | None = None
    roll: float = 0.0
    near: float = 0.1
    far: float = 1000.0
    field_of_view: float = 60.0
    aspect: float = 1.333
    animations: list[IRCameraKeyframes] = field(default_factory=list)
