"""Tests for Phase 1 — Container Extraction."""
import struct
from importer.phases.extract.extract import extract_dat, ContainerMetadata


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
    """An XD PKX has a 0xE60 byte header stripped (no GPT1)."""
    header = b'\x00' * 0xE60
    header = struct.pack('>I', 0xAAAAAAAA) + b'\x00' * 4 + struct.pack('>I', 0) + header[12:]
    header = header[:0x40] + struct.pack('>I', 0xBBBBBBBB) + header[0x44:]
    dat_body = b'\xFF' * 64
    raw = header + dat_body
    entries = extract_dat(raw, 'model.pkx')
    assert len(entries) == 1
    assert entries[0][0] == dat_body
