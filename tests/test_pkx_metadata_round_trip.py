"""Round-trip tests for PKX header metadata (XD + Colosseum).

Drives the *real* phase helpers as they are — no PKX-specific logic is
re-implemented here:

    PKXHeader
      --importer post_process._derive_pkx_custom_props-->  dat_pkx_* props
      --(written onto a lightweight fake armature + shiny attrs)-->
      --exporter describe.extract_pkx_header-->            PKXHeader'

`extract_pkx_header` reads the armature purely by duck-typing (`.get()`,
`.data.bones`, `.dat_pkx_shiny_*`), so a plain stand-in object closes the loop
without a live Blender scene. Fidelity is judged by `compare_pkx_headers`
(tools/pkx_metadata_compare.py), which encodes the documented policy.

Pure: runs under plain python3 (bpy is importable but unused).
"""
from types import SimpleNamespace

from importer.phases.post_process.post_process import _derive_pkx_custom_props
from exporter.phases.describe.helpers.scene import extract_pkx_header
from shared.helpers.pkx_header import (
    PKXHeader, AnimMetadataEntry, SubAnim, PartAnimData, BODY_MAP_KEYS,
)
from shared.helpers.pkx import _to_brightness
from pkx_metadata_compare import compare_pkx_headers, violations, format_diffs


# --------------------------------------------------------------------------
# Fake armature — duck-typed stand-in for the bits extract_pkx_header reads.
# --------------------------------------------------------------------------

class _FakeArmature:
    def __init__(self, props, bone_names, shiny=None, name="Armature"):
        self._props = dict(props)
        self.data = SimpleNamespace(bones=[SimpleNamespace(name=n) for n in bone_names])
        self.name = name
        if shiny is not None:
            route, brightness = shiny  # route: 4 ints; brightness: 3 floats
            self.dat_pkx_shiny_route_r = str(route[0])
            self.dat_pkx_shiny_route_g = str(route[1])
            self.dat_pkx_shiny_route_b = str(route[2])
            self.dat_pkx_shiny_route_a = str(route[3])
            self.dat_pkx_shiny_brightness_r = brightness[0]
            self.dat_pkx_shiny_brightness_g = brightness[1]
            self.dat_pkx_shiny_brightness_b = brightness[2]

    def get(self, key, default=None):
        return self._props.get(key, default)


_BONES = ["Bone_%02d" % i for i in range(20)]
_ACTIONS = [SimpleNamespace(name="Anim_%02d" % i) for i in range(12)]
_ACTION_INDEX = {a.name: i for i, a in enumerate(_ACTIONS)}


def _roundtrip(header, model_type, bone_names=_BONES, actions=_ACTIONS, shiny=True):
    """Header -> dat_pkx_* props -> fake armature -> reconstructed header."""
    props = _derive_pkx_custom_props(
        header, actions=actions, bone_names=bone_names, model_type=model_type)
    shiny_in = None
    if shiny:
        shiny_in = (list(header.shiny_route),
                    [_to_brightness(b) for b in header.shiny_brightness[:3]])
    arm = _FakeArmature(props, bone_names, shiny=shiny_in)
    return extract_pkx_header([arm], _ACTION_INDEX)


def _body_map(**slots):
    """Build a 16-entry body_map_bones list from {key: bone_index} overrides."""
    bones = [-1] * len(BODY_MAP_KEYS)
    for key, idx in slots.items():
        bones[BODY_MAP_KEYS.index(key)] = idx
    return bones


# --------------------------------------------------------------------------
# Fixtures: representative XD and Colosseum headers.
# --------------------------------------------------------------------------

