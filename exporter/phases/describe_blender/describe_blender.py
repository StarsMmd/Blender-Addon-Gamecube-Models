"""Phase 1 (Export): Read Blender scene into an IRScene.

Reads armatures and their child meshes from the Blender scene and
produces an IRScene suitable for composition into node trees.

Works with arbitrary Blender models — no assumptions about naming
conventions or import-specific metadata.

Also extracts shiny filter parameters from armature custom properties
if present, for writing back into PKX headers during packaging.
"""
import bpy

try:
    from ....shared.IR import IRScene, IRModel
    from ....shared.IR.animation import IRBoneAnimationSet
    from ....shared.IR.enums import SkinType
    from ....shared.Constants.hsd import (
        JOBJ_SKELETON, JOBJ_SKELETON_ROOT, JOBJ_ENVELOPE_MODEL,
        JOBJ_LIGHTING, JOBJ_OPA, JOBJ_ROOT_OPA, JOBJ_HIDDEN,
    )
    from ....shared.helpers.logger import StubLogger
    from .helpers.skeleton import describe_skeleton
    from .helpers.meshes import describe_meshes
    from .helpers.animations import describe_bone_animations
    from .helpers.lights import describe_lights
    from .helpers.cameras import describe_cameras
    from .helpers.constraints import describe_constraints
except (ImportError, SystemError):
    from shared.IR import IRScene, IRModel
    from shared.IR.animation import IRBoneAnimationSet
    from shared.IR.enums import SkinType
    from shared.Constants.hsd import (
        JOBJ_SKELETON, JOBJ_SKELETON_ROOT, JOBJ_ENVELOPE_MODEL,
        JOBJ_LIGHTING, JOBJ_OPA, JOBJ_ROOT_OPA, JOBJ_HIDDEN,
    )
    from shared.helpers.logger import StubLogger
    from exporter.phases.describe_blender.helpers.skeleton import describe_skeleton
    from exporter.phases.describe_blender.helpers.meshes import describe_meshes
    from exporter.phases.describe_blender.helpers.animations import describe_bone_animations
    from exporter.phases.describe_blender.helpers.lights import describe_lights
    from exporter.phases.describe_blender.helpers.cameras import describe_cameras
    from exporter.phases.describe_blender.helpers.constraints import describe_constraints


