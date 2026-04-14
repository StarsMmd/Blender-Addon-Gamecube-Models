"""Tests for GPT1 particle container parsing, serialization, and command disassembly."""
import struct
import pytest

from shared.helpers.gpt1 import (
    GPT1File, PTLSection, GeneratorDef, TXGSection, TextureContainer,
    GPT1_SIGNATURE, _HEADER_SIZE, _GEN_HEADER_SIZE,
)
from shared.helpers.gpt1_commands import (
    disassemble, format_instructions, ParticleInstruction,
)
from shared.helpers.binary import pack, pack_many


# ---------------------------------------------------------------------------
# Helpers to build synthetic GPT1 data
# ---------------------------------------------------------------------------

def _build_generator(cmd_bytes=b'\xFF', gen_type=5, lifetime=120, max_particles=36,
                     flags=0x01400001, params=None):
    """Build a raw generator header + command bytes."""
    header = bytearray(_GEN_HEADER_SIZE)
    struct.pack_into('>H', header, 0, gen_type)
    struct.pack_into('>H', header, 4, lifetime)
    struct.pack_into('>H', header, 6, max_particles)
    struct.pack_into('>I', header, 8, flags)
    if params:
        for i, v in enumerate(params[:12]):
            struct.pack_into('>f', header, 0x0C + i * 4, v)
    return bytes(header) + cmd_bytes


def _build_gpt1(generators=None, nb_tex_containers=0, tex_data=b'', ref_ids=None):
    """Build a complete synthetic GPT1 binary."""
    if generators is None:
        generators = [_build_generator()]
    if ref_ids is None:
        ref_ids = list(range(len(generators)))

    # Build PTL
    nb_gen = len(generators)
    ptl_header = bytearray(12)
    struct.pack_into('>H', ptl_header, 0, 0x43)  # version
    struct.pack_into('>I', ptl_header, 4, 0)      # skip_sections
    struct.pack_into('>I', ptl_header, 8, nb_gen)  # nb_generators

    # Generator pointer array + padding
    ptr_array_size = nb_gen * 4
    header_and_ptrs = 12 + ptr_array_size
    pad_to_8 = (8 - (header_and_ptrs % 8)) % 8
    gen_data_start = header_and_ptrs + pad_to_8

    gen_ptrs = bytearray()
    gen_blobs = bytearray()
    offset = gen_data_start
    for gen_bytes in generators:
        gen_ptrs.extend(struct.pack('>I', offset))
        gen_blobs.extend(gen_bytes)
        offset += len(gen_bytes)

    ptl_bytes = bytes(ptl_header) + bytes(gen_ptrs) + b'\xFF' * pad_to_8 + bytes(gen_blobs)

    # Build TXG (minimal)
    txg_bytes = struct.pack('>I', nb_tex_containers)
    if nb_tex_containers == 0:
        txg_bytes = struct.pack('>I', 0)

    # Build REF
    ref_bytes = b''.join(struct.pack('>I', rid) for rid in ref_ids)

    # Compute offsets
    ptl_off = _HEADER_SIZE
    txg_off = ptl_off + len(ptl_bytes)
    tex_start = txg_off + len(txg_bytes)
    ref_off = tex_start + len(tex_data)

    # Build header
    header = bytearray(_HEADER_SIZE)
    struct.pack_into('>I', header, 0, GPT1_SIGNATURE)
    struct.pack_into('>I', header, 4, ptl_off)
    struct.pack_into('>I', header, 8, txg_off)
    struct.pack_into('>I', header, 0x0C, len(tex_data))
    struct.pack_into('>I', header, 0x10, ref_off)

    return bytes(header) + ptl_bytes + txg_bytes + tex_data + ref_bytes


# ---------------------------------------------------------------------------
# GPT1 header tests
# ---------------------------------------------------------------------------

def test_gpt1_signature():
    data = _build_gpt1()
    gpt1 = GPT1File.from_bytes(data)
    assert gpt1.signature == GPT1_SIGNATURE

def test_gpt1_invalid_signature():
    data = bytearray(_build_gpt1())
    data[0:4] = b'\x00\x00\x00\x00'
    with pytest.raises(ValueError, match="Invalid GPT1 signature"):
        GPT1File.from_bytes(bytes(data))

def test_gpt1_too_small():
    with pytest.raises(ValueError, match="too small"):
        GPT1File.from_bytes(b'\x00' * 10)