def _xd_header():
    h = PKXHeader(is_xd=True)
    h.species_id = 376
    h.particle_orientation = 1
    h.flags = 0x01 | 0x40            # flying + no_root_anim
    h.distortion_param = 2
    h.distortion_type = 1
    h.head_bone_index = 3
    h.type_id = 0x000C
    h.shiny_route = (2, 1, 0, 3)
    h.shiny_brightness = (200, 60, 127, 127)
    h.anim_section_count = 11

    base_body = _body_map(origin=1, mouth=3, chest=5)
    h.part_anim_data = [
        PartAnimData(has_data=1, sub_param=0, bone_config=b"\xff" * 16, anim_index_ref=6),
        _targeted_part_anim([2, 5], anim_ref=7),
        PartAnimData(has_data=1, sub_param=0, bone_config=b"\xff" * 16, anim_index_ref=5),
        PartAnimData(has_data=0, sub_param=0, bone_config=b"\xff" * 16, anim_index_ref=0),
    ]

    def entry(anim_type, subs, count=None, body=None):
        return AnimMetadataEntry(
            anim_type=anim_type, sub_anim_count=count or len(subs),
            timing=(0.5, 1.0, 1.5, 2.0),
            body_map_bones=list(body if body is not None else base_body),
            sub_anims=subs, terminator=3,
        )

    h.anim_entries = [
        entry(2, [SubAnim(2, 0)]),                       # 0 idle (loop)
        entry(4, [SubAnim(1, 1)]),                       # 1 attack
        entry(4, [SubAnim(1, 2)]),                       # 2 attack
        entry(4, [SubAnim(1, 1)]),                       # 3 attack
        entry(3, [SubAnim(1, 4)], body=_body_map(origin=1, mouth=3, chest=5, tail=7)),  # 4 damage + body override
        entry(5, [SubAnim(1, 4), SubAnim(1, 3)]),        # 5 compound
        entry(3, [SubAnim(1, 3)]),                       # 6 faint
        entry(4, [SubAnim(0, 0)]),                       # 7 padding
        entry(4, [SubAnim(0, 0)]),                       # 8 padding
        entry(2, [SubAnim(0, 0)]),                       # 9 padding
        entry(4, [SubAnim(2, 6)]),                       # 10 take-flight (loop, active)
    ]
    return h


def _colo_header():
    h = PKXHeader(is_xd=False)
    h.species_id = 0
    h.particle_orientation = 1
    h.head_bone_index = 3
    h.type_id = 0x000C
    h.colo_unknown_10 = 5
    h.colo_unknown_14 = -1
    h.colo_part_anim_refs = [6, 7, 5]
    h.shiny_route = (2, 1, 0, 3)
    h.shiny_brightness = (200, 60, 127, 127)
    h.anim_section_count = 11

    base_body = _body_map(origin=1, mouth=3, chest=5)

    def entry(anim_type, subs, count=None, body=None):
        return AnimMetadataEntry(
            anim_type=anim_type, sub_anim_count=count or len(subs),
            timing=(0.25, 0.5, 0.75, 1.0),
            body_map_bones=list(body if body is not None else base_body),
            sub_anims=subs, terminator=1,
        )

    # Colosseum: real slots carry motion_type 0; padding carries 1.
    h.anim_entries = [
        entry(2, [SubAnim(0, 1)]),                       # 0 idle
        entry(4, [SubAnim(0, 2)]),                       # 1 attack
        entry(4, [SubAnim(0, 3)]),                       # 2 attack
        entry(4, [SubAnim(0, 4)]),                       # 3 attack
        entry(3, [SubAnim(0, 5)], body=_body_map(origin=1, mouth=3, chest=5, tail=7)),  # 4 damage + override
        entry(5, [SubAnim(0, 5), SubAnim(0, 7)]),        # 5 compound
        entry(3, [SubAnim(0, 6)]),                       # 6 faint
        entry(4, [SubAnim(1, 0)]),                       # 7 padding
        entry(4, [SubAnim(1, 0)]),                       # 8 padding
        entry(2, [SubAnim(1, 0)]),                       # 9 padding
        entry(4, [SubAnim(1, 0)]),                       # 10 padding
    ]
    return h


def _targeted_part_anim(bone_indices, anim_ref):
    config = bytearray(b"\xff" * 16)
    for i, idx in enumerate(bone_indices):
        config[i] = idx
    return PartAnimData(has_data=2, sub_param=len(bone_indices),
                        bone_config=bytes(config), anim_index_ref=anim_ref)


# --------------------------------------------------------------------------
# Full round-trip: no policy violations.
# --------------------------------------------------------------------------

def test_xd_full_roundtrip_no_violations():
    h = _xd_header()
    rebuilt = _roundtrip(h, model_type="POKEMON")
    bad = violations(compare_pkx_headers(h, rebuilt))
    assert not bad, "XD round-trip violations:\n" + format_diffs(bad)


def test_colosseum_full_roundtrip_no_violations():
    h = _colo_header()
    rebuilt = _roundtrip(h, model_type="POKEMON")
    bad = violations(compare_pkx_headers(h, rebuilt))
    assert not bad, "Colosseum round-trip violations:\n" + format_diffs(bad)


# --------------------------------------------------------------------------
# Targeted: motion_type polarity (the field most at risk).
# --------------------------------------------------------------------------

def test_xd_motion_type_roundtrips_via_anim_type():
    h = _xd_header()
    rebuilt = _roundtrip(h, model_type="POKEMON")
    assert rebuilt.anim_entries[0].sub_anims[0].motion_type == 2   # idle = loop
    assert rebuilt.anim_entries[1].sub_anims[0].motion_type == 1   # attack
    assert rebuilt.anim_entries[7].sub_anims[0].motion_type == 0   # padding