def describe_blender_scene(context, options=None, logger=StubLogger()):
    """Read the active Blender scene and produce an IRScene.

    Exports the entire Blender scene. Each armature becomes one IRModel
    with its parented meshes, animations, and constraints. Scene-level
    lights are also included.

    Args:
        context: Blender context with active scene.
        options: dict of exporter options.
        logger: Logger instance.

    Returns:
        (IRScene, ShinyParams | None) — the scene description and optional
        shiny filter parameters (or None if no shiny data found).
    """
    if options is None:
        options = {}

    logger.info("=== Export Phase 1: Describe Blender Scene ===")

    # Collect all armatures in the scene
    armatures = [
        obj for obj in context.scene.objects
        if obj.type == 'ARMATURE'
    ]

    if not armatures:
        raise ValueError(
            "No armatures in the scene. The scene must contain at least one armature to export."
        )

    models = []
    for armature in armatures:
        logger.info("  Processing armature '%s'", armature.name)

        bones = describe_skeleton(armature, logger=logger)
        meshes = describe_meshes(armature, bones, logger=logger)

        # Populate mesh_indices on bones
        for mesh_idx, ir_mesh in enumerate(meshes):
            bone_idx = ir_mesh.parent_bone_index
            if bone_idx < len(bones):
                bones[bone_idx].mesh_indices.append(mesh_idx)

        # Refine bone flags now that we know which bones own meshes
        _refine_bone_flags(bones, meshes, logger)

        bones_with_meshes = sum(1 for b in bones if b.mesh_indices)
        logger.info("  Mesh attachment: %d mesh(es) across %d bone(s)", len(meshes), bones_with_meshes)
        for b in bones:
            if b.mesh_indices:
                logger.debug("    bone '%s': mesh_indices=%s flags=%#x", b.name, b.mesh_indices, b.flags)

        # Describe animations from Blender actions
        use_bezier = options.get('sparsify_bezier', True)
        bone_animations = describe_bone_animations(armature, bones, logger=logger, use_bezier=use_bezier)

        # Describe constraints from pose bones
        ik_c, cl_c, tt_c, cr_c, lr_c, ll_c = describe_constraints(armature, bones, logger=logger)

        model = IRModel(
            name=armature.name,
            bones=bones,
            meshes=meshes,
            bone_animations=bone_animations,
            ik_constraints=ik_c,
            copy_location_constraints=cl_c,
            track_to_constraints=tt_c,
            copy_rotation_constraints=cr_c,
            limit_rotation_constraints=lr_c,
            limit_location_constraints=ll_c,
        )
        models.append(model)

    # Describe lights and cameras from the Blender scene
    ir_lights = describe_lights(context, logger=logger)
    ir_cameras = describe_cameras(context, logger=logger)

    ir_scene = IRScene(models=models, lights=ir_lights, cameras=ir_cameras)

    # Extract shiny filter parameters from the first armature that has them
    shiny_params = _extract_shiny_params(armatures, logger)

    # Build action name → export animation index mapping
    # (first model's bone_animations determine the DAT animation order)
    action_name_to_index = {}
    if models and models[0].bone_animations:
        for idx, anim_set in enumerate(models[0].bone_animations):
            action_name_to_index[anim_set.name] = idx

    # Extract PKX header metadata if present
    pkx_header = _extract_pkx_header(armatures, action_name_to_index, logger)

    logger.info("=== Export Phase 1 complete: %d model(s), %d light(s), %d camera(s), shiny=%s, pkx=%s ===",
                len(ir_scene.models), len(ir_scene.lights), len(ir_scene.cameras),
                shiny_params is not None, pkx_header is not None)
    return ir_scene, shiny_params, pkx_header



