"""Phase 2 (Export): Convert IRScene back to node trees.

Takes an IRScene (the platform-agnostic intermediate representation) and
reconstructs the SysDolphin node tree structure that can be serialized
to a .dat binary by DATBuilder.

Currently supports: skeleton (Joint tree), meshes (Mesh/PObject chains).
"""
try:
    from ....shared.Nodes.Classes.Joints.ModelSet import ModelSet
    from ....shared.Nodes.Classes.RootNodes.SceneData import SceneData
    from ....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.Nodes.Classes.Joints.ModelSet import ModelSet
    from shared.Nodes.Classes.RootNodes.SceneData import SceneData
    from shared.helpers.logger import StubLogger

from .helpers.bones import compose_bones
from .helpers.meshes import compose_meshes


def compose_scene(ir_scene, options=None, logger=StubLogger()):
    """Convert an IRScene into node trees ready for serialization.

    Args:
        ir_scene: IRScene from the describe phase.
        options: dict of exporter options (reserved for future use).
        logger: Logger instance.

    Returns:
        (root_nodes, section_names) — lists of root nodes and their
        corresponding section names for DATBuilder.
    """
    if options is None:
        options = {}

    logger.info("=== Export Phase 2: Compose ===")

    root_nodes = []
    section_names = []

    for mi, model in enumerate(ir_scene.models):
        logger.info("  Composing model '%s' (%d bones, %d meshes)",
                    model.name, len(model.bones), len(model.meshes))

        root_joint, joints = compose_bones(model.bones, logger)
        if root_joint is None:
            logger.info("    Skipped: no bones")
            continue

        compose_meshes(model.meshes, joints, model.bones, logger)

        # TODO: compose animations and attach to model_set

        model_set = ModelSet(address=None, blender_obj=None)
        model_set.root_joint = root_joint
        model_set.animated_joints = None
        model_set.animated_material_joints = None
        model_set.animated_shape_joints = None

        scene_data = SceneData(address=None, blender_obj=None)
        scene_data.models = [model_set]
        scene_data.camera = None
        scene_data.lights = None
        scene_data.fog = None

        root_nodes.append(scene_data)
        section_names.append('scene_data')

    # TODO: compose lights and add to scene_data.lights

    logger.info("=== Export Phase 2 complete: %d scene(s) ===", len(root_nodes))

    return root_nodes, section_names
