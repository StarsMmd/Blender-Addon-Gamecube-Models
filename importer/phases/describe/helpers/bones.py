"""Describe Joint tree as a flat list of IRBone dataclasses.

Ports the pure-data computation from Joint.buildBoneHierarchy() and
Joint.compileSRTMatrix(), producing IRBone instances without any bpy calls.
"""
try:
    from .....shared.helpers.math_shim import Matrix, Vector, Euler, compile_srt_matrix, matrix_to_list
    from .....shared.IR.skeleton import IRBone
    from .....shared.IR.enums import ScaleInheritance
    from .....shared.Constants.hsd import (
        JOBJ_HIDDEN, JOBJ_INSTANCE, JOBJ_EFFECTOR, JOBJ_SPLINE,
        JOBJ_TYPE_MASK, JOBJ_CLASSICAL_SCALING, JOBJ_USE_QUATERNION,
        JOBJ_BILLBOARD_FIELD, JOBJ_BILLBOARD, JOBJ_VBILLBOARD,
        JOBJ_HBILLBOARD, JOBJ_RBILLBOARD,
    )
except (ImportError, SystemError):
    from shared.helpers.math_shim import Matrix, Vector, Euler, compile_srt_matrix, matrix_to_list
    from shared.IR.skeleton import IRBone
    from shared.IR.enums import ScaleInheritance
    from shared.Constants.hsd import (
        JOBJ_HIDDEN, JOBJ_INSTANCE, JOBJ_EFFECTOR, JOBJ_SPLINE,
        JOBJ_TYPE_MASK, JOBJ_CLASSICAL_SCALING, JOBJ_USE_QUATERNION,
        JOBJ_BILLBOARD_FIELD, JOBJ_BILLBOARD, JOBJ_VBILLBOARD,
        JOBJ_HBILLBOARD, JOBJ_RBILLBOARD,
    )


