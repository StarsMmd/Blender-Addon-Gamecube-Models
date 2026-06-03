"""Describe material animation data from MaterialAnimationJoint trees.

Walks MaterialAnimationJoint tree parallel to Joint tree, decoding
material color/alpha and texture UV keyframes into IR types.
"""
from types import SimpleNamespace

try:
    from .....shared.Constants.hsd import *
    from .....shared.IR.animation import (
        IRMaterialTrack, IRTextureUVTrack, IRKeyframe,
    )
    from .....shared.IR.enums import Interpolation
    from .keyframe_decoder import decode_fobjdesc
except (ImportError, SystemError):
    from shared.Constants.hsd import *
    from shared.IR.animation import (
        IRMaterialTrack, IRTextureUVTrack, IRKeyframe,
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


def describe_material_animations(model_set, joint_to_bone_index, bones, options, logger, model_name=None, total_meshes=0):
    """Walk MaterialAnimationJoint trees and emit material animation sets.

    In: model_set (parsed, with .animated_material_joints); joint_to_bone_index (dict[int,int]); bones (list[IRBone]); options (dict); logger (Logger); model_name (str|None, name prefix); total_meshes (int, ≥0, controls index padding).
    Out: list[SimpleNamespace] each with .name (str) and .tracks (list[IRMaterialTrack]); empty if no tracks decoded.
    """
    mat_anim_joints = getattr(model_set, 'animated_material_joints', None) or []
    root_joint = model_set.root_joint
    name_prefix = model_name or root_joint.name or "Model"
    mesh_digits = len(str(max(total_meshes - 1, 0))) if total_meshes > 0 else 1
    anim_sets = []

    for i, mat_anim_root in enumerate(mat_anim_joints):
        name = "%s_MatAnim_%02d" % (name_prefix, i)
        tracks = []

        _walk_parallel(mat_anim_root, root_joint, tracks, joint_to_bone_index, bones, logger, mesh_digits=mesh_digits, options=options)

        if tracks:
            anim_sets.append(SimpleNamespace(name=name, tracks=tracks))
            logger.debug("  Material animation set '%s': %d tracks", name, len(tracks))

    return anim_sets


def _walk_parallel(mat_anim_joint, joint, tracks, jtb, bones, logger, mesh_digits=1, options=None):
    """Walk MaterialAnimationJoint and Joint trees in parallel, appending one IRMaterialTrack per PObj.

    In: mat_anim_joint (MaterialAnimationJoint); joint (Joint, tree-aligned); tracks (list[IRMaterialTrack], appended in place); jtb (dict[int,int]); bones (list[IRBone]); logger (Logger); mesh_digits (int, ≥1, name padding); options (dict|None).
    Out: None — mutates `tracks` in place.
    """
    try:
        from .....shared.Nodes.Classes.Mesh.Mesh import Mesh
    except (ImportError, SystemError):
        from shared.Nodes.Classes.Mesh.Mesh import Mesh

    if mat_anim_joint.animation and joint.property and isinstance(joint.property, Mesh):
        mat_anim = mat_anim_joint.animation
        mesh = joint.property
        bone_idx = jtb.get(joint.address, 0)
        bone = bones[bone_idx]
        # Use global mesh indices from IRBone to match build phase keying.
        # Each DObj may produce multiple PObjs (IRMeshes), so step through
        # mesh_indices by counting PObjs per DObj.
        pobj_offset = 0  # cumulative PObj count within this bone's meshes
        while mat_anim and mesh:
            # Count PObjs in this DObj
            pobj_count = 0
            pobj = mesh.pobject
            while pobj:
                pobj_count += 1
                pobj = pobj.next
            pobj_count = max(pobj_count, 1)

            # Create a track for EACH PObj in this DObj, since each PObj
            # becomes a separate IRMesh with its own Blender material.
            for p in range(pobj_count):
                idx = pobj_offset + p
                global_idx = bone.mesh_indices[idx] if idx < len(bone.mesh_indices) else 0
                track = _describe_material_track(mat_anim, mesh, bone.name, global_idx, logger, mesh_digits=mesh_digits, options=options)
                if track:
                    tracks.append(track)

            pobj_offset += pobj_count
            mat_anim = mat_anim.next
            mesh = mesh.next

    if mat_anim_joint.child and joint.child:
        _walk_parallel(mat_anim_joint.child, joint.child, tracks, jtb, bones, logger, mesh_digits=mesh_digits, options=options)
    if mat_anim_joint.next and joint.next:
        _walk_parallel(mat_anim_joint.next, joint.next, tracks, jtb, bones, logger, mesh_digits=mesh_digits, options=options)


def _describe_material_track(mat_anim, mesh, bone_name, mesh_idx, logger, mesh_digits=1, options=None):
    """Extract one MaterialAnimation (color/alpha + texture UV chains) into an IRMaterialTrack.

    In: mat_anim (MaterialAnimation node); mesh (Mesh node, for static texture lookup); bone_name (str); mesh_idx (int, ≥0, global IRMesh index); logger (Logger); mesh_digits (int, ≥1); options (dict|None).
    Out: IRMaterialTrack|None — None if the animation has neither AOBJ nor texture animation.
    """
    aobj = mat_anim.animation
    tex_anim = mat_anim.texture_animation

    has_aobj = aobj is not None and not (aobj.flags & AOBJ_NO_ANIM if aobj else True)
    has_tex = tex_anim is not None

    if not has_aobj and not has_tex:
        return None

    mesh_name = "mesh_%s_%s" % (str(mesh_idx).zfill(mesh_digits), bone_name)
    loop = bool(aobj.flags & AOBJ_ANIM_LOOP) if aobj else False

    track = IRMaterialTrack(
        material_mesh_name=mesh_name,
        loop=loop,
    )

    # Decode color/alpha tracks (stored as sRGB [0-1] in IR;
    # linearization for Blender happens in Phase 5).
    # Raw keyframe values from the FObjDesc are already in 0-1 range
    # (same encoding as bone animation tracks), not byte-range 0-255.
    if has_aobj:
        fobj = aobj.frame
        while fobj:
            field = _MAT_TRACK_MAP.get(fobj.type)
            if field:
                keyframes = decode_fobjdesc(fobj, bias=0, scale=1.0, logger=logger, options=options)
                setattr(track, field, keyframes)
            fobj = fobj.next

    # Build lookup of static texture nodes by index
    static_textures = {}
    if mesh.mobject and mesh.mobject.texture:
        tex = mesh.mobject.texture
        tex_idx = 0
        while tex:
            static_textures[tex_idx] = tex
            tex = tex.next
            tex_idx += 1

    # Decode texture UV tracks
    if has_tex:
        ta = tex_anim
        while ta:
            static_tex = static_textures.get(ta.id)
            uv_track = _describe_texture_uv_track(ta, static_tex, logger, options)
            if uv_track:
                track.texture_uv_tracks.append(uv_track)
            ta = ta.next

    return track


def _describe_texture_uv_track(tex_anim, static_texture, logger, options=None):
    """Extract one TextureAnimation into an IRTextureUVTrack with V-flipped translation.

    In: tex_anim (TextureAnimation node); static_texture (Texture|None, for static scale_v fallback); logger (Logger); options (dict|None).
    Out: IRTextureUVTrack|None — None if the animation is empty/disabled.
    """
    if not tex_anim.animation or (tex_anim.animation.flags & AOBJ_NO_ANIM):
        return None

    uv_track = IRTextureUVTrack(texture_index=tex_anim.id)

    fobj = tex_anim.animation.frame
    while fobj:
        field = _TEX_UV_MAP.get(fobj.type)
        if field:
            keyframes = decode_fobjdesc(fobj, logger=logger, options=options)
            setattr(uv_track, field, keyframes)
        fobj = fobj.next

    # Apply V-flip: v_corrected = 1 - scale_v - translation_v
    # GX UV origin is top-left, IR uses bottom-left (standard).
    if uv_track.translation_v:
        static_scale_v = static_texture.scale[1] if static_texture else 1.0
        uv_track.translation_v = _flip_translation_v(
            uv_track.translation_v, uv_track.scale_v, static_scale_v)

    return uv_track


def _flip_translation_v(translation_kfs, scale_kfs, static_scale_v):
    """Flip translation_v keyframes from GX top-left UV origin to standard bottom-left.

    In: translation_kfs (list[IRKeyframe], V translation); scale_kfs (list[IRKeyframe], may be empty for static scale); static_scale_v (float, used when scale_kfs empty).
    Out: list[IRKeyframe], same length as translation_kfs, with v = 1 - scale_v - translation_v applied (handles flipped too).
    """
    if not scale_kfs:
        # Static scale — simple offset
        return [IRKeyframe(
            frame=kf.frame,
            value=1.0 - static_scale_v - kf.value,
            interpolation=kf.interpolation,
            handle_left=(kf.handle_left[0], 1.0 - static_scale_v - kf.handle_left[1]) if kf.handle_left else None,
            handle_right=(kf.handle_right[0], 1.0 - static_scale_v - kf.handle_right[1]) if kf.handle_right else None,
        ) for kf in translation_kfs]

    # Animated scale — evaluate scale at each translation keyframe's frame
    result = []
    for kf in translation_kfs:
        scale_at_frame = _evaluate_track(scale_kfs, kf.frame)
        corrected = 1.0 - scale_at_frame - kf.value

        # For handles: evaluate scale at the handle's frame position too
        left = None
        if kf.handle_left:
            scale_at_left = _evaluate_track(scale_kfs, kf.handle_left[0])
            left = (kf.handle_left[0], 1.0 - scale_at_left - kf.handle_left[1])

        right = None
        if kf.handle_right:
            scale_at_right = _evaluate_track(scale_kfs, kf.handle_right[0])
            right = (kf.handle_right[0], 1.0 - scale_at_right - kf.handle_right[1])

        result.append(IRKeyframe(
            frame=kf.frame,
            value=corrected,
            interpolation=kf.interpolation,
            handle_left=left,
            handle_right=right,
        ))

    return result


def _evaluate_track(keyframes, frame):
    """Evaluate a keyframe track at a given frame using its per-keyframe interpolation.

    In: keyframes (list[IRKeyframe], sorted by frame, may be empty); frame (number, any).
    Out: float — interpolated value (CONSTANT/LINEAR/BEZIER); 0.0 if keyframes empty; clamped to endpoints outside range.
    """
    if not keyframes:
        return 0.0

    # Before first keyframe
    if frame <= keyframes[0].frame:
        return keyframes[0].value

    # After last keyframe
    if frame >= keyframes[-1].frame:
        return keyframes[-1].value

    # Binary search for the bracket containing frame
    lo, hi = 0, len(keyframes) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if keyframes[mid].frame <= frame:
            lo = mid
        else:
            hi = mid

    kf0 = keyframes[lo]
    kf1 = keyframes[hi]

    if kf0.interpolation == Interpolation.CONSTANT:
        return kf0.value

    t = (frame - kf0.frame) / (kf1.frame - kf0.frame) if kf1.frame != kf0.frame else 0.0

    if kf0.interpolation == Interpolation.LINEAR:
        return kf0.value + t * (kf1.value - kf0.value)

    if kf0.interpolation == Interpolation.BEZIER:
        if kf0.handle_right and kf1.handle_left:
            p0 = kf0.value
            p1 = kf0.handle_right[1]
            p2 = kf1.handle_left[1]
            p3 = kf1.value
            u = 1 - t
            return u*u*u*p0 + 3*u*u*t*p1 + 3*u*t*t*p2 + t*t*t*p3
        else:
            return kf0.value + t * (kf1.value - kf0.value)

    return keyframes[-1].value
