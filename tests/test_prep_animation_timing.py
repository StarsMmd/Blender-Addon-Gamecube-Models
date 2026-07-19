"""Pre-process guard: reject PKX exports whose assigned anim slots have a
zero primary timing.

The battle state machine divides by each PKX anim slot's `timing_1` to pace
its state transitions, so an *assigned* slot (one that references a real
action) with `timing_1 = 0` is a divide-by-zero that reliably crashes the
game on send-out. Empty / padding slots are exempt — the game never reads
their timing. The exporter therefore rejects the export when an assigned
slot carries a zero timing, instead of shipping a crash-on-send-out PKX.

Note: this replaces a previously-claimed-but-absent guard — earlier docs
asserted pre-process validated timings when no such check existed.
"""
import pytest


# --- _collect_zero_timing_slots (duck-typed on dict.get) -------------------

def test_collect_flags_assigned_zero_timing_slot():
    from exporter.phases.pre_process.pre_process import _collect_zero_timing_slots
    arm = {
        "dat_pkx_anim_count": 3,
        "dat_pkx_anim_00_sub_count": 1,
        "dat_pkx_anim_00_sub_0_anim": "Idle",
        "dat_pkx_anim_00_timing_1": 0.0,     # assigned + zero -> offending
        "dat_pkx_anim_01_sub_count": 1,
        "dat_pkx_anim_01_sub_0_anim": "Walk",
        "dat_pkx_anim_01_timing_1": 30.0,    # assigned + non-zero -> ok
        "dat_pkx_anim_02_sub_count": 1,
        "dat_pkx_anim_02_sub_0_anim": "",
        "dat_pkx_anim_02_timing_1": 0.0,     # unassigned -> exempt
    }
    assert _collect_zero_timing_slots(arm) == ["slot 00 (Idle)"]


def test_collect_excludes_unassigned_slots():
    from exporter.phases.pre_process.pre_process import _collect_zero_timing_slots
    arm = {
        "dat_pkx_anim_count": 2,
        "dat_pkx_anim_00_sub_0_anim": "",     # padding
        "dat_pkx_anim_00_timing_1": 0.0,
        "dat_pkx_anim_01_sub_0_anim": "",     # padding
        "dat_pkx_anim_01_timing_1": 0.0,
    }
    assert _collect_zero_timing_slots(arm) == []


def test_collect_missing_timing_prop_is_zero():
    from exporter.phases.pre_process.pre_process import _collect_zero_timing_slots
    arm = {
        "dat_pkx_anim_count": 1,
        "dat_pkx_anim_00_sub_count": 2,
        "dat_pkx_anim_00_sub_0_anim": "",
        "dat_pkx_anim_00_sub_1_anim": "Attack",  # assigned via sub_1
        # no timing_1 property at all -> default 0.0 -> offending
    }
    assert _collect_zero_timing_slots(arm) == ["slot 00 (Attack)"]


def test_collect_int_anim_ref_is_not_assigned():
    """An int sub-anim ref (raw index) is not a real assigned action, matching
    describe's has_anim = isinstance(name, str) test."""
    from exporter.phases.pre_process.pre_process import _collect_zero_timing_slots
    arm = {
        "dat_pkx_anim_count": 1,
        "dat_pkx_anim_00_sub_0_anim": 5,
        "dat_pkx_anim_00_timing_1": 0.0,
    }
    assert _collect_zero_timing_slots(arm) == []


def test_collect_nonzero_timing_passes():
    from exporter.phases.pre_process.pre_process import _collect_zero_timing_slots
    arm = {
        "dat_pkx_anim_count": 1,
        "dat_pkx_anim_00_sub_0_anim": "Idle",
        "dat_pkx_anim_00_timing_1": 12.5,
    }
    assert _collect_zero_timing_slots(arm) == []


# --- _check_animation_timing -----------------------------------------------

def test_guard_empty_is_fine():
    from exporter.phases.pre_process.pre_process import _check_animation_timing
    _check_animation_timing([])  # no raise


def test_guard_no_offending_slots_is_fine():
    from exporter.phases.pre_process.pre_process import _check_animation_timing
    _check_animation_timing([("rig", [])])  # no raise


def test_guard_rejects_zero_timing_slot():
    from exporter.phases.pre_process.pre_process import _check_animation_timing
    with pytest.raises(ValueError) as exc:
        _check_animation_timing([("badrig", ["slot 03 (Walk)"])])
    msg = str(exc.value)
    assert "badrig" in msg
    assert "Walk" in msg
    assert "send-out" in msg


def test_guard_collects_all_offenders():
    from exporter.phases.pre_process.pre_process import _check_animation_timing
    with pytest.raises(ValueError) as exc:
        _check_animation_timing([
            ("rigA", ["slot 00 (Idle)"]),
            ("rigB", []),                       # fine
            ("rigC", ["slot 01 (Attack)"]),
        ])
    msg = str(exc.value)
    assert "rigA" in msg and "rigC" in msg
    assert "rigB" not in msg
