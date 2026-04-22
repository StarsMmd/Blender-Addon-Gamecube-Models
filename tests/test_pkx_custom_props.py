"""Tests for _derive_pkx_custom_props — pure semantic-derivation helper."""
from types import SimpleNamespace

from importer.phases.post_process.post_process import (
    _derive_pkx_custom_props,
    _build_action_name_resolver, _build_bone_name_resolver,
    _derive_preamble_props, _derive_sub_anim_props,
    _derive_body_map_props, _derive_anim_entry_props,
)
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


# --- Tests for the responsibility-bounded helpers ---

class TestNodeProperties:
    """Pure derived properties on PKX dataclasses (single-instance state only)."""

    def test_subanim_is_active(self):
        assert SubAnim(motion_type=0, anim_index=0).is_active is False
        assert SubAnim(motion_type=1, anim_index=0).is_active is True
        assert SubAnim(motion_type=2, anim_index=5).is_active is True

    def test_partanim_is_active_and_targeted(self):
        assert PartAnimData(has_data=0).is_active is False
        assert PartAnimData(has_data=1).is_active is True
        assert PartAnimData(has_data=2).is_active is True
        assert PartAnimData(has_data=2).is_targeted is True
        assert PartAnimData(has_data=1).is_targeted is False

    def test_partanim_active_bone_indices_drops_ff(self):
        pad = PartAnimData(has_data=2, bone_config=bytes([3, 0xFF, 7, 0xFF, 0xFF, 12]))
        assert pad.active_bone_indices() == [3, 7, 12]

    def test_pkxheader_is_trainer(self):
        h = _xd_pokemon_header()
        assert h.is_trainer is False
        h.species_id = 0
        h.particle_orientation = 0
        assert h.is_trainer is True
        h.particle_orientation = 1
        assert h.is_trainer is False

    def test_pkxheader_format_and_model_type_labels(self):
        assert _xd_pokemon_header().format_label == "XD"
        assert _colo_header().format_label == "COLOSSEUM"
        assert _xd_trainer_header().model_type_label == "TRAINER"
        assert _xd_pokemon_header().model_type_label == "POKEMON"

    def test_pkxheader_flag_properties(self):
        h = _xd_pokemon_header()
        h.flags = 0x01 | 0x40
        assert h.flag_flying is True
        assert h.flag_skip_frac_frames is False
        assert h.flag_no_root_anim is True
        assert h.flag_bit7 is False


class TestNameResolvers:
    def test_action_name_resolver_returns_empty_when_index_missing(self):
        r = _build_action_name_resolver([_action("A"), _action("B")])
        assert r(0) == "A"
        assert r(1) == "B"
        assert r(99) == ""

    def test_action_name_resolver_handles_none(self):
        r = _build_action_name_resolver(None)
        assert r(0) == ""

    def test_bone_name_resolver_returns_empty_for_negative_or_oob(self):
        r = _build_bone_name_resolver(["a", "b"])
        assert r(0) == "a"
        assert r(-1) == ""
        assert r(2) == ""


class TestDerivePreambleProps:
    def test_preamble_keys_present(self):
        h = _xd_pokemon_header()
        h.head_bone_index = 1
        props = _derive_preamble_props(h, _build_bone_name_resolver(["root", "head"]))
        assert props["dat_pkx_format"] == "XD"
        assert props["dat_pkx_model_type"] == "POKEMON"
        assert props["dat_pkx_head_bone"] == "head"
        assert "dat_pkx_flag_flying" in props


