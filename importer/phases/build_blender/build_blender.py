"""Phase 5 build: BR scene → Blender scene via bpy.

Pure executor. All decisions (inherit_scale, shader graphs, animation
basis formula, coord conversions, FOV→lens, ...) are baked into BR by
the Plan phase. This layer only calls bpy APIs.
"""
from .helpers.skeleton import build_skeleton
from .helpers.meshes import build_meshes
from .helpers.animations import build_bone_animations, reset_pose
from .helpers.constraints import build_constraints
from .helpers.lights import build_lights
from .helpers.cameras import build_cameras
from .helpers.particles import build_particles

try:
    from ....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def build_blender_scene(br_scene, context, options, logger=StubLogger()):
    """Build Blender scene objects from a BRScene.

    Args:
        br_scene: BRScene produced by the Plan phase.
        context: Blender context.
        options: importer options dict (reads 'max_frame', 'import_lights',
            'import_cameras').
        logger: Logger instance.

    Returns:
        list of dicts, one per model, with keys ``armature``, ``actions``,
        ``mat_slot_indices``.
    """
    logger.info("=== Phase 5: Build Blender Scene ===")

    build_results = []

    for model_idx, br_model in enumerate(br_scene.models):
        logger.info("Building model: %s (%d bones, %d meshes)",
                    br_model.name, len(br_model.armature.bones), len(br_model.meshes))

        armature = build_skeleton(br_model.armature, context, logger=logger)
        material_lookup = build_meshes(br_model, armature, context, logger=logger)
        reset_pose(armature)

        actions = []
        mat_slot_indices = {}
        if br_model.actions:
            logger.info("  Building %d animation set(s)", len(br_model.actions))
            actions, mat_slot_indices = build_bone_animations(
                br_model.actions, armature, options, logger=logger,
                material_lookup=material_lookup,
            )

        build_constraints(br_model.constraints, armature, logger)
        build_particles(br_model.particles, armature, context, logger=logger)

        build_results.append({
            'armature': armature,
            'actions': actions,
            'mat_slot_indices': mat_slot_indices,
        })

    if br_scene.lights and options.get("import_lights", False):
        build_lights(br_scene.lights, logger)
    if br_scene.cameras and options.get("import_cameras", False):
        build_cameras(br_scene.cameras, logger)

    logger.info("=== Phase 5 complete ===")
    return build_results
