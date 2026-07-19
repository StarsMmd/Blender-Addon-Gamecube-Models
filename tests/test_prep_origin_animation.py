"""Pre-process guard: reject scenes whose root (origin) bone is animated.

The game does not treat the root JOBJ as a normal animatable joint. A
per-model flag can make it strip the root joint's animation when an
animation is selected (`ModelSequence::LoadData` sets it from PKX header
flag 0x40 → `GSmodelRemoveRootJointAnimation`; `GSmodelSetAnimIndex` then
calls `HSD_JObjRemoveAnim` on bone 0). Otherwise `modelUpdateTransform`
writes the root joint transform itself every frame as the model's world
placement, discarding the animation — or, in the "use root joint
animation" mode (flag 0x400), reads the animated root back into the
model position so the root animation slides the whole model off its
placed spot. Game-native models keep the root a static wrapper and
animate from its children (implementation_notes § Root joint animation).

The guard therefore refuses to export any scene whose parent-less root
bone carries transform keyframes, surfacing an actionable message at
validation time instead of shipping a model whose root motion is dropped
or whose body drifts in-game.
"""
import pytest


class _FakeFCurve:
    def __init__(self, data_path, n_keys):
        self.data_path = data_path
        self.keyframe_points = [None] * n_keys


class _FakeAction:
    def __init__(self, name, fcurves):
        self.name = name
        self.fcurves = fcurves


# --- _action_animates_bone --------------------------------------------------

def test_animates_bone_true_for_multi_key_root_track():
    from exporter.phases.pre_process.pre_process import _action_animates_bone
    action = _FakeAction("Walk", [_FakeFCurve('pose.bones["root"].location', 2)])
    assert _action_animates_bone(action, "root") is True


def test_animates_bone_true_for_quaternion_channel():
    from exporter.phases.pre_process.pre_process import _action_animates_bone
    action = _FakeAction(
        "Spin", [_FakeFCurve('pose.bones["root"].rotation_quaternion', 3)])
    assert _action_animates_bone(action, "root") is True


def test_animates_bone_false_for_single_static_key():
    """One keyframe is a static pose, not motion — allowed."""
    from exporter.phases.pre_process.pre_process import _action_animates_bone
    action = _FakeAction("Pose", [_FakeFCurve('pose.bones["root"].location', 1)])
    assert _action_animates_bone(action, "root") is False


def test_animates_bone_false_for_other_bone():
    from exporter.phases.pre_process.pre_process import _action_animates_bone
    action = _FakeAction("Walk", [_FakeFCurve('pose.bones["Spine"].location', 5)])
    assert _action_animates_bone(action, "root") is False


def test_animates_bone_false_for_non_transform_channel():
    from exporter.phases.pre_process.pre_process import _action_animates_bone
    action = _FakeAction(
        "Custom", [_FakeFCurve('pose.bones["root"]["influence"]', 5)])
    assert _action_animates_bone(action, "root") is False


def test_animates_bone_false_for_object_level_track():
    """An object-level location curve is not a pose-bone track."""
    from exporter.phases.pre_process.pre_process import _action_animates_bone
    action = _FakeAction("ObjMove", [_FakeFCurve('location', 4)])
    assert _action_animates_bone(action, "root") is False


def test_animates_bone_matches_bone_name_with_regex_metachars():
    from exporter.phases.pre_process.pre_process import _action_animates_bone
    action = _FakeAction(
        "Walk", [_FakeFCurve('pose.bones["root.001"].scale', 2)])
    assert _action_animates_bone(action, "root.001") is True
    assert _action_animates_bone(action, "root") is False


# --- _check_origin_bone_not_animated ---------------------------------------

def test_guard_empty_scene_is_fine():
    from exporter.phases.pre_process.pre_process import _check_origin_bone_not_animated
    _check_origin_bone_not_animated([])  # no raise


def test_guard_accepts_static_root():
    from exporter.phases.pre_process.pre_process import _check_origin_bone_not_animated
    _check_origin_bone_not_animated([("rig", "root", [])])  # no raise


def test_guard_rejects_animated_root():
    from exporter.phases.pre_process.pre_process import _check_origin_bone_not_animated
    with pytest.raises(ValueError) as exc:
        _check_origin_bone_not_animated([("badrig", "root", ["Walk"])])
    msg = str(exc.value)
    assert "badrig" in msg
    assert "root" in msg
    assert "Walk" in msg
    assert "Origin" in msg  # names the canonical-parent fix


def test_guard_collects_all_offenders():
    from exporter.phases.pre_process.pre_process import _check_origin_bone_not_animated
    with pytest.raises(ValueError) as exc:
        _check_origin_bone_not_animated([
            ("rigA", "root", ["Idle", "Walk"]),
            ("rigB", "base", ["Attack"]),
            ("rigC", "root", []),  # static — not an offender
        ])
    msg = str(exc.value)
    assert "rigA" in msg and "rigB" in msg
    assert "Idle" in msg and "Attack" in msg
    assert "rigC" not in msg


def test_guard_truncates_long_action_lists():
    from exporter.phases.pre_process.pre_process import _check_origin_bone_not_animated
    with pytest.raises(ValueError) as exc:
        _check_origin_bone_not_animated(
            [("rig", "root", ["a", "b", "c", "d", "e"])])
    assert "…" in str(exc.value)
