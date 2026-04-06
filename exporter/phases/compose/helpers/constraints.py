"""Compose IR constraints into Joint Reference chains.

Reverses importer/phases/describe/helpers/constraints.py. Takes IR
constraint lists and attaches Reference node chains to the appropriate
Joint nodes.
"""
import struct

try:
    from .....shared.Nodes.Classes.Joints.Reference import Reference
    from .....shared.Nodes.Classes.Joints.BoneReference import BoneReference
    from .....shared.Constants.hsd import (
        ROBJ_ACTIVE_BIT, REFTYPE_JOBJ, REFTYPE_LIMIT, REFTYPE_IKHINT,
        JOBJ_TYPE_MASK, JOBJ_JOINT1, JOBJ_JOINT2, JOBJ_EFFECTOR,
    )
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.Nodes.Classes.Joints.Reference import Reference
    from shared.Nodes.Classes.Joints.BoneReference import BoneReference
    from shared.Constants.hsd import (
        ROBJ_ACTIVE_BIT, REFTYPE_JOBJ, REFTYPE_LIMIT, REFTYPE_IKHINT,
        JOBJ_TYPE_MASK, JOBJ_JOINT1, JOBJ_JOINT2, JOBJ_EFFECTOR,
    )
    from shared.helpers.logger import StubLogger


def compose_constraints(model, joints, bones, logger=StubLogger()):
    """Convert IR constraints into Joint Reference chains.

    Modifies joints in-place by setting joint.reference and joint.flags
    for IK chain bones.

    Args:
        model: IRModel with constraint lists.
        joints: list[Joint] indexed by bone index.
        bones: list[IRBone] for name → index lookup.
        logger: Logger instance.
    """
    total = (len(model.ik_constraints) + len(model.copy_location_constraints) +
             len(model.track_to_constraints) + len(model.copy_rotation_constraints) +
             len(model.limit_rotation_constraints) + len(model.limit_location_constraints))
    if total == 0:
        return

    bone_name_to_idx = {b.name: i for i, b in enumerate(bones)}

    # Collect all references per bone, then chain them at the end
    refs_by_bone = {}

    def _add_ref(bone_idx, ref):
        refs_by_bone.setdefault(bone_idx, []).append(ref)

    # IK constraints — set joint type flags and create Reference nodes
    for ik in model.ik_constraints:
        _compose_ik(ik, joints, bones, bone_name_to_idx, _add_ref)

    # Copy Location
    for cl in model.copy_location_constraints:
        bone_idx = bone_name_to_idx.get(cl.bone_name)
        target_idx = bone_name_to_idx.get(cl.target_bone)
        if bone_idx is None or target_idx is None:
            continue

        ref = Reference(address=None, blender_obj=None)
        ref.flags = ROBJ_ACTIVE_BIT | REFTYPE_JOBJ | 1
        ref.sub_type = 1
        ref.property = joints[target_idx]
        ref.next = None
        _add_ref(bone_idx, ref)

    # Track To
    for tt in model.track_to_constraints:
        bone_idx = bone_name_to_idx.get(tt.bone_name)
        target_idx = bone_name_to_idx.get(tt.target_bone)
        if bone_idx is None or target_idx is None:
            continue

        ref = Reference(address=None, blender_obj=None)
        ref.flags = ROBJ_ACTIVE_BIT | REFTYPE_JOBJ | 2
        ref.sub_type = 2
        ref.property = joints[target_idx]
        ref.next = None
        _add_ref(bone_idx, ref)

    # Copy Rotation
    for cr in model.copy_rotation_constraints:
        bone_idx = bone_name_to_idx.get(cr.bone_name)
        target_idx = bone_name_to_idx.get(cr.target_bone)
        if bone_idx is None or target_idx is None:
            continue

        ref = Reference(address=None, blender_obj=None)
        ref.flags = ROBJ_ACTIVE_BIT | REFTYPE_JOBJ | 4
        ref.sub_type = 4
        ref.property = joints[target_idx]
        ref.next = None
        _add_ref(bone_idx, ref)

        # Set the LOCAL flag (bit 0x8) on the joint if the space is LOCAL
        if cr.owner_space == 'LOCAL':
            joints[bone_idx].flags |= 0x8

    # Limit Rotation (sub_types 1-6)
    for lim in model.limit_rotation_constraints:
        _compose_limits(lim, 'rot', joints, bone_name_to_idx, _add_ref)

    # Limit Location (sub_types 7-12)
    for lim in model.limit_location_constraints:
        _compose_limits(lim, 'pos', joints, bone_name_to_idx, _add_ref)

    # Chain references and attach to joints
    for bone_idx, ref_list in refs_by_bone.items():
        for i in range(len(ref_list) - 1):
            ref_list[i].next = ref_list[i + 1]
        joints[bone_idx].reference = ref_list[0]

    logger.info("    Composed %d constraint(s) across %d bone(s)",
                total, len(refs_by_bone))


