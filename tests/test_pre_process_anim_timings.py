"""Pre-process validator: PKX anim slots with assigned actions need non-zero timings.

The game's battle state machine pacing (loop modulo, hit-frame gates,
state-transition thresholds) reads `anim_entries[slot].timing_1..4`.
All-zero timings produce divide-by-zero on idle loops and immediate state
advance on transitions — reliably crashes on send-out. `derive_timing()`
in `scripts/prepare_for_export.py` computes these from action durations;
this validator guards against forgetting to run it after populating slots.
"""
import pytest

from exporter.phases.pre_process.pre_process import _check_anim_timings


# slot_state tuple shape (mirrors what _validate_anim_timings collects):
#   (armature_name, slot_index, sub_0_anim_name, action_duration, (t1, t2, t3, t4))


def test_empty_input_passes():
    _check_anim_timings([])


def test_unassigned_slot_with_zero_timings_passes():
    # No `sub_0_anim` → slot deliberately unused → zero timings are correct.
    _check_anim_timings([("arm", 0, "", 0.0, (0.0, 0.0, 0.0, 0.0))])


def test_assigned_slot_with_nonzero_timing_passes():
    _check_anim_timings([("arm", 0, "fight_idle", 1.6, (1.6, 0.0, 0.0, 0.0))])


def test_assigned_slot_with_all_zero_timings_rejected():
    with pytest.raises(ValueError, match="derive_timing"):
        _check_anim_timings([
            ("arm", 0, "fight_idle", 1.6, (0.0, 0.0, 0.0, 0.0))
        ])


def test_assigned_slot_referencing_missing_action_skipped():
    # Action name set but action not in scene → dur==0 → skip.
    # This is the "user typo / action renamed / action deleted" case —
    # the validator shouldn't noisy-fail here; that's a different concern.
    _check_anim_timings([("arm", 3, "typoed_action", 0.0, (0.0, 0.0, 0.0, 0.0))])


def test_assigned_slot_with_empty_keyframeless_action_skipped():
    # Same boundary condition as above — action exists but has no
    # keyframes, so dur==0 — skip.
    _check_anim_timings([("arm", 3, "empty_action", 0.0, (0.0, 0.0, 0.0, 0.0))])


def test_multiple_offenders_all_reported_in_error_message():
    state = [
        ("arm", 0, "idle_loop", 1.6, (0.0, 0.0, 0.0, 0.0)),
        ("arm", 4, "physical_c", 2.5, (0.0, 0.0, 0.0, 0.0)),
        ("arm", 8, "damage_hit", 0.7, (0.0, 0.0, 0.0, 0.0)),
    ]
    with pytest.raises(ValueError) as excinfo:
        _check_anim_timings(state)
    msg = str(excinfo.value)
    assert "slot 0" in msg
    assert "slot 4" in msg
    assert "slot 8" in msg
    assert "idle_loop" in msg
    assert "physical_c" in msg
    assert "damage_hit" in msg


def test_single_nonzero_timing_field_is_enough():
    # Attack slot only needs timing_1 set; timing_2..4 may legitimately be 0.
    _check_anim_timings([("arm", 4, "physical_a", 2.0, (0.0, 0.0, 2.0, 0.0))])
