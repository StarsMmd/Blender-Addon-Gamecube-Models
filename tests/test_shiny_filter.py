"""Tests for shiny color filter extraction and IR construction."""
import struct
import pytest
from importer.phases.extract.extract import extract_dat, _extract_shiny_params
from shared.IR.shiny import IRShinyFilter
from shared.IR.enums import ShinyChannel


# ---------------------------------------------------------------------------
# Helper to build a minimal Colosseum PKX with shiny data
# ---------------------------------------------------------------------------

def _build_colo_pkx(shiny_color1, shiny_color2_abgr, dat_body_size=64):
    """Build a Colosseum-style PKX with shiny data at file_length - 0x11.

    Args:
        shiny_color1: tuple of 4 ints (R, G, B, A route values) placed at 3-byte gaps.
        shiny_color2_abgr: tuple of 4 ints (A, B, G, R) — Colosseum ABGR order.
        dat_body_size: size of the DAT body after header.
    """
    # Colosseum: bytes at 0x00 == bytes at 0x40 (same uint)
    marker = 0x12345678
    header = struct.pack('>I', marker) + b'\x00' * 0x3C
    dat_body = struct.pack('>I', marker) + b'\x00' * (dat_body_size - 4)
    raw = bytearray(header + dat_body)

    # Shiny data lives at file_length - 0x11 (17 bytes from end)
    base = len(raw) - 0x11

    # Color1: bytes at base+0, base+4, base+8, base+12 with 3-byte gaps
    raw[base + 0] = shiny_color1[0]
    raw[base + 4] = shiny_color1[1]
    raw[base + 8] = shiny_color1[2]
    raw[base + 12] = shiny_color1[3]

    # Color2: bytes at base+13..16 in ABGR order
    raw[base + 13] = shiny_color2_abgr[0]
    raw[base + 14] = shiny_color2_abgr[1]
    raw[base + 15] = shiny_color2_abgr[2]
    raw[base + 16] = shiny_color2_abgr[3]

    return bytes(raw)


def _build_xd_pkx(shiny_color1, shiny_color2_rgba, dat_body_size=64):
    """Build an XD-style PKX with shiny data at offset 0x73.

    Args:
        shiny_color1: tuple of 4 ints (R, G, B, A route values).
        shiny_color2_rgba: tuple of 4 ints (R, G, B, A) — XD RGBA order.
        dat_body_size: size of the DAT body after header.
    """
    # XD: bytes at 0x00 != bytes at 0x40
    header_size = 0xE60
    raw = bytearray(header_size + dat_body_size)

    # Different values at 0x00 and 0x40 to signal XD
    struct.pack_into('>I', raw, 0, 0xAAAAAAAA)
    struct.pack_into('>I', raw, 0x40, 0xBBBBBBBB)
    # GPT1 size = 0 (no GPT1 chunk)
    struct.pack_into('>I', raw, 8, 0)

    # Shiny data at offset 0x73
    base = 0x73
    raw[base + 0] = shiny_color1[0]
    raw[base + 4] = shiny_color1[1]
    raw[base + 8] = shiny_color1[2]
    raw[base + 12] = shiny_color1[3]

    # Color2 in RGBA order
    raw[base + 13] = shiny_color2_rgba[0]
    raw[base + 14] = shiny_color2_rgba[1]
    raw[base + 15] = shiny_color2_rgba[2]
    raw[base + 16] = shiny_color2_rgba[3]

    return bytes(raw)


# ---------------------------------------------------------------------------
# Extraction tests
# ---------------------------------------------------------------------------

def test_colo_pkx_shiny_extraction():
    """Colosseum PKX: shiny params extracted with correct channel routing and ABGR-reversed brightness."""
    # Color1: R→G(1), G→B(2), B→R(0), A→A(3)
    color1 = (1, 2, 0, 3)
    # Color2 in ABGR: A=200, B=100, G=150, R=255
    # After reversal to RGBA: R=255, G=150, B=100, A=200
    color2_abgr = (200, 100, 150, 255)

    raw = _build_colo_pkx(color1, color2_abgr)
    params = _extract_shiny_params(raw, is_xd=False)

    assert params is not None
    assert params["route_r"] == 1
    assert params["route_g"] == 2
    assert params["route_b"] == 0
    assert params["route_a"] == 3

    # ABGR reversed → RGBA: R=255, G=150, B=100, A=200
    # Brightness: (value / 255 * 2) - 1
    assert pytest.approx(params["brightness_r"], abs=0.01) == (255 / 255.0 * 2.0) - 1.0  # 1.0
    assert pytest.approx(params["brightness_g"], abs=0.01) == (150 / 255.0 * 2.0) - 1.0
    assert pytest.approx(params["brightness_b"], abs=0.01) == (100 / 255.0 * 2.0) - 1.0
    assert pytest.approx(params["brightness_a"], abs=0.01) == (200 / 255.0 * 2.0) - 1.0


