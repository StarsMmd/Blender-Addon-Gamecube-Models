from __future__ import annotations
from dataclasses import dataclass, field

from .armature import BRArmature
from .meshes import BRMesh, BRMeshInstance


@dataclass
class BRModel:
    """One armature + its associated Blender-side data.

    Mirrors IRModel's shape: grows stage by stage as Plan-phase coverage
    expands (armature + meshes done; actions, materials, constraints still
    consumed from IR by build_blender until their stages land).
    """
    name: str
    armature: BRArmature
    meshes: list[BRMesh] = field(default_factory=list)
    mesh_instances: list[BRMeshInstance] = field(default_factory=list)


@dataclass
class BRScene:
    """Top-level Plan-phase output consumed by build_blender."""
    models: list[BRModel] = field(default_factory=list)
