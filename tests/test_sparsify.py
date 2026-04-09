"""Tests for bezier sparsification and slope computation.

Tests _compute_slopes, _hermite_eval, _sparsify_bezier with known curves:
constant, linear, quadratic, sine wave, step function.
"""
import math
import sys
import os
import pytest

# Add project root to path for direct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.IR.animation import IRKeyframe
from shared.IR.enums import Interpolation

# Import the functions under test from describe_blender animations helper.
# These are module-level functions, not class methods.
from exporter.phases.describe_blender.helpers.animations import (
    _compute_slopes,
    _hermite_eval,
    _sparsify_bezier,
    _sparsify,
)


# ---------------------------------------------------------------------------
# _compute_slopes tests
# ---------------------------------------------------------------------------

class TestComputeSlopes:
    def test_empty(self):
        assert _compute_slopes([]) == []

    def test_single_point(self):
        assert _compute_slopes([(0, 5.0)]) == [0.0]

    def test_constant(self):
        fv = [(i, 3.0) for i in range(10)]
        slopes = _compute_slopes(fv)
        assert all(abs(s) < 1e-10 for s in slopes)

    def test_linear_ramp(self):
        """Linear ramp y = 2*x should have slope 2 everywhere."""
        fv = [(i, 2.0 * i) for i in range(10)]
        slopes = _compute_slopes(fv)
        for s in slopes:
            assert abs(s - 2.0) < 1e-10, f"Expected slope 2.0, got {s}"

    def test_quadratic(self):
        """y = x^2 should have slope 2*x at interior points (central diff)."""
        fv = [(i, float(i * i)) for i in range(10)]
        slopes = _compute_slopes(fv)
        # Interior points: central diff gives exact derivative for quadratics
        for i in range(1, 9):
            expected = 2.0 * i
            assert abs(slopes[i] - expected) < 1e-10, \
                f"At x={i}: expected slope {expected}, got {slopes[i]}"

    def test_sine_wave(self):
        """sin(x) should have slope approximately cos(x)."""
        n = 100
        fv = [(i, math.sin(i * 2 * math.pi / n)) for i in range(n)]
        slopes = _compute_slopes(fv)
        # Check a few interior points (central diff is approximate for sin)
        for i in [25, 50, 75]:
            expected = (2 * math.pi / n) * math.cos(i * 2 * math.pi / n)
            assert abs(slopes[i] - expected) < 0.01, \
                f"At i={i}: expected ~{expected:.4f}, got {slopes[i]:.4f}"

    def test_two_points(self):
        """Two points: both endpoints use forward/backward diff."""
        fv = [(0, 0.0), (1, 3.0)]
        slopes = _compute_slopes(fv)
        assert abs(slopes[0] - 3.0) < 1e-10
        assert abs(slopes[1] - 3.0) < 1e-10


# ---------------------------------------------------------------------------
# _hermite_eval tests
# ---------------------------------------------------------------------------

class TestHermiteEval:
    def test_endpoints(self):
        """Hermite should return p0 at t=0 and p1 at t=1."""
        assert abs(_hermite_eval(1.0, 0.5, 3.0, 0.5, 10.0, 0.0) - 1.0) < 1e-10
        assert abs(_hermite_eval(1.0, 0.5, 3.0, 0.5, 10.0, 1.0) - 3.0) < 1e-10

    def test_linear_segment(self):
        """With matching chord slopes, hermite should produce linear interp."""
        p0, p1, dt = 0.0, 10.0, 5.0
        chord_slope = (p1 - p0) / dt  # 2.0
        for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
            expected = p0 + chord_slope * dt * t
            result = _hermite_eval(p0, chord_slope, p1, chord_slope, dt, t)
            assert abs(result - expected) < 1e-10, \
                f"At t={t}: expected {expected}, got {result}"

    def test_zero_slopes(self):
        """Zero slopes with different values creates S-curve (ease in/out)."""
        # At midpoint of [0, 1] with zero slopes: h(0.5) should be 0.5
        # h(0.5) = (2*0.125 - 3*0.25 + 1)*0 + ... + (-2*0.125 + 3*0.25)*1 = 0.5
        result = _hermite_eval(0.0, 0.0, 1.0, 0.0, 1.0, 0.5)
        assert abs(result - 0.5) < 1e-10

    def test_symmetry(self):
        """Symmetric slopes around midpoint."""
        v1 = _hermite_eval(0.0, 1.0, 0.0, -1.0, 2.0, 0.5)
        # At midpoint with opposing slopes, curve should peak/trough
        assert abs(v1 - 0.5) < 1e-10  # h10 and h11 contribute


# ---------------------------------------------------------------------------
# _sparsify_bezier tests
# ---------------------------------------------------------------------------

