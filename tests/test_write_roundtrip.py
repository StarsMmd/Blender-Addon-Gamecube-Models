"""Round-trip write tests.

Two kinds of round-trip:

1. **Node tree → binary → node tree** (TestNodeRoundtrip)
   Build synthetic node trees, serialize via DATBuilder, re-parse, compare fields.
   Validates data integrity through the binary format.

2. **Binary → node tree → binary** (TestBinaryRoundtrip)
   Parse a DAT binary, write it back, compare output against input using a
   fuzzy matching algorithm that measures the percentage of shared content
   regardless of exact byte positions.
"""
import io
import struct
import pytest

from helpers import (
    build_joint,
    build_dat_with_sections,
    JOINT_SIZE,
)
from shared.helpers.file_io import BinaryReader, BinaryWriter
from importer.phases.parse.helpers.dat_parser import DATParser
from exporter.phases.serialize.helpers.dat_builder import DATBuilder
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
# Fuzzy binary comparison
# ---------------------------------------------------------------------------

def compute_binary_match(data_a, data_b, word_size=4):
    """Compare two binaries by finding matching runs of aligned words.

    Splits both binaries into word_size-byte chunks, builds a set of all
    (word_value, occurrence_index) pairs in the input, then scans the output
    for matching words. Matching is by value, not position — this tolerates
    the builder reordering or shifting content to different offsets.

    To handle duplicate words fairly (e.g. many zero words), each unique word
    value is counted: the number of matches for a given value is the minimum
    of its count in input and output.

    Args:
        data_a: Input bytes.
        data_b: Output bytes.
        word_size: Chunk size in bytes (default 4, matching the format's alignment).

    Returns:
        (matched_words, total_words_a, total_words_b, match_pct) where
        match_pct = matched_words / max(total_words_a, total_words_b) * 100.
    """
    from collections import Counter

    def to_words(data):
        count = len(data) // word_size
        return [data[i * word_size:(i + 1) * word_size] for i in range(count)]

    words_a = to_words(data_a)
    words_b = to_words(data_b)

    counts_a = Counter(words_a)
    counts_b = Counter(words_b)

    matched = 0
    for word, count_a in counts_a.items():
        matched += min(count_a, counts_b.get(word, 0))

    total = max(len(words_a), len(words_b))
    pct = (matched / total * 100) if total > 0 else 100.0

    return matched, len(words_a), len(words_b), pct


# ---------------------------------------------------------------------------
# NIN comparison — counts all fields in the original tree
# ---------------------------------------------------------------------------

