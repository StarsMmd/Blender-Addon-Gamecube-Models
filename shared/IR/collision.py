"""Intermediate Representation for map collision.

A standalone IR root: collision is imported and exported on its own path and
never mixes with IRScene. Everything derivable is dropped — poly normals come
back from winding, the XZ lookup grid from the triangle bounds — leaving the
geometry plus the metadata that genuinely drives gameplay.

Coordinates follow the rest of the IR: Y-up world space, in meters.
"""
from __future__ import annotations
from dataclasses import dataclass, field

try:
    from ..Constants.collision import CollisionSubsystem, EDGE_MASK_ALL, WALK_LAYER_ANY
except (ImportError, SystemError):
    from shared.Constants.collision import (
        CollisionSubsystem, EDGE_MASK_ALL, WALK_LAYER_ANY,
    )


@dataclass
class IRCollisionFace:
    """One collision triangle.

    Which metadata applies depends on the owning mesh's subsystem; the fields
    that don't apply stay at their neutral defaults:

    - ``edge_mask``           WALL / NPC_WALL / ZONE_TRIGGER
    - ``region_id``           ZONE_TRIGGER / BUTTON_TRIGGER
    - ``layer_*`` / ``surface_*``  WALK
    """
    indices: tuple[int, int, int]
    # Which edges take part in the wall test: bit 0 = v0→v1, 1 = v1→v2,
    # 2 = v2→v0. An zone-trigger poly with no edges enabled is skipped
    # entirely.
    edge_mask: int = EDGE_MASK_ALL
    # Event/region ID, keyed with the room ID into common.rel's
    # InteractionPoints table.
    region_id: int = 0
    # The two 4-bit floor layers this poly belongs to; WALK_LAYER_ANY matches
    # whichever layer the actor is currently on.
    layer_a: int = WALK_LAYER_ANY
    layer_b: int = WALK_LAYER_ANY
    # The two 4-bit surface/effect nibbles reported to gameplay (footstep
    # sounds, surface effects).
    surface_a: int = 0
    surface_b: int = 0


@dataclass
class IRCollisionMesh:
    """The triangles one entry feeds to one collision subsystem.

    Vertices are welded — the file stores three independent corners per poly,
    which is a storage detail, not geometry — and scaled from GameCube units
    to meters, like every other position in the IR.
    """
    subsystem: CollisionSubsystem
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    faces: list[IRCollisionFace] = field(default_factory=list)


@dataclass
class IRCollisionEntry:
    """One independently toggleable collision object.

    ``index`` is addressed from outside the file (doors, ``Collision.setEnabled``),
    so it is data rather than list position.

    ``npc_shares_walls`` records how the NPC wall mesh relates to the player one:
    when set, the NPC mesh is the player's walls *plus* whatever extra polys the
    NPC_WALL mesh holds (usually none, so no NPC_WALL mesh is emitted at all);
    when clear, any NPC_WALL mesh stands alone.
    """
    index: int
    meshes: list[IRCollisionMesh] = field(default_factory=list)
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    is_dynamic: bool = False
    npc_shares_walls: bool = False

    def mesh(self, subsystem):
        """Return this entry's mesh for a subsystem, or None."""
        for mesh in self.meshes:
            if mesh.subsystem is subsystem:
                return mesh
        return None


@dataclass
class IRCollisionScene:
    """Root of the collision IR. One per .ccd file."""
    name: str = ""
    entries: list[IRCollisionEntry] = field(default_factory=list)
