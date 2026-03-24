from __future__ import annotations
from dataclasses import dataclass, field

from .enums import Interpolation


@dataclass
class IRKeyframe:
    """A single keyframe with interpolation data."""
    frame: float
    value: float
    interpolation: Interpolation
    handle_left: tuple[float, float] | None = None
    handle_right: tuple[float, float] | None = None


@dataclass
class IRBoneTrack:
    """Baked animation data for one bone, in bone-local space."""
    bone_name: str
    rotation: list[list[tuple[int, float]]]  # [X, Y, Z] Euler channels
    location: list[list[tuple[int, float]]]  # [X, Y, Z] location channels
    scale: list[list[tuple[int, float]]]  # [X, Y, Z] scale channels


@dataclass
class IRBoneAnimationSet:
    """One complete bone animation set."""
    name: str
    tracks: list[IRBoneTrack] = field(default_factory=list)
    loop: bool = False
    is_static: bool = False


@dataclass
class IRTextureUVTrack:
    """UV animation for one texture in a material."""
    texture_index: int
    translation_u: list[IRKeyframe] | None = None
    translation_v: list[IRKeyframe] | None = None
    scale_u: list[IRKeyframe] | None = None
    scale_v: list[IRKeyframe] | None = None
    rotation_x: list[IRKeyframe] | None = None
    rotation_y: list[IRKeyframe] | None = None
    rotation_z: list[IRKeyframe] | None = None


@dataclass
class IRMaterialTrack:
    """Animation tracks for a single material."""
    material_mesh_name: str
    diffuse_r: list[IRKeyframe] | None = None
    diffuse_g: list[IRKeyframe] | None = None
    diffuse_b: list[IRKeyframe] | None = None
    alpha: list[IRKeyframe] | None = None
    texture_uv_tracks: list[IRTextureUVTrack] = field(default_factory=list)
    loop: bool = False


@dataclass
class IRMaterialAnimationSet:
    """One material animation set."""
    name: str
    tracks: list[IRMaterialTrack] = field(default_factory=list)


@dataclass
class IRShapeTrack:
    """Blend weight keyframes for one morph target."""
    bone_name: str
    keyframes: list[IRKeyframe] = field(default_factory=list)


@dataclass
class IRShapeAnimationSet:
    """Morph target / blend shape animation set."""
    name: str
    tracks: list[IRShapeTrack] = field(default_factory=list)
