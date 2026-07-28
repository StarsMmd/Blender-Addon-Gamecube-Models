"""In-memory mirror of the .ccd binary layout — one dataclass per on-disk
structure.

This is the collision equivalent of the DAT node tree: a faithful, lossless
view of the file with no interpretation beyond field naming. Derived data
(poly normals, the XZ lookup grid) is kept here rather than dropped, so a
writer can be checked against what the original tool emitted; the IR discards
it because both are recomputable.

Pure data — no bpy, no mathutils.
"""
from __future__ import annotations
from dataclasses import dataclass, field

try:
    from ..Constants.collision import (
        CollisionSubsystem, CCD_ENTRY_FLAG_DYNAMIC,
        CCD_POLY_SIZE, CCD_SUN_POLY_SIZE,
    )
except (ImportError, SystemError):
    from shared.Constants.collision import (
        CollisionSubsystem, CCD_ENTRY_FLAG_DYNAMIC,
        CCD_POLY_SIZE, CCD_SUN_POLY_SIZE,
    )


@dataclass
class CCDPoly:
    """One collision triangle (0x34 bytes, 0x30 for sun polys).

    Vertices are world-space and Y-up, exactly as stored. ``normal`` is
    derived — ``normalize(cross(v1 - v0, v2 - v0))`` reproduces every poly in
    the shipped corpus, including the NaN normals of zero-area triangles.
    ``meta0`` / ``meta1`` are the raw halfwords; their meaning depends on the
    owning mesh's subsystem and is decoded by the describe leg.
    """
    v0: tuple[float, float, float]
    v1: tuple[float, float, float]
    v2: tuple[float, float, float]
    normal: tuple[float, float, float] = (0.0, 0.0, 0.0)
    meta0: int = 0
    meta1: int = 0

    @property
    def vertices(self):
        """The three corners as a tuple, in winding order."""
        return (self.v0, self.v1, self.v2)


@dataclass
class CCDMeshGrid:
    """The XZ lookup grid of a gridded mesh — derived, recomputable.

    Cells are row-major (``cells[z * width + x]``); each holds a slice
    ``(offset, count)`` of the shared index pool listing the polys that
    overlap it. A poly spanning several cells appears in each.
    """
    width: int = 0
    height: int = 0
    cell_size_x: float = 0.0
    cell_size_z: float = 0.0
    origin_x: float = 0.0
    origin_z: float = 0.0
    cells: list[tuple[int, int]] = field(default_factory=list)
    index_pool: list[int] = field(default_factory=list)


@dataclass
class CCDMesh:
    """One subsystem's triangle mesh within an entry."""
    subsystem: CollisionSubsystem
    polys: list[CCDPoly] = field(default_factory=list)
    grid: CCDMeshGrid | None = None   # None for the two non-gridded subsystems

    @property
    def poly_size(self):
        """On-disk stride of this mesh's polys, in bytes."""
        if self.subsystem is CollisionSubsystem.SUN:
            return CCD_SUN_POLY_SIZE
        return CCD_POLY_SIZE


@dataclass
class CCDEntry:
    """One collision object: a transform plus up to six subsystem meshes.

    Entries are referenced by index from outside the file — common.rel's Doors
    table and the ``Collision.setEnabled`` script call both address them that
    way — so the index is part of the data, not just list position.
    """
    index: int
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    flags: int = 0
    meshes: dict[CollisionSubsystem, CCDMesh] = field(default_factory=dict)

    @property
    def is_dynamic(self):
        """True when the runtime re-applies this entry's transform per frame."""
        return bool(self.flags & CCD_ENTRY_FLAG_DYNAMIC)


@dataclass
class CCDFile:
    """Root of the parsed collision database. One per .ccd."""
    name: str = ""
    entries: list[CCDEntry] = field(default_factory=list)
