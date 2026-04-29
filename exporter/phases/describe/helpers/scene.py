"""Scene-level describe helpers — bpy-side reads that don't fit a single
domain helper: baked-transform validation, PKX/shiny custom-property
extraction, and the optional diagnostic dump.
"""
import os
import bpy

try:
    from .....shared.helpers.logger import StubLogger
    from .....shared.helpers.shiny_params import ShinyParams
    from .....shared.helpers.pkx_header import (
        PKXHeader, AnimMetadataEntry, SubAnim, PartAnimData,
    )
    from .....shared.helpers.pkx import _from_brightness
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger
    from shared.helpers.shiny_params import ShinyParams
    from shared.helpers.pkx_header import (
        PKXHeader, AnimMetadataEntry, SubAnim, PartAnimData,
    )
    from shared.helpers.pkx import _from_brightness


_PKX_BODY_MAP_KEYS = [
    "root", "head", "center", "body_3", "neck", "head_top",
    "limb_a", "limb_b",
    "secondary_8", "secondary_9", "secondary_10", "secondary_11",
    "attach_a", "attach_b", "attach_c", "attach_d",
]


def validate_baked_transforms(armatures):
    """Reject armatures (and their child meshes) with non-identity matrix_world.

    The exporter's bone path decomposes world matrices into SRT, which loses
    any shear introduced by combining a non-uniform armature scale with an
    edit-bone rotation. The vertex path uses a plain matmul that preserves
    that shear, so the two paths drift apart the further down the chain you
    go. Baking transforms upstream (scripts/prepare_for_export.py) keeps
    both paths in the same frame.
    """
    children_by_armature = {
        arm: [obj for obj in bpy.data.objects
              if obj.parent is arm and obj.type == 'MESH']
        for arm in armatures
    }
    check_baked_transforms(armatures, children_by_armature)


def check_baked_transforms(armatures, children_by_armature):
    """Pure helper: reject any armature or listed child mesh whose
    matrix_world is not identity. Split out from `validate_baked_transforms`
    so unit tests can drive it without owning a real `bpy.data.objects`.
    """
    bad = []
    for arm in armatures:
        if not _is_identity_matrix(arm.matrix_world):
            bad.append(arm.name)
        for child in children_by_armature.get(arm, ()):
            if not _is_identity_matrix(child.matrix_world):
                bad.append(child.name)
    if bad:
        raise ValueError(
            "Unbaked transforms on: " + ", ".join(bad) + ". "
            "Run scripts/prepare_for_export.py (or apply Object > Apply > "
            "All Transforms manually) so every armature and child mesh has "
            "identity matrix_world before exporting."
        )


def _is_identity_matrix(m, tol=1e-5):
    for i in range(4):
        for j in range(4):
            expected = 1.0 if i == j else 0.0
            if abs(m[i][j] - expected) > tol:
                return False
    return True


def collect_pkx_referenced_actions(armature):
    """Return the set of action names referenced by this armature's PKX slots.

    Walks `dat_pkx_anim_NN_sub_M_anim` (main animation slots) and
    `dat_pkx_sub_anim_N_anim_ref` (part-anim sub-animations) custom
    properties. Empty strings are skipped.

    Returns:
        set[str] of referenced action names, or None when the armature has
        no PKX metadata at all. An empty set (PKX metadata exists but every
        slot is unassigned, e.g. scene still being set up) is returned as
        None so describe_actions falls through to keeping all actions —
        dropping them silently would lose data during setup.
    """
    if armature.get("dat_pkx_format") is None:
        return None

    refs = set()
    anim_count = armature.get("dat_pkx_anim_count", 17)
    for i in range(anim_count):
        prefix = "dat_pkx_anim_%02d" % i
        for s in range(3):
            name = armature.get(prefix + "_sub_%d_anim" % s, "")
            if isinstance(name, str) and name:
                refs.add(name)
    for i in range(4):
        name = armature.get("dat_pkx_sub_anim_%d_anim_ref" % i, "")
        if isinstance(name, str) and name:
            refs.add(name)

    if not refs:
        return None
    return refs


