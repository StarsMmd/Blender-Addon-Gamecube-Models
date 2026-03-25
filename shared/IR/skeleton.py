from __future__ import annotations
from dataclasses import dataclass, field

from .enums import ScaleInheritance


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


@dataclass
class IRModel:
    """One skeleton with its geometry, materials, and animations."""
    name: str
    bones: list[IRBone] = field(default_factory=list)
    meshes: list = field(default_factory=list)  # list[IRMesh]
    bone_animations: list = field(default_factory=list)  # list[IRBoneAnimationSet] (future: fully baked)
    raw_bone_animations: list = field(default_factory=list)  # list[RawAnimationSet] (pre-baked, for Phase 5A)
    material_animations: list = field(default_factory=list)  # list[IRMaterialAnimationSet]
    shape_animations: list = field(default_factory=list)  # list[IRShapeAnimationSet]
    # Constraints
    ik_constraints: list = field(default_factory=list)
    copy_location_constraints: list = field(default_factory=list)
    track_to_constraints: list = field(default_factory=list)
    copy_rotation_constraints: list = field(default_factory=list)
    limit_rotation_constraints: list = field(default_factory=list)
    limit_location_constraints: list = field(default_factory=list)
    # Coordinate system transform
    coordinate_rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
