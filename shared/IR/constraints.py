from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class IRBoneReposition:
    """Bone position offset applied during IK chain setup."""
    bone_name: str
    head_offset: tuple[float, float, float]
    tail_offset: tuple[float, float, float]


@dataclass
class IRIKConstraint:
    """Inverse kinematics constraint."""
    bone_name: str
    chain_length: int
    target_bone: str | None = None
    pole_target_bone: str | None = None
    pole_angle: float = 0.0
    bone_repositions: list[IRBoneReposition] = field(default_factory=list)


@dataclass
class IRCopyLocationConstraint:
    """Position tracking constraint."""
    bone_name: str
    target_bone: str
    influence: float = 1.0


@dataclass
class IRTrackToConstraint:
    """Aim / look-at constraint."""
    bone_name: str
    target_bone: str
    track_axis: str = "TRACK_X"
    up_axis: str = "UP_Y"


@dataclass
class IRCopyRotationConstraint:
    """Orientation tracking constraint."""
    bone_name: str
    target_bone: str
    owner_space: str = "WORLD"
    target_space: str = "WORLD"


@dataclass
class IRLimitConstraint:
    """Rotation or translation limit constraint."""
    bone_name: str
    owner_space: str = "LOCAL_WITH_PARENT"
    min_x: float | None = None
    max_x: float | None = None
    min_y: float | None = None
    max_y: float | None = None
    min_z: float | None = None
    max_z: float | None = None
