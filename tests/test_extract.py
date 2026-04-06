"""Tests for Phase 1 — Container Extraction."""
import struct
import pytest
from importer.phases.extract.extract import extract_dat, ContainerMetadata
from importer.phases.extract.helpers.lzss import is_lzss, decompress_lzss
from importer.phases.extract.helpers.fsys import is_fsys, parse_fsys
from helpers import build_fsys_archive, build_lzss_compressed


def test_dat_passthrough():
    """A .dat file is returned unchanged."""
    dat_bytes = b'\x00' * 64
    entries = extract_dat(dat_bytes, 'model.dat')
    assert len(entries) == 1
    assert entries[0][0] == dat_bytes
    assert entries[0][1].filename == 'model.dat'


def test_fdat_passthrough():
    """A .fdat file is treated as a plain DAT."""
    dat_bytes = b'\xAB' * 32
    entries = extract_dat(dat_bytes, 'model.fdat')
    assert len(entries) == 1
    assert entries[0][0] == dat_bytes
    assert entries[0][1].filename == 'model.fdat'


def test_pkx_colo_header_stripped():
    """A Colosseum PKX has a 0x40 byte header stripped."""
    # Colosseum: bytes at 0x00 == bytes at 0x40
    header = struct.pack('>I', 0x12345678) + b'\x00' * 0x3C
    dat_body = struct.pack('>I', 0x12345678) + b'\xFF' * 60
    raw = header + dat_body
    entries = extract_dat(raw, 'model.pkx')
    assert len(entries) == 1
    assert entries[0][0] == dat_body


def test_pkx_xd_header_stripped():
    """An XD PKX has a 0xE60 byte header stripped (no GPT1, 17 anim entries)."""
    header = bytearray(0xE60)
    struct.pack_into('>I', header, 0x00, 0xAAAAAAAA)  # dat_file_size (signals XD when != 0x40)
    struct.pack_into('>I', header, 0x08, 0)  # gpt1_length = 0
    struct.pack_into('>I', header, 0x10, 17)  # anim_section_count = 17
    struct.pack_into('>I', header, 0x40, 0xBBBBBBBB)  # different from 0x00 → XD detected
    dat_body = b'\xFF' * 64
    raw = bytes(header) + dat_body
    entries = extract_dat(raw, 'model.pkx')
    assert len(entries) == 1
    assert entries[0][0] == dat_body


# ---------------------------------------------------------------------------
# LZSS decompression tests
# ---------------------------------------------------------------------------

def test_lzss_magic_detected():
    data = b'LZSS' + b'\x00' * 12
    assert is_lzss(data)


def test_lzss_magic_not_detected():
    data = b'ABCD' + b'\x00' * 12
    assert not is_lzss(data)


def test_lzss_decompress_all_literals():
    """An LZSS stream where every byte is a literal."""
    original = b'\x41\x42\x43\x44\x45\x46\x47\x48'
    compressed = build_lzss_compressed(original)
    result = decompress_lzss(compressed)
    assert result == original


def test_lzss_decompress_multiple_chunks():
    """LZSS decompression across multiple 8-byte flag groups."""
    original = bytes(range(20))
    compressed = build_lzss_compressed(original)
    result = decompress_lzss(compressed)
    assert result == original


def test_lzss_decompress_bad_magic_raises():
    data = b'NOTZ' + b'\x00' * 12
    with pytest.raises(ValueError, match="LZSS magic not found"):
        decompress_lzss(data)


# ---------------------------------------------------------------------------
# FSYS archive tests
# ---------------------------------------------------------------------------

def test_fsys_magic_detected():
    data = b'FSYS' + b'\x00' * 92
    assert is_fsys(data)


def test_fsys_magic_not_detected():
    data = b'NOPE' + b'\x00' * 92
    assert not is_fsys(data)


def test_fsys_extracts_dat_entry():
    """A FSYS with one uncompressed .dat entry."""
    dat_body = b'\xDE\xAD' * 32
    archive = build_fsys_archive([
        {'file_type': 0x04, 'data': dat_body, 'compressed': False, 'filename': 'model'}
    ])
    entries = extract_dat(archive, 'archive.fsys')
    assert len(entries) == 1
    assert entries[0][0] == dat_body


def test_fsys_extracts_mdat_entry():
    """mdat (0x02) is treated as dat."""
    dat_body = b'\xBB' * 48
    archive = build_fsys_archive([
        {'file_type': 0x02, 'data': dat_body, 'compressed': False, 'filename': 'model'}
    ])
    entries = extract_dat(archive, 'archive.fsys')
    assert len(entries) == 1
    assert entries[0][0] == dat_body


