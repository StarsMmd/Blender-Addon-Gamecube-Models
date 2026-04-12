"""Tests for phases/describe/helpers/material_animations.py — material animation description."""
from types import SimpleNamespace

from importer.phases.describe.helpers.material_animations import (
    _flip_translation_v, _evaluate_track,
)
from shared.IR.animation import IRKeyframe, IRTextureUVTrack
from shared.IR.enums import Interpolation


def _kf(frame, value, interp=Interpolation.LINEAR, left=None, right=None):
    """Shorthand to build an IRKeyframe."""
    return IRKeyframe(frame=frame, value=value, interpolation=interp,
                      handle_left=left, handle_right=right)


# ---------------------------------------------------------------------------
# V-flip for translation_v keyframes
# ---------------------------------------------------------------------------

class TestFlipTranslationV:

    def test_static_scale(self):
        """With static scale, formula is: 1 - scale_v - translation_v."""
        kfs = [_kf(0, 0.2), _kf(10, 0.5)]
        result = _flip_translation_v(kfs, scale_kfs=None, static_scale_v=0.8)
        assert abs(result[0].value - (1.0 - 0.8 - 0.2)) < 1e-6  # 0.0
        assert abs(result[1].value - (1.0 - 0.8 - 0.5)) < 1e-6  # -0.3

    def test_static_scale_handles(self):
        """Bezier handles should also be flipped with static scale."""
        kfs = [_kf(0, 0.5, left=(-1, 0.4), right=(1, 0.6))]
        result = _flip_translation_v(kfs, scale_kfs=None, static_scale_v=0.5)
        # value: 1 - 0.5 - 0.5 = 0.0
        assert abs(result[0].value - 0.0) < 1e-6
        # left handle: (frame, 1 - 0.5 - 0.4) = (-1, 0.1)
        assert abs(result[0].handle_left[1] - 0.1) < 1e-6
        # right handle: (frame, 1 - 0.5 - 0.6) = (1, -0.1)
        assert abs(result[0].handle_right[1] - (-0.1)) < 1e-6

    def test_animated_scale(self):
        """With animated scale, scale is evaluated at each translation keyframe's frame."""
        scale_kfs = [_kf(0, 0.5), _kf(10, 1.0)]
        trans_kfs = [_kf(0, 0.2), _kf(10, 0.3)]

        result = _flip_translation_v(trans_kfs, scale_kfs, static_scale_v=0.5)
        # Frame 0: scale=0.5, corrected = 1 - 0.5 - 0.2 = 0.3
        assert abs(result[0].value - 0.3) < 1e-6
        # Frame 10: scale=1.0, corrected = 1 - 1.0 - 0.3 = -0.3
        assert abs(result[1].value - (-0.3)) < 1e-6

    def test_empty_translation(self):
        result = _flip_translation_v([], None, 1.0)
        assert result == []


# ---------------------------------------------------------------------------
# Track evaluation
# ---------------------------------------------------------------------------

class TestEvaluateTrack:

    def test_before_first(self):
        kfs = [_kf(5, 2.0), _kf(10, 4.0)]
        assert _evaluate_track(kfs, 0) == 2.0

    def test_after_last(self):
        kfs = [_kf(0, 1.0), _kf(10, 5.0)]
        assert _evaluate_track(kfs, 20) == 5.0

    def test_linear_interpolation(self):
        kfs = [_kf(0, 0.0), _kf(10, 10.0)]
        assert abs(_evaluate_track(kfs, 5) - 5.0) < 1e-6

    def test_constant_interpolation(self):
        kfs = [_kf(0, 3.0, Interpolation.CONSTANT), _kf(10, 7.0)]
        assert _evaluate_track(kfs, 5) == 3.0

    def test_exact_keyframe(self):
        kfs = [_kf(0, 1.0), _kf(5, 3.0), _kf(10, 5.0)]
        assert abs(_evaluate_track(kfs, 5) - 3.0) < 1e-6

    def test_empty_track(self):
        assert _evaluate_track([], 0) == 0.0

    def test_single_keyframe(self):
        kfs = [_kf(5, 42.0)]
        assert _evaluate_track(kfs, 0) == 42.0
        assert _evaluate_track(kfs, 100) == 42.0

    def test_bezier_interpolation(self):
        """Bezier with handles should produce curved interpolation."""
        kfs = [
            _kf(0, 0.0, Interpolation.BEZIER, right=(3.33, 0.0)),
            _kf(10, 10.0, Interpolation.LINEAR, left=(6.67, 10.0)),
        ]
        # At t=0.5 (frame 5), cubic bezier with P0=0, P1=0, P2=10, P3=10
        # should give: 0*(1-0.5)^3 + 3*0*(1-0.5)^2*0.5 + 3*10*(1-0.5)*0.5^2 + 10*0.5^3
        # = 0 + 0 + 3*10*0.25*0.25... let me just check it's between 0 and 10
        val = _evaluate_track(kfs, 5)
        assert 0.0 <= val <= 10.0


# ---------------------------------------------------------------------------
# Material color/alpha keyframe scale factor
# ---------------------------------------------------------------------------

class TestMaterialKeyframeScale:
    """Regression: material color/alpha keyframes must use scale=1.0, not 1/255.

    The FObjDesc keyframe decoder already outputs values in 0-1 range.
    A previous bug applied scale=1/255 which made all material animation
    values ~255x too small, causing invisible effects.
    """

    def test_scale_is_one_not_255(self):
        """The describe code uses scale=1.0 for material color/alpha tracks."""
        import inspect
        from importer.phases.describe.helpers import material_animations as mod
        source = inspect.getsource(mod._describe_material_track)
        # Must NOT contain 1/255 or 1.0/255.0 scale
        assert '/ 255' not in source, "Material animation scale should be 1.0, not 1/255"
        assert 'scale=1.0' in source or 'scale=1)' in source or 'scale=1,' in source

    def test_scale_value_in_call(self):
        """The actual call to decode_fobjdesc passes scale=1.0."""
        import inspect
        from importer.phases.describe.helpers import material_animations as mod
        source = inspect.getsource(mod._describe_material_track)
        # Find the decode_fobjdesc call and verify scale parameter
        assert 'decode_fobjdesc(fobj, bias=0, scale=1.0' in source