def compute_nin_score(original_node, composed_node):
    """Compare two node trees for NIN scoring.

    Walks the ORIGINAL tree to count every field (the denominator), and
    counts mismatches against the composed tree. When the composed side
    is missing a subtree, ALL fields in that original subtree count as
    mismatches — not just the single pointer field.

    Args:
        original_node: Root node from the parsed node tree.
        composed_node: Root node from the compose phase.

    Returns:
        (matched, total, pct) — matched fields, total fields, percentage.
    """
    from shared.Nodes.Node import Node

    total = [0]
    mismatches = [0]

    def _walk(orig, comp, visited):
        if orig is None:
            return
        if id(orig) in visited:
            return
        visited.add(id(orig))

        if not hasattr(orig, 'fields'):
            return

        for field_name, _ in orig.fields:
            if field_name == 'address':
                continue

            val_orig = getattr(orig, field_name, None)
            val_comp = getattr(comp, field_name, None) if comp is not None else None

            if isinstance(val_orig, Node):
                # Count this pointer field
                total[0] += 1
                comp_child = val_comp if isinstance(val_comp, Node) else None
                if comp_child is None and val_orig is not None:
                    mismatches[0] += 1
                # Recurse into the subtree (always walks original)
                _walk(val_orig, comp_child, visited)

            elif isinstance(val_orig, (list, tuple)):
                comp_list = val_comp if isinstance(val_comp, (list, tuple)) else []
                # Count the length field
                total[0] += 1
                if len(val_orig) != len(comp_list):
                    mismatches[0] += 1

                for i, item in enumerate(val_orig):
                    comp_item = comp_list[i] if i < len(comp_list) else None
                    if isinstance(item, Node):
                        total[0] += 1
                        comp_node = comp_item if isinstance(comp_item, Node) else None
                        if comp_node is None:
                            mismatches[0] += 1
                        _walk(item, comp_node, visited)
                    else:
                        total[0] += 1
                        if isinstance(item, float) and isinstance(comp_item, float):
                            if abs(item - comp_item) > 1e-5:
                                mismatches[0] += 1
                        elif item != comp_item:
                            mismatches[0] += 1
            else:
                total[0] += 1
                if isinstance(val_orig, float) and isinstance(val_comp, float):
                    if abs(val_orig - val_comp) > 1e-5:
                        mismatches[0] += 1
                elif val_orig != val_comp:
                    mismatches[0] += 1

    _walk(original_node, composed_node, set())

    matched = total[0] - mismatches[0]
    pct = (matched / total[0] * 100) if total[0] > 0 else 100.0
    return matched, total[0], pct


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_sections(dat_bytes, section_map=None):
    """Parse a DAT binary and return the sections list."""
    if section_map is None:
        section_map = {"test_joint": "Joint"}
    buf = io.BytesIO(dat_bytes)
    parser = DATParser(buf, {"section_map": section_map})
    parser.parseSections()
    sections = parser.sections
    parser.close()
    return sections


def _rebuild(sections):
    """Write parsed sections back to DAT bytes via DATBuilder."""
    root_nodes = [s.root_node for s in sections]
    section_names = [s.section_name for s in sections]
    out_buf = io.BytesIO()
    builder = DATBuilder(out_buf, root_nodes, section_names)
    builder.build()
    return out_buf.getvalue()


def _is_absent(val):
    """Check if a node pointer is absent (None, 0, or non-Node int)."""
    if val is None:
        return True
    if isinstance(val, int) and val == 0:
        return True
    return not isinstance(val, Joint)


def _compare_joints(joint_a, joint_b, path="root", mismatches=None):
    """Recursively compare Joint fields. Returns list of mismatch descriptions."""
    if mismatches is None:
        mismatches = []

    if _is_absent(joint_a) and _is_absent(joint_b):
        return mismatches
    if _is_absent(joint_a) or _is_absent(joint_b):
        mismatches.append(f"{path}: one is absent")
        return mismatches

    # Compare flags
    if joint_a.flags != joint_b.flags:
        mismatches.append(f"{path}.flags: {joint_a.flags} vs {joint_b.flags}")

    # Compare vec3 fields
    for attr in ('rotation', 'scale', 'position'):
        va = getattr(joint_a, attr)
        vb = getattr(joint_b, attr)
        for i in range(3):
            if abs(va[i] - vb[i]) > 1e-5:
                mismatches.append(f"{path}.{attr}[{i}]: {va[i]} vs {vb[i]}")

    # Recurse into child/next
    _compare_joints(joint_a.child, joint_b.child, f"{path}.child", mismatches)
    _compare_joints(joint_a.next, joint_b.next, f"{path}.next", mismatches)

    return mismatches


# ---------------------------------------------------------------------------
# Node tree → binary → node tree (field comparison)
# ---------------------------------------------------------------------------