def _refine_bone_flags(bones, meshes, logger):
    """Set bone flags based on mesh attachment and hierarchy position.

    Called after both bones and meshes are described, so we know which
    bones own geometry and what kind of skinning they use.

    Flag rules (matching HSD conventions):
        SKELETON_ROOT   — root bone of the armature
        SKELETON        — bones with inverse_bind_matrix (deformation bones)
        ENVELOPE_MODEL  — bones that own envelope-weighted meshes
        LIGHTING        — bones that own any mesh (mesh rendering uses lighting)
        OPA             — bones that own opaque meshes
        HIDDEN          — already set during skeleton describe from edit_bone.hide
        ROOT_OPA        — root-level bones in a chain that contains opaque meshes
        (none) / 0x0    — leaf bones with no mesh attachment and no deformation role
    """
    # Determine which bones own meshes and what kind
    bones_with_meshes = set()
    bones_with_envelope = set()
    for ir_mesh in meshes:
        bone_idx = ir_mesh.parent_bone_index
        if bone_idx < len(bones):
            bones_with_meshes.add(bone_idx)
            bw = ir_mesh.bone_weights
            if bw and bw.type == SkinType.WEIGHTED:
                bones_with_envelope.add(bone_idx)

    # Collect skinning target bones: any bone referenced by a mesh's
    # bone_weights as a SINGLE_BONE target or in WEIGHTED assignments.
    # These bones need inverse_bind_matrix and SKELETON flag.
    bone_name_to_idx = {b.name: i for i, b in enumerate(bones)}
    deformation_bones = set()
    for ir_mesh in meshes:
        bw = ir_mesh.bone_weights
        if bw and bw.bone_name:
            idx = bone_name_to_idx.get(bw.bone_name)
            if idx is not None:
                deformation_bones.add(idx)
        if bw and bw.assignments:
            for _, weight_list in bw.assignments:
                for bone_name, _ in weight_list:
                    idx = bone_name_to_idx.get(bone_name)
                    if idx is not None:
                        deformation_bones.add(idx)

    # Find which bones are at the root of a subtree containing meshes
    has_mesh_descendant = set()
    # Walk bottom-up: if a bone has meshes or a child with meshes, mark it
    for i in range(len(bones) - 1, -1, -1):
        if i in bones_with_meshes:
            has_mesh_descendant.add(i)
        if i in has_mesh_descendant and bones[i].parent_index is not None:
            has_mesh_descendant.add(bones[i].parent_index)

    for i, bone in enumerate(bones):
        flags = 0

        # Root bone
        if bone.parent_index is None:
            flags |= JOBJ_SKELETON_ROOT

        # Skeleton deformation bone
        if i in deformation_bones:
            flags |= JOBJ_SKELETON

        # Bone owns mesh(es)
        if i in bones_with_meshes:
            flags |= JOBJ_LIGHTING | JOBJ_OPA
            if i in bones_with_envelope:
                flags |= JOBJ_ENVELOPE_MODEL

        # ROOT_OPA: set on all bones in the hierarchy above mesh-owning bones.
        # In HSD, this marks the entire skeleton chain that participates in
        # rendering — from root down through all ancestors of mesh bones.
        if i in has_mesh_descendant:
            flags |= JOBJ_ROOT_OPA

        # HIDDEN: set if the bone is hidden in Blender (edit_bone.hide),
        # OR if all meshes on this bone are hidden (hide_render=True)
        if bone.is_hidden:
            flags |= JOBJ_HIDDEN
        elif i in bones_with_meshes:
            all_hidden = all(meshes[mi].is_hidden for mi in bone.mesh_indices)
            if all_hidden:
                flags |= JOBJ_HIDDEN
                bone.is_hidden = True

        bone.flags = flags

        # Only keep inverse_bind_matrix on skinning target bones
        if i not in deformation_bones:
            bone.inverse_bind_matrix = None

    logger.debug("  Refined bone flags for %d bones (%d with meshes, %d deformation, %d envelope)",
                 len(bones), len(bones_with_meshes), len(deformation_bones), len(bones_with_envelope))


def _extract_shiny_params(armatures, logger):
    """Extract shiny parameters from armature registered properties.

    Reads the dat_pkx_shiny_route_r/g/b/a enum props and
    dat_pkx_shiny_brightness_r/g/b float props.
    """
    try:
        from ....shared.helpers.shiny_params import ShinyParams
    except (ImportError, SystemError):
        from shared.helpers.shiny_params import ShinyParams

    for arm in armatures:
        try:
            route = [
                int(arm.dat_pkx_shiny_route_r),
                int(arm.dat_pkx_shiny_route_g),
                int(arm.dat_pkx_shiny_route_b),
                int(arm.dat_pkx_shiny_route_a),
            ]
            brightness = [
                arm.dat_pkx_shiny_brightness_r,
                arm.dat_pkx_shiny_brightness_g,
                arm.dat_pkx_shiny_brightness_b,
            ]
        except AttributeError:
            continue

        # Check if identity/neutral
        if route == [0, 1, 2, 3] and all(abs(b) < 0.01 for b in brightness):
            continue

        logger.info("  Found PKX shiny params on %s", arm.name)
        return ShinyParams(
            route_r=route[0], route_g=route[1],
            route_b=route[2], route_a=route[3],
            brightness_r=brightness[0],
            brightness_g=brightness[1],
            brightness_b=brightness[2],
            brightness_a=0.0,  # Alpha forced to max by the game
        )

    return None