def test_xd_pkx_shiny_extraction():
    """XD PKX: shiny params extracted with RGBA order brightness."""
    color1 = (0, 1, 2, 3)  # identity routing
    color2_rgba = (128, 0, 255, 64)

    raw = _build_xd_pkx(color1, color2_rgba)
    params = _extract_shiny_params(raw, is_xd=True)

    assert params is not None
    assert params["route_r"] == 0
    assert params["route_g"] == 1
    assert params["route_b"] == 2
    assert params["route_a"] == 3

    assert pytest.approx(params["brightness_r"], abs=0.01) == (128 / 255.0 * 2.0) - 1.0
    assert pytest.approx(params["brightness_g"], abs=0.01) == (0 / 255.0 * 2.0) - 1.0  # -1.0
    assert pytest.approx(params["brightness_b"], abs=0.01) == (255 / 255.0 * 2.0) - 1.0  # 1.0
    assert pytest.approx(params["brightness_a"], abs=0.01) == (64 / 255.0 * 2.0) - 1.0


def test_brightness_conversion_boundaries():
    """Brightness conversion: 0→-1.0, 128→~0.004, 255→1.0."""
    raw = _build_xd_pkx((0, 0, 0, 0), (0, 128, 255, 0))
    params = _extract_shiny_params(raw, is_xd=True)

    assert pytest.approx(params["brightness_r"], abs=0.001) == -1.0
    assert pytest.approx(params["brightness_g"], abs=0.01) == (128 / 255.0 * 2.0) - 1.0
    assert pytest.approx(params["brightness_b"], abs=0.001) == 1.0


def test_extract_dat_with_include_shiny_enabled():
    """extract_dat returns shiny_params on metadata when include_shiny is True."""
    # Non-identity routing so it's not detected as no-op
    raw = _build_colo_pkx((2, 1, 0, 3), (128, 128, 128, 128))
    options = {"include_shiny": True}
    entries = extract_dat(raw, 'pokemon.pkx', options=options)

    assert len(entries) == 1
    assert entries[0][1].shiny_params is not None
    assert "route_r" in entries[0][1].shiny_params
    assert "brightness_r" in entries[0][1].shiny_params


def test_extract_dat_with_include_shiny_disabled():
    """extract_dat returns shiny_params=None when include_shiny is False."""
    raw = _build_colo_pkx((2, 1, 0, 3), (128, 128, 128, 128))
    options = {"include_shiny": False}
    entries = extract_dat(raw, 'pokemon.pkx', options=options)

    assert len(entries) == 1
    assert entries[0][1].shiny_params is None


def test_extract_dat_no_options_no_shiny():
    """extract_dat without options returns shiny_params=None."""
    raw = _build_colo_pkx((0, 1, 2, 3), (128, 128, 128, 128))
    entries = extract_dat(raw, 'pokemon.pkx')

    assert len(entries) == 1
    assert entries[0][1].shiny_params is None


def test_non_pkx_has_no_shiny_params():
    """A .dat file has shiny_params=None regardless of options."""
    dat_bytes = b'\x00' * 64
    options = {"include_shiny": True}
    entries = extract_dat(dat_bytes, 'model.dat', options=options)

    assert len(entries) == 1
    assert entries[0][1].shiny_params is None


def test_extract_shiny_params_bounds_check():
    """Returns None if file is too small for shiny data."""
    # Tiny file that would fail bounds check
    raw = b'\x00' * 16
    result = _extract_shiny_params(raw, is_xd=True)
    assert result is None


def test_noop_shiny_returns_none():
    """Identity routing (0,1,2,3) + neutral brightness (128) is a no-op and returns None."""
    raw = _build_xd_pkx((0, 1, 2, 3), (128, 128, 128, 128))
    result = _extract_shiny_params(raw, is_xd=True)
    assert result is None


def test_noop_detection():
    """_is_noop_shiny correctly identifies identity routing + neutral brightness."""
    from importer.phases.extract.extract import _is_noop_shiny
    assert _is_noop_shiny(0, 1, 2, 3, [128, 128, 128, 128]) is True
    assert _is_noop_shiny(0, 1, 2, 3, [127, 127, 127, 127]) is True
    assert _is_noop_shiny(2, 1, 0, 3, [128, 128, 128, 128]) is False
    assert _is_noop_shiny(0, 1, 2, 3, [200, 128, 128, 128]) is False


# ---------------------------------------------------------------------------
# IR construction tests
# ---------------------------------------------------------------------------

def test_ir_shiny_filter_instantiation():
    """IRShinyFilter can be instantiated with ShinyChannel enum values."""
    sf = IRShinyFilter(
        channel_routing=(ShinyChannel.RED, ShinyChannel.GREEN, ShinyChannel.BLUE, ShinyChannel.ALPHA),
        brightness=(0.0, 0.5, -0.5, 1.0),
    )
    assert sf.channel_routing[0] == ShinyChannel.RED
    assert sf.channel_routing[3] == ShinyChannel.ALPHA
    assert sf.brightness[1] == 0.5


def test_shiny_channel_enum_values():
    """ShinyChannel enum has correct integer values."""
    assert ShinyChannel.RED.value == 0
    assert ShinyChannel.GREEN.value == 1
    assert ShinyChannel.BLUE.value == 2
    assert ShinyChannel.ALPHA.value == 3
    assert len(ShinyChannel) == 4


