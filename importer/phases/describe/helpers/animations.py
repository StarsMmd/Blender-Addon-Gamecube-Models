"""Describe animation data from AnimationJoint trees.

Walks AnimationJoint tree parallel to Joint tree, extracting raw HSD
keyframe data per channel per bone. The actual baking to bone-local
space is deferred to Phase 5A since it requires fcurve evaluation.
"""
import struct

try:
    from .....shared.Constants.hsd import *
    from .....shared.IO.Logger import NullLogger
except (ImportError, SystemError):
    from shared.Constants.hsd import *
    from shared.IO.Logger import NullLogger


class RawBoneAnimation:
    """Raw HSD keyframe data for one bone, before baking."""
    __slots__ = ('bone_name', 'bone_index', 'channels', 'end_frame', 'loop', 'has_path',
                 'rest_rotation', 'rest_position', 'rest_scale', 'path_fobj',
                 'parent_scl', 'spline_points')

    def __init__(self, bone_name, bone_index):
        self.bone_name = bone_name
        self.bone_index = bone_index
        self.channels = {}  # {hsd_type: Frame node}
        self.end_frame = 0
        self.loop = False
        self.has_path = False
        self.rest_rotation = (0, 0, 0)
        self.rest_position = (0, 0, 0)
        self.rest_scale = (1, 1, 1)
        self.parent_scl = None  # parent's accumulated scale for compileSRTMatrix
        self.path_fobj = None
        self.spline_points = None  # list of [x,y,z] control points for path animation


class RawAnimationSet:
    """Raw animation data for one animation set (all bones)."""
    __slots__ = ('name', 'bone_anims', 'bone_data_lookup', 'loop')

    def __init__(self, name, bone_data_lookup):
        self.name = name
        self.bone_anims = []  # list[RawBoneAnimation]
        self.bone_data_lookup = bone_data_lookup  # {bone_index: {name, parent_index, matrices...}}
        self.loop = False


def describe_bone_animations(model_set, joint_to_bone_index, bones, bone_data_lookup, options, logger=NullLogger()):
    """Walk AnimationJoint trees and extract raw animation data.

    Args:
        model_set: Parsed model set with animated_joints list.
        joint_to_bone_index: dict mapping Joint.address -> bone index.
        bones: list[IRBone] from describe_bones().
        bone_data_lookup: dict from build_bone_data_lookup().
        options: importer options dict.
        logger: Logger instance.

    Returns:
        list[RawAnimationSet] -- raw animation data for Phase 5A to bake.
    """

    animated_joints = getattr(model_set, 'animated_joints', [])
    root_joint = model_set.root_joint
    raw_sets = []

    for i, anim_joint_root in enumerate(animated_joints):
        name = "%s_Anim_%02d" % (root_joint.name or "Model", i)
        raw_set = RawAnimationSet(name, bone_data_lookup)

        _walk_parallel(anim_joint_root, root_joint, raw_set, joint_to_bone_index, bones, logger)

        raw_sets.append(raw_set)
        logger.debug("  Animation set '%s': %d bone animations", name, len(raw_set.bone_anims))

    return raw_sets


def _walk_parallel(anim_joint, joint, raw_set, joint_to_bone_index, bones, logger):
    """Walk AnimationJoint and Joint trees in parallel, extracting animation data."""
    bone_index = joint_to_bone_index.get(joint.address, 0)
    bone = bones[bone_index]

    if anim_joint.animation:
        aobj = anim_joint.animation

        if not (aobj.flags & AOBJ_NO_ANIM):
            raw_anim = RawBoneAnimation(bone.name, bone_index)
            raw_anim.end_frame = aobj.end_frame
            raw_anim.loop = bool(aobj.flags & AOBJ_ANIM_LOOP)
            raw_anim.rest_rotation = tuple(joint.rotation)
            raw_anim.rest_position = tuple(joint.position)
            raw_anim.rest_scale = tuple(joint.scale)
            raw_set.loop = raw_set.loop or raw_anim.loop

            # Store parent accumulated scale for compileSRTMatrix
            if bone.parent_index is not None:
                parent_bone = bones[bone.parent_index]
                raw_anim.parent_scl = parent_bone.accumulated_scale
            else:
                raw_anim.parent_scl = None

            fobj = aobj.frame
            while fobj:
                if fobj.type == HSD_A_J_PATH:
                    raw_anim.has_path = True
                    raw_anim.path_fobj = fobj
                    # Extract spline points from Joint property
                    if joint.property and hasattr(joint.property, 's1') and joint.property.s1:
                        raw_anim.spline_points = [list(p) for p in joint.property.s1]
                elif HSD_A_J_ROTX <= fobj.type <= HSD_A_J_SCAZ:
                    raw_anim.channels[fobj.type] = fobj
                fobj = fobj.next

            raw_set.bone_anims.append(raw_anim)

    # Parallel tree walk
    if anim_joint.child and joint.child:
        _walk_parallel(anim_joint.child, joint.child, raw_set, joint_to_bone_index, bones, logger)
    if anim_joint.next and joint.next:
        _walk_parallel(anim_joint.next, joint.next, raw_set, joint_to_bone_index, bones, logger)
