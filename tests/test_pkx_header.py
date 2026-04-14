"""Tests for PKX header parsing, serialization, and round-trip fidelity."""
import struct
import pytest

from shared.helpers.pkx_header import (
    PartAnimData, SubAnim, AnimMetadataEntry, PKXHeader,
    _align32, _COLO_FPS,
)
from shared.helpers.binary import read, pack, pack_many


# ---- align32 ----

def test_align32_zero():
    assert _align32(0) == 0

def test_align32_already_aligned():
    assert _align32(0x20) == 0x20
    assert _align32(0x40) == 0x40

def test_align32_needs_padding():
    assert _align32(1) == 0x20
    assert _align32(0x21) == 0x40
    assert _align32(0xE54) == 0xE60


# ---- PartAnimData ----

def test_part_anim_default_is_inactive():
    p = PartAnimData()
    assert p.has_data == 0
    assert p.bone_config == b'\xff' * 16
    assert p.anim_index_ref == 0

def test_part_anim_to_bytes_size():
    assert len(PartAnimData().to_bytes()) == 19

def test_part_anim_round_trip():
    p = PartAnimData(has_data=1, sub_param=0, bone_config=b'\xff' * 16, anim_index_ref=7)
    raw = p.to_bytes()
    p2 = PartAnimData.from_bytes(raw, 0)
    assert p2.has_data == 1
    assert p2.anim_index_ref == 7
    assert p2.to_bytes() == raw

def test_part_anim_complex():
    """Moltres-style complex part anim data."""
    raw = bytearray(19)
    raw[0] = 2   # has_data = complex
    raw[1] = 1   # sub_param
    raw[2] = 0x74
    raw[10] = 2
    raw[18] = 0x0A
    p = PartAnimData.from_bytes(bytes(raw), 0)
    assert p.has_data == 2
    assert p.sub_param == 1
    assert p.bone_config[0] == 0x74
    assert p.anim_index_ref == 10
    assert p.to_bytes() == bytes(raw)


# ---- AnimMetadataEntry ----

def test_entry_unused_defaults():
    e = AnimMetadataEntry.default_unused(is_xd=True)
    assert e.anim_type == 4
    assert e.terminator == 3
    assert e.body_map_bones == [-1] * 16
    assert e.sub_anims[0].motion_type == 0
    assert e.sub_anims[0].anim_index == 0

def test_entry_unused_colo():
    e = AnimMetadataEntry.default_unused(is_xd=False)
    assert e.terminator == 1

def test_entry_idle_defaults():
    e = AnimMetadataEntry.default_idle(is_xd=True)
    assert e.anim_type == 2
    assert e.sub_anims[0].motion_type == 2  # loop
    assert e.body_map_bones[0] == 0  # root bone

def test_entry_to_bytes_size():
    assert len(AnimMetadataEntry.default_unused().to_bytes()) == 0xD0

def test_entry_xd_round_trip():
    """Hand-crafted XD entry round-trips through from_bytes → to_bytes."""
    e = AnimMetadataEntry(
        anim_type=4,
        sub_anim_count=2,
        damage_flags=0,
        timing=(1.367, 2.267, 3.100, 0.0),
        body_map_bones=[0, 66, 60, 5, 65, 67, 66, 66, 0, 0, 0, 0, 40, 19, 53, 14],
        sub_anims=[SubAnim(1, 5), SubAnim(1, 7)],
        terminator=3,
    )
    raw = e.to_bytes(is_xd=True)
    assert len(raw) == 0xD0

    e2 = AnimMetadataEntry.from_bytes(raw, 0, is_xd=True)
    assert e2.anim_type == 4
    assert e2.sub_anim_count == 2
    assert e2.body_map_bones[1] == 66  # head bone
    assert len(e2.sub_anims) == 2
    assert e2.sub_anims[0].anim_index == 5
    assert e2.sub_anims[1].anim_index == 7
    assert e2.terminator == 3

    # Float precision: allow small epsilon
    for i in range(4):
        assert abs(e2.timing[i] - e.timing[i]) < 1e-4

