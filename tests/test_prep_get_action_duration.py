"""Regression: prep's _get_action_duration must match HSD's 30 tick/s rate.

XD AOBJs advance at 30 animation-units per second (verified by matching
`AOBJ.end_frame / 30` against every game-native PKX header `timing_1`
value for 6 diverse models: achamo, absol, rayquaza, cerebi, deoxys,
blacky). The importer samples `range(end_frame)` so the last keyframe
sits at `end_frame - 1`; `_get_action_duration` must add 1 back to
recover the true duration.

Before this fix the function divided by 60 (half the true rate) and did
not add the off-by-one back, producing durations approximately half the
source timing. Visible symptom: every animation in a round-tripped PKX
played at ~double speed until the game's state machine desynced.
"""
import os


PREP_PATH = os.path.join(
    os.path.dirname(__file__), "..", "scripts", "prepare_for_export.py"
)


def _prep_source():
    with open(PREP_PATH) as f:
        return f.read()


def test_get_action_duration_uses_30fps_divisor():
    """XD AOBJs advance at 30 units/s, not 60. Dividing by 60 halves the
    duration — one of the biggest visible prep regressions."""
    src = _prep_source()
    # Must reference / 30 in _get_action_duration, not / 60.
    i = src.index("def _get_action_duration")
    j = src.index("def ", i + 1)
    body = src[i:j]
    assert "/ 30" in body, (
        "_get_action_duration must divide by 30 (XD's AOBJ rate), not 60. "
        "Current body:\n" + body
    )
    assert "/ 60" not in body, (
        "_get_action_duration must not divide by 60 — that halves the true "
        "animation duration. Current body:\n" + body
    )


def test_get_action_duration_adds_off_by_one():
    """Importer samples range(end_frame) → last kf sits at end_frame - 1.
    We must add 1 back to recover the true duration."""
    src = _prep_source()
    i = src.index("def _get_action_duration")
    j = src.index("def ", i + 1)
    body = src[i:j]
    assert "max_frame + 1" in body, (
        "_get_action_duration must add 1 to max_frame to recover the true "
        "duration (importer samples range(end_frame), so the last keyframe "
        "lives at end_frame - 1). Current body:\n" + body
    )
