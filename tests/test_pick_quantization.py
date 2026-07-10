"""Tests for _pick_quantization — exact-first, tolerance-fallback selection.

The exact pass recovers the original compiler's format choice on
round-tripped data (decoded streams sit on their source quantization grid);
the tolerance pass preserves the previous compact behavior for fresh
Blender-authored values. Corpus measurements behind the rule live in
implementation_notes § animation quantization selection.
"""
from exporter.phases.compose.helpers.animations import _pick_quantization
from shared.Constants.hsd import (
    HSD_A_FRAC_FLOAT, HSD_A_FRAC_S16, HSD_A_FRAC_U16,
    HSD_A_FRAC_S8, HSD_A_FRAC_U8,
)


class TestExactPass:

    def test_u8_grid_recovered(self):
        # Values on the U8.7 grid (k/128), max 1.0 → int_bits 1 → frac 7.
        vals = [0.5, 1.0, 127 / 128]
        assert _pick_quantization(vals) == (HSD_A_FRAC_U8 | 7, 'uchar')

    def test_s16_grid_recovered(self):
        # Values on the S16.13 grid (k/8192) with a negative, max 1.25 →
        # int_bits 2 → frac 13.
        vals = [-0.5, 1.25, 1 / 8192]
        assert _pick_quantization(vals) == (HSD_A_FRAC_S16 | 13, 'short')

    def test_u16_grid_recovered(self):
        # Values on the U16.15 grid that don't fit 8 bits exactly.
        vals = [12345 / 32768, 0.5]
        assert _pick_quantization(vals) == (HSD_A_FRAC_U16 | 15, 'ushort')

    def test_all_zero_picks_u8(self):
        assert _pick_quantization([0.0, 0.0]) == (HSD_A_FRAC_U8 | 8, 'uchar')

    def test_smallest_type_wins_ties(self):
        # 0.5 is exact in every type; U8 (smallest, unsigned) must win.
        # max_abs 0.5 → int_bits = ceil(log2(1.5)) = 1 → frac 7.
        assert _pick_quantization([0.5]) == (HSD_A_FRAC_U8 | 7, 'uchar')

    def test_negative_skips_unsigned(self):
        got, pack = _pick_quantization([-0.5, 0.25])
        assert pack in ('char', 'short')
        assert got & 0xE0 in (HSD_A_FRAC_S8, HSD_A_FRAC_S16)

    def test_round_trip_stability(self):
        """Quantize → dequantize → re-pick must return the same format
        (the property NIN relies on)."""
        vals = [0.123, -0.456, 0.789]
        frac_byte, _pack = _pick_quantization(vals)
        frac = frac_byte & 0x1F
        scale = 1 << frac
        decoded = [round(v * scale) / scale for v in vals]
        assert _pick_quantization(decoded)[0] == frac_byte


class TestTolerancePass:

    def test_smooth_values_keep_previous_behavior(self):
        # Not on any grid — falls through to the tolerance pass, which picks
        # the compact U8.7 form exactly as before the exact pass existed
        # (max_abs 0.3 → int_bits 1; worst error 0.0016 < 0.004).
        vals = [0.1, 0.2, 0.3]
        assert _pick_quantization(vals) == (HSD_A_FRAC_U8 | 7, 'uchar')

    def test_empty_is_float(self):
        assert _pick_quantization([]) == (HSD_A_FRAC_FLOAT, 'float')

    def test_out_of_tolerance_everywhere_is_float(self):
        # Huge magnitude spread: frac goes negative for int types.
        vals = [3.0e9]
        assert _pick_quantization(vals) == (HSD_A_FRAC_FLOAT, 'float')
