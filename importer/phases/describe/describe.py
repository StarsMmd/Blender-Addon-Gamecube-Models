"""Phase 4: Convert node trees into an Intermediate Representation scene (pure dataclasses, no bpy)."""
import time

try:
    from ....shared.IR import IRScene
    from ....shared.IR.skeleton import IRModel
    from ....shared.IR.shiny import IRShinyFilter
    from ....shared.IR.enums import ShinyChannel
    from ....shared.Nodes.Classes.Joints.Joint import Joint
    from ....shared.Nodes.Classes.Joints.ModelSet import ModelSet
    from ....shared.Nodes.Classes.RootNodes.SceneData import SceneData
    from ....shared.Nodes.Classes.Animation.AnimationJoint import AnimationJoint
    from ....shared.Nodes.Classes.Material.MaterialAnimationJoint import MaterialAnimationJoint
    from ....shared.Nodes.Classes.Light.Light import Light
    from ....shared.Nodes.Classes.Light.LightSet import LightSet
    from ....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR import IRScene
    from shared.IR.skeleton import IRModel
    from shared.IR.shiny import IRShinyFilter
    from shared.IR.enums import ShinyChannel
    from shared.Nodes.Classes.Joints.Joint import Joint
    from shared.Nodes.Classes.Joints.ModelSet import ModelSet
    from shared.Nodes.Classes.RootNodes.SceneData import SceneData
    from shared.Nodes.Classes.Animation.AnimationJoint import AnimationJoint
    from shared.Nodes.Classes.Material.MaterialAnimationJoint import MaterialAnimationJoint
    from shared.Nodes.Classes.Light.Light import Light
    from shared.Nodes.Classes.Light.LightSet import LightSet
    from shared.helpers.logger import StubLogger

from .helpers.bones import describe_bones
from .helpers.meshes import describe_meshes
from .helpers.animations import describe_bone_animations
from .helpers.constraints import describe_constraints
from .helpers.lights import describe_light
from .helpers.material_animations import describe_material_animations


