"""Bezier handles from HSD tangents reproduce the runtime's cubic-Hermite.

The XD runtime interpolates spline keyframes with ``splGetHelmite`` (verified
against the GXXE01 disassembly: ``HSD_FObjInterpretAnim`` loads
``(1/fterm, time, p0, p1, d0, d1)`` and calls ``splGetHelmite``). The importer
must turn the authored tangents into Blender bezier handles so the sampled
curve matches frame-for-frame; previously the tangents were dropped and Blender
filled in AUTO_CLAMPED handles, producing multi-degree wobble between keys.
"""
from importer.phases.describe.helpers.animations import _assign_bezier_handles
from shared.IR.animation import IRKeyframe
from shared.IR.enums import Interpolation


def _spl_hermite(inv_dt, time, p0, p1, d0, d1):
    """Faithful port of the runtime ``splGetHelmite`` (== HSDRaw reference)."""
    h = inv_dt
    a = time * time
    b = h * h * a * time
    c = 3.0 * a * h * h
    d = b - a * h
    b2 = 2.0 * b * h
    return d1 * d + d0 * (time + (d - a * h)) + p0 * (1.0 + (b2 - c)) + p1 * (-b2 + c)


def _bezier_y(u, p0, c1, c2, p3):
    """Cubic bezier value at parameter u (handles at 1/3 spacing => x linear in u)."""
    mu = 1.0 - u
    return mu * mu * mu * p0 + 3 * mu * mu * u * c1 + 3 * mu * u * u * c2 + u * u * u * p3


def _kf(frame, value, slope_in, slope_out):
    return IRKeyframe(frame=frame, value=value, interpolation=Interpolation.BEZIER,
                      slope_in=slope_in, slope_out=slope_out)


def _assert_segment_matches(a, b):
    dt = b.frame - a.frame
    d0 = b.slope_in     # outgoing tangent at `a` (next key's carried-in slope)
    d1 = b.slope_out    # incoming tangent at `b`
    for step in range(dt + 1):
        u = step / dt
        bez = _bezier_y(u, a.value, a.handle_right[1], b.handle_left[1], b.value)
        game = _spl_hermite(1.0 / dt, step, a.value, b.value, d0, d1)
        assert abs(bez - game) < 1e-6, (step, bez, game)
    # handles sit at 1/3 of the frame span (keeps x linear in the bezier param)
    assert abs(a.handle_right[0] - (a.frame + dt / 3.0)) < 1e-9
    assert abs(b.handle_left[0] - (b.frame - dt / 3.0)) < 1e-9


def test_handles_reproduce_game_hermite_pure_spline():
    # plain SPL: each key's slope_in equals the previous key's slope_out
    kfs = [
        _kf(0, 1.0, 0.0, 0.5),
        _kf(10, 3.0, 0.5, -0.2),
        _kf(18, 2.0, -0.2, 0.1),
    ]
    _assign_bezier_handles(kfs)
    _assert_segment_matches(kfs[0], kfs[1])
    _assert_segment_matches(kfs[1], kfs[2])


def test_handles_reproduce_game_hermite_asymmetric_slp():
    # SLP override: the segment's outgoing tangent (key1.slope_in = -0.7) differs
    # from key0's own slope_out (1.0). The handle conversion must honour it.
    kfs = [
        _kf(0, 0.0, 0.0, 1.0),
        _kf(12, 5.0, -0.7, 0.3),
    ]
    _assign_bezier_handles(kfs)
    assert abs(kfs[0].handle_right[1] - (0.0 + (-0.7) * 12 / 3.0)) < 1e-9
    _assert_segment_matches(kfs[0], kfs[1])


def test_single_keyframe_gets_no_handles():
    kfs = [_kf(0, 1.0, 0.0, 0.0)]
    _assign_bezier_handles(kfs)
    assert kfs[0].handle_left is None
    assert kfs[0].handle_right is None


def test_non_bezier_keys_left_untouched():
    kfs = [
        IRKeyframe(frame=0, value=1.0, interpolation=Interpolation.LINEAR, slope_out=0.0),
        IRKeyframe(frame=5, value=2.0, interpolation=Interpolation.LINEAR, slope_out=0.0),
    ]
    _assign_bezier_handles(kfs)
    assert all(k.handle_left is None and k.handle_right is None for k in kfs)
