"""Describe constraints from Joint Reference chains into IR constraint types."""
import math

try:
    from .....shared.Constants.hsd import *
    from .....shared.IR.constraints import (
        IRIKConstraint, IRBoneReposition, IRCopyLocationConstraint,
        IRTrackToConstraint, IRCopyRotationConstraint, IRLimitConstraint,
    )
    from .....shared.Nodes.Classes.Joints.Joint import Joint as JointCls
    from .....shared.Nodes.Classes.Joints.BoneReference import BoneReference
    from .....shared.helpers.scale import GC_TO_METERS
except (ImportError, SystemError):
    from shared.Constants.hsd import *
    from shared.IR.constraints import (
        IRIKConstraint, IRBoneReposition, IRCopyLocationConstraint,
        IRTrackToConstraint, IRCopyRotationConstraint, IRLimitConstraint,
    )
    from shared.Nodes.Classes.Joints.Joint import Joint as JointCls
    from shared.Nodes.Classes.Joints.BoneReference import BoneReference
    from shared.helpers.scale import GC_TO_METERS


def describe_constraints(root_joint, bones, joint_to_bone_index):
    """Extract constraints from Joint Reference chains across the whole tree.

    In: root_joint (Joint, parsed root); bones (list[IRBone]); joint_to_bone_index (dict[int,int]).
    Out: tuple of 6 lists (ik: list[IRIKConstraint], copy_location, track_to, copy_rotation, limit_rotation, limit_location).
    """
    # Build lookup maps
    addr_to_joint = {}
    _build_addr_map(root_joint, addr_to_joint)

    # Reverse map: bone_index → address (for O(1) parent lookups)
    bone_idx_to_addr = {idx: addr for addr, idx in joint_to_bone_index.items()}

    # Build parent map from IRBone data
    bone_to_parent = {}
    for idx, bone in enumerate(bones):
        if bone.parent_index is not None:
            bone_to_parent[idx] = bone.parent_index

    ik = []
    copy_loc = []
    track_to = []
    copy_rot = []
    limit_rot = []
    limit_loc = []

    for joint in addr_to_joint.values():
        bone_idx = joint_to_bone_index.get(joint.address, 0)
        joint_type = joint.flags & JOBJ_TYPE_MASK

        if joint_type == JOBJ_EFFECTOR:
            result = _describe_ik(joint, bones, joint_to_bone_index, addr_to_joint, bone_idx_to_addr)
            if result:
                ik.append(result)
        elif joint_type != JOBJ_JOINT2:
            cl, tt, cr, lr, ll = _describe_regular(joint, bones, joint_to_bone_index)
            copy_loc.extend(cl)
            track_to.extend(tt)
            copy_rot.extend(cr)
            limit_rot.extend(lr)
            limit_loc.extend(ll)

    return ik, copy_loc, track_to, copy_rot, limit_rot, limit_loc


def _build_addr_map(joint, result):
    """Build {Joint.address: Joint node} map by depth-first traversal.

    In: joint (Joint, recursed); result (dict[int, Joint], populated in place).
    Out: None — mutates `result`.
    """
    result[joint.address] = joint
    if joint.child and not (joint.flags & JOBJ_INSTANCE):
        _build_addr_map(joint.child, result)
    if joint.next:
        _build_addr_map(joint.next, result)


def _get_parent(joint, bones, jtb, addr_to_joint, bone_idx_to_addr):
    """Get the parent Joint node by routing through the IRBone parent_index.

    In: joint (Joint); bones (list[IRBone]); jtb (dict[int,int]); addr_to_joint (dict[int,Joint]); bone_idx_to_addr (dict[int,int]).
    Out: Joint|None — None if joint is root or lookup fails.
    """
    bone_idx = jtb.get(joint.address, 0)
    parent_idx = bones[bone_idx].parent_index
    if parent_idx is None:
        return None
    parent_addr = bone_idx_to_addr.get(parent_idx)
    if parent_addr is None:
        return None
    return addr_to_joint.get(parent_addr)


