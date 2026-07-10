from __future__ import annotations
from dataclasses import dataclass, field

from .enums import ScaleInheritance


@dataclass
class IRBoneSpline:
    """A curve carried by a JOBJ_SPLINE joint (HSD_Spline).

    Fields mirror the Spline node verbatim. Control points (`control_points`,
    the `s1` cv array), `knots` (`s2`), and `coefficients` (`s3`, per-segment
    polynomial coefficients for linear/cardinal splines) are kept in the
    game's native GC units — no meters conversion — so the raw values round-
    trip exactly. `flags` high byte selects the spline type (0 linear,
    1 cubic-bezier, 2 B-spline, 3 cardinal).
    """
    flags: int
    n: int
    f0: float
    f1: float
    control_points: list[list[float]] = field(default_factory=list)
    knots: list[float] | None = None
    coefficients: list[list[float]] | None = None


@dataclass
class IRBone:
    """One bone in a flat list. Parent relationship via index."""
    name: str
    parent_index: int | None
    # Rest-pose transform
    position: tuple[float, float, float]
    rotation: tuple[float, float, float]  # Euler XYZ radians
    scale: tuple[float, float, float]
    inverse_bind_matrix: list[list[float]] | None  # 4x4 matrix or None
    # Flags
    flags: int
    is_hidden: bool
    inherit_scale: ScaleInheritance
    ik_shrink: bool
    # Pre-computed transforms (all 4x4 matrices stored as list[list[float]])
    world_matrix: list[list[float]]
    local_matrix: list[list[float]]
    normalized_world_matrix: list[list[float]]
    normalized_local_matrix: list[list[float]]
    scale_correction: list[list[float]]
    accumulated_scale: tuple[float, float, float]
    # Geometry binding
    mesh_indices: list[int] = field(default_factory=list)
    # Instancing
    instance_child_bone_index: int | None = None
    # JOBJ_SPLINE curve carried as the joint's `property` (maps only)
    spline: IRBoneSpline | None = None


@dataclass
class IRModel:
    """One skeleton with its geometry, materials, and animations."""
    name: str
    bones: list[IRBone] = field(default_factory=list)
    meshes: list = field(default_factory=list)  # list[IRMesh]
    bone_animations: list = field(default_factory=list)  # list[IRBoneAnimationSet]
    shape_animations: list = field(default_factory=list)  # list[IRShapeAnimationSet]
    # Constraints
    ik_constraints: list = field(default_factory=list)
    copy_location_constraints: list = field(default_factory=list)
    track_to_constraints: list = field(default_factory=list)
    copy_rotation_constraints: list = field(default_factory=list)
    limit_rotation_constraints: list = field(default_factory=list)
    limit_location_constraints: list = field(default_factory=list)
    # Particles
    particles: object = None  # IRParticleSystem or None
