"""Round-trip write tests: build synthetic binaries, parse them, write them back, and compare."""
import io
import struct
import pytest

from helpers import (
    build_archive_header,
    build_joint,
    build_mesh,
    build_pobject,
    build_vertex_list_terminator,
    build_dat_with_sections,
    build_relocation_table,
    build_section_info,
    JOINT_SIZE,
    MESH_SIZE,
    POBJECT_SIZE,
    VERTEX_SIZE,
)
from shared.IO.file_io import BinaryReader, BinaryWriter
from shared.IO.DAT_io import DATParser, DATBuilder
from shared.Nodes.Classes.Joints.Joint import Joint


# ---------------------------------------------------------------------------
# BinaryReader / BinaryWriter — BytesIO round-trip for primitives
# ---------------------------------------------------------------------------

class TestBinaryIOBytesIO:
    """Verify that BinaryReader and BinaryWriter work with io.BytesIO."""

    def test_write_and_read_uint(self):
        buf = io.BytesIO()
        writer = BinaryWriter(buf)
        writer.write('uint', 0xDEADBEEF)

        buf.seek(0)
        reader = BinaryReader(buf)
        assert reader.read('uint', 0) == 0xDEADBEEF

    def test_write_and_read_float(self):
        buf = io.BytesIO()
        writer = BinaryWriter(buf)
        writer.write('float', 3.14)

        buf.seek(0)
        reader = BinaryReader(buf)
        assert abs(reader.read('float', 0) - 3.14) < 1e-5

    def test_write_and_read_ushort(self):
        buf = io.BytesIO()
        writer = BinaryWriter(buf)
        writer.write('ushort', 0x1234)

        buf.seek(0)
        reader = BinaryReader(buf)
        assert reader.read('ushort', 0) == 0x1234

    def test_write_and_read_string_null_terminated(self):
        buf = io.BytesIO()
        writer = BinaryWriter(buf)
        writer.write('string', 'hello')

        raw = buf.getvalue()
        # Should be 'hello' + null byte
        assert raw == b'hello\x00'

        buf.seek(0)
        reader = BinaryReader(buf)
        assert reader.read('string', 0) == 'hello'

    def test_write_and_read_vec3(self):
        buf = io.BytesIO()
        writer = BinaryWriter(buf)
        writer.write('vec3', (1.0, 2.0, 3.0))

        buf.seek(0)
        reader = BinaryReader(buf)
        result = reader.read('vec3', 0)
        assert abs(result[0] - 1.0) < 1e-5
        assert abs(result[1] - 2.0) < 1e-5
        assert abs(result[2] - 3.0) < 1e-5

    def test_write_multiple_fields(self):
        buf = io.BytesIO()
        writer = BinaryWriter(buf)
        writer.write('uint', 42)
        writer.write('float', 1.5)
        writer.write('ushort', 7)

        buf.seek(0)
        reader = BinaryReader(buf)
        assert reader.read('uint', 0) == 42
        assert abs(reader.read('float', 4) - 1.5) < 1e-5
        assert reader.read('ushort', 8) == 7

    def test_reader_filesize_from_bytesio(self):
        data = b'\x00' * 100
        buf = io.BytesIO(data)
        reader = BinaryReader(buf)
        assert reader.filesize == 100


# ---------------------------------------------------------------------------
# DATParser with BytesIO — parse synthetic binary from memory
# ---------------------------------------------------------------------------

