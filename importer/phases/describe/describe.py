"""Phase 4: Convert node trees into an Intermediate Representation scene (pure dataclasses, no bpy)."""
import math
import time

try:
    from ....shared.IR import IRScene
    from ....shared.IR.skeleton import IRModel
    from ....shared.Nodes.Classes.Joints.Joint import Joint
    from ....shared.Nodes.Classes.Joints.ModelSet import ModelSet
    from ....shared.Nodes.Classes.RootNodes.SceneData import SceneData
    from ....shared.Nodes.Classes.Animation.AnimationJoint import AnimationJoint
    from ....shared.Nodes.Classes.Material.MaterialAnimationJoint import MaterialAnimationJoint
    from ....shared.IO.Logger import NullLogger
except (ImportError, SystemError):
    from shared.IR import IRScene
    from shared.IR.skeleton import IRModel
    from shared.Nodes.Classes.Joints.Joint import Joint
    from shared.Nodes.Classes.Joints.ModelSet import ModelSet
    from shared.Nodes.Classes.RootNodes.SceneData import SceneData
    from shared.Nodes.Classes.Animation.AnimationJoint import AnimationJoint
    from shared.Nodes.Classes.Material.MaterialAnimationJoint import MaterialAnimationJoint
    from shared.IO.Logger import NullLogger

from .helpers.bones import describe_bones, build_bone_data_lookup
from .helpers.meshes import describe_meshes
from .helpers.animations import describe_bone_animations


def describe_scene(sections, options, logger=None):
    """Converts parsed node tree sections into an IRScene.

    Routes sections to models/lights/cameras/fogs (matching ModelBuilder.__init__),
    then describes each model's bones and meshes as Intermediate Representation dataclasses.

    Args:
        sections: list of SectionInfo from DATParser.parseSections()
        options: dict of importer options
        logger: Logger instance for output (defaults to NullLogger)

    Returns:
        IRScene with models populated. Lights/cameras/fogs are stubs for now.
    """
    if logger is None:
        logger = NullLogger()

    logger.info("=== Phase 4: Describe Scene ===")
    t0 = time.time()

    # Route sections into model sets (matching legacy ModelBuilder logic)
    model_sets = []
    disjoint_root_joint = None
    disjoint_anim_joints = []
    disjoint_mat_anim_joints = []

    for section in sections:
        if section.root_node is None:
            continue

        root = section.root_node
        logger.debug("Section: %s -> %s", section.section_name, type(root).__name__)

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

    logger.info("Routed %d model set(s) in %.3fs", len(model_sets), time.time() - t0)

    # Describe each model
    ir_models = []
    all_raw_anims = []
    for model_set in model_sets:
        root_joint = model_set.root_joint
        if root_joint is None:
            continue

        model_name = root_joint.name or "Model"
        logger.info("Describing model: %s", model_name)

        t1 = time.time()
        bones, joint_to_bone_index = describe_bones(root_joint, options)
        bone_data_lookup = build_bone_data_lookup(bones)
        logger.info("  Bones: %d (%.3fs)", len(bones), time.time() - t1)

        t2 = time.time()
        meshes = describe_meshes(root_joint, bones, joint_to_bone_index, logger=logger)
        logger.info("  Meshes: %d (%.3fs)", len(meshes), time.time() - t2)

        for i, m in enumerate(meshes):
            uv_names = [uv.name for uv in m.uv_layers]
            color_names = [cl.name for cl in m.color_layers]
            logger.debug("  mesh[%d] '%s': verts=%d, faces=%d, uvs=%s, colors=%s, hidden=%s",
                         i, m.name, len(m.vertices), len(m.faces), uv_names, color_names, m.is_hidden)
            if m.bone_weights:
                logger.debug("    weights: type=%s, bone=%s, assignments=%d",
                             m.bone_weights.type.value,
                             m.bone_weights.bone_name or '-',
                             len(m.bone_weights.assignments) if m.bone_weights.assignments else 0)
            if m.material:
                mat = m.material
                logger.debug("    material: color_src=%s, alpha_src=%s, lighting=%s, specular=%s, "
                             "alpha=%.3f, textures=%d",
                             mat.color_source.value, mat.alpha_source.value,
                             mat.lighting.value, mat.enable_specular, mat.alpha,
                             len(mat.texture_layers))
                for j, tl in enumerate(mat.texture_layers):
                    img = tl.image
                    logger.debug("    tex[%d]: %s %dx%d, uv_idx=%d, coord=%s, "
                                 "color_blend=%s, alpha_blend=%s, blend=%.2f, bump=%s",
                                 j, img.name if img else 'None',
                                 img.width if img else 0, img.height if img else 0,
                                 tl.uv_index, tl.coord_type.value,
                                 tl.color_blend.value, tl.alpha_blend.value,
                                 tl.blend_factor, tl.is_bump)
                if mat.fragment_blending:
                    fb = mat.fragment_blending
                    logger.debug("    fragment: effect=%s, src=%s, dst=%s",
                                 fb.effect.value, fb.source_factor.value, fb.dest_factor.value)

        t3 = time.time()
        raw_anims = describe_bone_animations(model_set, joint_to_bone_index, bones, bone_data_lookup, options, logger)
        logger.info("  Animations: %d sets (%.3fs)", len(raw_anims), time.time() - t3)

        ir_model = IRModel(
            name=model_name,
            bones=bones,
            meshes=meshes,
            coordinate_rotation=(math.pi / 2, 0.0, 0.0),
        )
        ir_models.append(ir_model)
        all_raw_anims.append(raw_anims)

    logger.info("=== Phase 4 complete: %d model(s) ===", len(ir_models))
    return IRScene(models=ir_models), all_raw_anims