def extract_shiny_params(armatures, logger=StubLogger()):
    """Extract shiny parameters from armature registered properties."""
    for arm in armatures:
        try:
            route = [
                int(arm.dat_pkx_shiny_route_r),
                int(arm.dat_pkx_shiny_route_g),
                int(arm.dat_pkx_shiny_route_b),
                int(arm.dat_pkx_shiny_route_a),
            ]
            brightness = [
                arm.dat_pkx_shiny_brightness_r,
                arm.dat_pkx_shiny_brightness_g,
                arm.dat_pkx_shiny_brightness_b,
            ]
        except AttributeError:
            continue

        if route == [0, 1, 2, 3] and all(abs(b) < 0.01 for b in brightness):
            continue

        logger.info("  Found PKX shiny params on %s", arm.name)
        return ShinyParams(
            route_r=route[0], route_g=route[1],
            route_b=route[2], route_a=route[3],
            brightness_r=brightness[0],
            brightness_g=brightness[1],
            brightness_b=brightness[2],
            brightness_a=0.0,
        )
    return None


def extract_pkx_header(armatures, action_name_to_index, logger=StubLogger()):
    """Extract PKX header metadata from armature custom properties."""
    for arm in armatures:
        fmt = arm.get("dat_pkx_format")
        if fmt not in ("XD", "COLOSSEUM"):
            continue

        is_xd = (fmt == "XD")
        h = PKXHeader(is_xd=is_xd)
        h.species_id = arm.get("dat_pkx_species_id", 0)
        h.particle_orientation = arm.get("dat_pkx_particle_orientation", 0)
        flags = 0
        if arm.get("dat_pkx_flag_flying", False):
            flags |= 0x01
        if arm.get("dat_pkx_flag_skip_frac_frames", False):
            flags |= 0x04
        if arm.get("dat_pkx_flag_no_root_anim", False):
            flags |= 0x40
        if arm.get("dat_pkx_flag_bit7", False):
            flags |= 0x80
        h.flags = flags
        h.distortion_param = arm.get("dat_pkx_distortion_param", 0)
        h.distortion_type = arm.get("dat_pkx_distortion_type", 0)
        h.type_id = 0x000C

        bone_list = list(arm.data.bones)
        bone_name_to_idx = {b.name: i for i, b in enumerate(bone_list)}
        head_name = arm.get("dat_pkx_head_bone", "")
        h.head_bone_index = bone_name_to_idx.get(head_name, 0)

        try:
            h.shiny_route = (
                int(arm.dat_pkx_shiny_route_r),
                int(arm.dat_pkx_shiny_route_g),
                int(arm.dat_pkx_shiny_route_b),
                int(arm.dat_pkx_shiny_route_a),
            )
            h.shiny_brightness = (
                _from_brightness(arm.dat_pkx_shiny_brightness_r),
                _from_brightness(arm.dat_pkx_shiny_brightness_g),
                _from_brightness(arm.dat_pkx_shiny_brightness_b),
                0xFF,
            )
        except AttributeError:
            pass

        _SUB_TYPE_MAP = {"none": 0, "simple": 1, "targeted": 2}
        if is_xd:
            h.part_anim_data = []
            for i in range(4):
                prefix = "dat_pkx_sub_anim_%d" % i
                has_data = _SUB_TYPE_MAP.get(arm.get(prefix + "_type", "none"), 0)
                bone_config = b'\xff' * 16
                if has_data == 2:
                    bones_str = arm.get(prefix + "_bones", "")
                    if bones_str:
                        bone_names_list = [n.strip() for n in bones_str.split(',') if n.strip()]
                        config = bytearray(16)
                        for bi, bn in enumerate(bone_names_list[:8]):
                            idx = bone_name_to_idx.get(bn, 0xFF)
                            config[bi] = idx if idx < 256 else 0xFF
                        for bi in range(len(bone_names_list), 16):
                            config[bi] = 0xFF
                        bone_config = bytes(config)
                pad = PartAnimData(
                    has_data=has_data,
                    sub_param=len([n for n in bone_config[:8] if n != 0xFF]) if has_data == 2 else 0,
                    bone_config=bone_config,
                    anim_index_ref=action_name_to_index.get(arm.get(prefix + "_anim_ref", ""), 0) if arm.get(prefix + "_anim_ref", "") else 0,
                )
                h.part_anim_data.append(pad)
        else:
            h.colo_part_anim_refs = [
                arm.get("dat_pkx_colo_part_ref_0", -1),
                arm.get("dat_pkx_colo_part_ref_1", -1),
                arm.get("dat_pkx_colo_part_ref_2", -1),
            ]
            h.colo_unknown_10 = 5
            h.colo_unknown_14 = arm.get("dat_pkx_particle_orientation", -1)

        model_body_map = []
        for j in range(len(_PKX_BODY_MAP_KEYS)):
            name = arm.get("dat_pkx_body_%s" % _PKX_BODY_MAP_KEYS[j], "")
            model_body_map.append(bone_name_to_idx.get(name, -1) if name else -1)

        anim_count = arm.get("dat_pkx_anim_count", 17)
        h.anim_section_count = anim_count
        h.anim_entries = []
        for i in range(anim_count):
            prefix = "dat_pkx_anim_%02d" % i
            anim_type_str = arm.get(prefix + "_type", "action")
            _ANIM_TYPE_TO_INT = {"loop": 2, "hit_reaction": 3, "action": 4, "compound": 5}
            anim_type = _ANIM_TYPE_TO_INT.get(anim_type_str, int(anim_type_str) if anim_type_str.isdigit() else 4)
            sub_count = arm.get(prefix + "_sub_count", 1)

            subs = []
            for s in range(min(sub_count, 3)):
                anim_name = arm.get(prefix + "_sub_%d_anim" % s, "")
                if isinstance(anim_name, str) and anim_name:
                    anim_idx = action_name_to_index.get(anim_name, 0)
                elif isinstance(anim_name, int):
                    anim_idx = anim_name
                else:
                    anim_idx = 0
                has_anim = isinstance(anim_name, str) and anim_name != ""
                if is_xd and has_anim:
                    derived_motion = 2 if anim_type_str == "loop" else 1
                else:
                    derived_motion = 0
                subs.append(SubAnim(
                    motion_type=derived_motion,
                    anim_index=anim_idx,
                ))
            if not subs:
                subs = [SubAnim(0, 0)]

            entry_bones = list(model_body_map)
            for j in range(len(_PKX_BODY_MAP_KEYS)):
                override_name = arm.get(prefix + "_body_%s" % _PKX_BODY_MAP_KEYS[j])
                if override_name is not None:
                    entry_bones[j] = bone_name_to_idx.get(override_name, -1) if override_name else -1

            entry = AnimMetadataEntry(
                anim_type=anim_type,
                sub_anim_count=sub_count,
                damage_flags=arm.get(prefix + "_damage_flags", 0),
                timing=(
                    arm.get(prefix + "_timing_1", 0.0),
                    arm.get(prefix + "_timing_2", 0.0),
                    arm.get(prefix + "_timing_3", 0.0),
                    arm.get(prefix + "_timing_4", 0.0),
                ),
                body_map_bones=entry_bones,
                sub_anims=subs,
                terminator=arm.get(prefix + "_terminator", 3 if is_xd else 1),
            )
            h.anim_entries.append(entry)

        logger.info("  Extracted PKX header from %s: format=%s, species=%d, %d entries",
                    arm.name, fmt, h.species_id, len(h.anim_entries))
        return h
    return None


