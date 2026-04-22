"""Plan phase: IR (platform-agnostic) → BR (Blender-specialised).

Thin orchestrator. Per-concept conversion lives in helpers. Pure — no bpy,
no mutation of the input IR.
"""
try:
    from ....shared.BR.scene import BRScene, BRModel
    from ....shared.helpers.logger import StubLogger
    from .helpers.armature import plan_armature
    from .helpers.meshes import plan_meshes
except (ImportError, SystemError):
    from shared.BR.scene import BRScene, BRModel
    from shared.helpers.logger import StubLogger
    from importer.phases.plan.helpers.armature import plan_armature
    from importer.phases.plan.helpers.meshes import plan_meshes


def plan_scene(ir_scene, options=None, logger=StubLogger()):
    """Convert an IRScene to a BRScene.

    Covers armature and meshes so far. Build_blender still reads IR for
    materials, actions, constraints, etc.; subsequent stages migrate each.
    """
    options = options or {}
    models = []
    for i, ir_model in enumerate(ir_scene.models):
        br_meshes, br_instances = plan_meshes(ir_model)
        models.append(BRModel(
            name=ir_model.name,
            armature=plan_armature(ir_model, options, model_index=i),
            meshes=br_meshes,
            mesh_instances=br_instances,
        ))
    logger.info("  Planned %d model(s) for Blender build", len(models))
    return BRScene(models=models)