def _extract_pkx_header(armatures, action_name_to_index, logger):
    """Extract PKX header metadata from armature custom properties.

    Reads dat_pkx_* properties stored during import (or applied by script)
    and reconstructs a PKXHeader suitable for serialization. Animation
    references are stored as action names and resolved to DAT indices
    using the export animation order.

    Args:
        armatures: list of Blender armature objects.
        action_name_to_index: dict mapping action name → export animation index.
        logger: Logger instance.

    Returns:
        PKXHeader, or None if no PKX metadata found.
    """
    try:
        from ....shared.helpers.pkx_header import (
            PKXHeader, AnimMetadataEntry, SubAnim, PartAnimData,
        )
    except (ImportError, SystemError):
        from shared.helpers.pkx_header import (
            PKXHeader, AnimMetadataEntry, SubAnim, PartAnimData,
        )

    for arm in armatures:
        fmt = arm.get("dat_pkx_format")
        if fmt not in ("XD", "COLOSSEUM"):
            continue

        is_xd = (fmt == "XD")
        h = PKXHeader(is_xd=is_xd)
        h.species_id = arm.get("dat_pkx_species_id", 0)
        h.particle_orientation = arm.get("dat_pkx_particle_orientation", 0)
        # Reconstruct flags byte from individual booleans
        flags = 0
        if arm.get("dat_pkx_flag_flying", False):
            flags |= 0x01
        if arm.get("dat_pkx_flag_skip_frac_frames", False):
            flags |= 0x04
        if arm.get("dat_pkx_flag_no_root_anim", False):
            flags |= 0x40
        if arm.get("dat_pkx_flag_bit7", False):
            flags |= 0x80
        h.flags = flags
        h.distortion_param = arm.get("dat_pkx_distortion_param", 0)
        h.distortion_type = arm.get("dat_pkx_distortion_type", 0)
        h.type_id = 0x000C

        # Resolve head bone name to index
        bone_list = list(arm.data.bones)
        bone_name_to_idx = {b.name: i for i, b in enumerate(bone_list)}
        head_name = arm.get("dat_pkx_head_bone", "")
        h.head_bone_index = bone_name_to_idx.get(head_name, 0)

        # Shiny — read from registered properties
        try:
            h.shiny_route = (
                int(arm.dat_pkx_shiny_route_r),
                int(arm.dat_pkx_shiny_route_g),
                int(arm.dat_pkx_shiny_route_b),
                int(arm.dat_pkx_shiny_route_a),
            )
            try:
                from ....shared.helpers.pkx import _from_brightness
            except (ImportError, SystemError):
                from shared.helpers.pkx import _from_brightness
            h.shiny_brightness = (
                _from_brightness(arm.dat_pkx_shiny_brightness_r),
                _from_brightness(arm.dat_pkx_shiny_brightness_g),
                _from_brightness(arm.dat_pkx_shiny_brightness_b),
                0xFF,  # Alpha forced to max
            )
        except AttributeError:
            pass  # No shiny registered props

        # Sub-animation data (was "part_anim_data")
        _SUB_TYPE_MAP = {"none": 0, "simple": 1, "targeted": 2}
        if is_xd:
            h.part_anim_data = []
            for i in range(4):
                prefix = "dat_pkx_sub_anim_%d" % i
                has_data = _SUB_TYPE_MAP.get(arm.get(prefix + "_type", "none"), 0)
                # Reconstruct bone_config from bone names if targeted
                bone_config = b'\xff' * 16
                if has_data == 2:
                    bones_str = arm.get(prefix + "_bones", "")
                    if bones_str:
                        bone_names_list = [n.strip() for n in bones_str.split(',') if n.strip()]
                        config = bytearray(16)
                        for bi, bn in enumerate(bone_names_list[:8]):
                            idx = bone_name_to_idx.get(bn, 0xFF)
                            config[bi] = idx if idx < 256 else 0xFF
                        for bi in range(len(bone_names_list), 16):
                            config[bi] = 0xFF
                        bone_config = bytes(config)
                pad = PartAnimData(
                    has_data=has_data,
                    sub_param=len([n for n in bone_config[:8] if n != 0xFF]) if has_data == 2 else 0,
                    bone_config=bone_config,
                    anim_index_ref=action_name_to_index.get(arm.get(prefix + "_anim_ref", ""), 0) if arm.get(prefix + "_anim_ref", "") else 0,
                )
                h.part_anim_data.append(pad)
        else:
            h.colo_part_anim_refs = [
                arm.get("dat_pkx_colo_part_ref_0", -1),
                arm.get("dat_pkx_colo_part_ref_1", -1),
                arm.get("dat_pkx_colo_part_ref_2", -1),
            ]
            h.colo_unknown_10 = 5
            h.colo_unknown_14 = arm.get("dat_pkx_particle_orientation", -1)

        # Body map bones. The game uses 16 slots but only 0-7 are actively
        # referenced by the XD battle code (root, head tracking, particle/
        # effect attachment). Slots 8-15 are always written as -1 (skip).
        _BODY_MAP_KEYS = [
            "root", "head", "center", "body_3", "neck", "head_top",
            "limb_a", "limb_b",
        ]
        model_body_map = []
        for j in range(len(_BODY_MAP_KEYS)):
            name = arm.get("dat_pkx_body_%s" % _BODY_MAP_KEYS[j], "")
            model_body_map.append(bone_name_to_idx.get(name, -1) if name else -1)
        model_body_map.extend([-1] * (16 - len(_BODY_MAP_KEYS)))

        # Animation entries
        anim_count = arm.get("dat_pkx_anim_count", 17)
        h.anim_section_count = anim_count
        h.anim_entries = []
        for i in range(anim_count):
            prefix = "dat_pkx_anim_%02d" % i
            anim_type_str = arm.get(prefix + "_type", "action")
            _ANIM_TYPE_TO_INT = {"loop": 2, "hit_reaction": 3, "action": 4, "compound": 5}
            anim_type = _ANIM_TYPE_TO_INT.get(anim_type_str, int(anim_type_str) if anim_type_str.isdigit() else 4)
            sub_count = arm.get(prefix + "_sub_count", 1)

            subs = []
            for s in range(min(sub_count, 3)):
                anim_name = arm.get(prefix + "_sub_%d_anim" % s, "")
                # Resolve action name to export index. Empty string = inactive (idx 0).
                if isinstance(anim_name, str) and anim_name:
                    anim_idx = action_name_to_index.get(anim_name, 0)
                elif isinstance(anim_name, int):
                    anim_idx = anim_name
                else:
                    anim_idx = 0
                # Derive motion_type from slot type and whether an action is assigned.
                # loop=2, action/hit_reaction/compound=1, empty/disabled=0.
                has_anim = isinstance(anim_name, str) and anim_name != ""
                if is_xd and has_anim:
                    derived_motion = 2 if anim_type_str == "loop" else 1
                else:
                    derived_motion = 0
                subs.append(SubAnim(
                    motion_type=derived_motion,
                    anim_index=anim_idx,
                ))
            if not subs:
                subs = [SubAnim(0, 0)]

            # Per-entry body map overrides (slots 0-7 only; 8-15 always -1).
            entry_bones = list(model_body_map)
            for j in range(len(_BODY_MAP_KEYS)):
                override_name = arm.get(prefix + "_body_%s" % _BODY_MAP_KEYS[j])
                if override_name is not None:
                    entry_bones[j] = bone_name_to_idx.get(override_name, -1) if override_name else -1

            entry = AnimMetadataEntry(
                anim_type=anim_type,
                sub_anim_count=sub_count,
                damage_flags=arm.get(prefix + "_damage_flags", 0),
                timing=(
                    arm.get(prefix + "_timing_1", 0.0),
                    arm.get(prefix + "_timing_2", 0.0),
                    arm.get(prefix + "_timing_3", 0.0),
                    arm.get(prefix + "_timing_4", 0.0),
                ),
                body_map_bones=entry_bones,
                sub_anims=subs,
                terminator=arm.get(prefix + "_terminator", 3 if is_xd else 1),
            )
            h.anim_entries.append(entry)

        logger.info("  Extracted PKX header from %s: format=%s, species=%d, %d entries",
                    arm.name, fmt, h.species_id, len(h.anim_entries))
        return h

    return None
