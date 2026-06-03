from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class BRCameraAnimation:
    """Pre-converted camera animation keyframes.

    Positions are already in Blender Z-up space; ``lens`` values are
    focal-length in mm (FOV→lens conversion done in Plan); clip values
    are straight pass-through.
    """
    name: str
    loc_x: list = field(default_factory=list)   # list[IRKeyframe], values in BR space
    loc_y: list = field(default_factory=list)
    loc_z: list = field(default_factory=list)
    roll: list = field(default_factory=list)
    lens: list = field(default_factory=list)
    clip_start: list = field(default_factory=list)
    clip_end: list = field(default_factory=list)
    target_loc_x: list = field(default_factory=list)
    target_loc_y: list = field(default_factory=list)
    target_loc_z: list = field(default_factory=list)
    end_frame: float = 0.0
    loop: bool = False


@dataclass
class BRCamera:
    """One Blender camera + data block spec."""
    name: str
    projection: str  # 'PERSP' / 'ORTHO'
    # For PERSP: lens in mm. For ORTHO: the lens field holds ortho_scale.
    lens: float
    sensor_height: float
    clip_start: float
    clip_end: float
    aspect: float
    location: tuple[float, float, float] | None = None
    target_location: tuple[float, float, float] | None = None
    animations: list[BRCameraAnimation] = field(default_factory=list)