def test_entry_colo_timing_conversion():
    """Colosseum uses integer frame counts at 60fps."""
    e = AnimMetadataEntry(
        anim_type=4,
        sub_anim_count=1,
        timing=(1.8333, 3.0, 3.9667, 0.0),
        body_map_bones=[0] + [-1] * 15,
        sub_anims=[SubAnim(0, 3)],
        terminator=1,
    )
    raw = e.to_bytes(is_xd=False)

    # Timing should be stored as integer frame counts
    t1 = read('uint', raw, 0x10)
    t2 = read('uint', raw, 0x14)
    t3 = read('uint', raw, 0x18)
    assert t1 == 110  # round(1.8333 * 60)
    assert t2 == 180  # round(3.0 * 60)
    assert t3 == 238  # round(3.9667 * 60)

    # Round-trip: small rounding error acceptable
    e2 = AnimMetadataEntry.from_bytes(raw, 0, is_xd=False)
    assert abs(e2.timing[0] - 110 / 60.0) < 1e-6
    assert abs(e2.timing[1] - 3.0) < 1e-6

def test_entry_colo_motion_type_zero():
    """Colosseum sub-entries have motion_type always 0."""
    e = AnimMetadataEntry(
        anim_type=4, sub_anim_count=1,
        sub_anims=[SubAnim(0, 4)],
        terminator=1,
    )
    raw = e.to_bytes(is_xd=False)
    mt = read('uint', raw, 0x8C)
    assert mt == 0


# ---- PKXHeader ----

def test_header_xd_dynamic_size_17_entries():
    """17 entries, no GPT1 → 0xE60."""
    h = PKXHeader.default_xd()
    assert h.header_byte_size == 0xE60

def test_header_xd_dynamic_size_16_entries():
    """16 entries, no GPT1."""
    h = PKXHeader(is_xd=True, anim_section_count=16)
    expected = _align32(0x84 + 16 * 0xD0)
    assert h.header_byte_size == expected

def test_header_colo_size_is_fixed():
    h = PKXHeader(is_xd=False)
    assert h.header_byte_size == 0x40

def test_header_has_shiny_identity():
    """Identity routing + neutral brightness = no shiny."""
    h = PKXHeader()
    h.shiny_route = (0, 1, 2, 3)
    h.shiny_brightness = (0x7F, 0x7F, 0x7F, 0x7F)
    assert not h.has_shiny

def test_header_has_shiny_nonidentity():
    h = PKXHeader()
    h.shiny_route = (2, 1, 0, 3)
    h.shiny_brightness = (0x7F, 0x7F, 0x7F, 0x7F)
    assert h.has_shiny

def test_header_xd_round_trip():
    """Build an XD header, serialize, re-parse, compare fields."""
    h = PKXHeader.default_xd(dat_file_size=100000, species_id=280)
    h.particle_orientation = -1
    h.head_bone_index = 66
    h.flags = 0x80
    h.shiny_route = (2, 1, 0, 3)
    h.shiny_brightness = (0x9D, 0xA5, 0xC8, 0x7F)
    h.anim_entries[0] = AnimMetadataEntry(
        anim_type=2, sub_anim_count=1,
        timing=(2.633, 0.0, 0.0, 0.0),
        body_map_bones=[0, 66, 60, 5, 65, 67] + [-1] * 10,
        sub_anims=[SubAnim(2, 4)],
        terminator=3,
    )

    raw = h.to_bytes()
    assert isinstance(raw, bytes)
    assert len(raw) == 0xE60

    h2 = PKXHeader.from_bytes(raw, is_xd=True)
    assert h2.dat_file_size == 100000
    assert h2.species_id == 280
    assert h2.particle_orientation == -1
    assert h2.head_bone_index == 66
    assert h2.flags == 0x80
    assert h2.shiny_route == (2, 1, 0, 3)
    assert h2.shiny_brightness == (0x9D, 0xA5, 0xC8, 0x7F)
    assert h2.anim_section_count == 17
    assert len(h2.anim_entries) == 17
    assert h2.anim_entries[0].anim_type == 2
    assert h2.anim_entries[0].sub_anims[0].anim_index == 4
    assert h2.anim_entries[0].body_map_bones[1] == 66

