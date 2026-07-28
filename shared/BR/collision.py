"""Blender Representation for map collision.

Standalone root, mirroring the IR side: the collision path never mixes with
BRScene. Every value here is already a decided Blender value — object names,
custom-property keys, face-attribute names, linear RGBA, and the Y-up→Z-up
root transform — so the build leg is a mechanical bpy executor.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class BRCollisionMaterial:
    """One translucent viewport material, shared by every object of a type."""
    name: str
    color: tuple[float, float, float, float]   # linear RGB + alpha
    blend_method: str = 'BLEND'                # legacy EEVEE surface blending
    surface_render_method: str = 'BLENDED'     # EEVEE Next equivalent


@dataclass
class BRCollisionObject:
    """One collision mesh object."""
    name: str
    # Sub-collection this object is linked into — one per collision type, so a
    # type can be hidden or soloed on its own. Object parenting carries the
    # transform, not visibility; only collections hide their contents.
    collection_name: str = ""
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    faces: list[tuple[int, int, int]] = field(default_factory=list)
    # Per-face integer attributes, keyed by attribute name. One value per face.
    face_attributes: dict[str, list[int]] = field(default_factory=dict)
    # ID properties written verbatim onto the object.
    custom_props: dict[str, object] = field(default_factory=dict)
    material_index: int | None = None   # index into BRCollisionScene.materials
    matrix_basis: list[list[float]] | None = None   # 4x4, the entry's transform


@dataclass
class BRCollisionMarker:
    """An Empty standing in for an entry that carries no meshes.

    Entry indices are referenced from outside the file, so an empty entry still
    has to occupy its slot on the way back out.
    """
    name: str
    custom_props: dict[str, object] = field(default_factory=dict)
    matrix_basis: list[list[float]] | None = None


@dataclass
class BRCollisionScene:
    """Top-level plan output for one .ccd, consumed by build_collision."""
    name: str = ""
    root_name: str = ""
    # Collection holding the whole overlay — hiding it hides every mesh.
    collection_name: str = ""
    # Child collections, one per collision type present, in file slot order.
    subcollections: list[str] = field(default_factory=list)
    # 4x4 applied to the parent Empty: the GC Y-up → Blender Z-up rotation, so
    # the overlay lands on an imported map model without touching the geometry.
    root_matrix: list[list[float]] | None = None
    objects: list[BRCollisionObject] = field(default_factory=list)
    markers: list[BRCollisionMarker] = field(default_factory=list)
    materials: list[BRCollisionMaterial] = field(default_factory=list)
