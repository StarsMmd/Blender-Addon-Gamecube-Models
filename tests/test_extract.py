"""Tests for Phase 1 — Container Extraction."""
import struct
import tempfile
import os
from importer.phases.extract import extract_dat, ContainerMetadata


def _write_tmp(data, suffix='.dat'):
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.write(fd, data)
    os.close(fd)
    return path


def test_dat_passthrough():
    """A .dat file is returned unchanged."""
    dat_bytes = b'\x00' * 64
    path = _write_tmp(dat_bytes, suffix='.dat')
    try:
        entries = extract_dat(path)
        assert len(entries) == 1
        assert entries[0][0] == dat_bytes
        assert entries[0][1].container_type == 'dat'
    finally:
        os.unlink(path)


def test_fdat_passthrough():
    """A .fdat file is treated as a plain DAT."""
    dat_bytes = b'\xAB' * 32
    path = _write_tmp(dat_bytes, suffix='.fdat')
    try:
        entries = extract_dat(path)
        assert len(entries) == 1
        assert entries[0][0] == dat_bytes
        assert entries[0][1].container_type == 'dat'
    finally:
        os.unlink(path)


def test_pkx_colo_header_stripped():
    """A Colosseum PKX has a 0x40 byte header stripped."""
    # Colosseum: bytes at 0x00 == bytes at 0x40
    header = struct.pack('>I', 0x12345678) + b'\x00' * 0x3C
    dat_body = struct.pack('>I', 0x12345678) + b'\xFF' * 60  # same first 4 bytes
    raw = header + dat_body
    path = _write_tmp(raw, suffix='.pkx')
    try:
        entries = extract_dat(path)
        assert len(entries) == 1
        assert entries[0][0] == dat_body
        assert entries[0][1].container_type == 'pkx_colo'
        assert entries[0][1].is_xd_model is False
    finally:
        os.unlink(path)


def test_pkx_xd_header_stripped():
    """An XD PKX has a 0xE60 byte header stripped (no GPT1)."""
    # XD: bytes at 0x00 != bytes at 0x40
    header = b'\x00' * 0xE60
    # Make offset 0 != offset 0x40
    header = struct.pack('>I', 0xAAAAAAAA) + b'\x00' * 4 + struct.pack('>I', 0) + header[12:]
    # Ensure offset 0x40 is different
    header = header[:0x40] + struct.pack('>I', 0xBBBBBBBB) + header[0x44:]
    dat_body = b'\xFF' * 64
    raw = header + dat_body
    path = _write_tmp(raw, suffix='.pkx')
    try:
        entries = extract_dat(path)
        assert len(entries) == 1
        assert entries[0][0] == dat_body
        assert entries[0][1].container_type == 'pkx_xd'
        assert entries[0][1].is_xd_model is True
    finally:
        os.unlink(path)
