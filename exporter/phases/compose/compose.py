"""Phase 2 (Export): Convert IRScene back to node trees.

Takes an IRScene (the platform-agnostic intermediate representation) and
reconstructs the SysDolphin node tree structure that can be serialized
to a .dat binary by DATBuilder.

Supports: skeleton (Joint tree), meshes (Mesh/PObject chains), materials,
animations, and lights.
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
from .helpers.animations import compose_bone_animations
from .helpers.material_animations import compose_material_animations
from .helpers.lights import compose_lights
from .helpers.cameras import compose_camera
from .helpers.constraints import compose_constraints


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

        # Strip node names if requested (for round-trip testing against
        # original models that have empty name fields)
        if options.get('strip_names', False):
            for joint in joints:
                joint.name = None

        # Compose constraints (must happen before animations — sets joint type flags)
        compose_constraints(model, joints, model.bones, logger)

        # Compose animations
        anim_roots = compose_bone_animations(
            model.bone_animations, joints, model.bones, logger)

        # Compose material animations
        mat_anim_roots = None
        if model.bone_animations:
            mat_roots = []
            for anim_set in model.bone_animations:
                if anim_set.material_tracks:
                    root = compose_material_animations(anim_set, model.bones, logger)
                    if root:
                        mat_roots.append(root)
            mat_anim_roots = mat_roots if mat_roots else None

        model_set = ModelSet(address=None, blender_obj=None)
        model_set.root_joint = root_joint
        model_set.animated_joints = anim_roots
        model_set.animated_material_joints = mat_anim_roots
        model_set.animated_shape_joints = None

        scene_data = SceneData(address=None, blender_obj=None)
        scene_data.models = [model_set]
        scene_data.camera = compose_camera(ir_scene.cameras[0], logger) if ir_scene.cameras else None
        scene_data.lights = compose_lights(ir_scene.lights, logger=logger)
        scene_data.fog = None

        root_nodes.append(scene_data)
        section_names.append('scene_data')

        # Bound box — per-frame AABBs across all animation sets
        if options.get('include_bound_box', True):
            bb = _compose_bound_box(model, logger)
            if bb:
                root_nodes.append(bb)
                section_names.append('bound_box')
        else:
            logger.info("  Bound box: skipped (disabled in export options)")

    logger.info("=== Export Phase 2 complete: %d scene(s) ===", len(root_nodes))

    return root_nodes, section_names


def _compose_bound_box(model, logger):
    """Create a BoundBox node with per-frame AABBs computed from mesh vertices.

    Computes a single axis-aligned bounding box encompassing all mesh
    vertices and replicates it for each frame of each animation set.
    The static AABB is correct for the rest pose; per-frame animated
    AABBs would require evaluating the skeleton at each frame.

    The BoundBox fields are:
        anim_set_count: number of animation sets
        unknown: frame count of the first animation set (end_frame + 1)
        raw_aabb_data: one AABB (24 bytes) per frame across all sets

    Args:
        model: IRModel with meshes and bone_animations populated.
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

    # Compute per-animation-set frame counts
    anim_sets = model.bone_animations or []
    anim_count = max(1, len(anim_sets))
    frame_counts = []
    for anim_set in anim_sets:
        max_ef = max((int(t.end_frame) for t in anim_set.tracks), default=0)
        frame_counts.append(max_ef + 1)
    if not frame_counts:
        frame_counts = [1]

    # Build AABB data — one identical AABB per frame across all sets
    total_frames = sum(frame_counts)
    aabb_bytes = struct.pack('>ffffff', min_x, min_y, min_z, max_x, max_y, max_z)
    raw_data = aabb_bytes * total_frames

    bb = BoundBox(address=None, blender_obj=None)
    bb.anim_set_count = anim_count
    bb.first_anim_frame_count = frame_counts[0]
    bb.raw_aabb_data = raw_data

    logger.info("    Bound box: min=(%.2f,%.2f,%.2f) max=(%.2f,%.2f,%.2f), %d set(s), %d total frames",
                min_x, min_y, min_z, max_x, max_y, max_z, anim_count, total_frames)

    return bb
