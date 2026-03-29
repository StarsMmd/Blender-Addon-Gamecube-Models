"""Phase 5A: Build Blender scene objects from an Intermediate Representation scene."""
from .helpers.skeleton import build_skeleton
from .helpers.meshes import build_meshes
from .helpers.animations import build_bone_animations
from .helpers.constraints import build_constraints
from .helpers.lights import build_lights
from .helpers.shiny_filter import build_shiny_node_group, setup_shiny_properties

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
    """
    logger.info("=== Phase 5A: Build Blender Scene ===")

    for model_idx, ir_model in enumerate(ir_scene.models):
        logger.info("Building model: %s (%d bones, %d meshes)",
                    ir_model.name, len(ir_model.bones), len(ir_model.meshes))

        armature = build_skeleton(ir_model, context, options, logger=logger, model_index=model_idx)

        # Set up shiny filter node group if shiny params are present
        shiny_node_group = None
        if ir_model.shiny_filter is not None:
            group_name = "ShinyFilter_%s" % ir_model.name
            shiny_node_group = build_shiny_node_group(ir_model.shiny_filter, group_name)
            setup_shiny_properties(armature, ir_model.shiny_filter, group_name)
            logger.info("  Built shiny filter node group: %s", group_name)

        material_lookup = build_meshes(ir_model, armature, context, options, logger=logger,
                                       shiny_node_group=shiny_node_group)

        if ir_model.bone_animations:
            logger.info("  Building %d animation set(s)", len(ir_model.bone_animations))
            build_bone_animations(ir_model, armature, options, logger=logger, material_lookup=material_lookup)

        build_constraints(ir_model, armature, logger)

    if ir_scene.lights and options.get("import_lights", False):
        build_lights(ir_scene.lights, logger)

    logger.info("=== Phase 5A complete ===")
