"""Tests for WZX effect container extraction."""
import struct
import pytest
from shared.helpers.wzx import is_wzx, extract_wzx, _align32
from importer.phases.extract.extract import extract_dat


# ---------------------------------------------------------------------------
# Helpers — build synthetic WZX data
# ---------------------------------------------------------------------------

def _build_dat(data_size=64, root_count=1, reloc_count=4):
    """Build a minimal valid DAT binary for embedding in WZX."""
    data_block = b'\xAA' * data_size
    reloc_table = b'\x00\x00\x00\x00' * reloc_count
    # Root entry: node_offset, string_offset (pointing to "scene_data\0")
    string_data = b'scene_data\x00'
    root_entry = struct.pack('>II', 0x00, 0x00)  # placeholder offsets
    ref_count = 0
    section_info_size = (root_count + ref_count) * 8
    file_size = 0x20 + data_size + reloc_count * 4 + section_info_size + len(string_data)
    header = struct.pack('>IIIII', file_size, data_size, reloc_count, root_count, ref_count)
    header += b'\x00' * 12  # padding
    return header + data_block + reloc_table + root_entry + string_data


def _build_gpt1_v1(payload_size=64):
    """Build a minimal GPT1 V1 block."""
    # Header: sig, ptl_offset, txg_offset, tex_length, ref_offset, padding
    ptl_offset = 0x20
    txg_offset = ptl_offset + 0x10
    tex_length = 0
    ref_offset = txg_offset + 0x10
    total = ref_offset + 4  # 1 generator ref
    header = struct.pack('>IIIII', 0x47505431, ptl_offset, txg_offset, tex_length, ref_offset)
    header += b'\x00' * 12  # padding to 0x20
    # PTL: version, unknown, skip_sections, nb_generators
    ptl = struct.pack('>HHII', 0x43, 0, 0, 1)
    ptl += b'\x00' * (0x10 - len(ptl))
    # TXG: nb_containers = 0
    txg = struct.pack('>I', 0)
    txg += b'\x00' * (0x10 - len(txg))
    # REF: 1 entry
    ref = struct.pack('>I', 0)
    return header + ptl + txg + ref


def _build_wzx_header(entry_count=1, version=6, hsd_size=0):
    """Build a WZX file header (main entry + section header = 0xA0 bytes).

    Args:
        entry_count: Total entry count (sub_entries = entry_count - 1).
        version: 5 for Colosseum, 6 for XD.
        hsd_size: Size of embedded HSD archive (0 = none).
    """
    # Main SequenceEntry (0x70 bytes)
    main_entry = bytearray(0x70)
    # Timings at 0x10-0x18 = -1
    struct.pack_into('>iii', main_entry, 0x10, -1, -1, -1)
    # bone_attachment at 0x1C
    struct.pack_into('>I', main_entry, 0x1C, 2)
    # Version-like value at 0x68 (in extra_data)
    struct.pack_into('>I', main_entry, 0x68, version - 3)  # 2 for Colo(5), 3 for XD(6)

    # Section header (0x20 bytes at offset 0x70, padded to 0xA0)
    section_hdr = bytearray(0x30)  # 0x20 header + 0x10 padding
    struct.pack_into('>I', section_hdr, 0x04, entry_count)     # entry_count
    struct.pack_into('>I', section_hdr, 0x0C, 2)               # param
    struct.pack_into('>I', section_hdr, 0x10, version)          # version
    struct.pack_into('>I', section_hdr, 0x14, hsd_size)         # hsd_archive_size

    return bytes(main_entry) + bytes(section_hdr)


def _build_particle_sub_entry(gpt1_bytes, entry_type=2, link_ref=0, file_offset=0xA0):
    """Build a Particle sub-entry (0x70 header + padded 0x14 extra + GPT1 data).

    The extra data is padded to match _align32(file_offset + 0x70 + 0x14)
    since the game aligns the particle data start to a 0x20 boundary.
    """
    # SequenceEntry header (0x70)
    entry = bytearray(0x70)
    struct.pack_into('>I', entry, 0x04, entry_type)  # entry_type = 2 (Particle)
    struct.pack_into('>I', entry, 0x6C, link_ref)

    # Particle extra data header is 0x14 bytes; the game aligns the position
    # after it to a 0x20 boundary. Compute padding to match.
    extra_start = file_offset + 0x70
    gpt1_start = _align32(extra_start + 0x14)
    extra_padded_size = gpt1_start - extra_start

    extra = bytearray(extra_padded_size)
    struct.pack_into('>I', extra, 0x08, len(gpt1_bytes))  # particle_data_size

    # GPT1 data (align32)
    padded_gpt1 = gpt1_bytes + b'\x00' * (_align32(len(gpt1_bytes)) - len(gpt1_bytes))

    return bytes(entry) + bytes(extra) + padded_gpt1


