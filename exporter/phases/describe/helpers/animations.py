"""Snapshot Blender Actions into BRAction dataclasses.

The deep work — frame-by-frame fcurve sampling, pose unbaking, Bezier
sparsification, material-animation fcurve scanning — happens in
``animations_decode.py`` because it relies on bpy fcurve evaluation and
mathutils matrix math. That helper produces IRBoneAnimationSets; this
shell repackages each one into a BRAction with concrete BRBoneTracks
and BRMaterialTracks so the rest of the pipeline runs through BR types
without a side-channel stash.

The export side does not populate ``BRBoneTrack.bake_context`` — the
basis math is only used by `build_blender` on the importer side.
"""
try:
    from .....shared.BR.actions import BRAction, BRBoneTrack, BRMaterialTrack
    from .....shared.helpers.logger import StubLogger
    from .animations_decode import describe_bone_animations
except (ImportError, SystemError):
    from shared.BR.actions import BRAction, BRBoneTrack, BRMaterialTrack
    from shared.helpers.logger import StubLogger
    from exporter.phases.describe.helpers.animations_decode import describe_bone_animations


def describe_actions(armature, br_armature, ir_bones, logger=StubLogger(),
                     use_bezier=True, referenced_actions=None,
                     ir_meshes=None, blender_materials=None):
    """Read Blender Actions associated with an armature into BRAction list.

    In: armature (bpy.types.Object); br_armature (BRArmature, currently
        unused but kept for forward compatibility); ir_bones (list[IRBone]
        the unbaker needs for rest-pose data); logger; use_bezier (bool,
        controls sparsifier); referenced_actions (optional set[str] used
        to drop unreferenced actions that bloat the DAT); ir_meshes /
        blender_materials (parallel lists for material-anim binding;
        either both supplied or both None).
    Out: list[BRAction] with concrete BRBoneTracks + BRMaterialTracks.
    """
    ir_anim_sets = describe_bone_animations(
        armature, ir_bones, logger=logger, use_bezier=use_bezier,
        referenced_actions=referenced_actions,
        meshes=ir_meshes, mesh_materials=blender_materials,
    )

    return [_ir_anim_set_to_br_action(s) for s in ir_anim_sets]


def _ir_anim_set_to_br_action(ir_set):
    """Wrap an IRBoneAnimationSet's tracks into a BRAction. The IR
    keyframe objects (`IRKeyframe`) are reused by reference — BR's
    spec lets per-axis channels carry IRKeyframe instances directly.
    """
    return BRAction(
        name=ir_set.name,
        bone_tracks=[_ir_bone_track_to_br(t) for t in ir_set.tracks],
        material_tracks=[_ir_material_track_to_br(t) for t in ir_set.material_tracks],
        loop=ir_set.loop,
        is_static=getattr(ir_set, 'is_static', False),
    )


def _ir_bone_track_to_br(ir_track):
    return BRBoneTrack(
        bone_name=ir_track.bone_name,
        bone_index=ir_track.bone_index,
        rotation=ir_track.rotation,
        location=ir_track.location,
        scale=ir_track.scale,
        rest_rotation=ir_track.rest_rotation,
        rest_position=ir_track.rest_position,
        rest_scale=ir_track.rest_scale,
        end_frame=ir_track.end_frame,
        bake_context=None,  # Importer-only; exporter doesn't use it.
        spline_path=ir_track.spline_path,
    )


def _ir_material_track_to_br(ir_track):
    return BRMaterialTrack(
        material_mesh_name=ir_track.material_mesh_name,
        diffuse_r=ir_track.diffuse_r,
        diffuse_g=ir_track.diffuse_g,
        diffuse_b=ir_track.diffuse_b,
        alpha=ir_track.alpha,
        texture_uv_tracks=list(ir_track.texture_uv_tracks),
        loop=ir_track.loop,
    )
