"""Field-by-field comparison of two PKXHeaders under the metadata round-trip
fidelity policy.

Pure / bpy-free so it can be shared by the pytest round-trip
(`tests/test_pkx_metadata_round_trip.py`, plain python3) and the corpus
diagnostic (`tests/round_trip/run_round_trips.py`, python3.11).

`compare_pkx_headers(orig, rebuilt)` returns a flat list of `Diff` records.
Each diff is classified as one of:

  - "violation": a field that the round trip is expected to preserve but did
    not. The pytest asserts there are zero of these.
  - "expected":  a documented, intentional divergence (a re-derived field, a
    clamp, a value the exporter hard-codes, or shiny alpha forced to max).
    Informational only — surfaced so the corpus diagnostic can quantify it.

The policy is documented in technical-docs/implementation_notes.md
(§ PKX metadata round-trip).
"""
from collections import namedtuple

Diff = namedtuple("Diff", "path expected got kind")

_ANIM_TYPE_LOOP = 2  # AnimMetadataEntry.anim_type for a looping slot


def _clamp_int32(value):
    """Mirror post_process._clamp_int32: uint32 above 0x7FFFFFFF -> 0."""
    if isinstance(value, int) and value > 0x7FFFFFFF:
        return 0
    return value


def _expected_motion_type(is_xd, anim_type, orig_motion):
    """The motion_type the export side reconstructs for a sub-anim.

    The two games use opposite polarity (see sub_anim_is_active): XD marks a
    real slot with motion_type > 0 and derives 2 for a looping slot, 1
    otherwise; Colosseum marks a real slot with motion_type 0 and unused
    padding with 1. The round trip routes through the action name (present
    iff the slot is active), so motion_type is re-derived, never carried.
    """
    if is_xd:
        active = orig_motion > 0
        if not active:
            return 0
        return 2 if anim_type == _ANIM_TYPE_LOOP else 1
    # Colosseum
    active = orig_motion == 0
    return 0 if active else 1


def _cmp(diffs, path, expected, got, kind="violation", tol=0):
    if isinstance(expected, float) or isinstance(got, float):
        if abs((expected or 0) - (got or 0)) <= tol:
            return
    elif expected == got or (tol and abs(expected - got) <= tol):
        return
    diffs.append(Diff(path, expected, got, kind))


def _compare_shiny(diffs, orig, rebuilt):
    # Route is carried verbatim (enum-string round trip).
    for i, ch in enumerate("rgba"):
        _cmp(diffs, "shiny_route.%s" % ch, orig.shiny_route[i], rebuilt.shiny_route[i])
    # Brightness R/G/B survive byte -> float -> byte within a quantisation step.
    for i, ch in enumerate("rgb"):
        _cmp(diffs, "shiny_brightness.%s" % ch,
             orig.shiny_brightness[i], rebuilt.shiny_brightness[i], tol=1)
    # Alpha brightness is forced to max by the game/exporter.
    _cmp(diffs, "shiny_brightness.a",
         orig.shiny_brightness[3], rebuilt.shiny_brightness[3], kind="expected")


def _ref(actions, idx):
    """Resolve a DAT animation index to an identity for comparison.

    When `actions` (a DAT-ordered name list) is given, return the referenced
    name so refs compare by animation identity across two action orderings;
    otherwise fall back to the raw index.
    """
    if actions is None:
        return idx
    if 0 <= idx < len(actions):
        return actions[idx]
    return "<idx %d>" % idx


def _compare_part_anims(diffs, orig, rebuilt, orig_actions, rebuilt_actions):
    if orig.is_xd:
        for i in range(min(len(orig.part_anim_data), len(rebuilt.part_anim_data))):
            o, r = orig.part_anim_data[i], rebuilt.part_anim_data[i]
            _cmp(diffs, "part_anim[%d].has_data" % i, o.has_data, r.has_data)
            # anim_index_ref only meaningful for active blocks; compare by identity.
            if o.has_data > 0:
                _cmp(diffs, "part_anim[%d].anim_index_ref" % i,
                     _ref(orig_actions, o.anim_index_ref),
                     _ref(rebuilt_actions, r.anim_index_ref))
            if o.has_data == 2:
                _cmp(diffs, "part_anim[%d].bones" % i,
                     o.active_bone_indices(), r.active_bone_indices())
    else:
        for i in range(3):
            o = orig.colo_part_anim_refs[i]
            r = rebuilt.colo_part_anim_refs[i]
            if o >= 0:
                _cmp(diffs, "colo_part_anim_refs[%d]" % i,
                     _ref(orig_actions, o), _ref(rebuilt_actions, r))
            else:
                _cmp(diffs, "colo_part_anim_refs[%d]" % i, -1, r)


