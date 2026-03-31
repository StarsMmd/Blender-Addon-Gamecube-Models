"""Phase 1 (Export): Read Blender scene into an IRScene.

Reverses importer Phase 5 (build_blender). Reads armatures and their
child meshes from the Blender scene and produces an IRScene suitable
for composition into node trees.

Works with arbitrary Blender models — no assumptions about naming
conventions or import-specific metadata.

Also extracts shiny filter parameters from armature custom properties
if present, for writing back into PKX headers during packaging.
"""
import bpy

try:
    from .....shared.IR import IRScene, IRModel
    from .....shared.helpers.logger import StubLogger
    from .helpers.skeleton import describe_skeleton
    from .helpers.meshes import describe_meshes
except (ImportError, SystemError):
    from shared.IR import IRScene, IRModel
    from shared.helpers.logger import StubLogger
    from exporter.phases.describe_blender.helpers.skeleton import describe_skeleton
    from exporter.phases.describe_blender.helpers.meshes import describe_meshes


def describe_blender_scene(context, options=None, logger=StubLogger()):
    """Read the active Blender scene and produce an IRScene.

    Exports all currently selected armatures. Each armature becomes one
    IRModel. Meshes parented to a selected armature are automatically
    included. Meshes not parented to any selected armature are ignored.

    Args:
        context: Blender context with active scene.
        options: dict of exporter options.
        logger: Logger instance.

    Returns:
        (IRScene, ShinyParams | None) — the scene description and optional
        shiny filter parameters (or None if no shiny data found).
    """
    if options is None:
        options = {}

    logger.info("=== Export Phase 1: Describe Blender Scene ===")

    # Collect selected armatures
    armatures = [
        obj for obj in context.selected_objects
        if obj.type == 'ARMATURE'
    ]

    if not armatures:
        raise ValueError(
            "No armatures selected. Select the armature(s) you want to export."
        )

    models = []
    for armature in armatures:
        logger.info("  Processing armature '%s'", armature.name)

        bones = describe_skeleton(armature, logger=logger)
        meshes = describe_meshes(armature, bones, logger=logger)

        model = IRModel(
            name=armature.name,
            bones=bones,
            meshes=meshes,
        )
        models.append(model)

    ir_scene = IRScene(models=models, lights=[])

    # Extract shiny filter parameters from the first armature that has them
    shiny_params = _extract_shiny_params(armatures, logger)

    logger.info("=== Export Phase 1 complete: %d model(s), %d light(s), shiny=%s ===",
                len(ir_scene.models), len(ir_scene.lights), shiny_params is not None)
    return ir_scene, shiny_params


def _extract_shiny_params(armatures, logger):
    """Find and extract shiny filter custom properties from armatures.

    Scans the given armatures for the dat_shiny_* registered properties
    set during import. Returns the first set found, or None.

    Args:
        armatures: list of Blender armature objects.
        logger: Logger instance.

    Returns:
        ShinyParams, or None.
    """
    # TODO: Implement — scan armatures for dat_shiny_route_r, dat_shiny_brightness_r, etc.
    return None