def _compose_ik(ik, joints, bones, bone_name_to_idx, _add_ref):
    """Compose IK constraint into joint type flags and Reference nodes."""
    effector_idx = bone_name_to_idx.get(ik.bone_name)
    if effector_idx is None:
        return

    parent_idx = bones[effector_idx].parent_index
    if parent_idx is None:
        return

    # Set joint type flags on the IK chain bones
    # Clear existing type bits first, then set new ones
    joints[effector_idx].flags = (joints[effector_idx].flags & ~JOBJ_TYPE_MASK) | JOBJ_EFFECTOR

    if ik.chain_length == 3:
        joints[parent_idx].flags = (joints[parent_idx].flags & ~JOBJ_TYPE_MASK) | JOBJ_JOINT2
        grandparent_idx = bones[parent_idx].parent_index
        if grandparent_idx is not None:
            joints[grandparent_idx].flags = (joints[grandparent_idx].flags & ~JOBJ_TYPE_MASK) | JOBJ_JOINT1
            pole_data_idx = grandparent_idx
        else:
            pole_data_idx = parent_idx
    elif ik.chain_length == 2:
        joints[parent_idx].flags = (joints[parent_idx].flags & ~JOBJ_TYPE_MASK) | JOBJ_JOINT1
        pole_data_idx = parent_idx

    # Target reference on the effector
    if ik.target_bone:
        target_idx = bone_name_to_idx.get(ik.target_bone)
        if target_idx is not None:
            ref = Reference(address=None, blender_obj=None)
            ref.flags = ROBJ_ACTIVE_BIT | REFTYPE_JOBJ | 1
            ref.sub_type = 1
            ref.property = joints[target_idx]
            ref.next = None
            _add_ref(effector_idx, ref)

    # Pole target reference on the pole data joint (JOINT1 ancestor)
    if ik.pole_target_bone:
        pole_target_idx = bone_name_to_idx.get(ik.pole_target_bone)
        if pole_target_idx is not None:
            ref = Reference(address=None, blender_obj=None)
            ref.flags = ROBJ_ACTIVE_BIT | REFTYPE_JOBJ | 3
            ref.sub_type = 3
            ref.property = joints[pole_target_idx]
            ref.next = None
            _add_ref(pole_data_idx, ref)

    # BoneReference nodes for IK bone lengths
    # The effector's parent gets a BoneReference with the effector's bone length
    # The pole data joint gets a BoneReference with the JOINT2's bone length (chain_length=3)
    #
    # Pole angle encoding: the IR stores the final pole angle (after any
    # pole_flip addition in the describe phase). The original binary may store
    # the raw angle with or without the pole_flip flag — we preserve the raw
    # angle directly in the BoneReference since that's what the format expects.
    pole_angle = ik.pole_angle

    for reposition in ik.bone_repositions:
        repo_idx = bone_name_to_idx.get(reposition.bone_name)
        if repo_idx is None:
            continue

        repo_parent_idx = bones[repo_idx].parent_index
        if repo_parent_idx is None:
            continue

        # De-scale the bone length by the parent's accumulated scale
        parent_scale = bones[repo_parent_idx].accumulated_scale[0]
        if parent_scale == 0:
            parent_scale = 1.0
        raw_length = reposition.bone_length / parent_scale

        br = BoneReference(address=None, blender_obj=None)
        br.length = raw_length
        br.pole_angle = pole_angle

        ref = Reference(address=None, blender_obj=None)
        ref.flags = ROBJ_ACTIVE_BIT | REFTYPE_IKHINT | 0
        ref.sub_type = 0
        ref.property = br
        ref.next = None

        # BoneReference goes on the parent joint of the repositioned bone
        _add_ref(repo_parent_idx, ref)


def _compose_limits(lim, limit_var, joints, bone_name_to_idx, _add_ref):
    """Compose limit constraint into Reference nodes with float-as-uint property."""
    bone_idx = bone_name_to_idx.get(lim.bone_name)
    if bone_idx is None:
        return

    base_offset = 0 if limit_var == 'rot' else 6

    for component, axis in enumerate(('x', 'y', 'z')):
        for direction, dir_name in enumerate(('max', 'min')):
            attr = '%s_%s' % (dir_name, axis)
            value = getattr(lim, attr)
            if value is None:
                continue

            sub_type = base_offset + component * 2 + direction + 1

            ref = Reference(address=None, blender_obj=None)
            ref.flags = ROBJ_ACTIVE_BIT | REFTYPE_LIMIT | sub_type
            ref.sub_type = sub_type
            # Limit value: stored as float reinterpreted as uint
            ref.property = struct.unpack('>I', struct.pack('>f', value))[0]
            ref.next = None
            _add_ref(bone_idx, ref)