# ---------------------------------------------------------------------------
# PTL section tests
# ---------------------------------------------------------------------------

def test_ptl_version():
    data = _build_gpt1()
    gpt1 = GPT1File.from_bytes(data)
    assert gpt1.ptl.version == 0x43

def test_ptl_generator_count():
    gens = [_build_generator() for _ in range(3)]
    data = _build_gpt1(generators=gens)
    gpt1 = GPT1File.from_bytes(data)
    assert len(gpt1.ptl.generators) == 3

def test_generator_header_fields():
    gen = _build_generator(gen_type=5, lifetime=120, max_particles=36, flags=0x01400001)
    data = _build_gpt1(generators=[gen])
    gpt1 = GPT1File.from_bytes(data)
    g = gpt1.ptl.generators[0]
    assert g.gen_type == 5
    assert g.lifetime == 120
    assert g.max_particles == 36
    assert g.flags == 0x01400001

def test_generator_params():
    params = [0.1 * i for i in range(12)]
    gen = _build_generator(params=params)
    data = _build_gpt1(generators=[gen])
    gpt1 = GPT1File.from_bytes(data)
    for i in range(12):
        assert abs(gpt1.ptl.generators[0].params[i] - params[i]) < 1e-5

def test_generator_command_bytes():
    cmd = b'\xA0\x00\x3C\x3F\x80\x00\x00\xFF'  # SCALE time=60 target=1.0, then EXIT
    gen = _build_generator(cmd_bytes=cmd)
    data = _build_gpt1(generators=[gen])
    gpt1 = GPT1File.from_bytes(data)
    assert gpt1.ptl.generators[0].command_bytes == cmd


# ---------------------------------------------------------------------------
# REF section tests
# ---------------------------------------------------------------------------

def test_ref_ids():
    gens = [_build_generator() for _ in range(4)]
    ref_ids = [100, 200, 300, 400]
    data = _build_gpt1(generators=gens, ref_ids=ref_ids)
    gpt1 = GPT1File.from_bytes(data)
    assert gpt1.ref_ids == ref_ids


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------

def test_round_trip_single_generator():
    """Parse → serialize → reparse should preserve all fields."""
    cmd = b'\xA0\x00\x1E\x40\x00\x00\x00\xC0\x0F\x00\xFF\xFF'
    gen = _build_generator(cmd_bytes=cmd, gen_type=5, lifetime=60, max_particles=10)
    original = _build_gpt1(generators=[gen], ref_ids=[42])

    gpt1 = GPT1File.from_bytes(original)
    reserialized = gpt1.to_bytes()
    gpt1_2 = GPT1File.from_bytes(reserialized)

    assert gpt1_2.ptl.version == 0x43
    assert len(gpt1_2.ptl.generators) == 1
    assert gpt1_2.ptl.generators[0].gen_type == 5
    assert gpt1_2.ptl.generators[0].lifetime == 60
    assert gpt1_2.ptl.generators[0].command_bytes == cmd
    assert gpt1_2.ref_ids == [42]

def test_round_trip_multiple_generators():
    gens = [_build_generator(cmd_bytes=bytes([0xA0 + i, 0xFF])) for i in range(5)]
    original = _build_gpt1(generators=gens, ref_ids=[10, 20, 30, 40, 50])

    gpt1 = GPT1File.from_bytes(original)
    reserialized = gpt1.to_bytes()
    gpt1_2 = GPT1File.from_bytes(reserialized)

    assert len(gpt1_2.ptl.generators) == 5
    assert gpt1_2.ref_ids == [10, 20, 30, 40, 50]
    for i in range(5):
        assert gpt1_2.ptl.generators[i].command_bytes[0] == 0xA0 + i


# ---------------------------------------------------------------------------
# Command disassembly tests
# ---------------------------------------------------------------------------

def test_disasm_exit():
    result = disassemble(b'\xFF')
    assert len(result) == 1
    assert result[0].mnemonic == "EXIT"
    assert result[0].opcode == 0xFF

def test_disasm_lifetime():
    result = disassemble(b'\x05\xFF')
    assert result[0].mnemonic == "LIFETIME"
    assert result[0].args['frames'] == 5

def test_disasm_lifetime_extended():
    # Bit 5 set: extended lifetime = (low5 << 8) | next_byte
    result = disassemble(b'\x23\x10\xFF')  # 0x23 = 0b00100011, low5=3, extended
    assert result[0].mnemonic == "LIFETIME"
    assert result[0].args['frames'] == (3 << 8) | 0x10