class TestNodeRoundtrip:
    """Parse synthetic nodes, write them back via DATBuilder, re-parse, compare fields."""

    def _roundtrip_joint(self, dat_bytes, section_map=None):
        """Parse → write → reparse both, return (fresh_original, reparsed).

        DATBuilder mutates nodes during build, so we reparse the original
        bytes fresh for a clean comparison.
        """
        sections = _parse_sections(dat_bytes, section_map)
        rebuilt = _rebuild(sections)
        # Reparse both from clean bytes
        fresh_original = _parse_sections(dat_bytes, section_map)[0].root_node
        reparsed = _parse_sections(rebuilt, section_map)[0].root_node
        return fresh_original, reparsed

    def test_single_joint_fields(self):
        """Single Joint field values survive the round-trip."""
        joint_data = build_joint(
            flags=0x05,
            rotation=(0.1, 0.2, 0.3),
            scale=(1.0, 2.0, 3.0),
            position=(10.0, 20.0, 30.0),
        )

        dat_bytes = build_dat_with_sections(
            data_section=joint_data,
            relocations=[],
            sections=[(0, True)],
            section_names=["test_joint"],
        )

        original, reparsed = self._roundtrip_joint(dat_bytes)
        mismatches = _compare_joints(original, reparsed)
        assert mismatches == [], f"Mismatches: {mismatches}"

    def test_joint_with_child(self):
        """Parent→child structure survives the round-trip."""
        parent_data = build_joint(flags=0xAA, child_ptr=JOINT_SIZE)
        child_data = build_joint(flags=0xBB)

        dat_bytes = build_dat_with_sections(
            data_section=parent_data + child_data,
            relocations=[8],
            sections=[(0, True)],
            section_names=["test_joint"],
        )

        original, reparsed = self._roundtrip_joint(dat_bytes)
        mismatches = _compare_joints(original, reparsed)
        assert mismatches == [], f"Mismatches: {mismatches}"

    def test_joint_with_sibling(self):
        """Sibling linkage via next pointer survives the round-trip."""
        first_data = build_joint(flags=0x11, next_ptr=JOINT_SIZE)
        second_data = build_joint(flags=0x22)

        dat_bytes = build_dat_with_sections(
            data_section=first_data + second_data,
            relocations=[12],
            sections=[(0, True)],
            section_names=["test_joint"],
        )

        original, reparsed = self._roundtrip_joint(dat_bytes)
        mismatches = _compare_joints(original, reparsed)
        assert mismatches == [], f"Mismatches: {mismatches}"

    def test_three_deep_chain(self):
        """Root→child→grandchild chain survives the round-trip."""
        root_data = build_joint(flags=0x01, child_ptr=JOINT_SIZE)
        child_data = build_joint(flags=0x02, child_ptr=JOINT_SIZE * 2)
        grandchild_data = build_joint(flags=0x03)

        dat_bytes = build_dat_with_sections(
            data_section=root_data + child_data + grandchild_data,
            relocations=[8, JOINT_SIZE + 8],
            sections=[(0, True)],
            section_names=["test_joint"],
        )

        original, reparsed = self._roundtrip_joint(dat_bytes)
        mismatches = _compare_joints(original, reparsed)
        assert mismatches == [], f"Mismatches: {mismatches}"

    def test_all_transforms(self):
        """Non-trivial rotation, scale, position values survive the round-trip."""
        joint_data = build_joint(
            flags=0xFF,
            rotation=(1.5707963, -0.7853982, 3.1415927),
            scale=(0.5, 2.0, 0.189),
            position=(-100.0, 50.25, 0.001),
        )

        dat_bytes = build_dat_with_sections(
            data_section=joint_data,
            relocations=[],
            sections=[(0, True)],
            section_names=["test_joint"],
        )

        original, reparsed = self._roundtrip_joint(dat_bytes)
        mismatches = _compare_joints(original, reparsed)
        assert mismatches == [], f"Mismatches: {mismatches}"


# ---------------------------------------------------------------------------
# Binary → node tree → binary (fuzzy byte comparison)
# ---------------------------------------------------------------------------

