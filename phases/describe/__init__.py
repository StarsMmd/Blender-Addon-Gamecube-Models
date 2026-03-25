"""Phase 4: Convert node trees into an Intermediate Representation scene (pure dataclasses, no bpy)."""
import math

from shared.IR import IRScene
from shared.IR.skeleton import IRModel
from shared.Nodes.Classes.Joints.Joint import Joint
from shared.Nodes.Classes.Joints.ModelSet import ModelSet
from shared.Nodes.Classes.RootNodes.SceneData import SceneData
from shared.Nodes.Classes.Animation.AnimationJoint import AnimationJoint
from shared.Nodes.Classes.Material.MaterialAnimationJoint import MaterialAnimationJoint

from .bones import describe_bones
from .meshes import describe_meshes


def describe_scene(sections, options):
    """Converts parsed node tree sections into an IRScene.

    Routes sections to models/lights/cameras/fogs (matching ModelBuilder.__init__),
    then describes each model's bones and meshes as Intermediate Representation dataclasses.

    Args:
        sections: list of SectionInfo from DATParser.parseSections()
        options: dict of importer options

    Returns:
        IRScene with models populated. Lights/cameras/fogs are stubs for now.
    """
    # Route sections into model sets (matching legacy ModelBuilder logic)
    model_sets = []
    disjoint_root_joint = None
    disjoint_anim_joints = []
    disjoint_mat_anim_joints = []

    for section in sections:
        if section.root_node is None:
            continue

        root = section.root_node

        if isinstance(root, Joint):
            disjoint_root_joint = root

        elif isinstance(root, AnimationJoint):
            disjoint_anim_joints.append(root)

        elif isinstance(root, MaterialAnimationJoint):
            disjoint_mat_anim_joints.append(root)

        elif isinstance(root, SceneData):
            if root.models is not None:
                model_sets.extend(root.models)

    # If we accumulated disjoint sections into a model set, create one
    if disjoint_root_joint is not None:
        disjoint_set = type('DisjointModelSet', (), {
            'root_joint': disjoint_root_joint,
            'animated_joints': disjoint_anim_joints,
            'animated_material_joints': disjoint_mat_anim_joints,
        })()
        model_sets.append(disjoint_set)

    # Describe each model
    ir_models = []
    for model_set in model_sets:
        root_joint = model_set.root_joint
        if root_joint is None:
            continue

        bones, joint_to_bone_index = describe_bones(root_joint, options)
        meshes = describe_meshes(root_joint, bones, joint_to_bone_index)

        ir_model = IRModel(
            name=root_joint.name or "Model",
            bones=bones,
            meshes=meshes,
            coordinate_rotation=(math.pi / 2, 0.0, 0.0),
        )
        ir_models.append(ir_model)

    return IRScene(models=ir_models)