class TestSparsifyBezier:
    def test_empty(self):
        assert _sparsify_bezier([], []) == []

    def test_single_point(self):
        result = _sparsify_bezier([(0, 5.0)], [0.0])
        assert len(result) == 1
        assert result[0].interpolation == Interpolation.CONSTANT
        assert abs(result[0].value - 5.0) < 1e-10

    def test_constant_channel(self):
        """All same values → single CONSTANT keyframe."""
        fv = [(i, 3.0) for i in range(20)]
        slopes = _compute_slopes(fv)
        result = _sparsify_bezier(fv, slopes)
        assert len(result) == 1
        assert result[0].interpolation == Interpolation.CONSTANT
        assert abs(result[0].value - 3.0) < 1e-10

    def test_linear_ramp(self):
        """Perfect linear ramp → two LINEAR keyframes."""
        fv = [(i, 2.0 * i + 1.0) for i in range(30)]
        slopes = _compute_slopes(fv)
        result = _sparsify_bezier(fv, slopes)
        assert len(result) == 2
        assert result[0].interpolation == Interpolation.LINEAR
        assert result[1].interpolation == Interpolation.LINEAR
        assert abs(result[0].value - 1.0) < 1e-10
        assert abs(result[1].value - 59.0) < 1e-10

    def test_sine_wave_has_slopes(self):
        """Sine wave should produce BEZIER keyframes with slope data."""
        n = 60
        fv = [(i, math.sin(i * 2 * math.pi / n)) for i in range(n)]
        slopes = _compute_slopes(fv)
        result = _sparsify_bezier(fv, slopes)

        # Should have fewer keyframes than original (sparsified)
        assert len(result) < n, f"Expected sparsification, got {len(result)} kf (original {n})"

        # All non-constant/non-linear keyframes should have slopes
        for kf in result:
            if kf.interpolation == Interpolation.BEZIER:
                assert kf.slope_in is not None, "BEZIER keyframe missing slope_in"
                assert kf.slope_out is not None, "BEZIER keyframe missing slope_out"

    def test_sine_wave_reconstruction(self):
        """Hermite reconstruction from sparsified sine should stay within tolerance."""
        n = 60
        fv = [(i, math.sin(i * 2 * math.pi / n)) for i in range(n)]
        slopes = _compute_slopes(fv)
        result = _sparsify_bezier(fv, slopes)

        # Check reconstruction at all original sample points
        tolerance = 1e-4
        for f, v in fv:
            # Find which segment this frame falls in
            reconstructed = _reconstruct_at_frame(result, f)
            assert abs(reconstructed - v) < tolerance, \
                f"At frame {f}: original {v:.6f}, reconstructed {reconstructed:.6f}, " \
                f"error {abs(reconstructed - v):.6f} > {tolerance}"

    def test_step_function(self):
        """Step function should preserve the jump."""
        fv = [(i, 0.0 if i < 15 else 1.0) for i in range(30)]
        slopes = _compute_slopes(fv)
        result = _sparsify_bezier(fv, slopes)

        # Should have keyframes around the discontinuity
        assert len(result) >= 3, f"Step function should need at least 3 keyframes, got {len(result)}"

        # Check reconstruction at extremes
        tolerance = 1e-4
        for f, v in [(0, 0.0), (10, 0.0), (20, 1.0), (29, 1.0)]:
            reconstructed = _reconstruct_at_frame(result, f)
            assert abs(reconstructed - v) < tolerance, \
                f"At frame {f}: expected {v}, got {reconstructed}"

    def test_slopes_populated(self):
        """All BEZIER keyframes should have both slope_in and slope_out."""
        fv = [(i, math.sin(i * 0.3) * 2) for i in range(40)]
        slopes = _compute_slopes(fv)
        result = _sparsify_bezier(fv, slopes)

        for kf in result:
            if kf.interpolation == Interpolation.BEZIER:
                assert kf.slope_in is not None
                assert kf.slope_out is not None


class TestSparsifyBezierVsLinear:
    """Compare bezier and linear sparsification outputs."""

    def test_bezier_fewer_keyframes_for_curves(self):
        """Bezier should need fewer keyframes than linear for smooth curves."""
        n = 60
        fv = [(i, math.sin(i * 2 * math.pi / n)) for i in range(n)]
        slopes = _compute_slopes(fv)

        bezier_result = _sparsify_bezier(fv, slopes)
        linear_result = _sparsify(fv)

        # Bezier with slopes should compress better than piecewise linear
        assert len(bezier_result) <= len(linear_result), \
            f"Bezier ({len(bezier_result)} kf) should be <= linear ({len(linear_result)} kf)"


# ---------------------------------------------------------------------------
# Helper for reconstruction testing
# ---------------------------------------------------------------------------

def _reconstruct_at_frame(keyframes, frame):
    """Reconstruct the value at a given frame from a list of IRKeyframes.

    Uses linear or hermite interpolation based on the keyframe type.
    """
    if not keyframes:
        return 0.0

    # Before first keyframe
    if frame <= keyframes[0].frame:
        return keyframes[0].value

    # After last keyframe
    if frame >= keyframes[-1].frame:
        return keyframes[-1].value

    # Find the segment
    for i in range(len(keyframes) - 1):
        kf0 = keyframes[i]
        kf1 = keyframes[i + 1]
        if kf0.frame <= frame <= kf1.frame:
            dt = kf1.frame - kf0.frame
            if dt <= 0:
                return kf0.value

            t_frac = (frame - kf0.frame) / dt

            if kf0.interpolation == Interpolation.CONSTANT:
                return kf0.value
            elif kf0.interpolation == Interpolation.LINEAR:
                return kf0.value + t_frac * (kf1.value - kf0.value)
            elif kf0.interpolation == Interpolation.BEZIER:
                s0 = kf0.slope_out if kf0.slope_out is not None else 0.0
                s1 = kf1.slope_in if kf1.slope_in is not None else 0.0
                return _hermite_eval(kf0.value, s0, kf1.value, s1, dt, t_frac)

    return keyframes[-1].value