def _build_sound_sub_entry():
    """Build a Sound sub-entry (0x70 header + 0x14 extra)."""
    entry = bytearray(0x70)
    struct.pack_into('>I', entry, 0x04, 4)  # entry_type = 4 (Sound)
    extra = bytearray(0x14)
    return bytes(entry) + bytes(extra)


def _build_event_sub_entry():
    """Build an Event sub-entry (0x70 header + 0x08 extra)."""
    entry = bytearray(0x70)
    struct.pack_into('>I', entry, 0x04, 5)  # entry_type = 5 (Event)
    extra = bytearray(0x08)
    return bytes(entry) + bytes(extra)


def _build_model_sub_entry(dat_bytes=None, file_offset=0xA0):
    """Build a Model sub-entry (0x70 header + padded 0x28 extra + opt DAT)."""
    entry = bytearray(0x70)
    struct.pack_into('>I', entry, 0x04, 1)  # entry_type = 1 (Model)

    # Model extra is 0x28 bytes; game aligns position after it to 0x20.
    extra_start = file_offset + 0x70
    dat_start = _align32(extra_start + 0x28)
    extra_padded_size = dat_start - extra_start

    extra = bytearray(extra_padded_size)
    dat_size = len(dat_bytes) if dat_bytes else 0
    struct.pack_into('>I', extra, 0x1C, dat_size)

    result = bytes(entry) + bytes(extra)
    if dat_bytes:
        result += dat_bytes + b'\x00' * (_align32(len(dat_bytes)) - len(dat_bytes))
    return result


# ---------------------------------------------------------------------------
# is_wzx tests
# ---------------------------------------------------------------------------

def test_is_wzx_valid():
    """A proper WZX header is detected."""
    data = _build_wzx_header()
    assert is_wzx(data)


def test_is_wzx_too_short():
    """Data shorter than 0xA0 is not WZX."""
    assert not is_wzx(b'\x00' * 0x80)


def test_is_wzx_wrong_sentinel():
    """Data without the 0xFF sentinel is not WZX."""
    data = bytearray(_build_wzx_header())
    data[0x10:0x1C] = b'\x00' * 12
    assert not is_wzx(bytes(data))


# ---------------------------------------------------------------------------
# extract_wzx — empty / minimal files
# ---------------------------------------------------------------------------

def test_wzx_empty_file():
    """A minimal WZX (0xA0 bytes, 0 sub-entries) returns empty list."""
    data = _build_wzx_header(entry_count=1)
    results = extract_wzx(data)
    assert results == []


def test_wzx_not_wzx():
    """Non-WZX data returns empty list."""
    results = extract_wzx(b'\x00' * 256)
    assert results == []


# ---------------------------------------------------------------------------
# extract_wzx — DAT at 0xA0 (hsd_archive_size > 0)
# ---------------------------------------------------------------------------

def test_wzx_dat_at_a0():
    """A WZX with hsd_archive_size > 0 extracts the DAT at 0xA0."""
    dat = _build_dat(data_size=64)
    header = _build_wzx_header(entry_count=1, hsd_size=len(dat))
    data = header + dat
    results = extract_wzx(data)
    assert len(results) == 1
    dat_bytes, gpt1_bytes = results[0]
    assert dat_bytes == dat
    assert gpt1_bytes == b''


# ---------------------------------------------------------------------------
# extract_wzx — sub-entries with particles
# ---------------------------------------------------------------------------

def test_wzx_particle_sub_entry():
    """A WZX with a Particle sub-entry extracts the GPT1 via scan."""
    gpt1 = _build_gpt1_v1()
    particle_entry = _build_particle_sub_entry(gpt1)
    header = _build_wzx_header(entry_count=2)  # 1 sub-entry
    data = header + particle_entry
    results = extract_wzx(data)
    # The scan should find the GPT1
    assert len(results) >= 1
    # At least one result should have GPT1 data
    has_gpt1 = any(g for _, g in results if g)
    assert has_gpt1


