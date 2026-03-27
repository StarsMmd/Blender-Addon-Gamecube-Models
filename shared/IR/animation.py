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
    """Decoded animation keyframes for one bone in HSD world-space SRT.

    Channels contain decoded keyframes (not compressed bytes, not Blender-baked).
    The target-specific baking (e.g. Blender scale correction + Euler decomposition)
    happens in the build phase.
    """
    bone_name: str
    bone_index: int
    rotation: list[list[IRKeyframe]]  # [X, Y, Z] channels
    location: list[list[IRKeyframe]]  # [X, Y, Z] channels
    scale: list[list[IRKeyframe]]     # [X, Y, Z] channels
    # Rest pose (needed by build phase for baking)
    rest_rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rest_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rest_scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    parent_accumulated_scale: tuple[float, float, float] | None = None
    end_frame: float = 0  # animation duration from the source Animation object
    # Path animation (mutually exclusive with SRT location channels)
    path_keyframes: list[IRKeyframe] | None = None
    spline_points: list[list[float]] | None = None
    spline_type: int = 0       # 0=linear, 1=cubic bezier, 2=B-spline, 3=cardinal
    spline_tension: float = 0.0  # tension for cardinal splines
    spline_num_cvs: int = 0    # original control point count (before type-specific extras)
    spline_world_matrix: list[list[float]] | None = None  # 4x4 world matrix of the spline joint


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