def test_disasm_lifetime_texture():
    # Bit 6 set: texture select
    result = disassemble(b'\x40\x03\xFF')  # 0x40 = 0b01000000
    assert result[0].mnemonic == "LIFETIME_TEX"
    assert result[0].args['frames'] == 0
    assert result[0].args['texture'] == 3

def test_disasm_set_pos():
    # 0x83 = SET_POS with X+Y flags (bits 0,1)
    float_x = struct.pack('>f', 1.5)
    float_y = struct.pack('>f', -2.0)
    result = disassemble(b'\x83' + float_x + float_y + b'\xFF')
    assert result[0].mnemonic == "SET_POS"
    assert abs(result[0].args['x'] - 1.5) < 1e-5
    assert abs(result[0].args['y'] - (-2.0)) < 1e-5
    assert 'z' not in result[0].args

def test_disasm_scale():
    # getTime encodes 30 as a single byte (bit 7 not set since 30 < 128)
    float_bytes = struct.pack('>f', 2.5)
    result = disassemble(b'\xA0\x1E' + float_bytes + b'\xFF')
    assert result[0].mnemonic == "SCALE"
    assert result[0].args['time'] == 30
    assert abs(result[0].args['target'] - 2.5) < 1e-5

def test_disasm_gravity():
    float_bytes = struct.pack('>f', -0.01)
    result = disassemble(b'\xA2' + float_bytes + b'\xFF')
    assert result[0].mnemonic == "GRAVITY"
    assert abs(result[0].args['value'] - (-0.01)) < 1e-5

def test_disasm_spawn_particle():
    result = disassemble(b'\xA4\x00\x05\xFF')
    assert result[0].mnemonic == "SPAWN_PARTICLE"
    assert result[0].args['id'] == 5

def test_disasm_set_primcol():
    # 0xCF = SET_PRIMCOL with all 4 channels (bits 0-3 all set)
    # getTime encodes 30 as single byte 0x1E
    result = disassemble(b'\xCF\x1E\xFF\x80\x40\xC0\xFF')
    assert result[0].mnemonic == "SET_PRIMCOL"
    assert result[0].args['time'] == 30
    assert result[0].args['r'] == 0xFF
    assert result[0].args['g'] == 0x80
    assert result[0].args['b'] == 0x40
    assert result[0].args['a'] == 0xC0

def test_disasm_loop():
    result = disassemble(b'\xFA\x03\xA1\xFB\xFF')
    assert result[0].mnemonic == "LOOP_START"
    assert result[0].args['count'] == 3
    assert result[1].mnemonic == "TEX_OFF"
    assert result[2].mnemonic == "LOOP_END"

def test_disasm_scale_extended_time():
    """getTime with bit 7 set reads a second byte for 15-bit value."""
    # 0x80 | 0x01 = 0x81 as first byte, 0x00 as second → time = (1 << 8) | 0 = 256
    float_bytes = struct.pack('>f', 1.0)
    result = disassemble(b'\xA0\x81\x00' + float_bytes + b'\xFF')
    assert result[0].mnemonic == "SCALE"
    assert result[0].args['time'] == 256


def test_disasm_stops_at_exit():
    result = disassemble(b'\xFF\xA0\x00\x00\x00\x00\x00\x00')
    assert len(result) == 1  # Should stop after EXIT

def test_format_instructions():
    result = disassemble(b'\xA2' + struct.pack('>f', -9.8) + b'\xFF')
    text = format_instructions(result)
    assert "GRAVITY" in text
    assert "-9.8" in text


# ---------------------------------------------------------------------------
# IR particle integration test
# ---------------------------------------------------------------------------

def test_describe_particles_integration():
    """Verify describe_particles converts GPT1 to IRParticleSystem."""
    from importer.phases.describe.helpers.particles import describe_particles

    cmd = b'\xA0\x00\x3C\x3F\x80\x00\x00\xFF'  # SCALE 60 1.0, EXIT
    gens = [_build_generator(cmd_bytes=cmd) for _ in range(3)]
    data = _build_gpt1(generators=gens, ref_ids=[1, 2, 3])

    result = describe_particles(data)
    assert result is not None
    assert len(result.generators) == 3
    assert result.ref_ids == [1, 2, 3]
    assert len(result.generators[0].instructions) > 0
    assert result.generators[0].instructions[0].mnemonic == "SCALE"
