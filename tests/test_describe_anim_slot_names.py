"""Tests for trainer/Pokémon animation-slot naming in the describe phase.

Covers the importer-toggle (`colo_xd_kind`) routing into the semantic
animation-name map, plus the shared slot-name / active-slot helpers in
shared.helpers.pkx_header. Pure — no bpy required.
"""
from importer.phases.describe.helpers.animations import _build_anim_name_map
from shared.helpers.pkx_header import (
    PKXHeader, AnimMetadataEntry, SubAnim, PartAnimData,
    anim_slot_names, sub_anim_is_active, active_part_anim_refs,
    XD_POKEMON_ANIM_NAMES, XD_TRAINER_ANIM_NAMES, COLO_TRAINER_ANIM_NAMES,
)


# --- anim_slot_names selection --------------------------------------------

def test_anim_slot_names_pokemon_uses_xd_layout_for_both_games():
    assert anim_slot_names(True, False) is XD_POKEMON_ANIM_NAMES
    assert anim_slot_names(False, False) is XD_POKEMON_ANIM_NAMES


def test_anim_slot_names_trainer_selects_per_game_list():
    assert anim_slot_names(True, True) is XD_TRAINER_ANIM_NAMES
    assert anim_slot_names(False, True) is COLO_TRAINER_ANIM_NAMES


# --- sub_anim_is_active (XD motion_type vs Colo anim_type) -----------------

def test_sub_anim_active_xd_uses_motion_type():
    entry = AnimMetadataEntry(anim_type=2)
    assert sub_anim_is_active(entry, SubAnim(motion_type=1, anim_index=0), True)
    assert not sub_anim_is_active(entry, SubAnim(motion_type=0, anim_index=0), True)


def test_sub_anim_active_colo_inverts_motion_type():
    # Colosseum: real slots carry motion_type=0; unused padding carries 1.
    entry = AnimMetadataEntry(anim_type=4)
    assert sub_anim_is_active(entry, SubAnim(motion_type=0, anim_index=3), False)
    assert not sub_anim_is_active(entry, SubAnim(motion_type=1, anim_index=0), False)
    # anim_type does not change the verdict on Colo — motion_type alone decides.
    assert sub_anim_is_active(AnimMetadataEntry(anim_type=2),
                              SubAnim(motion_type=0, anim_index=3), False)


# --- _build_anim_name_map honours the importer toggle ---------------------

def _xd_header_with_slot1(anim_index):
    """XD header whose slot-1 sub-anim points at `anim_index`."""
    h = PKXHeader.default_xd()
    h.anim_entries[1] = AnimMetadataEntry(
        anim_type=4, sub_anim_count=1,
        sub_anims=[SubAnim(motion_type=1, anim_index=anim_index)],
    )
    return h


def test_name_map_trainer_uses_trainer_labels():
    h = _xd_header_with_slot1(5)
    name_map = _build_anim_name_map(h, 'PKX_TRAINER')
    assert name_map[5] == 'Pokéball Throw'


def test_name_map_pokemon_uses_pokemon_labels():
    h = _xd_header_with_slot1(5)
    name_map = _build_anim_name_map(h, 'PKX_POKEMON')
    assert name_map[5] == 'Special A'


def test_name_map_default_kind_falls_back_to_pokemon():
    """colo_xd_kind=None (raw .dat / non-Colo-XD game) keeps Pokémon labels."""
    h = _xd_header_with_slot1(5)
    assert _build_anim_name_map(h, None)[5] == 'Special A'


def test_name_map_colo_trainer_real_slot_named():
    """Colo real slot (motion_type=0) gets its trainer label."""
    h = PKXHeader.default_colosseum()
    h.anim_entries[6] = AnimMetadataEntry(
        anim_type=4, sub_anim_count=1,
        sub_anims=[SubAnim(motion_type=0, anim_index=7)],
        terminator=1,
    )
    name_map = _build_anim_name_map(h, 'PKX_TRAINER')
    assert name_map[7] == 'Battle Intro'  # Colo trainer slot 6


def test_name_map_colo_padding_slot_ignored():
    """Colo padding slot (motion_type=1, anim 0) must not name anim 0."""
    h = PKXHeader.default_colosseum()
    # A real idle on slot 0 (mt=0) plus a padding slot 12 (mt=1 -> anim 0).
    h.anim_entries[0] = AnimMetadataEntry(
        anim_type=2, sub_anims=[SubAnim(motion_type=0, anim_index=0)], terminator=1)
    h.anim_entries[12] = AnimMetadataEntry(
        anim_type=4, sub_anims=[SubAnim(motion_type=1, anim_index=0)], terminator=1)
    name_map = _build_anim_name_map(h, 'PKX_POKEMON')
    assert name_map[0] == 'Idle'  # named by slot 0, not overridden by padding


def test_name_map_empty_without_header():
    assert _build_anim_name_map(None, 'PKX_TRAINER') == {}


# --- active_part_anim_refs (sub-anim triggers, both formats) ---------------

def test_active_part_anim_refs_xd_skips_inactive_and_zero():
    h = PKXHeader.default_xd()
    h.part_anim_data = [
        PartAnimData(has_data=1, anim_index_ref=6),  # active -> kept
        PartAnimData(has_data=0, anim_index_ref=7),  # inactive -> dropped
        PartAnimData(has_data=1, anim_index_ref=0),  # active but anim 0 -> dropped
        PartAnimData(has_data=1, anim_index_ref=9),  # 4th block ignored (only 0..2)
    ]
    assert active_part_anim_refs(h) == [(0, 6)]


def test_active_part_anim_refs_colo_skips_sentinel_and_zero():
    h = PKXHeader.default_colosseum()
    h.colo_part_anim_refs = [6, -1, 0]  # only the first is a real ref
    assert active_part_anim_refs(h) == [(0, 6)]


def test_name_map_colo_sub_triggers_named():
    """Colosseum sub-anim refs (colo_part_anim_refs) now produce Sub labels."""
    h = PKXHeader.default_colosseum()
    h.colo_part_anim_refs = [6, 7, 5]
    name_map = _build_anim_name_map(h, 'PKX_POKEMON')
    assert name_map[6] == 'Sub SleepOnPose'
    assert name_map[7] == 'Sub SleepOffPose'
    assert name_map[5] == 'Sub Extra'
