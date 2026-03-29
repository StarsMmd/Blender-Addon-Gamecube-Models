"""Phase 5: Build Blender scene objects from an Intermediate Representation scene."""
from .helpers.skeleton import build_skeleton
from .helpers.meshes import build_meshes
from .helpers.animations import build_bone_animations, reset_pose
from .helpers.constraints import build_constraints
from .helpers.lights import build_lights

try:
    from ....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def build_blender_scene(ir_scene, context, options, logger=StubLogger()):
    """Consumes an IRScene and creates Blender objects via bpy API.

    Args:
        ir_scene: IRScene dataclass hierarchy
        context: Blender context
        options: dict of importer options
        logger: Logger instance (defaults to StubLogger)

    Returns:
        list of dicts, one per model, with keys:
            armature: Blender armature object
            actions: list of Blender Actions created for this armature
            mat_slot_indices: dict {material: slot_index} for material animations
    """
    logger.info("=== Phase 5: Build Blender Scene ===")

    build_results = []

    for model_idx, ir_model in enumerate(ir_scene.models):
        logger.info("Building model: %s (%d bones, %d meshes)",
                    ir_model.name, len(ir_model.bones), len(ir_model.meshes))

        armature = build_skeleton(ir_model, context, options, logger=logger, model_index=model_idx)

        material_lookup = build_meshes(ir_model, armature, context, options, logger=logger)

        reset_pose(armature)

        actions = []
        mat_slot_indices = {}
        if ir_model.bone_animations:
            logger.info("  Building %d animation set(s)", len(ir_model.bone_animations))
            actions, mat_slot_indices = build_bone_animations(
                ir_model, armature, options, logger=logger, material_lookup=material_lookup)

        build_constraints(ir_model, armature, logger)

        build_results.append({
            'armature': armature,
            'actions': actions,
            'mat_slot_indices': mat_slot_indices,
        })

    if ir_scene.lights and options.get("import_lights", False):
        build_lights(ir_scene.lights, logger)

    logger.info("=== Phase 5 complete ===")
    return build_results