class TestBinaryRoundtrip:
    """Parse a DAT, write it back, compare bytes with fuzzy matching.

    The builder may produce a different layout (alignment, ordering) than
    the original. These tests verify that the content is preserved by
    measuring the percentage of matching 4-byte words between input and
    output, regardless of position.
    """

    def _roundtrip_match(self, dat_bytes, section_map=None, skip_header=True):
        """Parse and rebuild, return (result_bytes, match_pct).

        When skip_header is True, the 32-byte DAT header is excluded from
        the comparison since the file_size field will always differ.
        """
        sections = _parse_sections(dat_bytes, section_map)
        result = _rebuild(sections)

        offset = 32 if skip_header else 0
        a = dat_bytes[offset:]
        b = result[offset:]
        _, _, _, pct = compute_binary_match(a, b)
        return result, pct

    def test_single_joint_high_match(self):
        """A single Joint should produce a high match percentage."""
        joint_data = build_joint(
            flags=0x05,
            rotation=(0.1, 0.2, 0.3),
            scale=(1.0, 2.0, 3.0),
            position=(10.0, 20.0, 30.0),
        )

        dat_bytes = build_dat_with_sections(
            data_section=joint_data,
            relocations=[],
            sections=[(0, True)],
            section_names=["test_joint"],
        )

        _, pct = self._roundtrip_match(dat_bytes)
        assert pct >= 80, f"Match too low: {pct:.1f}%"

    def test_joint_with_child_high_match(self):
        """Parent→child structure should produce a high match percentage."""
        parent_data = build_joint(flags=0xAA, child_ptr=JOINT_SIZE)
        child_data = build_joint(flags=0xBB)

        dat_bytes = build_dat_with_sections(
            data_section=parent_data + child_data,
            relocations=[8],
            sections=[(0, True)],
            section_names=["test_joint"],
        )

        _, pct = self._roundtrip_match(dat_bytes)
        assert pct >= 70, f"Match too low: {pct:.1f}%"

    def test_complex_tree_high_match(self):
        """Parent with children and siblings should maintain reasonable match."""
        root_data = build_joint(flags=0x01, child_ptr=JOINT_SIZE)
        child_a_data = build_joint(flags=0x02, next_ptr=JOINT_SIZE * 2)
        child_b_data = build_joint(flags=0x03)

        dat_bytes = build_dat_with_sections(
            data_section=root_data + child_a_data + child_b_data,
            relocations=[8, JOINT_SIZE + 12],
            sections=[(0, True)],
            section_names=["test_joint"],
        )

        _, pct = self._roundtrip_match(dat_bytes)
        assert pct >= 60, f"Match too low: {pct:.1f}%"

    def test_match_percentage_utility(self):
        """Verify the fuzzy match utility itself."""
        # Identical data = 100%
        data = b'\x00\x00\x00\x01' * 10
        _, _, _, pct = compute_binary_match(data, data)
        assert pct == 100.0

        # Completely different (non-zero) data
        a = b'\x00\x00\x00\x01' * 10
        b = b'\x00\x00\x00\x02' * 10
        _, _, _, pct = compute_binary_match(a, b)
        assert pct == 0.0

        # Half matching
        a = b'\x00\x00\x00\x01' * 5 + b'\x00\x00\x00\x02' * 5
        b = b'\x00\x00\x00\x01' * 5 + b'\x00\x00\x00\x03' * 5
        _, _, _, pct = compute_binary_match(a, b)
        assert pct == 50.0


# ---------------------------------------------------------------------------
# Real-file round-trip (opt-in, requires --dat-file)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# DAT header and alignment tests
# ---------------------------------------------------------------------------