def describe_scene(sections, options, logger=StubLogger()):
    """Converts parsed node tree sections into an IRScene.

    Routes sections to models/lights/cameras/fogs (matching ModelBuilder.__init__),
    then describes each model's bones and meshes as Intermediate Representation dataclasses.

    Args:
        sections: list of SectionInfo from DATParser.parseSections()
        options: dict of importer options
        logger: Logger instance for output (defaults to StubLogger)

    Returns:
        IRScene with models populated. Lights/cameras/fogs are stubs for now.
    """

    logger.info("=== Phase 4: Describe Scene ===")
    t0 = time.time()

    # Route sections into model sets and lights (matching legacy ModelBuilder logic)
    model_sets = []
    light_nodes = []
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

        elif isinstance(root, LightSet):
            if hasattr(root, 'light') and root.light:
                light_nodes.append(root.light)

        elif isinstance(root, Light):
            light_nodes.append(root)

        elif isinstance(root, SceneData):
            if root.models is not None:
                model_sets.extend(root.models)
            if root.lights is not None:
                for light_set in root.lights:
                    if hasattr(light_set, 'light') and light_set.light:
                        light_nodes.append(light_set.light)

    # If we accumulated disjoint sections into a model set, create one
    if disjoint_root_joint is not None:
        disjoint_set = type('DisjointModelSet', (), {
            'root_joint': disjoint_root_joint,
            'animated_joints': disjoint_anim_joints,
            'animated_material_joints': disjoint_mat_anim_joints,
        })()
        model_sets.append(disjoint_set)

    logger.info("Routed %d model set(s), %d light(s) in %.3fs",
                len(model_sets), len(light_nodes), time.time() - t0)

    # Describe each model
    ir_models = []
    for model_set in model_sets:
        root_joint = model_set.root_joint
        if root_joint is None:
            continue

        filepath = options.get("filepath", "")
        if filepath:
            import os
            base_name = os.path.basename(filepath).split('.')[0]
        else:
            base_name = None
        model_name = base_name or root_joint.name or "Model"
        logger.info("Describing model: %s", model_name)

        t1 = time.time()
        bones, joint_to_bone_index = describe_bones(root_joint, options)
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
                                 "color_blend=%s, alpha_blend=%s, blend=%.2f, bump=%s, "
                                 "scale=%s, trans=%s",
                                 j, img.name if img else 'None',
                                 img.width if img else 0, img.height if img else 0,
                                 tl.uv_index, tl.coord_type.value,
                                 tl.color_blend.value, tl.alpha_blend.value,
                                 tl.blend_factor, tl.is_bump,
                                 list(tl.scale), list(tl.translation))
                if mat.fragment_blending:
                    fb = mat.fragment_blending
                    logger.debug("    fragment: effect=%s, src=%s, dst=%s",
                                 fb.effect.value, fb.source_factor.value, fb.dest_factor.value)

        t3 = time.time()
        bone_anims = describe_bone_animations(model_set, joint_to_bone_index, bones, options, logger, model_name=model_name)
        logger.info("  Animations: %d sets (%.3fs)", len(bone_anims), time.time() - t3)

        t4 = time.time()
        ik_c, cl_c, tt_c, cr_c, lr_c, ll_c = describe_constraints(root_joint, bones, joint_to_bone_index)
        total_c = len(ik_c) + len(cl_c) + len(tt_c) + len(cr_c) + len(lr_c) + len(ll_c)
        logger.info("  Constraints: %d (%.3fs)", total_c, time.time() - t4)

        t5 = time.time()
        mat_anims = describe_material_animations(model_set, joint_to_bone_index, bones, options, logger, model_name=model_name)
        logger.info("  Material animations: %d sets (%.3fs)", len(mat_anims), time.time() - t5)

        # Pair material animations into bone animation sets by index
        for i, mat_anim_set in enumerate(mat_anims):
            if i < len(bone_anims):
                bone_anims[i].material_tracks = mat_anim_set.tracks
                logger.debug("  Paired material anim '%s' → '%s' (%d tracks)",
                             mat_anim_set.name, bone_anims[i].name, len(mat_anim_set.tracks))

        shiny_filter = _build_shiny_filter(options)

        ir_model = IRModel(
            name=model_name,
            bones=bones,
            meshes=meshes,
            bone_animations=bone_anims,
            ik_constraints=ik_c,
            copy_location_constraints=cl_c,
            track_to_constraints=tt_c,
            copy_rotation_constraints=cr_c,
            limit_rotation_constraints=lr_c,
            limit_location_constraints=ll_c,
            shiny_filter=shiny_filter,
        )
        ir_models.append(ir_model)

    # Describe lights
    ir_lights = []
    for i, light_node in enumerate(light_nodes):
        ir_light = describe_light(light_node, i)
        if ir_light:
            ir_lights.append(ir_light)
    if ir_lights:
        logger.info("Lights: %d", len(ir_lights))

    logger.info("=== Phase 4 complete: %d model(s), %d light(s) ===", len(ir_models), len(ir_lights))
    return IRScene(models=ir_models, lights=ir_lights)


def _build_shiny_filter(options):
    """Convert raw shiny_params dict from Phase 1 into an IRShinyFilter, or None."""
    shiny_params = options.get("shiny_params")
    if not shiny_params:
        return None

    return IRShinyFilter(
        channel_routing=(
            ShinyChannel(shiny_params["route_r"]),
            ShinyChannel(shiny_params["route_g"]),
            ShinyChannel(shiny_params["route_b"]),
            ShinyChannel(shiny_params["route_a"]),
        ),
        brightness=(
            shiny_params["brightness_r"],
            shiny_params["brightness_g"],
            shiny_params["brightness_b"],
            shiny_params["brightness_a"],
        ),
    )
