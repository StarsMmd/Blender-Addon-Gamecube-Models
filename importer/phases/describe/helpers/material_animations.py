"""Describe material animation data from MaterialAnimationJoint trees.

Walks MaterialAnimationJoint tree parallel to Joint tree, decoding
material color/alpha and texture UV keyframes into IR types.
"""
try:
    from .....shared.Constants.hsd import *
    from .....shared.helpers.srgb import srgb_to_linear
    from .....shared.IR.animation import (
        IRMaterialAnimationSet, IRMaterialTrack, IRTextureUVTrack, IRKeyframe,
    )
    from .....shared.IR.enums import Interpolation
    from .keyframe_decoder import decode_fobjdesc
except (ImportError, SystemError):
    from shared.Constants.hsd import *
    from shared.helpers.srgb import srgb_to_linear
    from shared.IR.animation import (
        IRMaterialAnimationSet, IRMaterialTrack, IRTextureUVTrack, IRKeyframe,
    )
    from shared.IR.enums import Interpolation
    from importer.phases.describe.helpers.keyframe_decoder import decode_fobjdesc

# HSD material color/alpha track type → IR field name
_MAT_TRACK_MAP = {
    HSD_A_M_DIFFUSE_R: 'diffuse_r',
    HSD_A_M_DIFFUSE_G: 'diffuse_g',
    HSD_A_M_DIFFUSE_B: 'diffuse_b',
    HSD_A_M_ALPHA:     'alpha',
}

_SRGB_TRACKS = {HSD_A_M_DIFFUSE_R, HSD_A_M_DIFFUSE_G, HSD_A_M_DIFFUSE_B}

# HSD texture UV track type → (IR field name on IRTextureUVTrack)
_TEX_UV_MAP = {
    HSD_A_T_TRAU: 'translation_u',
    HSD_A_T_TRAV: 'translation_v',
    HSD_A_T_SCAU: 'scale_u',
    HSD_A_T_SCAV: 'scale_v',
    HSD_A_T_ROTX: 'rotation_x',
    HSD_A_T_ROTY: 'rotation_y',
    HSD_A_T_ROTZ: 'rotation_z',
}


def describe_material_animations(model_set, joint_to_bone_index, bones, options, logger):
    """Walk MaterialAnimationJoint trees and produce IRMaterialAnimationSet list.

    Returns:
        list[IRMaterialAnimationSet]
    """
    mat_anim_joints = getattr(model_set, 'animated_material_joints', None) or []
    root_joint = model_set.root_joint
    anim_sets = []

    for i, mat_anim_root in enumerate(mat_anim_joints):
        name = "%s_MatAnim_%02d" % (root_joint.name or "Model", i)
        tracks = []

        _walk_parallel(mat_anim_root, root_joint, tracks, joint_to_bone_index, bones, logger)

        if tracks:
            anim_sets.append(IRMaterialAnimationSet(name=name, tracks=tracks))
            logger.debug("  Material animation set '%s': %d tracks", name, len(tracks))

    return anim_sets


def _walk_parallel(mat_anim_joint, joint, tracks, jtb, bones, logger):
    """Walk MaterialAnimationJoint and Joint trees in parallel."""
    try:
        from .....shared.Nodes.Classes.Mesh.Mesh import Mesh
    except (ImportError, SystemError):
        from shared.Nodes.Classes.Mesh.Mesh import Mesh

    if mat_anim_joint.animation and joint.property and isinstance(joint.property, Mesh):
        mat_anim = mat_anim_joint.animation
        mesh = joint.property
        mesh_idx = 0
        while mat_anim and mesh:
            bone_idx = jtb.get(joint.address, 0)
            track = _describe_material_track(mat_anim, mesh, bones[bone_idx].name, mesh_idx, logger)
            if track:
                tracks.append(track)
            mat_anim = mat_anim.next
            mesh = mesh.next
            mesh_idx += 1

    if mat_anim_joint.child and joint.child:
        _walk_parallel(mat_anim_joint.child, joint.child, tracks, jtb, bones, logger)
    if mat_anim_joint.next and joint.next:
        _walk_parallel(mat_anim_joint.next, joint.next, tracks, jtb, bones, logger)


def _describe_material_track(mat_anim, mesh, bone_name, mesh_idx, logger):
    """Extract one MaterialAnimation into an IRMaterialTrack."""
    aobj = mat_anim.animation
    tex_anim = mat_anim.texture_animation

    has_aobj = aobj is not None and not (aobj.flags & AOBJ_NO_ANIM if aobj else True)
    has_tex = tex_anim is not None

    if not has_aobj and not has_tex:
        return None

    mesh_name = "mesh_%d_%s" % (mesh_idx, bone_name)
    loop = bool(aobj.flags & AOBJ_ANIM_LOOP) if aobj else False

    track = IRMaterialTrack(
        material_mesh_name=mesh_name,
        loop=loop,
    )

    # Decode color/alpha tracks
    if has_aobj:
        fobj = aobj.frame
        while fobj:
            field = _MAT_TRACK_MAP.get(fobj.type)
            if field:
                is_srgb = fobj.type in _SRGB_TRACKS
                scale = 1.0 / 255.0
                keyframes = decode_fobjdesc(fobj, bias=0, scale=scale)

                # Apply sRGB→linear conversion to keyframe values
                if is_srgb:
                    keyframes = [IRKeyframe(
                        frame=kf.frame,
                        value=srgb_to_linear(max(0.0, min(1.0, kf.value))),
                        interpolation=Interpolation.LINEAR,  # baked, so linear
                        handle_left=None,
                        handle_right=None,
                    ) for kf in keyframes]

                setattr(track, field, keyframes)
            fobj = fobj.next

    # Decode texture UV tracks
    if has_tex:
        ta = tex_anim
        while ta:
            uv_track = _describe_texture_uv_track(ta, logger)
            if uv_track:
                track.texture_uv_tracks.append(uv_track)
            ta = ta.next

    return track


def _describe_texture_uv_track(tex_anim, logger):
    """Extract one TextureAnimation into IRTextureUVTrack."""
    if not tex_anim.animation or (tex_anim.animation.flags & AOBJ_NO_ANIM):
        return None

    uv_track = IRTextureUVTrack(texture_index=tex_anim.id)

    fobj = tex_anim.animation.frame
    while fobj:
        field = _TEX_UV_MAP.get(fobj.type)
        if field:
            keyframes = decode_fobjdesc(fobj)
            setattr(uv_track, field, keyframes)
        fobj = fobj.next

    return uv_track
