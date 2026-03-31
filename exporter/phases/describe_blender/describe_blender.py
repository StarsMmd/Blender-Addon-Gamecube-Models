"""Phase 1 (Export): Read Blender scene into an IRScene.

Reverses importer Phase 5 (build_blender). Reads armatures, meshes,
materials, animations, constraints, and lights from the Blender scene
and produces an IRScene suitable for composition into node trees.

Also extracts shiny filter parameters from armature custom properties
if present, for writing back into PKX headers during packaging.
"""
try:
    from .....shared.IR import IRScene
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR import IRScene
    from shared.helpers.logger import StubLogger


def describe_blender_scene(context, options=None, logger=StubLogger()):
    """Read the active Blender scene and produce an IRScene.

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

    # TODO: Implement — read armature, meshes, materials, animations, etc.
    ir_scene = IRScene(models=[], lights=[])

    # Extract shiny filter parameters from the first armature that has them
    shiny_params = _extract_shiny_params(context, logger)

    logger.info("=== Export Phase 1 complete: %d model(s), %d light(s), shiny=%s ===",
                len(ir_scene.models), len(ir_scene.lights), shiny_params is not None)
    return ir_scene, shiny_params


def _extract_shiny_params(context, logger):
    """Find and extract shiny filter custom properties from armatures.

    Scans armatures in the scene for the dat_shiny_* registered properties
    set during import. Returns the first set found, or None.

    Args:
        context: Blender context.
        logger: Logger instance.

    Returns:
        ShinyParams, or None.
    """
    # TODO: Implement — scan armatures for dat_shiny_route_r, dat_shiny_brightness_r, etc.
    return None
