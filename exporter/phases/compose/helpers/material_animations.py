"""Compose IRMaterialTrack into MaterialAnimationJoint node trees.

Builds MaterialAnimationJoint trees (parallel to Joint tree) from
IRMaterialTrack data in each IRBoneAnimationSet. Each track maps to
a MaterialAnimation node attached to the bone that owns the mesh.
"""
from collections import defaultdict

try:
    from .....shared.Nodes.Classes.Material.MaterialAnimationJoint import MaterialAnimationJoint
    from .....shared.Nodes.Classes.Material.MaterialAnimation import MaterialAnimation
    from .....shared.Nodes.Classes.Texture.TextureAnimation import TextureAnimation
    from .....shared.Nodes.Classes.Animation.Animation import Animation
    from .....shared.Nodes.Classes.Animation.Frame import Frame
    from .....shared.Constants.hsd import (
        HSD_A_M_DIFFUSE_R, HSD_A_M_DIFFUSE_G, HSD_A_M_DIFFUSE_B, HSD_A_M_ALPHA,
        HSD_A_T_TRAU, HSD_A_T_TRAV, HSD_A_T_SCAU, HSD_A_T_SCAV,
        HSD_A_T_ROTX, HSD_A_T_ROTY, HSD_A_T_ROTZ,
        AOBJ_ANIM_LOOP,
    )
    from .....shared.helpers.logger import StubLogger
    from .animations import _encode_channel
except (ImportError, SystemError):
    from shared.Nodes.Classes.Material.MaterialAnimationJoint import MaterialAnimationJoint
    from shared.Nodes.Classes.Material.MaterialAnimation import MaterialAnimation
    from shared.Nodes.Classes.Texture.TextureAnimation import TextureAnimation
    from shared.Nodes.Classes.Animation.Animation import Animation
    from shared.Nodes.Classes.Animation.Frame import Frame
    from shared.Constants.hsd import (
        HSD_A_M_DIFFUSE_R, HSD_A_M_DIFFUSE_G, HSD_A_M_DIFFUSE_B, HSD_A_M_ALPHA,
        HSD_A_T_TRAU, HSD_A_T_TRAV, HSD_A_T_SCAU, HSD_A_T_SCAV,
        HSD_A_T_ROTX, HSD_A_T_ROTY, HSD_A_T_ROTZ,
        AOBJ_ANIM_LOOP,
    )
    from shared.helpers.logger import StubLogger
    from exporter.phases.compose.helpers.animations import _encode_channel

# IR field → HSD channel type for material color/alpha
_COLOR_CHANNELS = [
    ('diffuse_r', HSD_A_M_DIFFUSE_R),
    ('diffuse_g', HSD_A_M_DIFFUSE_G),
    ('diffuse_b', HSD_A_M_DIFFUSE_B),
    ('alpha',     HSD_A_M_ALPHA),
]

# IR field → HSD channel type for texture UV
_UV_CHANNELS = [
    ('translation_u', HSD_A_T_TRAU),
    ('translation_v', HSD_A_T_TRAV),
    ('scale_u',       HSD_A_T_SCAU),
    ('scale_v',       HSD_A_T_SCAV),
    ('rotation_x',    HSD_A_T_ROTX),
    ('rotation_y',    HSD_A_T_ROTY),
    ('rotation_z',    HSD_A_T_ROTZ),
]


