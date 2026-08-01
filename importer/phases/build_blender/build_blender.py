"""Phase 6 build: BR scene → Blender scene via bpy.

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
from .helpers.linking import make_collection

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
    logger.info("=== Phase 6: Build Blender Scene ===")

    build_results = []
    scene_collection = _scene_collection(br_scene, options, logger)

    for model_idx, br_model in enumerate(br_scene.models):
        logger.info("Building model: %s (%d bones, %d meshes)",
                    br_model.name, len(br_model.armature.bones), len(br_model.meshes))

        # Everything else this model builds follows its armature's collection.
        model_collection = scene_collection
        if br_model.collection_name:
            model_collection = make_collection(br_model.collection_name,
                                               scene_collection)

        armature = build_skeleton(br_model.armature, context, logger=logger,
                                  collection=model_collection)
        material_lookup = build_meshes(br_model, armature, context, logger=logger)
        reset_pose(armature)

        actions = []
        mat_slot_indices = {}
        if br_model.actions:
            logger.info("  Building %d animation set(s)", len(br_model.actions))
            actions, mat_slot_indices = build_bone_animations(
                br_model.actions, armature, options,
                br_model.armature.bake_skeleton, logger=logger,
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
        build_lights(br_scene.lights, logger, scene_collection)
    if br_scene.cameras and options.get("import_cameras", False):
        build_cameras(br_scene.cameras, logger, scene_collection)

    _store_fog(getattr(br_scene, 'fogs', None), context, logger)
    _set_display_transform(context, logger)

    logger.info("=== Phase 6 complete ===")
    return build_results


def _set_display_transform(context, logger):
    """Show imported colours as authored: switch the view transform off AgX.

    The source hardware has no tonemapping — its colour values are
    display-referred, and the import pipeline treats them as sRGB
    throughout. Blender's default AgX transform remaps them (additive
    particle sprites in particular collapse into faint desaturated red),
    so the game-accurate display is the Standard transform.
    """
    if context is None or context.scene is None:
        return
    view = context.scene.view_settings
    if view.view_transform != 'Standard':
        view.view_transform = 'Standard'
        logger.info("  View transform set to Standard (source colours are "
                    "display-referred; AgX would remap them)")


def _scene_collection(br_scene, options, logger):
    """Create the collection this import files everything into.

    Returns None when the file builds no objects at all, so a skipped import
    (say a camera file with camera import switched off) leaves nothing behind.
    """
    builds_something = bool(br_scene.models) or (
        (br_scene.lights and options.get("import_lights", False))
        or (br_scene.cameras and options.get("import_cameras", False))
    )
    if not builds_something:
        return None
    collection = make_collection(br_scene.collection_name or "Imported")
    logger.info("  Filing the import into collection '%s'", collection.name)
    return collection


def _store_fog(br_fogs, context, logger):
    """Apply the scene fog to the world's native Mist settings.

    Blender's world holds one mist range, so only the first BRFog is applied
    (map archives carry at most one). ``use_mist`` is the presence signal the
    export describe reads back. When there's no fog we clear ``use_mist`` so a
    fog-carrying model built earlier in the same session can't leave stale
    mist on a later fog-less scene.
    """
    if context is None:
        return
    import bpy
    scene = context.scene
    if not scene.world:
        scene.world = bpy.data.worlds.new("World")
    mist = scene.world.mist_settings

    if br_fogs:
        fog = br_fogs[0]
        scene.world.color = fog.color
        mist.use_mist = True
        mist.start = fog.mist_start
        mist.depth = fog.mist_depth
        mist.falloff = fog.falloff
        mist.intensity = fog.intensity
        logger.info("  Applied fog to world mist (start=%.3f depth=%.3f falloff=%s)",
                    fog.mist_start, fog.mist_depth, fog.falloff)
    else:
        mist.use_mist = False
