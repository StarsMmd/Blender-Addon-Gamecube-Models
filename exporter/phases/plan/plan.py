"""Phase 2 (Export): BRScene → IRScene.

Pure — no `bpy`. Plans what the DAT will contain: takes the
Blender-specialised representation produced by ``describe`` and produces
an IRScene that ``compose`` consumes.

In the current incarnation, describe pre-computes IR bones + merged IR
meshes per model (because the legacy animation unbaker depends on them
in describe's phase) and stashes them on each ``BRModel``; plan reads
those stashes, then runs ``refine_bone_flags`` + the per-domain plan
unwrappers (``plan_actions``, ``plan_constraints``, ``plan_lights``,
``plan_cameras``) and assembles the IRScene.
"""
try:
    from ....shared.IR import IRScene, IRModel
    from ....shared.helpers.logger import StubLogger
    from .helpers.animations import plan_actions
    from .helpers.constraints import plan_constraints
    from .helpers.lights import plan_lights
    from .helpers.cameras import plan_cameras
    from .helpers.scene import refine_bone_flags
except (ImportError, SystemError):
    from shared.IR import IRScene, IRModel
    from shared.helpers.logger import StubLogger
    from exporter.phases.plan.helpers.animations import plan_actions
    from exporter.phases.plan.helpers.constraints import plan_constraints
    from exporter.phases.plan.helpers.lights import plan_lights
    from exporter.phases.plan.helpers.cameras import plan_cameras
    from exporter.phases.plan.helpers.scene import refine_bone_flags


def plan_scene(br_scene, options=None, logger=StubLogger()):
    """Convert a BRScene to an IRScene.

    In: br_scene (BRScene); options (dict|None); logger.
    Out: IRScene ready for compose.
    """
    if options is None:
        options = {}

    logger.info("=== Export Phase 2: Plan (BR → IR) ===")

    ir_models = []
    for br_model in br_scene.models:
        ir_models.append(_plan_one_model(br_model, logger))

    ir_lights = plan_lights(br_scene.lights, logger=logger)
    ir_cameras = plan_cameras(br_scene.cameras, logger=logger)

    return IRScene(models=ir_models, lights=ir_lights, cameras=ir_cameras)


def _plan_one_model(br_model, logger):
    ir_bones = br_model._ir_bones
    ir_meshes = br_model._ir_meshes

    # Populate mesh_indices on bones, then refine flags now that mesh
    # attachment + skinning are known.
    for mesh_idx, ir_mesh in enumerate(ir_meshes):
        bone_idx = ir_mesh.parent_bone_index
        if bone_idx < len(ir_bones):
            ir_bones[bone_idx].mesh_indices.append(mesh_idx)
    refine_bone_flags(ir_bones, ir_meshes, logger=logger)

    bones_with_meshes = sum(1 for b in ir_bones if b.mesh_indices)
    logger.info("  Mesh attachment: %d mesh(es) across %d bone(s)",
                len(ir_meshes), bones_with_meshes)

    bone_animations = plan_actions(br_model.actions, logger=logger)
    ik, cl, tt, cr, lr, ll = plan_constraints(br_model.constraints, logger=logger)

    return IRModel(
        name=br_model.name,
        bones=ir_bones,
        meshes=ir_meshes,
        bone_animations=bone_animations,
        ik_constraints=ik,
        copy_location_constraints=cl,
        track_to_constraints=tt,
        copy_rotation_constraints=cr,
        limit_rotation_constraints=lr,
        limit_location_constraints=ll,
    )
