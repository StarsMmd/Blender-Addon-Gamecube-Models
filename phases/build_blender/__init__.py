"""Phase 5A: Build Blender scene objects from an Intermediate Representation scene."""
from .skeleton import build_skeleton
from .meshes import build_meshes

try:
    from ...shared.IO.Logger import NullLogger
except (ImportError, SystemError):
    from shared.IO.Logger import NullLogger


def build_blender_scene(ir_scene, context, options, logger=None):
    """Consumes an IRScene and creates Blender objects via bpy API.

    Args:
        ir_scene: IRScene dataclass hierarchy
        context: Blender context
        options: dict of importer options
        logger: Logger instance (defaults to NullLogger)
    """
    if logger is None:
        logger = NullLogger()

    logger.info("=== Phase 5A: Build Blender Scene ===")

    for ir_model in ir_scene.models:
        logger.info("Building model: %s (%d bones, %d meshes)",
                    ir_model.name, len(ir_model.bones), len(ir_model.meshes))

        armature = build_skeleton(ir_model, context, options, logger=logger)
        build_meshes(ir_model, armature, context, options, logger=logger)

    logger.info("=== Phase 5A complete ===")

    # TODO: build lights, cameras, fogs
