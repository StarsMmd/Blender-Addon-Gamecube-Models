"""Phase 1 (Export): Read Blender scene into a BRScene.

The only export phase that touches `bpy`. Walks every armature in the
scene, snapshots its bones / meshes / materials / actions / constraints
into BR dataclasses, and collects scene-level lights and cameras. PKX
header and shiny filter parameters are extracted from armature custom
properties as side outputs.

Per-domain BR producers live under ``helpers/``. Animation unbaking
still depends on already-converted IR bones and merged IR meshes, so the
loop interleaves describe + plan calls and stashes the IR results on
each BRModel for the plan phase to reuse instead of re-deriving.
"""
import bpy

try:
    from ....shared.BR.scene import BRScene, BRModel
    from ....shared.helpers.logger import StubLogger
    from .helpers.armature import describe_armature
    from .helpers.meshes import describe_meshes
    from .helpers.animations import describe_actions
    from .helpers.constraints import describe_constraints
    from .helpers.lights import describe_lights
    from .helpers.cameras import describe_cameras
    from .helpers.scene import (
        validate_baked_transforms,
        collect_pkx_referenced_actions,
        extract_shiny_params,
        extract_pkx_header,
        maybe_dump_diagnostic,
    )
    from ..plan.helpers.armature import plan_armature
    from ..plan.helpers.meshes import plan_meshes
    from ..plan.helpers.merge_meshes import merge_meshes
except (ImportError, SystemError):
    from shared.BR.scene import BRScene, BRModel
    from shared.helpers.logger import StubLogger
    from exporter.phases.describe.helpers.armature import describe_armature
    from exporter.phases.describe.helpers.meshes import describe_meshes
    from exporter.phases.describe.helpers.animations import describe_actions
    from exporter.phases.describe.helpers.constraints import describe_constraints
    from exporter.phases.describe.helpers.lights import describe_lights
    from exporter.phases.describe.helpers.cameras import describe_cameras
    from exporter.phases.describe.helpers.scene import (
        validate_baked_transforms,
        collect_pkx_referenced_actions,
        extract_shiny_params,
        extract_pkx_header,
        maybe_dump_diagnostic,
    )
    from exporter.phases.plan.helpers.armature import plan_armature
    from exporter.phases.plan.helpers.meshes import plan_meshes
    from exporter.phases.plan.helpers.merge_meshes import merge_meshes


def describe_scene(context, options=None, logger=StubLogger(), output_ext=''):
    """Read the active Blender scene and produce a BRScene.

    In: context (bpy.types.Context); options (dict|None, reads
        ``sparsify_bezier``); logger; output_ext (str, e.g. 'dat'/'pkx' —
        when 'dat', the prep-script's auto-generated preview lights and
        debug camera are dropped so bare .dat exports stay lean).
    Out: (BRScene, ShinyParams|None, PKXHeader|None).
    """
    if options is None:
        options = {}

    logger.info("=== Export Phase 1: Describe Blender Scene ===")

    armatures = [obj for obj in context.scene.objects if obj.type == 'ARMATURE']
    if not armatures:
        raise ValueError(
            "No armatures in the scene. The scene must contain at least one armature to export."
        )

    validate_baked_transforms(armatures)

    use_bezier = options.get('sparsify_bezier', True)

    br_models = []
    for armature in armatures:
        logger.info("  Processing armature '%s'", armature.name)
        br_model = _describe_one_model(armature, use_bezier, logger)
        br_models.append(br_model)
        maybe_dump_diagnostic(
            armature, br_model._ir_bones,
            [a._ir_animation_set for a in br_model.actions],
            logger,
        )

    skip_prep_auto = (output_ext == 'dat')
    br_lights = describe_lights(context, logger=logger, skip_prep_auto=skip_prep_auto)
    br_cameras = describe_cameras(context, logger=logger, skip_prep_auto=skip_prep_auto)

    br_scene = BRScene(models=br_models, lights=br_lights, cameras=br_cameras)

    shiny_params = extract_shiny_params(armatures, logger)

    # Build action_name → DAT animation index from the first model's
    # action ordering (compose ultimately keys DAT animation slots off
    # this same list).
    action_name_to_index = {}
    if br_models and br_models[0].actions:
        for idx, br_action in enumerate(br_models[0].actions):
            action_name_to_index[br_action.name] = idx

    pkx_header = extract_pkx_header(armatures, action_name_to_index, logger)

    logger.info("=== Export Phase 1 complete: %d model(s), %d light(s), %d camera(s), shiny=%s, pkx=%s ===",
                len(br_scene.models), len(br_scene.lights), len(br_scene.cameras),
                shiny_params is not None, pkx_header is not None)
    return br_scene, shiny_params, pkx_header


def _describe_one_model(armature, use_bezier, logger):
    """Pull one armature's full BR description out of Blender.

    Computes the IR bones + merged IR meshes inline because the legacy
    animation unbaker reads them, then stashes both on the BRModel for
    the plan phase to reuse.
    """
    br_armature = describe_armature(armature, logger=logger)
    ir_bones = plan_armature(br_armature, logger=logger)

    br_meshes, _br_instances, br_materials, blender_materials = describe_meshes(
        armature, br_armature, logger=logger,
    )
    ir_meshes = plan_meshes(br_meshes, br_materials, ir_bones, logger=logger)
    ir_meshes, blender_materials_merged = merge_meshes(
        ir_meshes, parallel=blender_materials, logger=logger,
    )

    referenced_actions = collect_pkx_referenced_actions(armature)
    br_actions = describe_actions(
        armature, br_armature, ir_bones, logger=logger,
        use_bezier=use_bezier,
        referenced_actions=referenced_actions,
        ir_meshes=ir_meshes, blender_materials=blender_materials_merged,
    )

    br_constraints = describe_constraints(armature, ir_bones, logger=logger)

    br_model = BRModel(
        name=armature.name,
        armature=br_armature,
        meshes=br_meshes,
        materials=br_materials,
        actions=br_actions,
        constraints=br_constraints,
    )
    # Side-channel: pre-computed IR for plan to reuse rather than redo.
    br_model._ir_bones = ir_bones
    br_model._ir_meshes = ir_meshes
    return br_model
