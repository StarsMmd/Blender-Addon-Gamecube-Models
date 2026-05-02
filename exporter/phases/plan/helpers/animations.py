"""Plan BRAction list into IRBoneAnimationSet list.

Pure — no bpy. Walks each BRAction's BRBoneTracks + BRMaterialTracks
and produces an IRBoneAnimationSet with IRBoneTracks + IRMaterialTracks.
The rest-pose local matrix the IR carries (used by compose to
reconstruct the source SRT) is rebuilt from the BR rest SRT triple via
`compile_srt_matrix` — same formula the importer uses on the way down.
"""
try:
    from .....shared.IR.animation import (
        IRBoneAnimationSet, IRBoneTrack, IRMaterialTrack,
    )
    from .....shared.helpers.math_shim import compile_srt_matrix
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR.animation import (
        IRBoneAnimationSet, IRBoneTrack, IRMaterialTrack,
    )
    from shared.helpers.math_shim import compile_srt_matrix
    from shared.helpers.logger import StubLogger


def plan_actions(br_actions, logger=StubLogger()):
    """Convert BRAction list to IRBoneAnimationSet list.

    In: br_actions (list[BRAction]); logger.
    Out: list[IRBoneAnimationSet] in the same order.
    """
    return [_br_action_to_ir(a) for a in br_actions]


def _br_action_to_ir(br_action):
    return IRBoneAnimationSet(
        name=br_action.name,
        tracks=[_br_bone_track_to_ir(t) for t in br_action.bone_tracks],
        material_tracks=[_br_material_track_to_ir(t) for t in br_action.material_tracks],
        loop=br_action.loop,
        is_static=br_action.is_static,
    )


def _br_bone_track_to_ir(br_track):
    rest_local = compile_srt_matrix(
        br_track.rest_scale,
        br_track.rest_rotation,
        br_track.rest_position,
    )
    rest_local_matrix = _matrix_to_list(rest_local)
    return IRBoneTrack(
        bone_name=br_track.bone_name,
        bone_index=br_track.bone_index,
        rotation=br_track.rotation,
        location=br_track.location,
        scale=br_track.scale,
        rest_local_matrix=rest_local_matrix,
        rest_rotation=br_track.rest_rotation,
        rest_position=br_track.rest_position,
        rest_scale=br_track.rest_scale,
        end_frame=br_track.end_frame,
        spline_path=br_track.spline_path,
    )


def _br_material_track_to_ir(br_track):
    return IRMaterialTrack(
        material_mesh_name=br_track.material_mesh_name,
        diffuse_r=br_track.diffuse_r,
        diffuse_g=br_track.diffuse_g,
        diffuse_b=br_track.diffuse_b,
        alpha=br_track.alpha,
        texture_uv_tracks=list(br_track.texture_uv_tracks),
        loop=br_track.loop,
    )


def _matrix_to_list(m):
    """Coerce a mathutils.Matrix or 4x4 nested list into a list of lists
    of floats. Pure path — `compile_srt_matrix` returns a Matrix when
    mathutils is available and a list-of-lists otherwise."""
    if hasattr(m, 'to_list'):
        return [list(row) for row in m.to_list()]
    if hasattr(m, '__getitem__') and hasattr(m, '__len__') and len(m) == 4:
        return [
            [float(m[i][j]) for j in range(4)]
            for i in range(4)
        ]
    return m
