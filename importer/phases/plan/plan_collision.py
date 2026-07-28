"""Phase 5 (collision): IRCollisionScene → BRCollisionScene.

Owns every Blender-side decision for the collision overlay: object naming and
grouping, which metadata becomes an object property and which becomes a
per-face attribute, the translucent colour per subsystem, and the Y-up→Z-up
root transform. Pure — no bpy, no mutation of the input IR.
"""

try:
    from ....shared.helpers.logger import StubLogger
    from ....shared.helpers.srgb import srgb_to_linear
    from ....shared.helpers.math_shim import compile_srt_matrix, matrix_to_list
    from ....shared.BR.collision import (
        BRCollisionScene, BRCollisionObject, BRCollisionMarker,
        BRCollisionMaterial,
    )
    from ....shared.Constants.collision import (
        CollisionSubsystem, SUBSYSTEM_ORDER, SUBSYSTEM_LABELS,
        REGION_SUBSYSTEMS,
    )
    from .helpers.armature import Y_UP_TO_Z_UP
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger
    from shared.helpers.srgb import srgb_to_linear
    from shared.helpers.math_shim import compile_srt_matrix, matrix_to_list
    from shared.BR.collision import (
        BRCollisionScene, BRCollisionObject, BRCollisionMarker,
        BRCollisionMaterial,
    )
    from shared.Constants.collision import (
        CollisionSubsystem, SUBSYSTEM_ORDER, SUBSYSTEM_LABELS,
        REGION_SUBSYSTEMS,
    )
    from importer.phases.plan.helpers.armature import Y_UP_TO_Z_UP

# Object custom-property keys. `dat_col_entry` is the grouping key on the way
# back out — object names are display labels and Blender may suffix them.
PROP_TYPE = "dat_col_type"
PROP_ENTRY = "dat_col_entry"
PROP_REGION = "dat_col_region"
PROP_NPC_BLOCKS = "dat_col_npc_blocks"
PROP_DYNAMIC = "dat_col_dynamic"

# Per-face integer attribute names.
ATTR_EDGE_MASK = "col_edge_mask"
ATTR_LAYER_A = "col_layer_a"
ATTR_LAYER_B = "col_layer_b"
ATTR_SURFACE_A = "col_surface_a"
ATTR_SURFACE_B = "col_surface_b"

# Region-bearing meshes are split so one object carries exactly one region,
# which is also how the game's script side addresses them.

# Viewport colours, authored in sRGB and linearised below.
_SUBSYSTEM_COLORS = {
    CollisionSubsystem.WALK: (0.15, 0.80, 0.25),
    CollisionSubsystem.WALL: (0.90, 0.10, 0.10),
    CollisionSubsystem.ZONE_TRIGGER: (0.15, 0.40, 1.00),
    CollisionSubsystem.BUTTON_TRIGGER: (1.00, 0.90, 0.10),
    CollisionSubsystem.NPC_WALL: (1.00, 0.50, 0.05),
    CollisionSubsystem.SUN: (1.00, 1.00, 1.00),
}
# Per-type opacity. Walls read more solid than the floor they stand on, and
# triggers — the thing you actually author — read strongest of all.
_SUBSYSTEM_ALPHA = {
    CollisionSubsystem.WALK: 0.3,
    CollisionSubsystem.WALL: 0.5,
    CollisionSubsystem.NPC_WALL: 0.5,
    CollisionSubsystem.ZONE_TRIGGER: 0.7,
    CollisionSubsystem.BUTTON_TRIGGER: 0.7,
    CollisionSubsystem.SUN: 0.3,
}


def plan_collision(ir_collision, options=None, logger=StubLogger()):
    """Convert a collision IR scene into its Blender build plan.

    In: ir_collision (IRCollisionScene); options (dict|None, unused today);
        logger (Logger).
    Out: BRCollisionScene.
    """
    name = ir_collision.name or "collision"
    materials = []
    material_indices = {}
    objects = []
    markers = []

    for entry in ir_collision.entries:
        matrix_basis = _entry_matrix(entry)
        if not entry.meshes:
            markers.append(BRCollisionMarker(
                name="Col_%s_%02d" % (name, entry.index),
                custom_props={
                    PROP_ENTRY: entry.index,
                    PROP_DYNAMIC: entry.is_dynamic,
                },
                matrix_basis=matrix_basis,
            ))
            continue

        for mesh in entry.meshes:
            for region_id, faces in _split_by_region(mesh):
                objects.append(_plan_object(
                    name, entry, mesh, region_id, faces, matrix_basis,
                    _material_index(mesh.subsystem, materials, material_indices),
                ))

    logger.info("  Planned collision '%s': %d object(s), %d entry marker(s), "
                "%d material(s)", name, len(objects), len(markers), len(materials))
    return BRCollisionScene(
        name=name,
        root_name="Collision_%s" % name,
        collection_name="Collision_%s" % name,
        subcollections=_subcollections(name, objects),
        root_matrix=Y_UP_TO_Z_UP,
        objects=objects,
        markers=markers,
        materials=materials,
    )