def describe_bones(root_joint, options=None, logger=None):
    """Walk a Joint tree and produce a flat list of IRBone.

    Args:
        root_joint: Root Joint node from the parsed node tree.
        options: dict of importer options (uses 'ik_hack').
        logger: optional Logger instance.

    Returns:
        (list[IRBone], dict[int, int]) — bones list and joint_address→bone_index map.
    """
    if options is None:
        options = {}

    bones = []
    joint_to_bone_index = {}
    bone_count = [0]  # mutable counter for closure

    # Pre-count total bones to determine digit padding
    def _count_joints(joint):
        n = 1
        if joint.child and not (joint.flags & (1 << 12)):
            n += _count_joints(joint.child)
        if joint.next:
            n += _count_joints(joint.next)
        return n
    total_bones = _count_joints(root_joint)
    bone_digits = len(str(max(total_bones - 1, 0)))

    # Build bone_index → null joint suffix from PKX header
    _null_joint_suffixes = {}
    pkx_header = options.get("pkx_header") if options else None
    if pkx_header and pkx_header.anim_entries:
        _NJ_LABELS = [
            "Root", "Head", "Center", "Body3", "Neck", "HeadTop",
            "LimbA", "LimbB", "Sec8", "Sec9", "Sec10", "Sec11",
            "AttachA", "AttachB", "AttachC", "AttachD",
        ]
        # Count how many null joint fields reference each bone index
        bone_ref_counts = {}
        first_entry = pkx_header.anim_entries[0]
        for j in range(16):
            idx = first_entry.null_joint_bones[j]
            if idx >= 0:
                bone_ref_counts.setdefault(idx, []).append(_NJ_LABELS[j])
        # Only suffix bones referenced by exactly one field
        for idx, labels in bone_ref_counts.items():
            if len(labels) == 1:
                _null_joint_suffixes[idx] = labels[0]

    def _walk(joint, parent_index, parent_data):
        """Recursively describe a Joint and its children/siblings.

        parent_data is a dict with keys: scl, world_matrix, edit_matrix,
        edit_scale_correction — or None for roots.
        """
        my_index = len(bones)
        joint_to_bone_index[joint.address] = my_index

        idx = bone_count[0]
        name = 'Bone_%s' % str(idx).zfill(bone_digits)
        suffix = _null_joint_suffixes.get(idx)
        if suffix:
            name = '%s_%s' % (name, suffix)
        bone_count[0] += 1

        # Warn about special JOBJ flags that we preserve but don't fully handle.
        if logger:
            if joint.flags & JOBJ_USE_QUATERNION:
                logger.info("  WARNING: %s has JOBJ_USE_QUATERNION flag (0x%X) — "
                            "rotation may be incorrect if stored as quaternion",
                            name, joint.flags)
            billboard_type = joint.flags & JOBJ_BILLBOARD_FIELD
            if billboard_type:
                bb_names = {
                    JOBJ_BILLBOARD: 'BILLBOARD', JOBJ_VBILLBOARD: 'VBILLBOARD',
                    JOBJ_HBILLBOARD: 'HBILLBOARD', JOBJ_RBILLBOARD: 'RBILLBOARD',
                }
                logger.info("  INFO: %s has billboard flag: %s (camera-dependent, not visualized)",
                            name, bb_names.get(billboard_type, hex(billboard_type)))

        # Determine IK shrink
        ik_shrink = bool(
            options.get("ik_hack")
            and ((joint.flags & JOBJ_TYPE_MASK) == JOBJ_EFFECTOR
                 or joint.flags & JOBJ_SPLINE)
        )

        # Accumulate parent scales for aligned scale inheritance.
        # When JOBJ_CLASSICAL_SCALING is set, the bone's own scale does NOT
        # accumulate into the chain — only the parent's accumulated scale
        # passes through. Confirmed in HSD_JObjMakeMatrix.s: the flag
        # causes a direct copy of parent accumulated_scale, skipping the
        # multiplication by own scale.
        if parent_data:
            if joint.flags & JOBJ_CLASSICAL_SCALING:
                accumulated_scale = parent_data['scl']
            else:
                accumulated_scale = tuple(
                    joint.scale[i] * parent_data['scl'][i] for i in range(3)
                )
            parent_scl = parent_data['scl']
        else:
            accumulated_scale = tuple(joint.scale)
            parent_scl = None

        # Build local SRT matrix
        local_matrix = compile_srt_matrix(
            joint.scale, joint.rotation, joint.position, parent_scl
        )

        # Compute world matrix
        if parent_data:
            world_matrix = parent_data['world_matrix'] @ local_matrix
        else:
            world_matrix = local_matrix

        # Compute normalized matrices for rest-pose binding
        normalized_world = world_matrix.normalized()
        if parent_data:
            normalized_local = parent_data['edit_matrix'].inverted() @ normalized_world
            scale_correction = (
                parent_data['edit_scale_correction']
                @ local_matrix.normalized().inverted()
                @ local_matrix
            )
        else:
            normalized_local = normalized_world
            scale_correction = local_matrix.normalized().inverted() @ local_matrix

        # Get inverse bind matrix if present
        inverse_bind = None
        if hasattr(joint, 'inverse_bind') and joint.inverse_bind is not None:
            inv = joint.inverse_bind
            if hasattr(inv, 'to_list'):
                inverse_bind = inv.to_list()
            elif isinstance(inv, (list, tuple)):
                inverse_bind = [list(row) for row in inv]
            else:
                inverse_bind = [[inv[i][j] for j in range(4)] for i in range(4)]

        bone = IRBone(
            name=name,
            parent_index=parent_index,
            position=tuple(joint.position),
            rotation=tuple(joint.rotation),
            scale=tuple(joint.scale),
            inverse_bind_matrix=inverse_bind,
            flags=joint.flags,
            is_hidden=bool(joint.flags & JOBJ_HIDDEN),
            inherit_scale=ScaleInheritance.ALIGNED,
            ik_shrink=ik_shrink,
            world_matrix=matrix_to_list(world_matrix),
            local_matrix=matrix_to_list(local_matrix),
            normalized_world_matrix=matrix_to_list(normalized_world),
            normalized_local_matrix=matrix_to_list(normalized_local),
            scale_correction=matrix_to_list(scale_correction),
            accumulated_scale=accumulated_scale,
        )
        bones.append(bone)

        # Data passed to children
        my_data = {
            'scl': accumulated_scale,
            'world_matrix': world_matrix,
            'edit_matrix': normalized_world,
            'edit_scale_correction': scale_correction,
        }

        # Recurse into children (skip instances)
        if joint.child and not (joint.flags & JOBJ_INSTANCE):
            _walk(joint.child, my_index, my_data)

        # Recurse into siblings (same parent)
        if joint.next:
            _walk(joint.next, parent_index, parent_data)

    _walk(root_joint, None, None)

    # Set instance_child_bone_index for JOBJ_INSTANCE bones
    _set_instance_refs(root_joint, bones, joint_to_bone_index)

    return bones, joint_to_bone_index


