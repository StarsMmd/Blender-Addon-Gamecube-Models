"""Rotation source must follow the bone's rotation_mode, not the fcurve set.

A pose bone evaluates exactly one rotation channel, chosen by its
rotation_mode. An Action can still carry stale fcurves for the *other*
channel — most commonly the flat identity ``rotation_quaternion`` curves
Blender leaves behind for every bone after one is switched to an Euler
mode. The unbaker used to prefer quaternion whenever *any* quaternion
fcurves existed, so an XYZ-mode bone with animated ``rotation_euler`` curves
plus those leftover identity quaternions had its rotation read from the flat
quaternions instead — silently exporting the bone with no rotation at all.

`_prefer_quaternion_rotation` encodes the fix: respect rotation_mode, and
only fall back to the other channel when the mode's own channel is absent.
"""
from exporter.phases.describe.helpers.animations_decode import (
    _prefer_quaternion_rotation,
)


def test_euler_mode_ignores_stale_quaternion_curves():
    """THE BUG: XYZ bone with animated euler + leftover flat quaternion curves
    must read euler, not the stale quaternion."""
    assert _prefer_quaternion_rotation('XYZ', has_quat_fcurves=True,
                                       has_euler_fcurves=True) is False


def test_euler_mode_without_euler_curves_falls_back_to_quaternion():
    """If an Euler-mode bone somehow has only quaternion curves, use them
    rather than emitting no rotation."""
    assert _prefer_quaternion_rotation('XYZ', has_quat_fcurves=True,
                                       has_euler_fcurves=False) is True


def test_euler_mode_plain_euler_curves():
    assert _prefer_quaternion_rotation('YZX', has_quat_fcurves=False,
                                       has_euler_fcurves=True) is False


def test_quaternion_mode_uses_quaternion():
    assert _prefer_quaternion_rotation('QUATERNION', has_quat_fcurves=True,
                                       has_euler_fcurves=True) is True


def test_quaternion_mode_without_quaternion_curves_falls_back_to_euler():
    assert _prefer_quaternion_rotation('QUATERNION', has_quat_fcurves=False,
                                       has_euler_fcurves=True) is False


def test_quaternion_mode_quaternion_only():
    assert _prefer_quaternion_rotation('QUATERNION', has_quat_fcurves=True,
                                       has_euler_fcurves=False) is True