def _subcollection_name(scene_name, subsystem):
    """Name of the per-type sub-collection an object is filed under."""
    return "Collision_%s_%s" % (scene_name, SUBSYSTEM_LABELS[subsystem])


def _subcollections(scene_name, objects):
    """The sub-collections in use, in file slot order.

    In: scene_name (str); objects (list[BRCollisionObject]).
    Out: list[str], each name appearing once, empty types omitted.
    """
    used = {obj.collection_name for obj in objects}
    return [name for name in
            (_subcollection_name(scene_name, subsystem)
             for subsystem in SUBSYSTEM_ORDER)
            if name in used]


def _plan_object(scene_name, entry, mesh, region_id, faces, matrix_basis,
                 material_index):
    """Build one BRCollisionObject from a mesh, or from one region of it."""
    subsystem = mesh.subsystem
    vertices, indices = _compact(mesh.vertices, faces)

    custom_props = {
        PROP_TYPE: subsystem.value,
        PROP_ENTRY: entry.index,
        PROP_DYNAMIC: entry.is_dynamic,
    }
    if region_id is not None:
        custom_props[PROP_REGION] = region_id
    if subsystem is CollisionSubsystem.WALL:
        custom_props[PROP_NPC_BLOCKS] = entry.npc_shares_walls

    suffix = "" if region_id is None else "_r%d" % region_id
    return BRCollisionObject(
        name="Col_%s_%02d_%s%s" % (
            scene_name, entry.index, subsystem.value.lower(), suffix),
        collection_name=_subcollection_name(scene_name, subsystem),
        vertices=vertices,
        faces=indices,
        face_attributes=_face_attributes(subsystem, faces),
        custom_props=custom_props,
        material_index=material_index,
        matrix_basis=matrix_basis,
    )


def _split_by_region(mesh):
    """Group a mesh's faces into the objects it should become.

    Region-bearing subsystems yield one group per region ID, ascending, so the
    ID lives on the object instead of on every face. Everything else yields a
    single group.

    In: mesh (IRCollisionMesh).
    Out: list[tuple[region_id|None, list[IRCollisionFace]]].
    """
    if mesh.subsystem not in REGION_SUBSYSTEMS:
        return [(None, list(mesh.faces))]

    grouped = {}
    for face in mesh.faces:
        grouped.setdefault(face.region_id, []).append(face)
    return [(region_id, grouped[region_id]) for region_id in sorted(grouped)]


def _compact(vertices, faces):
    """Re-index a subset of faces onto only the vertices it uses.

    In: vertices (list of positions); faces (list[IRCollisionFace] referencing
        them).
    Out: (vertices, index triples) for the subset.
    """
    remap = {}
    out_vertices = []
    out_faces = []
    for face in faces:
        indices = []
        for index in face.indices:
            compacted = remap.get(index)
            if compacted is None:
                compacted = len(out_vertices)
                out_vertices.append(vertices[index])
                remap[index] = compacted
            indices.append(compacted)
        out_faces.append(tuple(indices))
    return out_vertices, out_faces


def _face_attributes(subsystem, faces):
    """Per-face integer attributes for one subsystem's faces."""
    if subsystem in (CollisionSubsystem.WALL, CollisionSubsystem.NPC_WALL,
                     CollisionSubsystem.ZONE_TRIGGER):
        return {ATTR_EDGE_MASK: [face.edge_mask for face in faces]}
    if subsystem is CollisionSubsystem.WALK:
        return {
            ATTR_LAYER_A: [face.layer_a for face in faces],
            ATTR_LAYER_B: [face.layer_b for face in faces],
            ATTR_SURFACE_A: [face.surface_a for face in faces],
            ATTR_SURFACE_B: [face.surface_b for face in faces],
        }
    return {}


def _material_index(subsystem, materials, material_indices):
    """Index of this subsystem's material, appending it on first use."""
    index = material_indices.get(subsystem)
    if index is not None:
        return index
    red, green, blue = _SUBSYSTEM_COLORS[subsystem]
    index = len(materials)
    materials.append(BRCollisionMaterial(
        name="DATPlugin_Collision_%s" % subsystem.value,
        color=(srgb_to_linear(red), srgb_to_linear(green), srgb_to_linear(blue),
               _SUBSYSTEM_ALPHA[subsystem]),
    ))
    material_indices[subsystem] = index
    return index


def _entry_matrix(entry):
    """The entry transform as a 4x4, or None when it is the identity.

    Composed with the same SRT convention as HSD joints; the parent Empty
    holds the Y-up→Z-up rotation, so this stays in game space.
    """
    if (entry.position == (0.0, 0.0, 0.0)
            and entry.rotation == (0.0, 0.0, 0.0)
            and entry.scale == (1.0, 1.0, 1.0)):
        return None
    return matrix_to_list(
        compile_srt_matrix(entry.scale, entry.rotation, entry.position))
