"""Round-trip test: build a synthetic Frame binary, parse it, verify fields."""
import io
import struct
import pytest

from helpers import build_minimal_dat, build_frame
from importer.phases.parse.helpers.dat_parser import DATParser
from shared.Nodes.Classes.Animation.Frame import Frame


def _parse_frame(**frame_kwargs):
    """Build a minimal DAT containing a single Frame, parse and return it."""
    dat_bytes = build_minimal_dat(build_frame(**frame_kwargs))
    parser = DATParser(io.BytesIO(dat_bytes), {})
    frame = Frame(0, None)
    frame.loadFromBinary(parser)
    parser.close()
    return frame


class TestFrameRoundtrip:

    def test_parse_empty_frame(self):
        """A Frame with all-zero fields should parse without error."""
        frame = _parse_frame()
        assert frame.next is None
        assert frame.data_length == 0
        assert frame.start_frame == 0.0
        assert frame.type == 0
        assert frame.frac_value == 0
        assert frame.frac_slope == 0
        assert frame.ad == 0

    def test_parse_frame_fields(self):
        """Fields should reflect the values encoded in the binary."""
        frame = _parse_frame(
            data_length=10,
            start_frame=2.5,
            ftype=1,
            frac_value=0x20,
            frac_slope=0x60,
            ad_ptr=0,
        )
        assert frame.data_length == 10
        assert abs(frame.start_frame - 2.5) < 1e-6
        assert frame.type == 1
        assert frame.frac_value == 0x20
        assert frame.frac_slope == 0x60
        assert frame.ad == 0