class TestDATParserBytesIO:
    """Verify DATParser works when given a BytesIO instead of a file path."""

    def test_parse_single_joint_from_bytesio(self):
        """Parse a minimal DAT containing one Joint from a BytesIO stream."""
        joint_data = build_joint(
            flags=0x02,
            rotation=(1.0, 2.0, 3.0),
            scale=(4.0, 5.0, 6.0),
            position=(7.0, 8.0, 9.0),
        )

        # Wrap in a full DAT with header, one relocation-free section pointing at the joint
        dat_bytes = build_dat_with_sections(
            data_section=joint_data,
            relocations=[],
            sections=[(0, True)],
            section_names=["test_joint"],
        )

        buf = io.BytesIO(dat_bytes)
        parser = DATParser(buf, {"section_names": []})

        # Manually parse a Joint at offset 0
        joint = Joint(0, None)
        joint.loadFromBinary(parser)
        parser.close()

        assert joint.flags == 0x02
        assert abs(joint.rotation[0] - 1.0) < 1e-5
        assert abs(joint.scale[1] - 5.0) < 1e-5
        assert abs(joint.position[2] - 9.0) < 1e-5

    def test_parse_joint_with_child_from_bytesio(self):
        """Parse a Joint whose child pointer references a second Joint."""
        child_offset = JOINT_SIZE
        parent_data = build_joint(flags=0xAA, child_ptr=child_offset)
        child_data = build_joint(flags=0xBB)
        data_section = parent_data + child_data

        # Both pointer fields (child) need relocation entries
        # child_ptr is at offset 8 in the Joint struct
        relocations = [8]

        dat_bytes = build_dat_with_sections(
            data_section=data_section,
            relocations=relocations,
            sections=[(0, True)],
            section_names=["test_joint"],
        )

        buf = io.BytesIO(dat_bytes)
        parser = DATParser(buf, {"section_names": []})

        joint = Joint(0, None)
        joint.loadFromBinary(parser)
        parser.close()

        assert joint.flags == 0xAA
        assert isinstance(joint.child, Joint)
        assert joint.child.flags == 0xBB

    def test_parse_joint_with_next_sibling_from_bytesio(self):
        """Parse a Joint linked to a sibling via next pointer."""
        next_offset = JOINT_SIZE
        first_data = build_joint(flags=0x11, next_ptr=next_offset)
        second_data = build_joint(flags=0x22)
        data_section = first_data + second_data

        # next_ptr is at offset 12 in the Joint struct
        relocations = [12]

        dat_bytes = build_dat_with_sections(
            data_section=data_section,
            relocations=relocations,
            sections=[(0, True)],
            section_names=["test_joint"],
        )

        buf = io.BytesIO(dat_bytes)
        parser = DATParser(buf, {"section_names": []})

        joint = Joint(0, None)
        joint.loadFromBinary(parser)
        parser.close()

        assert joint.flags == 0x11
        assert isinstance(joint.next, Joint)
        assert joint.next.flags == 0x22


# ---------------------------------------------------------------------------
# Write round-trip: parse → write → re-parse → compare fields
# ---------------------------------------------------------------------------

class TestWriteRoundtrip:
    """Parse synthetic nodes, write them back via DATBuilder, re-parse, and compare."""

    def _parse_joint_from_bytes(self, dat_bytes):
        """Helper: parse a Joint at offset 0 from the given DAT binary."""
        buf = io.BytesIO(dat_bytes)
        parser = DATParser(buf, {"section_names": []})
        joint = Joint(0, None)
        joint.loadFromBinary(parser)
        parser.close()
        return joint

    def test_roundtrip_single_joint_fields(self):
        """Parse a single Joint, write it back, re-parse, and compare field values."""
        original_data = build_joint(
            flags=0x05,
            rotation=(0.1, 0.2, 0.3),
            scale=(1.0, 2.0, 3.0),
            position=(10.0, 20.0, 30.0),
        )

        dat_bytes = build_dat_with_sections(
            data_section=original_data,
            relocations=[],
            sections=[(0, True)],
            section_names=["test_joint"],
        )

        # Parse the original
        original_joint = self._parse_joint_from_bytes(dat_bytes)

        # Write it back using DATBuilder
        out_buf = io.BytesIO()
        builder = DATBuilder(out_buf, [original_joint])
        builder.build()

        # Re-parse from the written output
        written_bytes = out_buf.getvalue()
        re_buf = io.BytesIO(written_bytes)
        re_parser = DATParser(re_buf, {"section_names": []})
        re_joint = Joint(original_joint.address, None)
        re_joint.loadFromBinary(re_parser)
        re_parser.close()

        # Compare field values
        assert re_joint.flags == original_joint.flags
        for i in range(3):
            assert abs(re_joint.rotation[i] - original_joint.rotation[i]) < 1e-5
            assert abs(re_joint.scale[i] - original_joint.scale[i]) < 1e-5
            assert abs(re_joint.position[i] - original_joint.position[i]) < 1e-5
