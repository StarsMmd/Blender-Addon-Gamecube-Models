"""Tests for shared/helpers/fsys_writer.py — LZSS compression and FSYS rebuild."""
import os
import struct

import pytest

from shared.helpers.fsys_writer import (
    compress_lzss,
    parse_fsys_summary,
    find_model_entries,
    rebuild_fsys_replacing,
    MODEL_TYPE_DAT,
    MODEL_TYPE_PKX,
)
from importer.phases.extract.helpers.lzss import decompress_lzss
from importer.phases.extract.helpers.fsys import parse_fsys

from helpers import build_fsys_archive, build_lzss_compressed


# ---------------------------------------------------------------------------
# LZSS compress → decompress round-trip
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    b"",
    b"A",
    b"hello world",
    b"AB" * 500,
    b"The quick brown fox jumps over the lazy dog. " * 50,
    bytes(range(256)) * 4,
])
def test_lzss_round_trip(payload):
    if not payload:
        # Compressor returns empty; nothing to decompress.
        assert compress_lzss(payload) == b""
        return
    compressed = compress_lzss(payload)
    wrapped = (b'LZSS' + struct.pack('>III', len(payload), len(compressed) + 16, 0)
               + compressed)
    assert decompress_lzss(wrapped) == payload


# ---------------------------------------------------------------------------
# FSYS summary + replace
# ---------------------------------------------------------------------------

def _archive_with_two_entries(replace_compressed):
    other = b"some-non-model-bytes-padding-x"  # type 0x06 (CCD) — ignored
    model = b"ORIGINAL-DAT-PAYLOAD" + b"\xAA" * 80
    if replace_compressed:
        model_stored = build_lzss_compressed(model)
    else:
        model_stored = model
    archive = build_fsys_archive([
        {'file_type': 0x06, 'data': other, 'compressed': False, 'filename': 'collide.ccd'},
        {'file_type': 0x04, 'data': model_stored, 'compressed': replace_compressed,
         'filename': 'character.dat'},
    ])
    return archive, other, model


def test_summary_finds_one_model_entry():
    archive, _, _ = _archive_with_two_entries(replace_compressed=False)
    entries = parse_fsys_summary(archive)
    assert len(entries) == 2
    models = find_model_entries(entries)
    assert len(models) == 1
    assert models[0].filename == 'character.dat'
    assert models[0].model_kind == MODEL_TYPE_DAT


def test_rebuild_preserves_other_entry_and_replaces_model_uncompressed():
    archive, other_payload, _ = _archive_with_two_entries(replace_compressed=False)
    entries = parse_fsys_summary(archive)
    target = find_model_entries(entries)[0]

    new_payload = b"REPLACED-DAT" + b"\x55" * 200
    rebuilt = rebuild_fsys_replacing(archive, target.index, new_payload)

    rebuilt_entries = parse_fsys_summary(rebuilt)
    assert len(rebuilt_entries) == 2

    # Other entry's stored bytes are byte-identical to the original.
    other_new = next(e for e in rebuilt_entries if e.filename == 'collide.ccd')
    assert rebuilt[other_new.data_address:
                   other_new.data_address + other_new.file_size] == other_payload

    # Model entry now has the new payload, uncompressed flag preserved.
    model_new = next(e for e in rebuilt_entries if e.filename == 'character.dat')
    assert not model_new.is_compressed
    assert model_new.file_size == len(new_payload)
    assert model_new.uncompressed_size == len(new_payload)
    assert rebuilt[model_new.data_address:
                   model_new.data_address + model_new.file_size] == new_payload

    # Header file_size matches new total length.
    assert struct.unpack_from('>I', rebuilt, 0x20)[0] == len(rebuilt)


def test_rebuild_recompresses_when_original_was_compressed():
    archive, other_payload, _ = _archive_with_two_entries(replace_compressed=True)
    entries = parse_fsys_summary(archive)
    target = find_model_entries(entries)[0]
    assert target.is_compressed

    new_payload = b"NEW-COMPRESSED-PAYLOAD" + b"\xCC" * 1000
    rebuilt = rebuild_fsys_replacing(archive, target.index, new_payload)

    # The model entry survives a real round-trip via the importer's
    # parse_fsys (which decompresses LZSS automatically).
    extracted = parse_fsys(rebuilt, 'rebuilt.fsys')
    assert any(data == new_payload for data, _, _ in extracted), (
        "Replaced entry should decompress back to the new payload"
    )

    # Other entry's bytes preserved verbatim (parse_fsys filters to model
    # types, so check by direct slice instead).
    rebuilt_entries = parse_fsys_summary(rebuilt)
    other_new = next(e for e in rebuilt_entries if e.filename == 'collide.ccd')
    assert rebuilt[other_new.data_address:
                   other_new.data_address + other_new.file_size] == other_payload


def test_rebuild_rejects_bad_index():
    archive, _, _ = _archive_with_two_entries(replace_compressed=False)
    with pytest.raises(ValueError, match="out of range"):
        rebuild_fsys_replacing(archive, 99, b"x")


def test_summary_rejects_non_fsys():
    with pytest.raises(ValueError, match="magic"):
        parse_fsys_summary(b"NOTFSYS" + b"\x00" * 200)
