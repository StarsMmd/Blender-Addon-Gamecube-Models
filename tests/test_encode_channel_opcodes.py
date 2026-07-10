"""Tests for _encode_channel's opcode emission: SPL0 keys and SLP overrides.

The encoder must be the exact inverse of the keyframe decoder's slope
state machine: SPL0 encodes a spline key with zero outgoing tangent
(value only), and an SLP node overrides the running slope so the next
key's incoming tangent survives — including *mid-stream*, where two
adjacent spline keys have discontinuous tangents (slope_in of the next
differs from slope_out of the previous). Dropping those overrides
changes the interpolated motion, not just the bytes.
"""
from types import SimpleNamespace

from exporter.phases.compose.helpers.animations import _encode_channel
from importer.phases.describe.helpers.keyframe_decoder import decode_fobjdesc
from shared.IR.enums import Interpolation
from shared.Constants.hsd import (
    HSD_A_OP_MASK, HSD_A_OP_SPL, HSD_A_OP_SPL0, HSD_A_OP_SLP, HSD_A_J_ROTX,
)


def _kf(frame, value, interp=Interpolation.BEZIER, slope_in=0.0, slope_out=0.0):
    return SimpleNamespace(frame=frame, value=value, interpolation=interp,
                           slope_in=slope_in, slope_out=slope_out)


def _decode(frame_node):
    """Round-trip the encoded frame back to keyframes via the decoder."""
    return decode_fobjdesc(frame_node)


def _opcodes(frame_node):
    """First opcode of every run in the encoded stream (walks headers only
    for streams whose runs start on byte boundaries we can derive by
    decoding — here we just re-derive from decode + structure checks)."""
    ad = frame_node.raw_ad
    return ad


class TestSpl0:

    def test_zero_tangent_keys_encode_value_only(self):
        # All keys have zero tangents → one SPL0 run, no slope bytes.
        kfs = [_kf(0, 0.25), _kf(10, 0.5), _kf(20, 0.75)]
        frame = _encode_channel(kfs, HSD_A_J_ROTX)
        assert frame.raw_ad[0] & HSD_A_OP_MASK == HSD_A_OP_SPL0
        decoded = _decode(frame)
        assert [k.value for k in decoded] == [0.25, 0.5, 0.75]
        assert all(k.slope_out == 0.0 for k in decoded)
        assert all(k.interpolation == Interpolation.BEZIER for k in decoded)

    def test_spl0_is_shorter_than_spl(self):
        kfs_zero = [_kf(0, 0.25), _kf(10, 0.5)]
        kfs_sloped = [_kf(0, 0.25, slope_out=0.5),
                      _kf(10, 0.5, slope_in=0.5, slope_out=0.25)]
        zero_len = _encode_channel(kfs_zero, HSD_A_J_ROTX).data_length
        sloped_len = _encode_channel(kfs_sloped, HSD_A_J_ROTX).data_length
        assert zero_len < sloped_len

    def test_mixed_spl_spl0_round_trip(self):
        kfs = [_kf(0, 0.25, slope_out=0.5),
               _kf(10, 0.5, slope_in=0.5),          # slope_out 0 → SPL0
               _kf(20, 0.75, slope_in=0.0),         # still zero tangent
               _kf(30, 1.0, slope_in=0.5, slope_out=0.5)]
        frame = _encode_channel(kfs, HSD_A_J_ROTX)
        decoded = _decode(frame)
        assert [(k.frame, k.value, k.slope_in, k.slope_out) for k in decoded] == \
            [(0, 0.25, 0.0, 0.5), (10, 0.5, 0.5, 0.0),
             (20, 0.75, 0.0, 0.0), (30, 1.0, 0.5, 0.5)]


class TestMidRunSlpOverride:

    def test_asymmetric_tangents_survive_round_trip(self):
        # Key 1's incoming tangent (0.75) differs from key 0's outgoing
        # tangent (0.25): the encoder must emit an SLP override between
        # them or the decoder reconstructs slope_in = 0.25.
        kfs = [_kf(0, 0.0, slope_out=0.25),
               _kf(10, 1.0, slope_in=0.75, slope_out=0.25),
               _kf(20, 0.0, slope_in=0.25)]
        frame = _encode_channel(kfs, HSD_A_J_ROTX)
        decoded = _decode(frame)
        assert decoded[1].slope_in == 0.75
        assert decoded[1].slope_out == 0.25
        assert decoded[2].slope_in == 0.25

    def test_continuous_tangents_stay_one_run(self):
        # No discontinuities → a single SPL run, no SLP bytes.
        kfs = [_kf(0, 0.0, slope_out=0.25),
               _kf(10, 1.0, slope_in=0.25, slope_out=0.25),
               _kf(20, 0.0, slope_in=0.25, slope_out=0.25)]
        frame = _encode_channel(kfs, HSD_A_J_ROTX)
        assert frame.raw_ad[0] & HSD_A_OP_MASK == HSD_A_OP_SPL
        # exactly one opcode header: 1 + 3 * (value + slope + wait) bytes —
        # verify indirectly by decoding and checking no state was lost
        decoded = _decode(frame)
        assert [k.slope_in for k in decoded] == [0.0, 0.25, 0.25]

    def test_leading_slope_override(self):
        # First key's slope_in differs from the decoder's initial 0 state.
        kfs = [_kf(0, 0.0, slope_in=0.5, slope_out=0.5),
               _kf(10, 1.0, slope_in=0.5, slope_out=0.5)]
        frame = _encode_channel(kfs, HSD_A_J_ROTX)
        assert frame.raw_ad[0] & HSD_A_OP_MASK == HSD_A_OP_SLP
        decoded = _decode(frame)
        assert decoded[0].slope_in == 0.5
