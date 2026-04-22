"""Phase 4: Convert node trees into an Intermediate Representation scene (pure dataclasses, no bpy)."""
import time

try:
    from ....shared.IR import IRScene
    from ....shared.IR.skeleton import IRModel
    from ....shared.IR.animation import IRBoneAnimationSet
    from ....shared.Nodes.Classes.Joints.Joint import Joint
    from ....shared.Nodes.Classes.Joints.ModelSet import ModelSet
    from ....shared.Nodes.Classes.RootNodes.SceneData import SceneData
    from ....shared.Nodes.Classes.Animation.AnimationJoint import AnimationJoint
    from ....shared.Nodes.Classes.Material.MaterialAnimationJoint import MaterialAnimationJoint
    from ....shared.Nodes.Classes.Light.Light import Light
    from ....shared.Nodes.Classes.Light.LightSet import LightSet
    from ....shared.Nodes.Classes.Camera.CameraSet import CameraSet
    from ....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR import IRScene
    from shared.IR.skeleton import IRModel
    from shared.IR.animation import IRBoneAnimationSet
    from shared.Nodes.Classes.Joints.Joint import Joint
    from shared.Nodes.Classes.Joints.ModelSet import ModelSet
    from shared.Nodes.Classes.RootNodes.SceneData import SceneData
    from shared.Nodes.Classes.Animation.AnimationJoint import AnimationJoint
    from shared.Nodes.Classes.Material.MaterialAnimationJoint import MaterialAnimationJoint
    from shared.Nodes.Classes.Light.Light import Light
    from shared.Nodes.Classes.Light.LightSet import LightSet
    from shared.Nodes.Classes.Camera.CameraSet import CameraSet
    from shared.helpers.logger import StubLogger

from .helpers.bones import describe_bones
from .helpers.meshes import describe_meshes
from .helpers.animations import describe_bone_animations
from .helpers.constraints import describe_constraints
from .helpers.lights import describe_light
from .helpers.cameras import describe_camera, describe_camera_animations
from .helpers.material_animations import describe_material_animations


