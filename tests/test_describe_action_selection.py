"""Tests for _actions_for_armature — action→armature binding rules.

The selection must attach each action to exactly the armature it is bound
to (assigned / NLA strip / OBJECT slot named after the armature / name
prefix). The any-pose-action catch-all applies only in single-armature
scenes: in multi-armature scenes it would attach every action to every
armature — quadratic unbake cost and wrong per-model DAT contents.
"""
from types import SimpleNamespace

from exporter.phases.describe.helpers.animations_decode import (
    _actions_for_armature, _is_pose_action,
)


def _fcurve(path):
    return SimpleNamespace(data_path=path)


def _action(name, pose=True, slots=(), id_root='OBJECT'):
    return SimpleNamespace(
        name=name,
        id_root=id_root,
        fcurves=[_fcurve('pose.bones["Bone_0"].location')] if pose else [],
        slots=list(slots),
    )


def _slot(target_id_type, name_display):
    return SimpleNamespace(target_id_type=target_id_type,
                           name_display=name_display)


def _armature(name, assigned=None, nla_actions=()):
    tracks = []
    if nla_actions:
        tracks = [SimpleNamespace(
            strips=[SimpleNamespace(action=a) for a in nla_actions])]
    anim_data = SimpleNamespace(action=assigned, nla_tracks=tracks)
    return SimpleNamespace(name=name, animation_data=anim_data)


class TestSingleArmatureScene:

    def test_catch_all_keeps_loose_pose_actions(self):
        arm = _armature('Model')
        loose = _action('SomethingUnrelated')
        assert _actions_for_armature([loose], arm, armature_count=1) == [loose]

    def test_non_pose_actions_excluded(self):
        arm = _armature('Model')
        mat_anim = _action('MatOnly', pose=False)
        assert _actions_for_armature([mat_anim], arm, armature_count=1) == []


class TestMultiArmatureScene:

    def test_loose_pose_action_not_attached(self):
        arm = _armature('ModelA')
        loose = _action('SomethingUnrelated')
        assert _actions_for_armature([loose], arm, armature_count=3) == []

    def test_assigned_action_attached(self):
        act = _action('X')
        arm = _armature('ModelA', assigned=act)
        assert _actions_for_armature([act], arm, armature_count=3) == [act]

    def test_nla_action_attached(self):
        act = _action('X')
        arm = _armature('ModelA', nla_actions=[act])
        assert _actions_for_armature([act], arm, armature_count=3) == [act]

    def test_slot_bound_action_attached(self):
        act = _action('X', slots=[_slot('OBJECT', 'ModelA.001')])
        mine = _armature('ModelA.001')
        other = _armature('ModelA')
        assert _actions_for_armature([act], mine, armature_count=2) == [act]
        assert _actions_for_armature([act], other, armature_count=2) == []

    def test_name_prefix_attached(self):
        act = _action('ModelA_walk')
        arm = _armature('ModelA')
        assert _actions_for_armature([act], arm, armature_count=2) == [act]

    def test_each_armature_gets_only_its_own(self):
        """The map-archive scenario: uniquified armature names, shared action
        name prefixes, per-armature slot bindings. Slots are authoritative —
        no cross-attachment even though every action carries a0's prefix."""
        a0 = _armature('D6_out_all')
        a1 = _armature('D6_out_all.001')
        act0 = _action('D6_out_all_anim0', slots=[_slot('OBJECT', 'D6_out_all')])
        act1 = _action('D6_out_all_anim1', slots=[_slot('OBJECT', 'D6_out_all.001')])
        assert _actions_for_armature([act0, act1], a0, 2) == [act0]
        assert _actions_for_armature([act0, act1], a1, 2) == [act1]

    def test_slot_binding_overrides_prefix_match(self):
        """An action slot-bound to another armature is an explicit
        non-match, even when the name prefix matches this armature."""
        arm = _armature('ModelA')
        act = _action('ModelA_walk', slots=[_slot('OBJECT', 'ModelB')])
        assert _actions_for_armature([act], arm, armature_count=2) == []

    def test_prefix_fallback_only_for_slotless_actions(self):
        arm = _armature('ModelA')
        legacy = _action('ModelA_walk')  # no slots — pre-4.4 action
        assert _actions_for_armature([legacy], arm, armature_count=2) == [legacy]

    def test_iteration_order_preserved(self):
        acts = [_action('ModelA_b'), _action('ModelA_a')]
        arm = _armature('ModelA')
        assert _actions_for_armature(acts, arm, armature_count=2) == acts


class TestIsPoseAction:

    def test_pose_action(self):
        assert _is_pose_action(_action('X'))

    def test_object_action_without_pose_curves(self):
        assert not _is_pose_action(_action('X', pose=False))

    def test_non_object_action(self):
        assert not _is_pose_action(_action('X', id_root='MATERIAL'))
