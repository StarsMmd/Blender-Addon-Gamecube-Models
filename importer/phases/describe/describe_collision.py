"""Phase 4 (collision): CCD structures → IRCollisionScene.

Drops what the format can recompute (poly normals, the XZ lookup grid), welds
the per-poly corner triples into indexed meshes, decodes the metadata
halfwords into named gameplay fields, and reduces the NPC wall mesh to its
difference from the player wall mesh.

Pure — no bpy, no mutation of the input structures.
"""
from collections import Counter

try:
    from ....shared.helpers.logger import StubLogger
    from ....shared.helpers.scale import GC_TO_METERS
    from ....shared.IR.collision import (
        IRCollisionScene, IRCollisionEntry, IRCollisionMesh, IRCollisionFace,
    )
    from ....shared.Constants.collision import (
        CollisionSubsystem, SUBSYSTEM_ORDER, EDGE_MASK_ALL,
    )
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger
    from shared.helpers.scale import GC_TO_METERS
    from shared.IR.collision import (
        IRCollisionScene, IRCollisionEntry, IRCollisionMesh, IRCollisionFace,
    )
    from shared.Constants.collision import (
        CollisionSubsystem, SUBSYSTEM_ORDER, EDGE_MASK_ALL,
    )


def describe_collision(ccd_file, logger=StubLogger()):
    """Convert a parsed collision database into the collision IR.

    In: ccd_file (CCDFile from parse_collision); logger (Logger).
    Out: IRCollisionScene.
    """
    entries = []
    mirrored = standalone = extra_polys = duplicates = 0

    for ccd_entry in ccd_file.entries:
        npc_polys, npc_shares_walls = _reduce_npc_walls(
            ccd_entry.meshes.get(CollisionSubsystem.WALL),
            ccd_entry.meshes.get(CollisionSubsystem.NPC_WALL),
        )
        if ccd_entry.meshes.get(CollisionSubsystem.NPC_WALL) is not None:
            if npc_shares_walls:
                mirrored += 1
                extra_polys += len(npc_polys)
            else:
                standalone += 1

        meshes = []
        for subsystem in SUBSYSTEM_ORDER:
            ccd_mesh = ccd_entry.meshes.get(subsystem)
            if ccd_mesh is None:
                continue
            polys = ccd_mesh.polys
            if subsystem is CollisionSubsystem.NPC_WALL:
                polys = npc_polys
                if not polys:
                    # Every NPC wall is already a player wall — the flag on the
                    # entry carries the whole mesh, so nothing to build.
                    continue
            vertices, faces, split = _weld(polys)
            duplicates += split
            meshes.append(IRCollisionMesh(
                subsystem=subsystem,
                vertices=vertices,
                faces=_describe_faces(subsystem, polys, faces),
            ))

        entries.append(IRCollisionEntry(
            index=ccd_entry.index,
            meshes=meshes,
            position=tuple(axis * GC_TO_METERS for axis in ccd_entry.position),
            rotation=ccd_entry.rotation,
            scale=ccd_entry.scale,
            is_dynamic=ccd_entry.is_dynamic,
            npc_shares_walls=npc_shares_walls,
        ))

    logger.info("  Described %d collision entr%s: %d NPC wall mesh(es) mirror "
                "the player walls (%d extra poly(s)), %d stand alone",
                len(entries), "y" if len(entries) == 1 else "ies",
                mirrored, extra_polys, standalone)
    if duplicates:
        logger.debug("  %d poly(s) duplicate another triangle in the same mesh "
                     "and keep private vertices", duplicates)
    return IRCollisionScene(name=ccd_file.name, entries=entries)


def _reduce_npc_walls(wall_mesh, npc_mesh):
    """Reduce the NPC wall mesh to what it adds over the player wall mesh.

    In: wall_mesh (CCDMesh|None); npc_mesh (CCDMesh|None).
    Out: (polys, npc_shares_walls). When npc_shares_walls is True the returned
        polys are only the extras; otherwise they are the NPC mesh whole.
    """
    if npc_mesh is None:
        return [], False
    if wall_mesh is None:
        return list(npc_mesh.polys), False

    outstanding = Counter(_poly_key(poly) for poly in wall_mesh.polys)
    extras = []
    for poly in npc_mesh.polys:
        key = _poly_key(poly)
        if outstanding.get(key):
            outstanding[key] -= 1
        else:
            extras.append(poly)

    if any(outstanding.values()):
        # The NPC mesh leaves out at least one player wall, so it can't be
        # expressed as "the player walls plus extras" — keep it whole.
        return list(npc_mesh.polys), False
    return extras, True


def _poly_key(poly):
    """Identity of a poly for wall-set comparison: geometry plus edge mask."""
    return (poly.v0, poly.v1, poly.v2, poly.meta0)


def _weld(polys):
    """Weld per-poly corner triples into an indexed mesh, scaled to meters.

    A face whose welded corners repeat an earlier face's would be dropped as a
    duplicate when Blender validates the mesh, so those polys keep private
    vertices instead — the geometry is identical, the indices are not.

    In: polys (list[CCDPoly]).
    Out: (vertices, faces, private_count) where faces are index triples.
    """
    index_of = {}
    vertices = []
    faces = []
    claimed = set()
    private_count = 0

    for poly in polys:
        indices = []
        for vertex in poly.vertices:
            index = index_of.get(vertex)
            if index is None:
                index = len(vertices)
                vertices.append(_to_meters(vertex))
                index_of[vertex] = index
            indices.append(index)

        key = frozenset(indices)
        if len(key) < 3 or key in claimed:
            indices = []
            for vertex in poly.vertices:
                indices.append(len(vertices))
                vertices.append(_to_meters(vertex))
            key = frozenset(indices)
            private_count += 1

        claimed.add(key)
        faces.append(tuple(indices))

    return vertices, faces, private_count


def _to_meters(vertex):
    """Convert one GameCube-unit position to the IR's meters."""
    return tuple(axis * GC_TO_METERS for axis in vertex)


def _describe_faces(subsystem, polys, faces):
    """Decode each poly's metadata halfwords for one subsystem.

    In: subsystem (CollisionSubsystem); polys (list[CCDPoly]); faces (list of
        index triples, parallel to polys).
    Out: list[IRCollisionFace].
    """
    described = []
    for poly, indices in zip(polys, faces):
        face = IRCollisionFace(indices=indices)
        if subsystem in (CollisionSubsystem.WALL, CollisionSubsystem.NPC_WALL):
            face.edge_mask = poly.meta0 & EDGE_MASK_ALL
        elif subsystem is CollisionSubsystem.ZONE_TRIGGER:
            face.edge_mask = poly.meta0 & EDGE_MASK_ALL
            face.region_id = poly.meta1
        elif subsystem is CollisionSubsystem.BUTTON_TRIGGER:
            face.region_id = poly.meta0
        elif subsystem is CollisionSubsystem.WALK:
            # meta0's high byte holds the two layer nibbles, its low byte the
            # two surface/effect nibbles.
            face.layer_a = (poly.meta0 >> 12) & 0xF
            face.layer_b = (poly.meta0 >> 8) & 0xF
            face.surface_a = (poly.meta0 >> 4) & 0xF
            face.surface_b = poly.meta0 & 0xF
        described.append(face)
    return described