def describe_scene(sections, options, logger=StubLogger()):
    """Convert parsed node tree sections into a fully populated IRScene.

    In: sections (list[SectionInfo], from Phase 3); options (dict, importer options including 'filepath', 'pkx_header', 'strict_mirror'); logger (Logger, defaults to StubLogger).
    Out: IRScene, with models/lights/cameras populated (no bpy state touched).
    """

    logger.info("=== Phase 4: Describe Scene ===")
    t0 = time.time()

    # Route sections into model sets and lights (matching legacy ModelBuilder logic)
    model_sets = []
    light_nodes = []
    camera_nodes = []      # Camera nodes (for static properties)
    camera_set_nodes = []  # CameraSet nodes (for animations)
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

        elif isinstance(root, CameraSet):
            if root.camera:
                camera_nodes.append(root.camera)
                camera_set_nodes.append(root)

        elif isinstance(root, SceneData):
            if root.models is not None:
                model_sets.extend(root.models)
            if root.lights is not None:
                for light_set in root.lights:
                    if hasattr(light_set, 'light') and light_set.light:
                        light_nodes.append(light_set.light)
            if root.camera and root.camera.camera:
                camera_nodes.append(root.camera.camera)
                camera_set_nodes.append(root.camera)

    # If we accumulated disjoint sections into a model set, create one
    if disjoint_root_joint is not None:
        disjoint_set = type('DisjointModelSet', (), {
            'root_joint': disjoint_root_joint,
            'animated_joints': disjoint_anim_joints,
            'animated_material_joints': disjoint_mat_anim_joints,
        })()
        model_sets.append(disjoint_set)

    logger.info("Routed %d model set(s), %d light(s), %d camera(s) in %.3fs",
                len(model_sets), len(light_nodes), len(camera_nodes), time.time() - t0)

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
        bones, joint_to_bone_index = describe_bones(root_joint, options, logger=logger)
        logger.info("  Bones: %d (%.3fs)", len(bones), time.time() - t1)

        t3 = time.time()
        bone_anims = describe_bone_animations(model_set, joint_to_bone_index, bones, options, logger, model_name=model_name)
        logger.info("  Animations: %d sets (%.3fs)", len(bone_anims), time.time() - t3)

        # Rebind near-zero-rest bones *before* mesh vertices get baked into
        # world space. describe_meshes transforms bone-local vertices via
        # bones[i].world_matrix, so it has to run after the world matrices
        # are rebound — otherwise mesh verts stay at pre-rebind positions
        # while bones move to post-rebind positions, breaking skinning.
        if not options.get("strict_mirror"):
            from .helpers.bones import fix_near_zero_bone_matrices
            fix_near_zero_bone_matrices(bones, bone_anims, logger)
        else:
            near_zero_count = sum(
                1 for b in bones if any(abs(b.scale[c]) < 0.001 for c in range(3))
            )
            if near_zero_count:
                logger.leniency("near_zero_bone_not_rescued",
                                "%d bones have near-zero rest scale; not rescued in strict mode",
                                near_zero_count)

        t2 = time.time()
        meshes = describe_meshes(root_joint, bones, joint_to_bone_index, logger=logger, options=options)
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

        t4 = time.time()
        ik_c, cl_c, tt_c, cr_c, lr_c, ll_c = describe_constraints(root_joint, bones, joint_to_bone_index)
        total_c = len(ik_c) + len(cl_c) + len(tt_c) + len(cr_c) + len(lr_c) + len(ll_c)
        logger.info("  Constraints: %d (%.3fs)", total_c, time.time() - t4)

        t5 = time.time()
        mat_anims = describe_material_animations(model_set, joint_to_bone_index, bones, options, logger, model_name=model_name, total_meshes=len(meshes))
        logger.info("  Material animations: %d sets (%.3fs)", len(mat_anims), time.time() - t5)

        # Pair material animations into bone animation sets by index.
        # If there are more material animation sets than bone animation sets,
        # create placeholder bone animation sets for the unpaired ones so
        # material-only animations (e.g. water UV scrolling) aren't dropped.
        for i, mat_anim_set in enumerate(mat_anims):
            if i < len(bone_anims):
                bone_anims[i].material_tracks = mat_anim_set.tracks
                logger.debug("  Paired material anim '%s' → '%s' (%d tracks)",
                             mat_anim_set.name, bone_anims[i].name, len(mat_anim_set.tracks))
            else:
                placeholder_name = mat_anim_set.name.replace('MatAnim', 'Anim')
                placeholder = IRBoneAnimationSet(
                    name=placeholder_name,
                    tracks=[],
                    material_tracks=mat_anim_set.tracks,
                )
                bone_anims.append(placeholder)
                logger.leniency("material_anim_placeholder",
                                "Created placeholder bone anim '%s' for unpaired material anim '%s' (%d tracks)",
                                placeholder_name, mat_anim_set.name, len(mat_anim_set.tracks))

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

    # Describe cameras
    ir_cameras = []
    for i, cam_node in enumerate(camera_nodes):
        ir_cam = describe_camera(cam_node, i, options=options, logger=logger)
        if ir_cam:
            # Decode camera animations from the corresponding CameraSet
            if i < len(camera_set_nodes):
                ir_cam.animations = describe_camera_animations(
                    camera_set_nodes[i], camera_index=i, logger=logger, options=options)
            ir_cameras.append(ir_cam)
    if ir_cameras:
        logger.info("Cameras: %d", len(ir_cameras))

    if logger.leniency_count:
        summary = ", ".join("%d %s" % (v, k) for k, v in sorted(logger.leniency_categories.items()))
        logger.warning("Leniencies applied: %d (%s)", logger.leniency_count, summary)

    logger.info("=== Phase 4 complete: %d model(s), %d light(s), %d camera(s) ===",
                len(ir_models), len(ir_lights), len(ir_cameras))
    return IRScene(models=ir_models, lights=ir_lights, cameras=ir_cameras)