def compose_material_animations(anim_set, bones, meshes, logger=StubLogger()):
    """Build a MaterialAnimationJoint tree from one IRBoneAnimationSet.

    The MaterialAnimation chain attached to each joint is walked in lockstep
    with the DObj (Mesh node) chain on import, so a MaterialAnimation at
    position N pairs with the Nth DObj under that bone. compose_meshes groups
    IRMeshes by material identity under each bone (one DObj per material);
    this function must mirror that grouping and emit one MaterialAnimation per
    DObj, using empty placeholders for DObjs whose material has no animation.

    Args:
        anim_set: IRBoneAnimationSet with material_tracks populated.
        bones: list[IRBone] from the IR.
        meshes: list[IRMesh] from the IR (needed to re-derive the per-bone
            DObj ordering compose_meshes will emit).
        logger: Logger instance.

    Returns:
        MaterialAnimationJoint root, or None if no material tracks.
    """
    if not anim_set.material_tracks:
        return None

    # Map mesh_index → bone_index from the IRBone mesh_indices lists
    mesh_to_bone = {}
    for bone_idx, bone in enumerate(bones):
        for mesh_idx in bone.mesh_indices:
            mesh_to_bone[mesh_idx] = bone_idx

    # Map id(material) → (track, material). DObjs group meshes by material
    # identity, so the track for one IRMesh's material is also the track
    # that applies to every other IRMesh sharing that same material on
    # the same bone. The material is carried alongside so
    # `_build_texture_animation` can look up the TObj's static UV scale
    # for the V-flip reversal.
    #
    # Foreign-key resolution: each track's `material_mesh_name` is an
    # opaque mesh id (matches `IRMesh.id`). Build a one-shot id→index
    # lookup so we don't depend on the legacy `mesh_NN_<bone>` synthetic
    # format being parseable. Falls back to that format only when an
    # IRMesh has no `id` set (legacy fixtures, intermediate test data).
    mesh_id_to_index = _build_mesh_id_lookup(meshes, bones)

    track_by_material_id = {}
    for track in anim_set.material_tracks:
        mesh_idx = mesh_id_to_index.get(track.material_mesh_name)
        if mesh_idx is None:
            continue
        if 0 <= mesh_idx < len(meshes):
            mat = meshes[mesh_idx].material
            if mat is not None:
                track_by_material_id[id(mat)] = (track, mat)

    # Per-bone DObj ordering must mirror compose_meshes: within each bone,
    # group by first-seen material id. The resulting list of material ids
    # gives the DObj positions 0..N-1.
    dobj_materials_by_bone = {}
    for bone_idx, bone in enumerate(bones):
        seen = []
        seen_set = set()
        for mesh_idx in bone.mesh_indices:
            if 0 <= mesh_idx < len(meshes):
                mat = meshes[mesh_idx].material
                mat_id = id(mat) if mat is not None else None
                if mat_id not in seen_set:
                    seen_set.add(mat_id)
                    seen.append(mat_id)
        dobj_materials_by_bone[bone_idx] = seen

    # Create MaterialAnimationJoint for every bone
    mat_joints = []
    bones_with_tracks = 0
    total_tracks = 0
    for i, bone in enumerate(bones):
        maj = MaterialAnimationJoint(address=None, blender_obj=None)
        maj.child = None
        maj.next = None

        dobj_mats = dobj_materials_by_bone.get(i, [])
        chain_head, real_count = _build_material_animation_chain(
            dobj_mats, track_by_material_id, anim_set.loop)
        maj.animation = chain_head
        if real_count:
            bones_with_tracks += 1
            total_tracks += real_count

        mat_joints.append(maj)

    # Reconstruct child/next tree from parent_index
    children_of = defaultdict(list)
    roots = []
    for i, bone in enumerate(bones):
        if bone.parent_index is None:
            roots.append(i)
        else:
            children_of[bone.parent_index].append(i)

    for parent_idx, child_indices in children_of.items():
        mat_joints[parent_idx].child = mat_joints[child_indices[0]]
        for j in range(1, len(child_indices)):
            mat_joints[child_indices[j - 1]].next = mat_joints[child_indices[j]]

    for j in range(1, len(roots)):
        mat_joints[roots[j - 1]].next = mat_joints[roots[j]]

    logger.info("    Composed material animation: %d track(s) across %d bone(s)",
                total_tracks, bones_with_tracks)

    return mat_joints[roots[0]] if roots else None


def _build_mesh_id_lookup(meshes, bones):
    """Map opaque IRMesh.id → mesh index, with a legacy fallback.

    Material animation tracks reference meshes by id-string. The
    canonical id is set on `IRMesh.id` at describe-time; for legacy
    paths that left it unset we fabricate the same `mesh_NN_<bone>`
    synthetic id on the fly so older IR data still binds.
    """
    digit_width = max(1, len(str(max(len(meshes) - 1, 0))))
    out = {}
    for i, mesh in enumerate(meshes):
        mesh_id = getattr(mesh, 'id', None)
        if not mesh_id:
            bone_idx = mesh.parent_bone_index
            bone_name = (bones[bone_idx].name
                         if 0 <= bone_idx < len(bones) else 'unknown')
            mesh_id = "mesh_%s_%s" % (str(i).zfill(digit_width), bone_name)
        out[mesh_id] = i
    return out


