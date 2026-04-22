from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class BRUVLayer:
    name: str
    uvs: list[tuple[float, float]]


@dataclass
class BRColorLayer:
    name: str
    colors: list[tuple[float, float, float, float]]


@dataclass
class BRVertexGroup:
    """One Blender vertex group — name + per-vertex weights.

    Plan flattens IR's three SkinType variants (WEIGHTED / SINGLE_BONE /
    RIGID) into this uniform representation so build_blender doesn't need
    to switch on skin type.
    """
    name: str  # bone name the group is named after
    assignments: list[tuple[int, float]]  # (vertex_index, weight)


@dataclass
class BRMesh:
    """Geometry + metadata for one Blender mesh object."""
    name: str  # Blender object / mesh-data name
    mesh_key: str  # stable id shared with material animation tracks
    vertices: list[tuple[float, float, float]]
    faces: list[list[int]]
    uv_layers: list[BRUVLayer] = field(default_factory=list)
    color_layers: list[BRColorLayer] = field(default_factory=list)
    normals: list[tuple[float, float, float]] | None = None
    vertex_groups: list[BRVertexGroup] = field(default_factory=list)
    parent_bone_name: str | None = None  # records mesh → bone ownership
    is_hidden: bool = False
    shape_keys: list[object] = field(default_factory=list)  # IRShapeKey pass-through

    # Index into BRModel.materials, or None for a placeholder material.
    # Build phase resolves: identical material_index → same bpy material.
    material_index: int | None = None


@dataclass
class BRMeshInstance:
    """A copy of an existing mesh placed at a different bone.

    Corresponds to HSD's JOBJ_INSTANCE bones: one entry per (source mesh,
    target bone) pair.
    """
    source_mesh_index: int  # index into BRModel.meshes
    target_parent_bone_name: str
    matrix_local: list[list[float]]  # 4x4
