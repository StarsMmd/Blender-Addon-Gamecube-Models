"""Describe animation data from AnimationJoint trees.

Walks AnimationJoint tree parallel to Joint tree, extracting raw HSD
keyframe data per channel per bone. The actual baking to bone-local
space is deferred to Phase 5A since it requires fcurve evaluation.
"""
import struct

try:
    from ...shared.Constants.hsd import *
    from ...shared.IO.Logger import NullLogger
except (ImportError, SystemError):
    from shared.Constants.hsd import *
    from shared.IO.Logger import NullLogger


# Lightweight container for raw animation data passed to Phase 5A
class RawBoneAnimation:
    """Raw HSD keyframe data for one bone, before baking."""
    __slots__ = ('bone_name', 'bone_index', 'channels', 'end_frame', 'loop', 'has_path',
                 'rest_rotation', 'rest_position', 'rest_scale', 'path_fobj', 'joint')

    def __init__(self, bone_name, bone_index, joint):
        self.bone_name = bone_name
        self.bone_index = bone_index
        self.joint = joint  # The Joint node (needed for compileSRTMatrix in Phase 5A)
        self.channels = {}  # {hsd_type: Frame node}
        self.end_frame = 0
        self.loop = False
        self.has_path = False
        self.rest_rotation = (0, 0, 0)
        self.rest_position = (0, 0, 0)
        self.rest_scale = (1, 1, 1)
        self.path_fobj = None


class RawAnimationSet:
    """Raw animation data for one animation set (all bones)."""
    __slots__ = ('name', 'bone_anims', 'loop')

    def __init__(self, name):
        self.name = name
        self.bone_anims = []  # list[RawBoneAnimation]
        self.loop = False


def describe_bone_animations(model_set, joint_to_bone_index, bones, options, logger=None):
    """Walk AnimationJoint trees and extract raw animation data.

    Args:
        model_set: Parsed model set with animated_joints list.
        joint_to_bone_index: dict mapping Joint.address → bone index.
        bones: list[IRBone] from describe_bones().
        options: importer options dict.
        logger: Logger instance.

    Returns:
        list[RawAnimationSet] — raw animation data for Phase 5A to bake.
    """
    if logger is None:
        logger = NullLogger()

    animated_joints = getattr(model_set, 'animated_joints', [])
    root_joint = model_set.root_joint
    raw_sets = []

    for i, anim_joint_root in enumerate(animated_joints):
        name = "%s_Anim_%02d" % (root_joint.name or "Model", i)
        raw_set = RawAnimationSet(name)

        _walk_parallel(anim_joint_root, root_joint, raw_set, joint_to_bone_index, bones, logger)

        raw_sets.append(raw_set)
        logger.debug("  Animation set '%s': %d bone animations", name, len(raw_set.bone_anims))

    return raw_sets


def _walk_parallel(anim_joint, joint, raw_set, joint_to_bone_index, bones, logger):
    """Walk AnimationJoint and Joint trees in parallel, extracting animation data."""
    bone_index = joint_to_bone_index.get(joint.address, 0)
    bone_name = bones[bone_index].name

    if anim_joint.animation:
        aobj = anim_joint.animation

        if not (aobj.flags & AOBJ_NO_ANIM):
            raw_anim = RawBoneAnimation(bone_name, bone_index, joint)
            raw_anim.end_frame = aobj.end_frame
            raw_anim.loop = bool(aobj.flags & AOBJ_ANIM_LOOP)
            raw_anim.rest_rotation = tuple(joint.rotation)
            raw_anim.rest_position = tuple(joint.position)
            raw_anim.rest_scale = tuple(joint.scale)
            raw_set.loop = raw_set.loop or raw_anim.loop

            fobj = aobj.frame
            while fobj:
                if fobj.type == HSD_A_J_PATH:
                    raw_anim.has_path = True
                    raw_anim.path_fobj = fobj
                elif HSD_A_J_ROTX <= fobj.type <= HSD_A_J_SCAZ:
                    raw_anim.channels[fobj.type] = fobj
                fobj = fobj.next

            raw_set.bone_anims.append(raw_anim)

    # Parallel tree walk
    if anim_joint.child and joint.child:
        _walk_parallel(anim_joint.child, joint.child, raw_set, joint_to_bone_index, bones, logger)
    if anim_joint.next and joint.next:
        _walk_parallel(anim_joint.next, joint.next, raw_set, joint_to_bone_index, bones, logger)
