"""Round-trip test: build a synthetic Frame binary, parse it, verify fields."""
import struct
import tempfile
import os
import pytest

from helpers import build_minimal_dat, build_frame
from importer.phases.parse.helpers.dat_parser import DATParser
from shared.Nodes.Classes.Animation.Frame import Frame


def _make_dat_with_frame(**frame_kwargs) -> str:
    """Write a minimal DAT file containing a single Frame struct and return its path."""
    data_section = build_frame(**frame_kwargs)
    dat_bytes = build_minimal_dat(data_section)
    f = tempfile.NamedTemporaryFile(delete=False, suffix='.dat')
    f.write(dat_bytes)
    f.close()
    return f.name


class TestFrameRoundtrip:

    def test_parse_empty_frame(self):
        """A Frame with all-zero fields should parse without error."""
        path = _make_dat_with_frame()
        try:
            import io; parser = DATParser(io.BytesIO(open(path, "rb").read()), {})
            frame = Frame(0, None)
            frame.loadFromBinary(parser)
            parser.close()

            assert frame.next is None          # null pointer
            assert frame.data_length == 0
            assert frame.start_frame == 0.0
            assert frame.type == 0
            assert frame.frac_value == 0
            assert frame.frac_slope == 0
            assert frame.ad == 0               # not overwritten (length == 0)
        finally:
            os.unlink(path)

    def test_parse_frame_fields(self):
        """Fields should reflect the values encoded in the binary."""
        path = _make_dat_with_frame(
            data_length=10,
            start_frame=2.5,
            ftype=1,          # HSD_A_OP_CON
            frac_value=0x20,  # HSD_A_FRAC_S16 (1 << 5)
            frac_slope=0x60,  # HSD_A_FRAC_S8  (3 << 5)
            ad_ptr=0,         # null → no chunk read
        )
        try:
            import io; parser = DATParser(io.BytesIO(open(path, "rb").read()), {})
            frame = Frame(0, None)
            frame.loadFromBinary(parser)
            parser.close()

            assert frame.data_length == 10
            assert abs(frame.start_frame - 2.5) < 1e-6
            assert frame.type == 1
            assert frame.frac_value == 0x20
            assert frame.frac_slope == 0x60
            assert frame.ad == 0  # null ad_ptr → not overwritten
        finally:
            os.unlink(path)