# ---------------------------------------------------------------------------
# extract_wzx — sub-entries with sound and event
# ---------------------------------------------------------------------------

def test_wzx_sound_and_event_entries():
    """Sound and Event sub-entries are skipped without error."""
    sound = _build_sound_sub_entry()
    event = _build_event_sub_entry()
    header = _build_wzx_header(entry_count=3)  # 2 sub-entries
    data = header + sound + event
    results = extract_wzx(data)
    assert results == []  # No DAT or GPT1 content


# ---------------------------------------------------------------------------
# extract_wzx — model sub-entry with embedded DAT
# ---------------------------------------------------------------------------

def test_wzx_model_with_dat():
    """A Model sub-entry with an embedded DAT is found via scan."""
    dat = _build_dat(data_size=32)
    model = _build_model_sub_entry(dat_bytes=dat)
    header = _build_wzx_header(entry_count=2)  # 1 sub-entry
    data = header + model
    results = extract_wzx(data)
    assert len(results) >= 1
    found_dat = any(d == dat for d, _ in results)
    assert found_dat


# ---------------------------------------------------------------------------
# extract_wzx — multiple DATs (chained sections)
# ---------------------------------------------------------------------------

def test_wzx_chained_sections():
    """A WZX with a DAT at 0xA0 and another in a chained section."""
    dat1 = _build_dat(data_size=64)
    dat2 = _build_dat(data_size=128)

    header1 = _build_wzx_header(entry_count=1, hsd_size=len(dat1))
    padded_dat1 = dat1 + b'\x00' * (_align32(len(dat1)) - len(dat1))

    # Second section: another SequenceEntry + header + DAT
    header2 = _build_wzx_header(entry_count=1, hsd_size=len(dat2))
    padded_dat2 = dat2 + b'\x00' * (_align32(len(dat2)) - len(dat2))

    data = header1 + padded_dat1 + header2 + padded_dat2
    results = extract_wzx(data)
    assert len(results) >= 2


# ---------------------------------------------------------------------------
# Integration: extract_dat with .wzx extension
# ---------------------------------------------------------------------------

def test_extract_dat_wzx_extension():
    """extract_dat dispatches to WZX handler for .wzx files."""
    dat = _build_dat(data_size=64)
    header = _build_wzx_header(entry_count=1, hsd_size=len(dat))
    data = header + dat
    entries = extract_dat(data, 'effect.wzx')
    assert len(entries) == 1
    assert entries[0][0] == dat
    assert entries[0][1].filename == 'effect.wzx'


def test_extract_dat_wzx_detected_by_sentinel():
    """WZX detection works by sentinel even with wrong extension."""
    dat = _build_dat(data_size=64)
    header = _build_wzx_header(entry_count=1, hsd_size=len(dat))
    data = header + dat
    entries = extract_dat(data, 'misnamed.dat')
    assert len(entries) == 1
    assert entries[0][0] == dat


def test_extract_dat_wzx_empty_returns_empty():
    """A WZX with no extractable content returns empty list."""
    data = _build_wzx_header(entry_count=1)
    entries = extract_dat(data, 'empty.wzx')
    assert len(entries) == 0


def test_extract_dat_wzx_multiple_dats_get_suffixes():
    """Multiple DATs from a WZX get indexed filenames."""
    dat1 = _build_dat(data_size=64)
    dat2 = _build_dat(data_size=128)

    header1 = _build_wzx_header(entry_count=1, hsd_size=len(dat1))
    padded_dat1 = dat1 + b'\x00' * (_align32(len(dat1)) - len(dat1))
    header2 = _build_wzx_header(entry_count=1, hsd_size=len(dat2))
    padded_dat2 = dat2 + b'\x00' * (_align32(len(dat2)) - len(dat2))

    data = header1 + padded_dat1 + header2 + padded_dat2
    entries = extract_dat(data, 'carde_bg.wzx')
    assert len(entries) >= 2
    # Check filenames have suffixes
    names = [e[1].filename for e in entries]
    assert 'carde_bg_0.wzx' in names
    assert 'carde_bg_1.wzx' in names
