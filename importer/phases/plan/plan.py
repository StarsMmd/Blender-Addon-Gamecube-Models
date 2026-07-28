"""Plan phase: IR (platform-agnostic) → BR (Blender-specialised).

Thin orchestrator. Per-concept conversion lives in helpers. Pure — no bpy,
no mutation of the input IR.
"""
try:
    from ....shared.BR.scene import BRScene, BRModel
    from ....shared.helpers.logger import StubLogger
    from .helpers.armature import plan_armature, derive_scene_name
    from .helpers.meshes import plan_meshes
    from .helpers.animations import plan_actions
    from .helpers.particles import plan_particles
    from .helpers.scene import (
        plan_lights, plan_cameras, plan_constraints, plan_fogs,
    )
except (ImportError, SystemError):
    from shared.BR.scene import BRScene, BRModel
    from shared.helpers.logger import StubLogger
    from importer.phases.plan.helpers.armature import (
        plan_armature, derive_scene_name,
    )
    from importer.phases.plan.helpers.meshes import plan_meshes
    from importer.phases.plan.helpers.animations import plan_actions
    from importer.phases.plan.helpers.particles import plan_particles
    from importer.phases.plan.helpers.scene import (
        plan_lights, plan_cameras, plan_constraints, plan_fogs,
    )


def plan_scene(ir_scene, options=None, logger=StubLogger()):
    """Convert an IRScene to a BRScene.

    Full coverage: armature, meshes, materials, actions, constraints,
    particles, lights, cameras. build_blender should not import from IR
    on the planned path.

    In: ir_scene (IRScene); options (dict|None, reads 'filepath', 'ik_hack');
        logger (Logger, defaults to StubLogger).
    Out: BRScene with models/lights/cameras populated.
    """
    options = options or {}
    models = []
    # One sub-collection per skeleton only once there is more than one to tell
    # apart; a lone model would just add a level of nesting for nothing.
    per_model_collections = len(ir_scene.models) > 1
    for i, ir_model in enumerate(ir_scene.models):
        br_meshes, br_instances, br_materials = plan_meshes(ir_model)
        br_actions = plan_actions(ir_model.bone_animations, ir_model.bones)
        br_armature = plan_armature(ir_model, options, model_index=i)
        models.append(BRModel(
            name=ir_model.name,
            armature=br_armature,
            collection_name=br_armature.name if per_model_collections else None,
            meshes=br_meshes,
            mesh_instances=br_instances,
            actions=br_actions,
            materials=br_materials,
            constraints=plan_constraints(
                ir_model.ik_constraints,
                ir_model.copy_location_constraints,
                ir_model.track_to_constraints,
                ir_model.copy_rotation_constraints,
                ir_model.limit_rotation_constraints,
                ir_model.limit_location_constraints,
            ),
            particles=plan_particles(ir_model.particles, ir_model.name,
                                     ir_model.bone_animations, logger=logger),
        ))
    br_scene = BRScene(
        collection_name=derive_scene_name(options),
        models=models,
        lights=plan_lights(ir_scene.lights),
        cameras=plan_cameras(ir_scene.cameras),
        fogs=plan_fogs(getattr(ir_scene, 'fogs', None)),
    )
    logger.info("  Planned %d model(s), %d light(s), %d camera(s), %d fog",
                len(models), len(br_scene.lights), len(br_scene.cameras),
                len(br_scene.fogs))
    return br_scene