class TestDATHeaderAndAlignment:
    """Verify DAT header fields and file alignment."""

    def test_file_size_includes_header(self):
        """file_size field in DAT header includes the 0x20 header bytes."""
        joint_data = build_joint(flags=1, scale=(1, 1, 1))
        dat_bytes = build_dat_with_sections(
            joint_data, relocations=[], sections=[(0, True)],
            section_names=["test_joint"])

        sections = _parse_sections(dat_bytes)
        result = _rebuild(sections)

        file_size = struct.unpack('>I', result[0:4])[0]
        assert file_size > 32, "file_size should be larger than the 0x20 header"
        # file_size should include the 0x20 header
        assert file_size <= len(result), "file_size should not exceed total bytes"
        # The content should end at file_size (rest is padding)
        assert result[file_size - 1:file_size] == b'\x00', \
            "last byte of content (at file_size-1) should be null terminator"

    def test_file_size_ends_at_string_null_terminator(self):
        """file_size points to the byte after the last section name's null terminator."""
        joint_data = build_joint(flags=1, scale=(1, 1, 1))
        dat_bytes = build_dat_with_sections(
            joint_data, relocations=[], sections=[(0, True)],
            section_names=["scene_data"])

        sections = _parse_sections(dat_bytes, section_map={"scene_data": "Joint"})
        result = _rebuild(sections)

        file_size = struct.unpack('>I', result[0:4])[0]
        # The content before the null terminator should be the section name
        name_end = file_size - 1  # the null terminator
        assert result[name_end] == 0, "should end with null terminator"
        # Walk backward to find the start of the name
        name_start = name_end - 1
        while name_start > 0 and result[name_start] != 0:
            name_start -= 1
        name_start += 1  # skip past the previous null or section info
        name_bytes = result[name_start:name_end]
        assert name_bytes == b'scene_data', f"expected 'scene_data', got {name_bytes!r}"

    def test_file_size_excludes_padding(self):
        """file_size should not include trailing 0x20-alignment padding."""
        joint_data = build_joint(flags=1, scale=(1, 1, 1))
        dat_bytes = build_dat_with_sections(
            joint_data, relocations=[], sections=[(0, True)],
            section_names=["test_joint"])

        sections = _parse_sections(dat_bytes)
        result = _rebuild(sections)

        file_size = struct.unpack('>I', result[0:4])[0]
        # If the file was padded, file_size should be less than total length
        # (unless content happens to be exactly aligned)
        if len(result) != file_size:
            # Padding bytes should all be zero
            padding = result[file_size:]
            assert all(b == 0 for b in padding), "padding bytes should be zero"

    def test_serialize_output_0x20_aligned(self):
        """serialize() output should be padded to 0x20 (32-byte) alignment."""
        from exporter.phases.serialize.serialize import serialize
        from shared.Nodes.Classes.Joints.Joint import Joint as JointNode
        from shared.Nodes.Classes.Joints.ModelSet import ModelSet
        from shared.Nodes.Classes.RootNodes.SceneData import SceneData

        # Build a minimal scene
        joint = JointNode(address=None, blender_obj=None)
        joint.name = None
        joint.flags = 1
        joint.child = None
        joint.next = None
        joint.property = None
        joint.rotation = [0, 0, 0]
        joint.scale = [1, 1, 1]
        joint.position = [0, 0, 0]
        joint.inverse_bind = None
        joint.reference = None

        model_set = ModelSet(address=None, blender_obj=None)
        model_set.root_joint = joint
        model_set.animated_joints = None
        model_set.animated_material_joints = None
        model_set.animated_shape_joints = None

        scene_data = SceneData(address=None, blender_obj=None)
        scene_data.models = [model_set]
        scene_data.camera = None
        scene_data.lights = None
        scene_data.fog = None

        result = serialize([scene_data], ['scene_data'])
        assert len(result) % 0x20 == 0, \
            f"serialize output should be 0x20 aligned, got {len(result)} bytes ({len(result) % 0x20} remainder)"

    def test_data_size_excludes_header(self):
        """data_size field should not include the 0x20 header."""
        joint_data = build_joint(flags=1, scale=(1, 1, 1))
        dat_bytes = build_dat_with_sections(
            joint_data, relocations=[], sections=[(0, True)],
            section_names=["test_joint"])

        sections = _parse_sections(dat_bytes)
        result = _rebuild(sections)

        data_size = struct.unpack('>I', result[4:8])[0]
        file_size = struct.unpack('>I', result[0:4])[0]
        assert data_size < file_size, "data_size should be less than file_size"
        assert data_size < file_size - 32, \
            "data_size should be significantly less than file_size (excludes header + relocs + sections)"


