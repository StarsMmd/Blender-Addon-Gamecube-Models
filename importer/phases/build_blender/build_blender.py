"""Phase 5: Build Blender scene objects from an Intermediate Representation scene."""
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


def build_blender_scene(ir_scene, context, options, logger=StubLogger(), br_scene=None):
    """Consumes a BR scene + IR scene and creates Blender objects via bpy API.

    Stage-1 migration: BR is consulted for the armature; meshes, materials,
    actions, etc. still come from IR and will migrate to BR in later stages.
    ``br_scene`` may be None for compatibility while callers are updated.

    Args:
        ir_scene: IRScene dataclass hierarchy
        context: Blender context
        options: dict of importer options
        logger: Logger instance (defaults to StubLogger)
        br_scene: BRScene dataclass (Plan-phase output). Required for models
            that should be planned; falls back to IR-only skeleton build if
            absent.

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

        if br_scene is None or model_idx >= len(br_scene.models):
            raise ValueError(
                "build_blender_scene requires a BR scene with an entry for every model; "
                "missing BR for model index %d" % model_idx
            )
        br_model = br_scene.models[model_idx]
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

        build_constraints(ir_model, armature, logger)

        if ir_model.particles:
            build_particles(ir_model.particles, armature, context, logger=logger)

        build_results.append({
            'armature': armature,
            'actions': actions,
            'mat_slot_indices': mat_slot_indices,
        })

    if ir_scene.lights and options.get("import_lights", False):
        build_lights(ir_scene.lights, logger)

    if ir_scene.cameras and options.get("import_cameras", False):
        build_cameras(ir_scene.cameras, logger)

    logger.info("=== Phase 5 complete ===")
    return build_results