def _set_instance_refs(joint, bones, jtb):
    """Set instance_child_bone_index for JOBJ_INSTANCE bones."""
    if joint.flags & JOBJ_INSTANCE and joint.child:
        my_idx = jtb.get(joint.address)
        child_idx = jtb.get(joint.child.address)
        if my_idx is not None and child_idx is not None:
            bones[my_idx].instance_child_bone_index = child_idx
    if joint.child and not (joint.flags & JOBJ_INSTANCE):
        _set_instance_refs(joint.child, bones, jtb)
    if joint.next:
        _set_instance_refs(joint.next, bones, jtb)


def fix_near_zero_bone_matrices(bones, bone_animations, logger=None):
    """Recompute world matrices for bones with near-zero rest scale.

    When a bone has near-zero scale at rest, its world matrix has near-zero
    columns. Children's world matrices collapse to the parent's position.
    This fixes them by substituting the "visible scale" found in animation
    keyframes, then cascading corrected world matrices to all descendants.

    Must run AFTER both describe_bones and describe_bone_animations, since
    visible scales come from animation keyframe data.

    Args:
        bones: list[IRBone] — mutated in-place.
        bone_animations: list[IRBoneAnimationSet] from describe_bone_animations.
        logger: optional Logger instance.
    """
    nz = 0.001

    # Find bones with near-zero rest scale
    near_zero = set()
    for i, bone in enumerate(bones):
        if any(abs(bone.scale[c]) < nz for c in range(3)):
            near_zero.add(i)

    if not near_zero:
        return

    # Scan animation keyframes for visible scales
    visible_scales = {}  # {bone_index: (sx, sy, sz)}
    for anim_set in bone_animations:
        for track in anim_set.tracks:
            if track.bone_index not in near_zero:
                continue
            if track.bone_index in visible_scales:
                continue
            best = [None, None, None]
            for ch in range(3):
                for kf in track.scale[ch]:
                    if abs(kf.value) >= nz and best[ch] is None:
                        best[ch] = kf.value
            if all(v is not None for v in best):
                visible_scales[track.bone_index] = tuple(best)

    if not visible_scales:
        return

    # Determine which bones need world matrix recomputation:
    # near-zero bones with visible scales AND all their descendants
    needs_recompute = set()
    for idx in visible_scales:
        needs_recompute.add(idx)
    # Add all descendants of corrected bones
    for i, bone in enumerate(bones):
        if bone.parent_index in needs_recompute:
            needs_recompute.add(i)

    if logger:
        logger.debug("  fix_near_zero_bone_matrices: %d near-zero, %d with visible scale, %d to recompute",
                     len(near_zero), len(visible_scales), len(needs_recompute))

    # Walk top-down (bones are in DFS order = parent before child)
    for i in range(len(bones)):
        if i not in needs_recompute:
            continue

        bone = bones[i]

        if i in visible_scales:
            # Recompute local matrix with visible scale
            vis = visible_scales[i]
            local = compile_srt_matrix(vis, bone.rotation, bone.position)
        else:
            # Descendant of a corrected bone — keep own local matrix
            local = Matrix(bone.local_matrix)

        # Recompute world matrix from (potentially corrected) parent
        if bone.parent_index is not None:
            parent_world = Matrix(bones[bone.parent_index].world_matrix)
        else:
            parent_world = Matrix.Identity(4)

        world = parent_world @ local
        normalized_world = world.normalized()

        bone.world_matrix = matrix_to_list(world)
        bone.normalized_world_matrix = matrix_to_list(normalized_world)

        if i in visible_scales and logger:
            logger.debug("    Bone_%d: corrected with visible_scale=%s", i, visible_scales[i])