class TestRealFileRoundtrip:
    """Round-trip a real .dat/.pkx file. Opt-in via --dat-file flag."""

    def test_real_file_node_roundtrip(self, dat_file):
        """Parse a real file, write it back, reparse, compare node fields."""
        from importer.phases.extract.extract import extract_dat
        from shared.Nodes.Node import Node

        def compare_nodes(node_a, node_b, path="root", mismatches=None):
            if mismatches is None:
                mismatches = []
            if type(node_a) != type(node_b):
                mismatches.append(f"{path}: type mismatch {type(node_a).__name__} vs {type(node_b).__name__}")
                return mismatches
            if not hasattr(node_a, 'fields'):
                return mismatches
            for field_name, _ in node_a.fields:
                val_a = getattr(node_a, field_name, None)
                val_b = getattr(node_b, field_name, None)
                field_path = f"{path}.{field_name}"
                if isinstance(val_a, Node) and isinstance(val_b, Node):
                    compare_nodes(val_a, val_b, field_path, mismatches)
                elif isinstance(val_a, (list, tuple)) and isinstance(val_b, (list, tuple)):
                    if len(val_a) != len(val_b):
                        mismatches.append(f"{field_path}: list length {len(val_a)} vs {len(val_b)}")
                    else:
                        for i, (a, b) in enumerate(zip(val_a, val_b)):
                            if isinstance(a, Node) and isinstance(b, Node):
                                compare_nodes(a, b, f"{field_path}[{i}]", mismatches)
                            elif isinstance(a, float) and isinstance(b, float):
                                if abs(a - b) > 1e-5:
                                    mismatches.append(f"{field_path}[{i}]: {a} vs {b}")
                            elif a != b:
                                mismatches.append(f"{field_path}[{i}]: {a!r} vs {b!r}")
                elif isinstance(val_a, float) and isinstance(val_b, float):
                    if abs(val_a - val_b) > 1e-5:
                        mismatches.append(f"{field_path}: {val_a} vs {val_b}")
                elif val_a != val_b and field_name != 'address':
                    mismatches.append(f"{field_path}: {val_a!r} vs {val_b!r}")
            return mismatches

        with open(dat_file, 'rb') as f:
            raw_bytes = f.read()

        filename = dat_file.rsplit('/', 1)[-1] if '/' in dat_file else dat_file
        entries = extract_dat(raw_bytes, filename)
        dat_bytes = entries[0][0]

        sections = _parse_sections(dat_bytes, section_map=None)
        result = _rebuild(sections)
        re_sections = _parse_sections(result, section_map=None)

        all_mismatches = []
        for orig, rewritten in zip(sections, re_sections):
            mismatches = compare_nodes(orig.root_node, rewritten.root_node,
                                       path=orig.section_name)
            all_mismatches.extend(mismatches)

        assert all_mismatches == [], (
            f"{len(all_mismatches)} field mismatch(es):\n" +
            "\n".join(all_mismatches[:20])
        )

    def test_real_file_binary_match(self, dat_file):
        """Parse a real file, write it back, report match percentage."""
        from importer.phases.extract.extract import extract_dat

        with open(dat_file, 'rb') as f:
            raw_bytes = f.read()

        filename = dat_file.rsplit('/', 1)[-1] if '/' in dat_file else dat_file
        entries = extract_dat(raw_bytes, filename)
        dat_bytes = entries[0][0]

        sections = _parse_sections(dat_bytes, section_map=None)
        result = _rebuild(sections)

        matched, total_a, total_b, pct = compute_binary_match(
            dat_bytes[32:], result[32:]
        )
        print(f"\n  {filename}: {pct:.1f}% match "
              f"({matched} words, input={total_a}, output={total_b})")

        # Real files should have very high match since DATBuilder is proven
        assert pct >= 95, f"Match too low for real file: {pct:.1f}%"
