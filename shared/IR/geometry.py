from __future__ import annotations
from dataclasses import dataclass, field

from .enums import SkinType


@dataclass
class IRMesh:
    """One geometry batch with its material."""
    name: str
    vertices: list[tuple[float, float, float]]
    faces: list[list[int]]
    uv_layers: list[IRUVLayer] = field(default_factory=list)
    color_layers: list[IRColorLayer] = field(default_factory=list)
    normals: list[tuple[float, float, float]] | None = None
    material: object = None  # IRMaterial, typed loosely to avoid circular import
    bone_weights: IRBoneWeights | None = None
    shape_keys: list[IRShapeKey] | None = None
    is_hidden: bool = False
    parent_bone_index: int = 0
    local_matrix: list[list[float]] | None = None
    cull_front: bool = False
    cull_back: bool = False
    # Opaque stable identifier used for cross-references (e.g.
    # IRMaterialTrack.material_mesh_name → this id). Not for display.
    # Minted at describe time and preserved through plan / merge /
    # compose so foreign keys stay valid even if mesh ordering changes.
    # Default None means "not yet assigned" — tests and legacy code
    # that don't construct material-anim references can leave it unset.
    id: str | None = None


@dataclass
class IRUVLayer:
    """One UV coordinate layer."""
    name: str
    uvs: list[tuple[float, float]]


@dataclass
class IRColorLayer:
    """One vertex color or alpha layer."""
    name: str
    colors: list[tuple[float, float, float, float]]


@dataclass
class IRBoneWeights:
    """Vertex-to-bone weight assignments for mesh skinning."""
    type: SkinType
    # For WEIGHTED: per-vertex bone assignments
    assignments: list[tuple[int, list[tuple[str, float]]]] | None = None
    # For SINGLE_BONE/RIGID: single bone name
    bone_name: str | None = None
    # Pre-computed deformed geometry
    deformed_vertices: list[tuple[float, float, float]] | None = None
    deformed_normals: list[tuple[float, float, float]] | None = None


@dataclass
class IRShapeKey:
    """One morph target / blend shape."""
    name: str
    vertex_positions: list[tuple[float, float, float]]