def _describe_ik(joint, bones, jtb, addr_to_joint, bone_idx_to_addr):
    """Extract an IRIKConstraint from a JOBJ_EFFECTOR joint and its chain.

    In: joint (Joint, must be effector type); bones (list[IRBone]); jtb (dict[int,int]); addr_to_joint (dict[int,Joint]); bone_idx_to_addr (dict[int,int]).
    Out: IRIKConstraint|None — None if chain or required reference objects are missing.
    """
    parent = _get_parent(joint, bones, jtb, addr_to_joint, bone_idx_to_addr)
    if not parent:
        return None

    parent_type = parent.flags & JOBJ_TYPE_MASK
    if parent_type == JOBJ_JOINT2:
        chain_length = 3
        grandparent = _get_parent(parent, bones, jtb, addr_to_joint, bone_idx_to_addr)
    elif parent_type == JOBJ_JOINT1:
        chain_length = 2
        grandparent = parent
    else:
        return None

    pole_data_joint = grandparent
    bone_idx = jtb.get(joint.address, 0)
    bone_name = bones[bone_idx].name

    target_robj = joint.getReferenceObject(JointCls, 1)
    poletarget_robj = pole_data_joint.getReferenceObject(JointCls, 3) if pole_data_joint else None
    effector_length_robj = parent.getReferenceObject(BoneReference, 0)
    joint2_length_robj = pole_data_joint.getReferenceObject(BoneReference, 0) if pole_data_joint else None

    if not effector_length_robj:
        return None

    # Pole angle
    pole_angle = (joint2_length_robj.property.pole_angle if joint2_length_robj
                  else effector_length_robj.property.pole_angle)
    if getattr(effector_length_robj.property, 'pole_flip', False):
        pole_angle += math.pi

    # Target bone names
    target_bone = _bone_name_for(target_robj, bones, jtb) if target_robj else None
    pole_target_bone = _bone_name_for(poletarget_robj, bones, jtb) if poletarget_robj else None

    # Bone repositions
    repositions = []
    parent_idx = jtb.get(parent.address, 0)
    parent_scale = bones[parent_idx].accumulated_scale[0]

    repositions.append(IRBoneReposition(
        bone_name=bone_name,
        bone_length=effector_length_robj.property.length * parent_scale * GC_TO_METERS,
    ))

    if chain_length == 3 and joint2_length_robj and pole_data_joint:
        pole_idx = jtb.get(pole_data_joint.address, 0)
        pole_scale = bones[pole_idx].accumulated_scale[0]
        parent_bone_name = bones[parent_idx].name
        repositions.append(IRBoneReposition(
            bone_name=parent_bone_name,
            bone_length=joint2_length_robj.property.length * pole_scale * GC_TO_METERS,
        ))

    return IRIKConstraint(
        bone_name=bone_name,
        chain_length=chain_length,
        target_bone=target_bone,
        pole_target_bone=pole_target_bone,
        pole_angle=pole_angle,
        bone_repositions=repositions,
    )


def _describe_regular(joint, bones, jtb):
    """Extract non-IK constraints (copy-loc/rot, track-to, limits) from a joint's Reference chain.

    In: joint (Joint, non-effector); bones (list[IRBone]); jtb (dict[int,int]).
    Out: tuple of 5 lists (copy_location, track_to, copy_rotation, limit_rotation, limit_location); each may be empty.
    """
    bone_idx = jtb.get(joint.address, 0)
    bone_name = bones[bone_idx].name

    copy_loc = []
    track_to = []
    copy_rot = []
    limit_rot = []
    limit_loc = []

    if not joint.reference:
        return copy_loc, track_to, copy_rot, limit_rot, limit_loc

    copy_pos_refs = []
    dirup_x_ref = None
    orientation_ref = None
    limits = []

    reference = joint.reference
    while reference:
        if not (reference.flags & ROBJ_ACTIVE_BIT):
            reference = reference.next
            continue

        ref_type = reference.flags & ROBJ_TYPE_MASK

        if ref_type == REFTYPE_JOBJ and isinstance(reference.property, JointCls):
            if reference.sub_type == 1:
                copy_pos_refs.append(reference)
            elif reference.sub_type == 2:
                dirup_x_ref = reference
            elif reference.sub_type == 4:
                orientation_ref = reference

        elif ref_type == REFTYPE_LIMIT:
            ct = reference.sub_type
            if 1 <= ct <= 12:
                limit_var = ['rot', 'pos'][(ct - 1) // 6]
                component = ((ct - 1) % 6) // 2
                direction = (ct - 1) % 2
                limits.append((limit_var, component, direction, reference.property))

        reference = reference.next

    # Copy Location
    if copy_pos_refs:
        weight = 1.0 / len(copy_pos_refs)
        for ref in copy_pos_refs:
            tname = _bone_name_for(ref, bones, jtb)
            if tname:
                copy_loc.append(IRCopyLocationConstraint(
                    bone_name=bone_name, target_bone=tname, influence=weight))

    # Track To
    if dirup_x_ref:
        tname = _bone_name_for(dirup_x_ref, bones, jtb)
        if tname:
            track_to.append(IRTrackToConstraint(
                bone_name=bone_name, target_bone=tname,
                track_axis='TRACK_X', up_axis='UP_Y'))

    # Copy Rotation
    if orientation_ref:
        tname = _bone_name_for(orientation_ref, bones, jtb)
        if tname:
            space = 'LOCAL' if (joint.flags & 0x8) else 'WORLD'
            copy_rot.append(IRCopyRotationConstraint(
                bone_name=bone_name, target_bone=tname,
                owner_space=space, target_space=space))

    # Limits
    for limit_var, component, direction, value in limits:
        axis = ['x', 'y', 'z'][component]
        # Scale location limits to meters (rotation limits stay in radians)
        if limit_var == 'pos':
            value *= GC_TO_METERS
        target_list = limit_rot if limit_var == 'rot' else limit_loc
        existing = next((c for c in target_list if c.bone_name == bone_name), None)
        if not existing:
            existing = IRLimitConstraint(bone_name=bone_name)
            target_list.append(existing)
        attr = '%s_%s' % ('max' if direction == 0 else 'min', axis)
        current = getattr(existing, attr)
        if current is not None:
            if direction == 0:
                value = max(current, value)
            else:
                value = min(current, value)
        setattr(existing, attr, value)

    return copy_loc, track_to, copy_rot, limit_rot, limit_loc


def _bone_name_for(ref_obj, bones, jtb):
    """Resolve the bone name targeted by a Reference object's Joint property.

    In: ref_obj (Reference|None, with .property→Joint); bones (list[IRBone]); jtb (dict[int,int]).
    Out: str|None — bone name, or None if ref_obj is None or address not found.
    """
    if ref_obj and hasattr(ref_obj.property, 'address'):
        idx = jtb.get(ref_obj.property.address)
        if idx is not None:
            return bones[idx].name
    return None
