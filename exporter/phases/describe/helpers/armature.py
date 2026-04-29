"""Snapshot a Blender armature into a BRArmature.

bpy lives here. Pure transformation (BR → IR) lives in
`exporter/phases/plan/helpers/armature.py`.
"""
import bpy

try:
    from .....shared.BR.armature import BRArmature, BRBone
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.BR.armature import BRArmature, BRBone
    from shared.helpers.logger import StubLogger


def describe_armature(armature, logger=StubLogger()):
    """Read a Blender armature into a BRArmature.

    Bones are captured depth-first (parents before children), the order
    the DAT format expects.

    In: armature (bpy.types.Object, type='ARMATURE'); logger.
    Out: BRArmature with edit-bone matrices in Blender frame.
    """
    armature_data = armature.data

    prev_active = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = armature
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    armature.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    roots = [b for b in armature_data.edit_bones if b.parent is None]
    ordered = []
    _collect_depth_first(roots, ordered)
    name_to_index = {b.name: i for i, b in enumerate(ordered)}

    snapshots = []
    for b in ordered:
        snapshots.append({
            'name': b.name,
            'parent_name': b.parent.name if b.parent else None,
            'matrix': [list(row) for row in b.matrix],
            'tail_offset': (
                b.tail.x - b.head.x,
                b.tail.y - b.head.y,
                b.tail.z - b.head.z,
            ),
            'use_connect': b.use_connect,
            'inherit_scale': b.inherit_scale,
            'hide': b.hide,
        })

    bpy.ops.object.mode_set(mode='OBJECT')

    pose_rotation_modes = {
        pb.name: pb.rotation_mode for pb in armature.pose.bones
    } if armature.pose else {}

    bpy.context.view_layer.objects.active = prev_active

    bones = []
    for snap in snapshots:
        parent_index = (
            name_to_index.get(snap['parent_name'])
            if snap['parent_name'] else None
        )
        bones.append(BRBone(
            name=snap['name'],
            parent_index=parent_index,
            edit_matrix=snap['matrix'],
            tail_offset=snap['tail_offset'],
            inherit_scale=snap['inherit_scale'],
            rotation_mode=pose_rotation_modes.get(snap['name'], 'XYZ'),
            use_connect=snap['use_connect'],
            is_hidden=snap['hide'],
        ))

    custom_props = {k: armature[k] for k in armature.keys()}

    logger.info("  Described armature '%s': %d bone(s)", armature.name, len(bones))
    return BRArmature(
        name=armature.name,
        bones=bones,
        display_type=armature_data.display_type,
        matrix_basis=[list(row) for row in armature.matrix_basis],
        custom_props=custom_props,
    )


def _collect_depth_first(siblings, result):
    for bone in siblings:
        result.append(bone)
        if bone.children:
            _collect_depth_first(bone.children, result)
