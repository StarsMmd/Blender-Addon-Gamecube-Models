"""Actions must export in PKX-slot order so slot `anim_index` values resolve correctly.

The PKX header stores each `AnimMetadataEntry.sub_anims[j].anim_index` as a DAT
index into the model's `animated_joints[]` array. If the exporter enumerates
Blender actions alphabetically (`bpy.data.actions` default order) but the PKX
slots expect slot 0's action to live at DAT[0], the game ends up playing the
wrong animation — e.g. slot 0 (battle idle) playing `basic_anim_0` when the
slot actually referenced `fight_anim_0`.
"""
from exporter.phases.describe_blender.helpers.animations import (
    _collect_slot_ordered_action_names,
    _reorder_actions_by_slot,
)


class _FakeAction:
    def __init__(self, name):
        self.name = name


class _FakeArmature:
    def __init__(self, props):
        self._props = props

    def get(self, key, default=None):
        return self._props.get(key, default)


def test_collect_slot_order_returns_none_without_pkx_format():
    arm = _FakeArmature({})
    assert _collect_slot_ordered_action_names(arm) is None


def test_collect_slot_order_walks_slots_in_index_order():
    arm = _FakeArmature({
        "dat_pkx_format": "XD",
        "dat_pkx_anim_count": 3,
        "dat_pkx_anim_00_sub_0_anim": "fight_anim_0",
        "dat_pkx_anim_01_sub_0_anim": "fight_anim_1",
        "dat_pkx_anim_02_sub_0_anim": "basic_anim_0",
    })
    assert _collect_slot_ordered_action_names(arm) == [
        "fight_anim_0", "fight_anim_1", "basic_anim_0",
    ]


def test_collect_slot_order_dedups_multi_slot_references():
    # Two different slots both reference the same action. The action should
    # appear once, at the position of its first mention, so DAT indices don't
    # get inflated.
    arm = _FakeArmature({
        "dat_pkx_format": "XD",
        "dat_pkx_anim_count": 3,
        "dat_pkx_anim_00_sub_0_anim": "fight_anim_0",
        "dat_pkx_anim_01_sub_0_anim": "fight_anim_0",
        "dat_pkx_anim_02_sub_0_anim": "basic_anim_0",
    })
    assert _collect_slot_ordered_action_names(arm) == [
        "fight_anim_0", "basic_anim_0",
    ]


def test_collect_slot_order_picks_up_sub_anim_refs():
    # Part-anim references live under `dat_pkx_sub_anim_N_anim_ref`.
    arm = _FakeArmature({
        "dat_pkx_format": "XD",
        "dat_pkx_anim_count": 1,
        "dat_pkx_anim_00_sub_0_anim": "fight_anim_0",
        "dat_pkx_sub_anim_0_anim_ref": "eye_blink",
    })
    assert _collect_slot_ordered_action_names(arm) == [
        "fight_anim_0", "eye_blink",
    ]


def test_collect_slot_order_skips_empty_strings():
    arm = _FakeArmature({
        "dat_pkx_format": "XD",
        "dat_pkx_anim_count": 3,
        "dat_pkx_anim_00_sub_0_anim": "",
        "dat_pkx_anim_01_sub_0_anim": "fight_anim_0",
        "dat_pkx_anim_02_sub_0_anim": "",
    })
    assert _collect_slot_ordered_action_names(arm) == ["fight_anim_0"]


def test_collect_slot_order_returns_none_when_all_slots_empty():
    arm = _FakeArmature({
        "dat_pkx_format": "XD",
        "dat_pkx_anim_count": 3,
        "dat_pkx_anim_00_sub_0_anim": "",
        "dat_pkx_anim_01_sub_0_anim": "",
    })
    assert _collect_slot_ordered_action_names(arm) is None


def test_reorder_places_slot_actions_first():
    # bpy.data.actions order (alphabetical) vs slot order — slot 0 wants
    # fight_anim_0 at DAT[0], so fight_anim_0 moves to the front.
    alphabetical = [
        _FakeAction("basic_anim_0"),
        _FakeAction("basic_anim_1"),
        _FakeAction("fight_anim_0"),
        _FakeAction("fight_anim_1"),
    ]
    slot_order = ["fight_anim_0", "fight_anim_1", "basic_anim_0"]

    result = _reorder_actions_by_slot(alphabetical, slot_order)

    assert [a.name for a in result] == [
        "fight_anim_0", "fight_anim_1", "basic_anim_0",
        "basic_anim_1",  # unreferenced, stays at end
    ]


def test_reorder_keeps_unreferenced_actions_trailing():
    # During iterative setup the user might wire up only a few slots.
    # Unreferenced actions must still export so they remain addressable if
    # the user wires them up later.
    alphabetical = [
        _FakeAction("a_anim"), _FakeAction("b_anim"), _FakeAction("c_anim"),
    ]
    slot_order = ["c_anim"]

    result = _reorder_actions_by_slot(alphabetical, slot_order)

    assert [a.name for a in result] == ["c_anim", "a_anim", "b_anim"]


def test_reorder_ignores_slot_names_that_do_not_match_any_action():
    # Typo in a slot reference must not crash and must not displace real actions.
    alphabetical = [_FakeAction("real_anim")]
    slot_order = ["nonexistent_anim", "real_anim"]

    result = _reorder_actions_by_slot(alphabetical, slot_order)

    assert [a.name for a in result] == ["real_anim"]


def test_all_slots_pointing_at_one_action_collapses_dat_to_that_action():
    # `apply_pkx_metadata` points every slot at the same default action so
    # every `anim_index` resolves to 0 deterministically. The collect helper
    # must dedupe so the DAT only gets one entry for that action.
    arm = _FakeArmature({
        "dat_pkx_format": "XD",
        "dat_pkx_anim_count": 17,
        **{
            f"dat_pkx_anim_{i:02d}_sub_0_anim": "basic_anim_0"
            for i in range(17)
        },
    })
    assert _collect_slot_ordered_action_names(arm) == ["basic_anim_0"]
