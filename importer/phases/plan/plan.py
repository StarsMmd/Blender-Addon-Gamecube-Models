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
except (ImportError, SystemError):
    from shared.BR.scene import BRScene, BRModel
    from shared.helpers.logger import StubLogger
    from importer.phases.plan.helpers.armature import plan_armature
    from importer.phases.plan.helpers.meshes import plan_meshes
    from importer.phases.plan.helpers.animations import (
        plan_actions, attach_parent_edit_scale_corrections,
    )


def plan_scene(ir_scene, options=None, logger=StubLogger()):
    """Convert an IRScene to a BRScene.

    Covers armature, meshes, materials, and actions so far. Build_blender
    still reads IR for constraints, lights, cameras, particles.
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
        ))
    logger.info("  Planned %d model(s) for Blender build", len(models))
    return BRScene(models=models)