def _build_material_animation_chain(dobj_materials, track_by_material_id, loop):
    """Build a MaterialAnimation chain aligned with one bone's DObj ordering.

    `dobj_materials` is the ordered list of `id(material)` values the compose
    phase will emit as DObjs under this bone. The returned chain places a real
    MaterialAnimation at every DObj position whose material has a track, and
    an empty placeholder (animation=None, texture_animation=None) at every
    position whose material is unanimated. The chain length always equals the
    bone's DObj count — originals don't trim trailing empties and neither do
    we.

    Returns (chain_head, real_count). chain_head is None only when the bone
    has no DObjs at all. Mesh-bones with DObjs but no animated material emit
    an all-empty chain so the MAJ-to-DObj lockstep walk stays aligned.
    """
    mas = []
    for mat_id in dobj_materials:
        entry = track_by_material_id.get(mat_id)
        if entry is not None:
            track, material = entry
            ma = _build_material_animation(track, material, loop)
            if ma is None:
                ma = _build_empty_material_animation()
        else:
            ma = _build_empty_material_animation()
        mas.append(ma)

    if not mas:
        return None, 0

    for i in range(len(mas) - 1):
        mas[i].next = mas[i + 1]

    real_count = sum(1 for ma in mas if ma.animation is not None or ma.texture_animation is not None)
    return mas[0], real_count


def _build_empty_material_animation():
    """Placeholder MaterialAnimation for DObj positions that have no anim.

    The importer walks mat_anim alongside mesh (DObj) in lockstep; an MA with
    no animation and no texture_animation lets the walk advance to the next
    DObj without applying any fcurves to the current one.
    """
    ma = MaterialAnimation(address=None, blender_obj=None)
    ma.next = None
    ma.animation = None
    ma.texture_animation = None
    ma.render_animation = None
    return ma


def _build_material_animation(track, material, loop):
    """Build a MaterialAnimation node from one IRMaterialTrack.

    `material` is the IRMaterial that owns the track — its texture_layers
    provide the static UV scale needed to reverse the import-time V-flip.
    """
    ma = MaterialAnimation(address=None, blender_obj=None)
    ma.next = None
    ma.render_animation = None

    # Color/alpha animation
    color_frames = []
    for field_name, channel_type in _COLOR_CHANNELS:
        keyframes = getattr(track, field_name, None)
        if keyframes:
            # Scale values back to [0-255] range for HSD encoding
            scaled = []
            for kf in keyframes:
                from copy import copy
                skf = copy(kf)
                skf.value = kf.value * 255.0
                if kf.slope_in is not None:
                    skf.slope_in = kf.slope_in * 255.0
                if kf.slope_out is not None:
                    skf.slope_out = kf.slope_out * 255.0
                scaled.append(skf)
            frame = _encode_channel(scaled, channel_type)
            if frame is not None:
                color_frames.append(frame)

    if color_frames:
        for i in range(len(color_frames) - 1):
            color_frames[i].next = color_frames[i + 1]
        anim = Animation(address=None, blender_obj=None)
        anim.flags = AOBJ_ANIM_LOOP if loop else 0
        anim.end_frame = _end_frame_from_keyframes(
            track.diffuse_r, track.diffuse_g, track.diffuse_b, track.alpha)
        anim.joint = None
        anim.frame = color_frames[0]
        ma.animation = anim
    else:
        ma.animation = None

    # Texture UV animations
    tex_anims = []
    for uv_track in track.texture_uv_tracks:
        layer = None
        if material is not None and 0 <= uv_track.texture_index < len(material.texture_layers):
            layer = material.texture_layers[uv_track.texture_index]
        ta = _build_texture_animation(uv_track, layer, loop)
        if ta is not None:
            tex_anims.append(ta)

    if tex_anims:
        for i in range(len(tex_anims) - 1):
            tex_anims[i].next = tex_anims[i + 1]
        ma.texture_animation = tex_anims[0]
    else:
        ma.texture_animation = None

    # Only return if there's actual animation data
    if ma.animation is None and ma.texture_animation is None:
        return None

    return ma


