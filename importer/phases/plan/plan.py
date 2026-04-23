"""Plan phase: IR (platform-agnostic) → BR (Blender-specialised).

Thin orchestrator. Per-concept conversion lives in helpers. Pure — no bpy,
no mutation of the input IR.
"""
try:
    from ....shared.BR.scene import BRScene, BRModel
    from ....shared.helpers.logger import StubLogger
    from .helpers.armature import plan_armature
    from .helpers.meshes import plan_meshes
    from .helpers.animations import plan_actions, attach_parent_edit_scale_corrections
    from .helpers.scene import (
        plan_lights, plan_cameras, plan_constraints, plan_particle_summary,
    )
except (ImportError, SystemError):
    from shared.BR.scene import BRScene, BRModel
    from shared.helpers.logger import StubLogger
    from importer.phases.plan.helpers.armature import plan_armature
    from importer.phases.plan.helpers.meshes import plan_meshes
    from importer.phases.plan.helpers.animations import (
        plan_actions, attach_parent_edit_scale_corrections,
    )
    from importer.phases.plan.helpers.scene import (
        plan_lights, plan_cameras, plan_constraints, plan_particle_summary,
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
    for i, ir_model in enumerate(ir_scene.models):
        br_meshes, br_instances, br_materials = plan_meshes(ir_model)
        br_actions = plan_actions(ir_model.bone_animations, ir_model.bones)
        attach_parent_edit_scale_corrections(br_actions, ir_model.bones)
        models.append(BRModel(
            name=ir_model.name,
            armature=plan_armature(ir_model, options, model_index=i),
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
            particles=plan_particle_summary(ir_model.particles),
        ))
    br_scene = BRScene(
        models=models,
        lights=plan_lights(ir_scene.lights),
        cameras=plan_cameras(ir_scene.cameras),
    )
    logger.info("  Planned %d model(s), %d light(s), %d camera(s)",
                len(models), len(br_scene.lights), len(br_scene.cameras))
    return br_scene
