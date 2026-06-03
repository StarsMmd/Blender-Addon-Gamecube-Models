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


# ---------------------------------------------------------------------------
# WZX inside FSYS tests
# ---------------------------------------------------------------------------

def test_fsys_wzx_entry_extracted():
    """A WZX entry inside FSYS is extracted through the WZX handler."""
    from tests.test_wzx import _build_wzx_header, _build_dat
    dat = _build_dat(data_size=64)
    wzx_data = _build_wzx_header(entry_count=1, hsd_size=len(dat)) + dat

    archive = build_fsys_archive([
        {'file_type': 0x20, 'data': wzx_data, 'compressed': False, 'filename': 'effect'}
    ])
    entries = extract_dat(archive, 'archive.fsys')
    assert len(entries) == 1
    assert entries[0][0] == dat
    assert 'effect' in entries[0][1].filename


# ---------------------------------------------------------------------------
# Kirby Air Ride "A2" multi-asset container detection
# ---------------------------------------------------------------------------

def _build_a2_container(entry_names):
    """Build a minimal A2-style container: file_size=0 sentinel, count, TOC, names."""
    n = len(entry_names)
    # TOC entries (end_offset, name_offset) at u32[5..5+2n)
    # Names live immediately after the TOC.
    header = struct.pack('>5I', 0, n, 0, 0, 0)
    toc = b''
    names_block = b''
    name_base = 20 + n * 8  # start of name block
    cursor = name_base
    for i, name in enumerate(entry_names):
        name_bytes = name.encode('ascii') + b'\x00'
        toc += struct.pack('>II', 0x10000 + i * 0x100, cursor)  # fake end_offset, real name_offset
        names_block += name_bytes
        cursor += len(name_bytes)
    # Pad out to something larger so offsets look plausible
    body = b'\x00' * 0x20000
    return header + toc + names_block + body


def test_a2_container_rejected_under_kar_game():
    """Kirby Air Ride A2 containers are detected and rejected in extract."""
    a2 = _build_a2_container(['AC0002.tm', 'KIRBY.tm', 'STAR1500.tm'])
    with pytest.raises(ValueError, match="multi-asset container"):
        extract_dat(a2, 'A2Kirby.dat', options={'game': 'KIRBY_AIR_RIDE'})


def test_a2_container_preview_names_in_error():
    """The rejection message mentions the first entry names so the user can tell what was in the file."""
    a2 = _build_a2_container(['bar.tex', 'base0.tex', 'base1.tex'])
    with pytest.raises(ValueError, match=r"bar\.tex.*base0\.tex"):
        extract_dat(a2, 'A2Window.dat', options={'game': 'KIRBY_AIR_RIDE'})


def test_a2_container_rejected_regardless_of_game():
    """The A2 signature is distinctive enough that the check runs unconditionally — no real HAL DAT trips it, so we don't gate on game."""
    a2 = _build_a2_container(['AC0002.tm'])
    with pytest.raises(ValueError, match="multi-asset container"):
        extract_dat(a2, 'A2Kirby.dat', options={'game': 'COLO_XD'})
    with pytest.raises(ValueError, match="multi-asset container"):
        extract_dat(a2, 'A2Kirby.dat')  # no options at all


def test_normal_dat_not_flagged_as_a2_under_kar():
    """A legitimate HAL DAT (file_size != 0) is not mis-detected as an A2 container."""
    # Minimal HAL DAT with file_size set to actual length
    dat = struct.pack('>5I', 64, 0, 0, 0, 0) + b'\x00' * 44
    entries = extract_dat(dat, 'EmScarfy.dat', options={'game': 'KIRBY_AIR_RIDE'})
    assert len(entries) == 1
    assert entries[0][0] == dat


def test_a2_inline_name_variant_rejected():
    """A2a2dBG_*-style containers embed names inline rather than via a name-offset table.

    The detector recognises them by the same file_size=0 signature plus a
    string sweep over the head of the file, so it should reject this layout
    just like the offset-table variant.
    """
    header = struct.pack('>5I', 0, 2, 24, 60, 38)
    # Single offset, then two null-terminated names inline
    body = struct.pack('>I', 0xC41BC)
    body += b'a2dBG_000F.tm\x00a2dBG_0100.tm\x00'
    body += b'\x00' * 0x1000
    a2 = header + body
    with pytest.raises(ValueError, match=r"a2dBG_000F\.tm.*a2dBG_0100\.tm"):
        extract_dat(a2, 'A2a2dBG_000F.dat')
