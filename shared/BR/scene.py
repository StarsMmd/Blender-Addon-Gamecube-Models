from __future__ import annotations
from dataclasses import dataclass, field

from .armature import BRArmature
from .meshes import BRMesh, BRMeshInstance
from .actions import BRAction
from .materials import BRMaterial
from .lights import BRLight
from .cameras import BRCamera
from .constraints import BRConstraints, BRParticleSummary


@dataclass
class BRModel:
    """One armature + its associated Blender-side data. Fully BR — no IR
    access required by build_blender on the planned path."""
    name: str
    armature: BRArmature
    meshes: list[BRMesh] = field(default_factory=list)
    mesh_instances: list[BRMeshInstance] = field(default_factory=list)
    actions: list[BRAction] = field(default_factory=list)
    materials: list[BRMaterial] = field(default_factory=list)
    constraints: BRConstraints = field(default_factory=BRConstraints)
    particles: BRParticleSummary | None = None


@dataclass
class BRScene:
    """Top-level Plan-phase output consumed by build_blender."""
    models: list[BRModel] = field(default_factory=list)
    lights: list[BRLight] = field(default_factory=list)
    cameras: list[BRCamera] = field(default_factory=list)
