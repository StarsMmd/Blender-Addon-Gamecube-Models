"""Tests for _decode_bone_channels — pure Fobj-walk + channel decode."""
from types import SimpleNamespace
from unittest.mock import patch

from importer.phases.describe.helpers.animations import _decode_bone_channels
from shared.Constants.hsd import (
    HSD_A_J_ROTX, HSD_A_J_ROTY, HSD_A_J_ROTZ,
    HSD_A_J_TRAX, HSD_A_J_TRAY, HSD_A_J_TRAZ,
    HSD_A_J_SCAX, HSD_A_J_SCAY, HSD_A_J_SCAZ,
)
from shared.IR.animation import IRKeyframe
from shared.IR.enums import Interpolation
from shared.helpers.scale import GC_TO_METERS


def _kf(value, frame=0):
    return IRKeyframe(frame=frame, value=value, interpolation=Interpolation.LINEAR)


def _fobj_chain(types_and_kfs):
    """Build a fake null-terminated Fobj chain.

    types_and_kfs is a list of (channel_type, list[IRKeyframe]).
    """
    head = None
    for ch_type, kfs in reversed(types_and_kfs):
        head = SimpleNamespace(type=ch_type, _kfs=kfs, next=head)
    return head


def test_routes_rotation_channels_to_xyz():
    aobj = SimpleNamespace(frame=_fobj_chain([
        (HSD_A_J_ROTX, [_kf(0.1)]),
        (HSD_A_J_ROTY, [_kf(0.2)]),
        (HSD_A_J_ROTZ, [_kf(0.3)]),
    ]))
    with patch('importer.phases.describe.helpers.animations.decode_fobjdesc',
               side_effect=lambda f, **kw: list(f._kfs)):
        rot, loc, scl, spline = _decode_bone_channels(aobj)
    assert rot[0][0].value == 0.1
    assert rot[1][0].value == 0.2
    assert rot[2][0].value == 0.3
    assert loc == [[], [], []]
    assert scl == [[], [], []]
    assert spline is None


def test_routes_scale_channels_to_xyz():
    aobj = SimpleNamespace(frame=_fobj_chain([
        (HSD_A_J_SCAX, [_kf(1.0)]),
        (HSD_A_J_SCAY, [_kf(2.0)]),
        (HSD_A_J_SCAZ, [_kf(3.0)]),
    ]))
    with patch('importer.phases.describe.helpers.animations.decode_fobjdesc',
               side_effect=lambda f, **kw: list(f._kfs)):
        rot, loc, scl, spline = _decode_bone_channels(aobj)
    assert scl[0][0].value == 1.0
    assert scl[1][0].value == 2.0
    assert scl[2][0].value == 3.0


def test_translation_keyframes_scaled_to_meters():
    """Location channels must be multiplied by GC_TO_METERS."""
    aobj = SimpleNamespace(frame=_fobj_chain([
        (HSD_A_J_TRAX, [_kf(100.0)]),
        (HSD_A_J_TRAY, [_kf(200.0)]),
        (HSD_A_J_TRAZ, [_kf(300.0)]),
    ]))
    with patch('importer.phases.describe.helpers.animations.decode_fobjdesc',
               side_effect=lambda f, **kw: list(f._kfs)):
        _, loc, _, _ = _decode_bone_channels(aobj)
    assert abs(loc[0][0].value - 100.0 * GC_TO_METERS) < 1e-9
    assert abs(loc[1][0].value - 200.0 * GC_TO_METERS) < 1e-9
    assert abs(loc[2][0].value - 300.0 * GC_TO_METERS) < 1e-9


def test_translation_handles_and_slopes_scaled():
    """Bezier handles and tangent slopes also scaled to meters."""
    kf = IRKeyframe(
        frame=0, value=10.0, interpolation=Interpolation.BEZIER,
        handle_left=(0, 5.0), handle_right=(2, 7.0),
        slope_in=1.0, slope_out=2.0,
    )
    aobj = SimpleNamespace(frame=_fobj_chain([(HSD_A_J_TRAX, [kf])]))
    with patch('importer.phases.describe.helpers.animations.decode_fobjdesc',
               side_effect=lambda f, **kw: list(f._kfs)):
        _, loc, _, _ = _decode_bone_channels(aobj)
    out = loc[0][0]
    assert abs(out.value - 10.0 * GC_TO_METERS) < 1e-9
    assert abs(out.handle_left[1] - 5.0 * GC_TO_METERS) < 1e-9
    assert abs(out.handle_right[1] - 7.0 * GC_TO_METERS) < 1e-9
    assert abs(out.slope_in - 1.0 * GC_TO_METERS) < 1e-9
    assert abs(out.slope_out - 2.0 * GC_TO_METERS) < 1e-9


def test_empty_fobj_chain_returns_empty_channels():
    aobj = SimpleNamespace(frame=None)
    rot, loc, scl, spline = _decode_bone_channels(aobj)
    assert rot == [[], [], []]
    assert loc == [[], [], []]
    assert scl == [[], [], []]
    assert spline is None


def test_path_channel_skipped_without_bone_context():
    """HSD_A_J_PATH needs bone hierarchy; absent it, spline_path stays None."""
    from shared.Constants.hsd import HSD_A_J_PATH
    aobj = SimpleNamespace(
        frame=_fobj_chain([(HSD_A_J_PATH, [_kf(0.0)])]),
        joint=None,
    )
    rot, loc, scl, spline = _decode_bone_channels(aobj)
    assert spline is None