def test_colo_motion_type_uses_inverted_polarity():
    """Colosseum real slots must come back as motion_type 0, padding as 1."""
    h = _colo_header()
    rebuilt = _roundtrip(h, model_type="POKEMON")
    assert rebuilt.anim_entries[0].sub_anims[0].motion_type == 0   # idle (real)
    assert rebuilt.anim_entries[1].sub_anims[0].motion_type == 0   # attack (real)
    assert rebuilt.anim_entries[5].sub_anims[1].motion_type == 0   # compound 2nd sub
    assert rebuilt.anim_entries[7].sub_anims[0].motion_type == 1   # padding


# --------------------------------------------------------------------------
# Body-map: an index past the model's bones is a dead null-joint reference the
# game resolves to NULL (identical to -1), so it must score as expected.
# --------------------------------------------------------------------------

def test_body_map_out_of_range_index_scores_expected_with_bone_count():
    h = _xd_header()
    # additional_5 (slot 15) points past the 20-bone armature.
    h.anim_entries[0].body_map_bones = _body_map(origin=1, mouth=3, additional_5=99)
    rebuilt = _roundtrip(h, model_type="POKEMON")

    # No bone to name -> the slot collapses to -1 on the way out.
    assert rebuilt.anim_entries[0].body_map_bones[15] == -1

    path = "anim[00].body[15]"
    # Without the bone count, the comparator can't tell it was out of range,
    # so it reads as a violation...
    assert any(d.path == path for d in violations(compare_pkx_headers(h, rebuilt)))
    # ...but given the bone count it's classified as an expected divergence.
    assert not any(d.path == path for d in
                   violations(compare_pkx_headers(h, rebuilt, bone_count=len(_BONES))))


# --------------------------------------------------------------------------
# Targeted: shiny, body-map overrides, part-anim bones, damage clamp.
# --------------------------------------------------------------------------

def test_shiny_route_and_brightness_roundtrip():
    h = _xd_header()
    rebuilt = _roundtrip(h, model_type="POKEMON")
    assert rebuilt.shiny_route == (2, 1, 0, 3)
    assert rebuilt.shiny_brightness[0] == 200
    assert rebuilt.shiny_brightness[1] == 60
    assert rebuilt.shiny_brightness[2] == 127


def test_shiny_alpha_forced_max_is_expected_not_violation():
    h = _xd_header()
    rebuilt = _roundtrip(h, model_type="POKEMON")
    diffs = compare_pkx_headers(h, rebuilt)
    alpha = [d for d in diffs if d.path == "shiny_brightness.a"]
    assert alpha and alpha[0].kind == "expected"
    assert rebuilt.shiny_brightness[3] == 0xFF


def test_body_map_override_roundtrips():
    h = _xd_header()
    rebuilt = _roundtrip(h, model_type="POKEMON")
    tail = BODY_MAP_KEYS.index("tail")
    assert rebuilt.anim_entries[4].body_map_bones[tail] == 7
    assert rebuilt.anim_entries[0].body_map_bones[tail] == -1


def test_targeted_part_anim_bones_roundtrip():
    h = _xd_header()
    rebuilt = _roundtrip(h, model_type="POKEMON")
    assert rebuilt.part_anim_data[1].has_data == 2
    assert rebuilt.part_anim_data[1].active_bone_indices() == [2, 5]
    assert rebuilt.part_anim_data[1].anim_index_ref == 7
    # selectors stay 0xFF → still classified as a joint target
    assert rebuilt.part_anim_data[1].is_joint_target()


def test_targeted_texture_selectors_roundtrip():
    """A per-part texture block preserves its bone list AND selector array."""
    h = _xd_header()
    config = bytearray(b"\xff" * 16)
    config[0], config[1] = 4, 7      # part indices (bytes 2-3 of block)
    config[8], config[9] = 5, 2      # selectors (bytes 10-11) — not 0xFF
    h.part_anim_data[1] = PartAnimData(
        has_data=2, sub_param=2, bone_config=bytes(config), anim_index_ref=6)

    rebuilt = _roundtrip(h, model_type="POKEMON")
    pad = rebuilt.part_anim_data[1]
    assert pad.has_data == 2
    assert pad.is_joint_target() is False
    assert pad.active_entries() == [(4, 5), (7, 2)]
    assert pad.anim_index_ref == 6


def test_damage_flags_clamp_is_expected_divergence():
    h = _xd_header()
    h.anim_entries[0].damage_flags = 0xCDCDCDCD  # debug heap fill
    rebuilt = _roundtrip(h, model_type="POKEMON")
    diffs = compare_pkx_headers(h, rebuilt)
    dmg = [d for d in diffs if d.path == "anim[00].damage_flags"]
    assert dmg and dmg[0].kind == "expected"
    assert rebuilt.anim_entries[0].damage_flags == 0