class TestDeriveSubAnimProps:
    def test_xd_active_pad_resolves_action_name(self):
        h = _xd_pokemon_header()
        h.part_anim_data[0] = PartAnimData(has_data=1, anim_index_ref=2)
        props = _derive_sub_anim_props(
            h, _build_action_name_resolver([_action("A"), _action("B"), _action("C")]),
            _build_bone_name_resolver([]),
        )
        assert props["dat_pkx_sub_anim_0_anim_ref"] == "C"
        assert props["dat_pkx_sub_anim_0_type"] == "simple"

    def test_xd_inactive_pad_yields_empty_ref(self):
        h = _xd_pokemon_header()
        h.part_anim_data[0] = PartAnimData(has_data=0, anim_index_ref=99)
        props = _derive_sub_anim_props(
            h, _build_action_name_resolver([_action("A")] * 100),
            _build_bone_name_resolver([]),
        )
        assert props["dat_pkx_sub_anim_0_anim_ref"] == ""

    def test_xd_targeted_pad_lists_bone_names(self):
        h = _xd_pokemon_header()
        h.part_anim_data[0] = PartAnimData(
            has_data=2, anim_index_ref=0,
            bone_config=bytes([1, 2, 0xFF] + [0xFF] * 13),
        )
        props = _derive_sub_anim_props(
            h, _build_action_name_resolver([_action("A")]),
            _build_bone_name_resolver(["root", "head", "tail"]),
        )
        assert props["dat_pkx_sub_anim_0_bones"] == "head, tail"

    def test_colo_branch_uses_part_anim_refs(self):
        h = _colo_header()
        h.colo_part_anim_refs = [-1, 5, -1]
        props = _derive_sub_anim_props(
            h, _build_action_name_resolver([_action("A%d" % i) for i in range(10)]),
            _build_bone_name_resolver([]),
        )
        assert props["dat_pkx_sub_anim_1_type"] == "simple"
        assert props["dat_pkx_sub_anim_1_anim_ref"] == "A5"
        assert props["dat_pkx_sub_anim_0_type"] == "none"


class TestDeriveBodyMapProps:
    def test_resolves_each_slot(self):
        entry = AnimMetadataEntry.default_idle(is_xd=True)
        entry.body_map_bones = [0, 1, -1] + [-1] * 13
        props = _derive_body_map_props(entry, _build_bone_name_resolver(["root", "head"]))
        assert props["dat_pkx_body_root"] == "root"
        assert props["dat_pkx_body_head"] == "head"
        assert props["dat_pkx_body_center"] == ""


class TestDeriveAnimEntryProps:
    def test_basic_fields(self):
        entry = AnimMetadataEntry.default_idle(is_xd=True)
        entry.timing = (0.5, 1.0, 1.5, 2.0)
        entry.sub_anims = [SubAnim(motion_type=2, anim_index=0)]
        props = _derive_anim_entry_props(
            3, entry, first_active=entry,
            name_resolver=_build_action_name_resolver([_action("Idle")]),
            bone_resolver=_build_bone_name_resolver([]),
        )
        assert props["dat_pkx_anim_03_type"] == "loop"
        assert props["dat_pkx_anim_03_timing_1"] == 0.5
        assert props["dat_pkx_anim_03_sub_0_anim"] == "Idle"

    def test_inactive_sub_anim_is_empty(self):
        entry = AnimMetadataEntry.default_idle(is_xd=True)
        entry.sub_anims = [SubAnim(motion_type=0, anim_index=3)]
        props = _derive_anim_entry_props(
            0, entry, first_active=entry,
            name_resolver=_build_action_name_resolver([_action("X")] * 10),
            bone_resolver=_build_bone_name_resolver([]),
        )
        assert props["dat_pkx_anim_00_sub_0_anim"] == ""

    def test_per_entry_body_override_emitted_only_when_different(self):
        first = AnimMetadataEntry.default_idle(is_xd=True)
        first.body_map_bones = [0] + [-1] * 15
        entry = AnimMetadataEntry.default_idle(is_xd=True)
        entry.body_map_bones = [2] + [-1] * 15  # differs at slot 0
        props = _derive_anim_entry_props(
            1, entry, first_active=first,
            name_resolver=_build_action_name_resolver([]),
            bone_resolver=_build_bone_name_resolver(["a", "b", "c"]),
        )
        assert props["dat_pkx_anim_01_body_root"] == "c"
        # Slot 1 (head) is the same (-1) on both → no override key
        assert "dat_pkx_anim_01_body_head" not in props
