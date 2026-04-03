"""Phase 2 (Export): Convert IRScene back to node trees.

Takes an IRScene (the platform-agnostic intermediate representation) and
reconstructs the SysDolphin node tree structure that can be serialized
to a .dat binary by DATBuilder.

Currently supports: skeleton (Joint tree), meshes (Mesh/PObject chains).
"""
try:
    from ....shared.Nodes.Classes.Joints.ModelSet import ModelSet
    from ....shared.Nodes.Classes.RootNodes.SceneData import SceneData
    from ....shared.Nodes.Classes.RootNodes.BoundBox import BoundBox
    from ....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.Nodes.Classes.Joints.ModelSet import ModelSet
    from shared.Nodes.Classes.RootNodes.SceneData import SceneData
    from shared.Nodes.Classes.RootNodes.BoundBox import BoundBox
    from shared.helpers.logger import StubLogger

from .helpers.bones import compose_bones
from .helpers.meshes import compose_meshes
from .helpers.animations import compose_placeholder_animation


def compose_scene(ir_scene, options=None, logger=StubLogger()):
    """Convert an IRScene into node trees ready for serialization.

    Args:
        ir_scene: IRScene from the describe phase.
        options: dict of exporter options (reserved for future use).
        logger: Logger instance.

    Returns:
        (root_nodes, section_names) — lists of root nodes and their
        corresponding section names for DATBuilder.
    """
    if options is None:
        options = {}

    logger.info("=== Export Phase 2: Compose ===")

    root_nodes = []
    section_names = []

    for mi, model in enumerate(ir_scene.models):
        logger.info("  Composing model '%s' (%d bones, %d meshes)",
                    model.name, len(model.bones), len(model.meshes))

        root_joint, joints = compose_bones(model.bones, logger)
        if root_joint is None:
            logger.info("    Skipped: no bones")
            continue

        compose_meshes(model.meshes, joints, model.bones, logger)

        # Placeholder animations — one rest pose per animation set found in Blender
        anim_count = max(1, len(model.bone_animations))
        anim_roots = []
        for ai in range(anim_count):
            anim_root = compose_placeholder_animation(joints, model.bones, logger)
            if anim_root:
                anim_roots.append(anim_root)
        logger.info("    Created %d placeholder animation slot(s)", len(anim_roots))

        model_set = ModelSet(address=None, blender_obj=None)
        model_set.root_joint = root_joint
        model_set.animated_joints = anim_roots if anim_roots else None
        model_set.animated_material_joints = None
        model_set.animated_shape_joints = None

        scene_data = SceneData(address=None, blender_obj=None)
        scene_data.models = [model_set]
        scene_data.camera = None
        scene_data.lights = None
        scene_data.fog = None

        root_nodes.append(scene_data)
        section_names.append('scene_data')

        # Bound box — one AABB per animation set, computed from mesh vertices
        bb = _compose_bound_box(model, anim_count, logger)
        if bb:
            root_nodes.append(bb)
            section_names.append('bound_box')

    # TODO: compose lights and add to scene_data.lights

    logger.info("=== Export Phase 2 complete: %d scene(s) ===", len(root_nodes))

    return root_nodes, section_names


def _compose_bound_box(model, anim_count, logger):
    """Create a BoundBox node with static AABBs computed from mesh vertices.

    Computes a single axis-aligned bounding box encompassing all mesh
    vertices and replicates it for each animation set. For placeholder
    animations (single-frame rest pose), this is the correct AABB.

    Args:
        model: IRModel with meshes populated.
        anim_count: Number of animation sets.
        logger: Logger instance.

    Returns:
        BoundBox node, or None if no meshes.
    """
    import struct

    if not model.meshes:
        return None

    # Compute AABB from all mesh vertices
    min_x = min_y = min_z = float('inf')
    max_x = max_y = max_z = float('-inf')

    for mesh in model.meshes:
        for v in mesh.vertices:
            min_x = min(min_x, v[0])
            min_y = min(min_y, v[1])
            min_z = min(min_z, v[2])
            max_x = max(max_x, v[0])
            max_y = max(max_y, v[1])
            max_z = max(max_z, v[2])

    if min_x == float('inf'):
        return None

    # Add a small margin to avoid zero-size boxes
    margin = 0.1
    min_x -= margin
    min_y -= margin
    min_z -= margin
    max_x += margin
    max_y += margin
    max_z += margin

    # Build AABB data — one identical AABB per animation set
    aabb_bytes = struct.pack('>ffffff', min_x, min_y, min_z, max_x, max_y, max_z)
    raw_data = aabb_bytes * anim_count

    bb = BoundBox(address=None, blender_obj=None)
    bb.anim_set_count = anim_count
    bb.unknown = 0
    bb.raw_aabb_data = raw_data

    logger.info("    Bound box: min=(%.2f,%.2f,%.2f) max=(%.2f,%.2f,%.2f), %d AABB(s)",
                min_x, min_y, min_z, max_x, max_y, max_z, anim_count)

    return bb