def _build_texture_animation(uv_track, texture_layer, loop):
    """Build a TextureAnimation node from one IRTextureUVTrack.

    `texture_layer` is the IRTextureLayer the track targets; its `scale[1]`
    is the TObj's static V scale, needed to reverse the import V-flip when
    scale_v is not animated. Multi-frame eye textures have scale_v != 1.0
    (e.g. 0.25 for 4 stacked blink frames) and were previously broken.
    """
    static_scale_v = texture_layer.scale[1] if texture_layer is not None else 1.0
    uv_frames = []
    for field_name, channel_type in _UV_CHANNELS:
        keyframes = getattr(uv_track, field_name, None)
        if keyframes:
            # Reverse V-flip for translation_v: GX uses top-left origin
            if field_name == 'translation_v':
                keyframes = _unflip_translation_v(
                    keyframes, uv_track.scale_v, static_scale_v)

            frame = _encode_channel(keyframes, channel_type)
            if frame is not None:
                uv_frames.append(frame)

    if not uv_frames:
        return None

    for i in range(len(uv_frames) - 1):
        uv_frames[i].next = uv_frames[i + 1]

    all_kf_lists = []
    for field_name, _ in _UV_CHANNELS:
        kfs = getattr(uv_track, field_name, None)
        if kfs:
            all_kf_lists.append(kfs)

    anim = Animation(address=None, blender_obj=None)
    anim.flags = AOBJ_ANIM_LOOP if loop else 0
    anim.end_frame = _end_frame_from_keyframes(*all_kf_lists)
    anim.joint = None
    anim.frame = uv_frames[0]

    ta = TextureAnimation(address=None, blender_obj=None)
    ta.next = None
    ta.id = uv_track.texture_index
    ta.animation = anim
    ta.image_table = None
    ta.palette_table = None
    ta.image_table_count = 0
    ta.palette_table_count = 0

    return ta


def _unflip_translation_v(translation_kfs, scale_kfs, static_scale_v=1.0):
    """Reverse the V-flip applied during import.

    Import applied: v_ir = 1 - scale_v - v_gx, using the TObj's static
    scale[1] when scale_v is not animated. The reverse is the same
    formula; `static_scale_v` must match what the importer used or
    multi-frame eye textures (scale_v=0.25 for 4 stacked blink frames)
    round-trip to garbage.
    """
    from copy import copy

    if not scale_kfs:
        result = []
        for kf in translation_kfs:
            skf = copy(kf)
            skf.value = 1.0 - static_scale_v - kf.value
            # Slopes negate (derivative of -v is -slope)
            if kf.slope_in is not None:
                skf.slope_in = -kf.slope_in
            if kf.slope_out is not None:
                skf.slope_out = -kf.slope_out
            result.append(skf)
        return result

    # Animated scale — evaluate scale at each keyframe's frame
    try:
        from .....importer.phases.describe.helpers.material_animations import _evaluate_track
    except (ImportError, SystemError):
        from importer.phases.describe.helpers.material_animations import _evaluate_track

    result = []
    for kf in translation_kfs:
        skf = copy(kf)
        scale_at_frame = _evaluate_track(scale_kfs, kf.frame)
        skf.value = 1.0 - scale_at_frame - kf.value
        if kf.slope_in is not None:
            skf.slope_in = -kf.slope_in
        if kf.slope_out is not None:
            skf.slope_out = -kf.slope_out
        result.append(skf)
    return result


def _end_frame_from_keyframes(*channel_lists):
    """Get the maximum frame value across multiple keyframe channel lists."""
    max_frame = 0.0
    for channel in channel_lists:
        if channel:
            for kf in channel:
                max_frame = max(max_frame, kf.frame)
    return max_frame