def test_header_colo_round_trip():
    """Build a Colosseum header, serialize, re-parse."""
    h = PKXHeader.default_colosseum(dat_file_size=200000)
    h.particle_orientation = -1
    h.colo_part_anim_refs = [6, 7, 5]
    h.shiny_route = (2, 1, 0, 3)
    h.shiny_brightness = (0x9D, 0xA5, 0xC8, 0x7F)

    header_bytes, meta_bytes = h.to_bytes()
    assert len(header_bytes) == 0x40
    # meta = 17 * 0xD0 + 20 shiny
    assert len(meta_bytes) == 17 * 0xD0 + 20

    # Simulate full file layout for re-parsing
    # [header 0x40][DAT padded][meta+shiny]
    dat_padded = b'\x00' * _align32(200000)
    full_file = header_bytes + dat_padded + meta_bytes
    meta_start = 0x40 + len(dat_padded)

    h2 = PKXHeader.from_bytes(full_file, is_xd=False, meta_start=meta_start)
    assert h2.dat_file_size == 200000
    assert h2.particle_orientation == -1
    assert h2.colo_part_anim_refs == [6, 7, 5]
    assert h2.shiny_route == (2, 1, 0, 3)
    assert h2.shiny_brightness == (0x9D, 0xA5, 0xC8, 0x7F)
    assert len(h2.anim_entries) == 17


# ---- PKXContainer integration ----

def test_container_xd_header_size_dynamic():
    """Verify PKXContainer uses dynamic header size, not hardcoded 0xE60."""
    from shared.helpers.pkx import PKXContainer

    h = PKXHeader.default_xd(dat_file_size=32)
    raw = h.to_bytes()

    # Build minimal DAT: 32 bytes (file_size=32 in first uint)
    dat = bytearray(32)
    struct.pack_into('>I', dat, 0, 32)

    # Build PKX file: header + DAT
    pkx_bytes = raw + bytes(dat)
    pkx = PKXContainer(pkx_bytes)

    assert pkx.is_xd
    assert pkx.header_size == 0xE60
    assert len(pkx.dat_bytes) == 32

def test_container_gpt1_extraction():
    """Verify GPT1 data can be extracted."""
    from shared.helpers.pkx import PKXContainer

    h = PKXHeader.default_xd(dat_file_size=32)
    gpt1 = b'\xAA' * 100
    dat = bytearray(32)
    struct.pack_into('>I', dat, 0, 32)

    pkx = PKXContainer.build_xd(bytes(dat), h, gpt1_data=gpt1)
    extracted = pkx.gpt1_data
    assert extracted[:100] == gpt1

def test_body_map_keys_cover_all_16_slots():
    """All three places that define body-map keys agree on the 16-slot layout."""
    import pathlib
    import re

    addon_root = pathlib.Path(__file__).resolve().parent.parent
    expected_tail = [
        "secondary_8", "secondary_9", "secondary_10", "secondary_11",
        "attach_a", "attach_b", "attach_c", "attach_d",
    ]

    for rel in (
        'importer/phases/post_process/post_process.py',
        'exporter/phases/describe_blender/describe_blender.py',
        'BlenderPlugin.py',
    ):
        src = (addon_root / rel).read_text()
        # Find the _BODY_MAP_KEYS literal and ensure each extended suffix appears.
        assert 'secondary_8' in src, f'{rel}: missing secondary_8'
        assert 'attach_d' in src, f'{rel}: missing attach_d'
        for suffix in expected_tail:
            assert f'"{suffix}"' in src, f'{rel}: missing "{suffix}"'


def test_body_map_extended_slots_survive_header_round_trip():
    """Slots 8-15 of body_map_bones serialize/parse losslessly."""
    extended = [0, 66, 60, 5, 65, 67, 66, 66, 96, 112, 95, 111, 21, 42, 2, 113]
    h = PKXHeader.default_xd(dat_file_size=100000)
    h.anim_entries[0] = AnimMetadataEntry(
        anim_type=2, sub_anim_count=1,
        timing=(1.0, 0.0, 0.0, 0.0),
        body_map_bones=extended,
        sub_anims=[SubAnim(2, 0)],
        terminator=3,
    )
    raw = h.to_bytes()
    h2 = PKXHeader.from_bytes(raw, is_xd=True)
    assert h2.anim_entries[0].body_map_bones == extended


def test_container_shiny_xd_reads_correctly():
    """XD shiny params read from full uint32 routing words."""
    from shared.helpers.pkx import PKXContainer

    h = PKXHeader.default_xd(dat_file_size=32)
    h.shiny_route = (2, 1, 0, 3)
    h.shiny_brightness = (0x9D, 0xA5, 0xC8, 0x7F)
    dat = bytearray(32)
    struct.pack_into('>I', dat, 0, 32)

    pkx = PKXContainer.build_xd(bytes(dat), h)
    sp = pkx.shiny_params
    assert sp is not None
    assert sp.route_r == 2
    assert sp.route_g == 1
    assert sp.route_b == 0
    assert sp.route_a == 3
