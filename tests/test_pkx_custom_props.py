"""Tests for _derive_pkx_custom_props — pure semantic-derivation helper."""
from types import SimpleNamespace

from importer.phases.post_process.post_process import _derive_pkx_custom_props
from shared.helpers.pkx_header import (
    PKXHeader, AnimMetadataEntry, SubAnim, PartAnimData,
)


def _action(name):
    return SimpleNamespace(name=name)


def _xd_pokemon_header():
    """Minimal XD Pokémon header — species_id != 0."""
    h = PKXHeader(is_xd=True)
    h.species_id = 25  # any non-zero
    h.particle_orientation = 0
    h.flags = 0
    h.head_bone_index = 1
    h.distortion_param = 0
    h.distortion_type = 0
    h.part_anim_data = [PartAnimData() for _ in range(4)]
    h.anim_entries = [AnimMetadataEntry.default_idle(is_xd=True)]
    return h


def _xd_trainer_header():
    """XD Trainer header — species_id == 0 and particle_orientation == 0."""
    h = _xd_pokemon_header()
    h.species_id = 0
    h.particle_orientation = 0
    return h


def _colo_header():
    h = PKXHeader(is_xd=False)
    h.species_id = 25
    h.particle_orientation = 0
    h.flags = 0
    h.head_bone_index = 0
    h.colo_part_anim_refs = [-1, 5, -1]
    h.anim_entries = [AnimMetadataEntry.default_idle(is_xd=False)]
    return h


def test_xd_pokemon_format_and_model_type():
    props = _derive_pkx_custom_props(_xd_pokemon_header())
    assert props["dat_pkx_format"] == "XD"
    assert props["dat_pkx_model_type"] == "POKEMON"
    assert props["dat_pkx_species_id"] == 25


def test_xd_trainer_model_type():
    props = _derive_pkx_custom_props(_xd_trainer_header())
    assert props["dat_pkx_format"] == "XD"
    assert props["dat_pkx_model_type"] == "TRAINER"


def test_colosseum_format():
    props = _derive_pkx_custom_props(_colo_header())
    assert props["dat_pkx_format"] == "COLOSSEUM"


def test_no_actions_yields_empty_anim_refs():
    """Sub-anim refs should be "" when no action list is supplied."""
    h = _xd_pokemon_header()
    h.part_anim_data[0] = PartAnimData(has_data=1, anim_index_ref=2)
    props = _derive_pkx_custom_props(h, actions=None)
    assert props["dat_pkx_sub_anim_0_anim_ref"] == ""


def test_actions_resolve_anim_refs_by_index():
    h = _xd_pokemon_header()
    h.part_anim_data[0] = PartAnimData(has_data=1, anim_index_ref=2)
    actions = [_action("A"), _action("B"), _action("C"), _action("D")]
    props = _derive_pkx_custom_props(h, actions=actions)
    assert props["dat_pkx_sub_anim_0_anim_ref"] == "C"


def test_bone_names_resolve_head_bone():
    h = _xd_pokemon_header()
    h.head_bone_index = 2
    props = _derive_pkx_custom_props(h, bone_names=["root", "neck", "head"])
    assert props["dat_pkx_head_bone"] == "head"


def test_out_of_range_bone_index_yields_empty_string():
    h = _xd_pokemon_header()
    h.head_bone_index = 99
    props = _derive_pkx_custom_props(h, bone_names=["root"])
    assert props["dat_pkx_head_bone"] == ""


def test_flags_decompose_to_individual_booleans():
    h = _xd_pokemon_header()
    h.flags = 0x01 | 0x40
    props = _derive_pkx_custom_props(h)
    assert props["dat_pkx_flag_flying"] is True
    assert props["dat_pkx_flag_skip_frac_frames"] is False
    assert props["dat_pkx_flag_no_root_anim"] is True
    assert props["dat_pkx_flag_bit7"] is False


def test_no_pkx_anim_entries_yields_zero_count():
    h = _xd_pokemon_header()
    h.anim_entries = []
    props = _derive_pkx_custom_props(h)
    assert props["dat_pkx_anim_count"] == 0
    # No body_pkx_body_* keys when there's no first_active entry
    assert not any(k.startswith("dat_pkx_body_") for k in props)


def test_anim_entry_fields_written():
    h = _xd_pokemon_header()
    entry = AnimMetadataEntry.default_idle(is_xd=True)
    entry.timing = (0.5, 1.0, 1.5, 2.0)
    entry.sub_anims = [SubAnim(motion_type=2, anim_index=0)]
    h.anim_entries = [entry]
    props = _derive_pkx_custom_props(h, actions=[_action("Idle")])
    assert props["dat_pkx_anim_count"] == 1
    assert props["dat_pkx_anim_00_type"] == "loop"
    assert props["dat_pkx_anim_00_timing_1"] == 0.5
    assert props["dat_pkx_anim_00_timing_4"] == 2.0
    assert props["dat_pkx_anim_00_sub_0_anim"] == "Idle"


def test_inactive_sub_anim_yields_empty_ref():
    """sub.motion_type == 0 → no action lookup, empty string."""
    h = _xd_pokemon_header()
    entry = AnimMetadataEntry.default_idle(is_xd=True)
    entry.sub_anims = [SubAnim(motion_type=0, anim_index=3)]
    h.anim_entries = [entry]
    props = _derive_pkx_custom_props(h, actions=[_action("A")] * 10)
    assert props["dat_pkx_anim_00_sub_0_anim"] == ""


def test_colo_sub_anim_refs_resolved():
    h = _colo_header()
    actions = [_action("A%d" % i) for i in range(10)]
    props = _derive_pkx_custom_props(h, actions=actions)
    assert props["dat_pkx_sub_anim_1_type"] == "simple"
    assert props["dat_pkx_sub_anim_1_anim_ref"] == "A5"
    assert props["dat_pkx_sub_anim_0_type"] == "none"
    assert props["dat_pkx_sub_anim_0_anim_ref"] == ""


def test_body_map_resolves_bone_names():
    h = _xd_pokemon_header()
    entry = AnimMetadataEntry.default_idle(is_xd=True)
    entry.body_map_bones = [0, 1, -1] + [-1] * 13
    h.anim_entries = [entry]
    props = _derive_pkx_custom_props(h, bone_names=["root", "head", "tail"])
    assert props["dat_pkx_body_root"] == "root"
    assert props["dat_pkx_body_head"] == "head"
    assert props["dat_pkx_body_center"] == ""
