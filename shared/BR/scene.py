from __future__ import annotations
from dataclasses import dataclass, field

from .armature import BRArmature
from .meshes import BRMesh, BRMeshInstance
from .actions import BRAction
from .materials import BRMaterial


@dataclass
class BRModel:
    """One armature + its associated Blender-side data.

    Mirrors IRModel's shape: armature, meshes, actions, and materials
    covered by Plan; constraints/lights/cameras/particles still consumed
    from IR by build_blender until their stages land.
    """
    name: str
    armature: BRArmature
    meshes: list[BRMesh] = field(default_factory=list)
    mesh_instances: list[BRMeshInstance] = field(default_factory=list)
    actions: list[BRAction] = field(default_factory=list)
    materials: list[BRMaterial] = field(default_factory=list)


@dataclass
class BRScene:
    """Top-level Plan-phase output consumed by build_blender."""
    models: list[BRModel] = field(default_factory=list)
