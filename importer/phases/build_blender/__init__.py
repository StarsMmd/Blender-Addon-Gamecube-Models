"""Phase 5A: Build Blender scene objects from an Intermediate Representation scene."""
from .skeleton import build_skeleton
from .meshes import build_meshes
from .animations import build_bone_animations

try:
    from ....shared.IO.Logger import NullLogger
except (ImportError, SystemError):
    from shared.IO.Logger import NullLogger


def build_blender_scene(ir_scene, context, options, logger=None, raw_animations=None):
    """Consumes an IRScene and creates Blender objects via bpy API.

    Args:
        ir_scene: IRScene dataclass hierarchy
        context: Blender context
        options: dict of importer options
        logger: Logger instance (defaults to NullLogger)
        raw_animations: list of list[RawAnimationSet] per model (from Phase 4)
    """
    if logger is None:
        logger = NullLogger()
    if raw_animations is None:
        raw_animations = [[] for _ in ir_scene.models]

    logger.info("=== Phase 5A: Build Blender Scene ===")

    for i, ir_model in enumerate(ir_scene.models):
        logger.info("Building model: %s (%d bones, %d meshes)",
                    ir_model.name, len(ir_model.bones), len(ir_model.meshes))

        armature = build_skeleton(ir_model, context, options, logger=logger)
        build_meshes(ir_model, armature, context, options, logger=logger)

        if i < len(raw_animations) and raw_animations[i]:
            logger.info("  Building %d animation set(s)", len(raw_animations[i]))
            build_bone_animations(raw_animations[i], ir_model, armature, options, logger=logger)

    logger.info("=== Phase 5A complete ===")

    # TODO: build lights, cameras, fogs