def _compare_entries(diffs, orig, rebuilt, orig_actions, rebuilt_actions):
    n = min(len(orig.anim_entries), len(rebuilt.anim_entries))
    if len(orig.anim_entries) != len(rebuilt.anim_entries):
        _cmp(diffs, "len(anim_entries)",
             len(orig.anim_entries), len(rebuilt.anim_entries))
    for i in range(n):
        o, r = orig.anim_entries[i], rebuilt.anim_entries[i]
        p = "anim[%02d]" % i
        _cmp(diffs, p + ".anim_type", o.anim_type, r.anim_type)
        _cmp(diffs, p + ".sub_anim_count", o.sub_anim_count, r.sub_anim_count)
        _cmp(diffs, p + ".terminator", o.terminator, r.terminator)
        # damage_flags is clamped to signed int32 on import (debug heap fill).
        if r.damage_flags != o.damage_flags:
            kind = "expected" if r.damage_flags == _clamp_int32(o.damage_flags) else "violation"
            diffs.append(Diff(p + ".damage_flags", o.damage_flags, r.damage_flags, kind))
        for k in range(4):
            _cmp(diffs, p + ".timing_%d" % (k + 1), o.timing[k], r.timing[k], tol=1e-6)
        # body_map: bones survive by name; -1 / out-of-range collapse to -1.
        for j in range(min(len(o.body_map_bones), len(r.body_map_bones))):
            _cmp(diffs, p + ".body[%02d]" % j, o.body_map_bones[j], r.body_map_bones[j])
        # sub-anims: anim_index by identity (active slots only); motion_type
        # re-derived per policy (all slots, padding included).
        for s in range(min(len(o.sub_anims), len(r.sub_anims), r.sub_anim_count, 3)):
            os_, rs = o.sub_anims[s], r.sub_anims[s]
            active = (os_.motion_type > 0) if orig.is_xd else (os_.motion_type == 0)
            # A source ref whose index lands outside the action table is
            # uninitialised/garbage (heap fill); it can't round-trip and
            # collapses to idx 0 / inactive, so both the index and the
            # cascaded motion_type are documented divergences, not losses.
            garbage = (active and orig_actions is not None
                       and not (0 <= os_.anim_index < len(orig_actions)))
            kind = "expected" if garbage else "violation"
            if active:
                _cmp(diffs, "%s.sub[%d].anim_index" % (p, s),
                     _ref(orig_actions, os_.anim_index),
                     _ref(rebuilt_actions, rs.anim_index), kind=kind)
            exp_motion = _expected_motion_type(orig.is_xd, o.anim_type, os_.motion_type)
            _cmp(diffs, "%s.sub[%d].motion_type" % (p, s), exp_motion, rs.motion_type, kind=kind)


def compare_pkx_headers(orig, rebuilt, orig_actions=None, rebuilt_actions=None):
    """Compare two PKXHeaders under the round-trip fidelity policy.

    In: orig (PKXHeader, the source); rebuilt (PKXHeader, reconstructed by the
        export side from custom properties); orig_actions / rebuilt_actions
        (optional DAT-ordered action-name lists). When both lists are given,
        animation references compare by resolved name rather than raw index,
        so a benign re-ordering of the action list on export is not flagged.
    Out: list[Diff]. A Diff with kind="violation" is a real mismatch; kind=
        "expected" is a documented divergence.
    """
    diffs = []
    if rebuilt is None:
        return [Diff("<header>", "PKXHeader", None, "violation")]

    _cmp(diffs, "is_xd", orig.is_xd, rebuilt.is_xd)
    _cmp(diffs, "species_id", orig.species_id, rebuilt.species_id)
    _cmp(diffs, "particle_orientation", orig.particle_orientation, rebuilt.particle_orientation)
    _cmp(diffs, "flags", orig.flags, rebuilt.flags)
    _cmp(diffs, "distortion_param", orig.distortion_param, rebuilt.distortion_param)
    _cmp(diffs, "distortion_type", orig.distortion_type, rebuilt.distortion_type)
    _cmp(diffs, "head_bone_index", orig.head_bone_index, rebuilt.head_bone_index)
    # type_id is hard-coded to the PKX marker on export.
    _cmp(diffs, "type_id", orig.type_id, rebuilt.type_id,
         kind="expected" if orig.type_id != 0x000C else "violation")
    if not orig.is_xd:
        # The exporter writes fixed Colosseum preamble scratch values.
        _cmp(diffs, "colo_unknown_10", orig.colo_unknown_10, rebuilt.colo_unknown_10,
             kind="expected" if orig.colo_unknown_10 != 5 else "violation")
        _cmp(diffs, "colo_unknown_14", orig.colo_unknown_14, rebuilt.colo_unknown_14,
             kind="expected" if orig.colo_unknown_14 != -1 else "violation")

    _compare_shiny(diffs, orig, rebuilt)
    _compare_part_anims(diffs, orig, rebuilt, orig_actions, rebuilt_actions)
    _compare_entries(diffs, orig, rebuilt, orig_actions, rebuilt_actions)
    return diffs


def violations(diffs):
    """Filter a diff list down to policy violations (kind == 'violation')."""
    return [d for d in diffs if d.kind == "violation"]


def format_diffs(diffs):
    """Render a diff list as aligned human-readable lines."""
    return "\n".join(
        "  [%s] %s: expected %r, got %r" % (d.kind, d.path, d.expected, d.got)
        for d in diffs
    )