def maybe_dump_diagnostic(armature, bones, bone_animations, logger=StubLogger()):
    """Optional skinning-drift diagnostic dump (gated by env vars).

    Activate with DAT_DUMP_BONES (comma-separated needles) and DAT_DUMP_PATH
    (output file). Optionally DAT_DUMP_FRAME and DAT_DUMP_ACTION.
    """
    needles = os.environ.get('DAT_DUMP_BONES', '').strip()
    path = os.environ.get('DAT_DUMP_PATH', '').strip()
    if not needles or not path:
        return

    needle_list = [n.strip() for n in needles.split(',') if n.strip()]
    matched = set()
    for i, bone in enumerate(bones):
        if any(n in bone.name for n in needle_list):
            matched.add(i)
    if not matched:
        logger.info("  [diagnostic] no bones match DAT_DUMP_BONES=%s", needles)
        return

    to_dump = set(matched)
    for i in list(matched):
        p = bones[i].parent_index
        while p is not None:
            to_dump.add(p)
            p = bones[p].parent_index
    ordered = sorted(to_dump)

    try:
        frame = int(os.environ.get('DAT_DUMP_FRAME', '').strip() or
                    str(bpy.context.scene.frame_current))
    except ValueError:
        frame = bpy.context.scene.frame_current

    action_name = os.environ.get('DAT_DUMP_ACTION', '').strip()
    active_action = None
    ad = armature.animation_data
    if action_name:
        active_action = bpy.data.actions.get(action_name)
    elif ad and ad.action:
        active_action = ad.action

    pose_matrices = {}
    pose_srt = {}
    if active_action is not None and ad is not None:
        saved = ad.action
        saved_frame = bpy.context.scene.frame_current
        try:
            ad.action = active_action
            bpy.context.scene.frame_set(frame)
            for i in ordered:
                pb = armature.pose.bones.get(bones[i].name)
                if pb is None:
                    continue
                pose_matrices[i] = [list(row) for row in pb.matrix]
                loc = pb.location
                rot = pb.rotation_quaternion
                scl = pb.scale
                pose_srt[i] = (
                    (loc.x, loc.y, loc.z),
                    (rot.w, rot.x, rot.y, rot.z),
                    (scl.x, scl.y, scl.z),
                )
        finally:
            ad.action = saved
            bpy.context.scene.frame_set(saved_frame)

    bones_with_tracks = {}
    for anim_set in bone_animations:
        for track in anim_set.tracks:
            bones_with_tracks.setdefault(anim_set.name, set()).add(track.bone_index)

    lines = ["=== DAT skinning diagnostic dump ===",
             "armature: %s" % armature.name,
             "frame: %d  action: %s" % (frame, active_action.name if active_action else "<none>"),
             "needles: %s" % needles,
             "bones dumped (matched + ancestors): %d" % len(ordered), ""]

    def _mfmt(m):
        return "[" + ", ".join(
            "(" + ", ".join("%+.6f" % v for v in row) + ")"
            for row in m
        ) + "]"

    for i in ordered:
        b = bones[i]
        lines.append("--- bone[%d] '%s' ---" % (i, b.name))
        lines.append("  parent_index: %s" % b.parent_index)
        lines.append("  flags: 0x%x  hidden: %s  inherit_scale: %s" %
                     (b.flags, b.is_hidden, b.inherit_scale))
        lines.append("  rest position: (%+.6f, %+.6f, %+.6f)" % b.position)
        lines.append("  rest rotation: (%+.6f, %+.6f, %+.6f)" % b.rotation)
        lines.append("  rest scale:    (%+.6f, %+.6f, %+.6f)" % b.scale)
        lines.append("  accumulated_scale: (%+.6f, %+.6f, %+.6f)" % b.accumulated_scale)
        if b.world_matrix:
            lines.append("  world_matrix: %s" % _mfmt(b.world_matrix))
        if b.inverse_bind_matrix:
            lines.append("  inverse_bind: %s" % _mfmt(b.inverse_bind_matrix))
        else:
            lines.append("  inverse_bind: None")
        if i in pose_matrices:
            lines.append("  pose.matrix (armature-space @ f%d): %s" %
                         (frame, _mfmt(pose_matrices[i])))
            ploc, pquat, pscl = pose_srt[i]
            lines.append("  pose.location (bone-local): (%+.6f, %+.6f, %+.6f)" % ploc)
            lines.append("  pose.rotation_quaternion:   (%+.6f, %+.6f, %+.6f, %+.6f)" % pquat)
            lines.append("  pose.scale:                 (%+.6f, %+.6f, %+.6f)" % pscl)
        tracks_here = [an for an, bs in bones_with_tracks.items() if i in bs]
        if tracks_here:
            lines.append("  has anim tracks in: %s" % ", ".join(tracks_here))
        lines.append("")

    try:
        with open(path, 'a') as f:
            f.write("\n".join(lines) + "\n")
        logger.info("  [diagnostic] wrote dump for %d bones to %s", len(ordered), path)
    except OSError as e:
        logger.info("  [diagnostic] failed to write %s: %s", path, e)