def test_fsys_skips_non_model_types():
    """Non-model file types are skipped."""
    archive = build_fsys_archive([
        {'file_type': 0x0E, 'data': b'\x00' * 16, 'compressed': False, 'filename': 'script'},
        {'file_type': 0x04, 'data': b'\xFF' * 32, 'compressed': False, 'filename': 'model'},
    ])
    entries = extract_dat(archive, 'archive.fsys')
    assert len(entries) == 1
    assert entries[0][0] == b'\xFF' * 32


def test_fsys_extracts_multiple_models():
    """A FSYS with two dat entries returns two results with distinct names."""
    archive = build_fsys_archive([
        {'file_type': 0x04, 'data': b'\xAA' * 32, 'compressed': False, 'filename': 'model1'},
        {'file_type': 0x02, 'data': b'\xBB' * 32, 'compressed': False, 'filename': 'model2'},
    ])
    entries = extract_dat(archive, 'archive.fsys')
    assert len(entries) == 2
    assert entries[0][0] == b'\xAA' * 32
    assert entries[1][0] == b'\xBB' * 32
    assert entries[0][1].filename == 'model1.dat'
    assert entries[1][1].filename == 'model2.dat'


def test_fsys_decompresses_lzss_entry():
    """An LZSS-compressed entry is decompressed before return."""
    original = b'\xCA\xFE' * 24
    compressed = build_lzss_compressed(original)
    archive = build_fsys_archive([
        {'file_type': 0x04, 'data': compressed, 'compressed': True, 'filename': 'model'}
    ])
    entries = extract_dat(archive, 'archive.fsys')
    assert len(entries) == 1
    assert entries[0][0] == original


def test_fsys_pkx_entry_has_header_stripped():
    """A PKX entry inside FSYS gets both FSYS extraction and PKX header stripping."""
    # Build a Colosseum-style PKX: 0x40 header + dat body
    dat_body = struct.pack('>I', 0x12345678) + b'\xFF' * 60
    pkx_header = struct.pack('>I', 0x12345678) + b'\x00' * 0x3C
    pkx_data = pkx_header + dat_body

    archive = build_fsys_archive([
        {'file_type': 0x1E, 'data': pkx_data, 'compressed': False, 'filename': 'pokemon'}
    ])
    entries = extract_dat(archive, 'archive.fsys')
    assert len(entries) == 1
    assert entries[0][0] == dat_body


def test_fsys_empty_archive():
    """An FSYS with zero entries returns an empty list."""
    archive = build_fsys_archive([])
    entries = extract_dat(archive, 'empty.fsys')
    assert len(entries) == 0


def test_fsys_detected_by_magic_bytes():
    """FSYS detection works by magic bytes even with .dat extension."""
    dat_body = b'\xFF' * 32
    archive = build_fsys_archive([
        {'file_type': 0x04, 'data': dat_body, 'compressed': False, 'filename': 'model'}
    ])
    entries = extract_dat(archive, 'misnamed.dat')
    assert len(entries) == 1
    assert entries[0][0] == dat_body


def test_fsys_entry_gets_file_type_extension():
    """Entry filenames have the file type extension appended."""
    archive = build_fsys_archive([
        {'file_type': 0x04, 'data': b'\xFF' * 32, 'compressed': False, 'filename': 'battle_model'},
    ])
    entries = extract_dat(archive, 'archive.fsys')
    assert entries[0][1].filename == 'battle_model.dat'


def test_fsys_pkx_entry_gets_pkx_filename():
    """PKX entries inside FSYS carry their entry filename through extraction."""
    dat_body = struct.pack('>I', 0x12345678) + b'\xFF' * 60
    pkx_header = struct.pack('>I', 0x12345678) + b'\x00' * 0x3C
    pkx_data = pkx_header + dat_body
    archive = build_fsys_archive([
        {'file_type': 0x1E, 'data': pkx_data, 'compressed': False, 'filename': 'pokemon_001'}
    ])
    entries = extract_dat(archive, 'archive.fsys')
    assert entries[0][1].filename == 'pokemon_001.pkx'


def test_fsys_detected_by_extension():
    """FSYS detection works by .fsys extension."""
    dat_body = b'\xFF' * 32
    archive = build_fsys_archive([
        {'file_type': 0x04, 'data': dat_body, 'compressed': False, 'filename': 'model'}
    ])
    entries = extract_dat(archive, 'archive.fsys')
    assert len(entries) == 1
