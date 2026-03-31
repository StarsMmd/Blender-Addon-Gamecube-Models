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
class IRSplinePath:
    """A spline curve that a bone follows.

    Generic representation: control points, curve type, and parameter keyframes.
    The build phase creates the target-specific curve object and constraint.
    """
    control_points: list[list[float]]     # 3D control points
    parameter_keyframes: list[IRKeyframe]  # path parameter over time
    curve_type: int = 0                    # 0=linear, 1=cubic bezier, 2=B-spline, 3=cardinal
    tension: float = 0.0                   # tension for cardinal splines
    num_control_points: int = 0            # original CV count (before type-specific extras)
    world_matrix: list[list[float]] | None = None  # 4x4 world matrix for curve positioning


@dataclass
class IRBoneTrack:
    """Decoded animation keyframes for one bone.

    Channels contain decoded keyframes (not compressed bytes, not target-baked).
    Keyframe values are raw per-channel SRT values from the source format.
    The build phase composes them via plain T @ R @ S (no format-specific corrections).

    The rest_local_matrix is a 4x4 matrix encoding the bone's rest-pose local
    transform with all format-specific corrections pre-applied (e.g. aligned
    scale inheritance from the source engine). The build phase uses it as:
        Bmtx = rest_local_matrix.inv() @ animated_SRT_matrix
    This keeps format-specific logic in the describe phase and lets the build
    phase work with generic matrices.

    For bones hidden at rest (near-zero scale), the rest_local_matrix uses a
    "visible scale" discovered by scanning animation keyframes, ensuring the
    inverse is numerically stable.
    """
    bone_name: str
    bone_index: int
    rotation: list[list[IRKeyframe]]  # [X, Y, Z] channels
    location: list[list[IRKeyframe]]  # [X, Y, Z] channels
    scale: list[list[IRKeyframe]]     # [X, Y, Z] channels
    # Rest-pose local matrix (4x4) with format-specific corrections pre-applied.
    # The build phase inverts this and multiplies by the animated T@R@S matrix.
    rest_local_matrix: list[list[float]] | None = None
    # Raw rest-pose SRT — used to fill missing animation channels with constants
    rest_rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rest_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rest_scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    end_frame: float = 0  # animation duration from the source Animation object
    # Path animation — bone follows a spline curve (mutually exclusive with SRT location)
    spline_path: IRSplinePath | None = None


@dataclass
class IRBoneAnimationSet:
    """One complete animation set (bone + optional paired material animations)."""
    name: str
    tracks: list[IRBoneTrack] = field(default_factory=list)
    material_tracks: list[IRMaterialTrack] = field(default_factory=list)
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
class IRShapeTrack:
    """Blend weight keyframes for one morph target."""
    bone_name: str
    keyframes: list[IRKeyframe] = field(default_factory=list)


@dataclass
class IRShapeAnimationSet:
    """Morph target / blend shape animation set."""
    name: str
    tracks: list[IRShapeTrack] = field(default_factory=list)
