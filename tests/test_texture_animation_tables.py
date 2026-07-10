"""TextureAnimation frame-swap tables (image_table / palette_table).

The image_table field is a double pointer — TextureAnimation holds the
address of a table of `image_table_count` pointers, each pointing to an
Image struct (one per animation frame). Regression coverage for the parse
side (previously only the first table entry was read, as a mis-typed single
Image) and for the write side (previously the table and its frame images
were dropped entirely, shrinking the rebuilt file).
"""
import io
import struct

from helpers import build_dat_with_sections
from importer.phases.parse.parse import parse_sections
from exporter.phases.serialize.helpers.dat_builder import DATBuilder


TA_SECTION = {'test_texanim': 'TextureAnimation'}


def _build_ta_dat():
    """Data section layout:

      0   TextureAnimation (24 B): image_table -> 72, counts (2, 0)
      24  Image A (24 B): 4x4 I8, pixels at 80
      48  Image B (24 B): 8x8 I8, pixels at 80
      72  pointer table: [24, 48]
      80  shared pixel data (128 B of zeroes)
    """
    ta = struct.pack('>IIIIIHH', 0, 1, 0, 72, 0, 2, 0)
    img_a = struct.pack('>IHHIIff', 80, 4, 4, 1, 0, 0.0, 0.0)
    img_b = struct.pack('>IHHIIff', 80, 8, 8, 1, 0, 0.0, 0.0)
    table = struct.pack('>II', 24, 48)
    pixels = b'\x00' * 128
    data = ta + img_a + img_b + table + pixels
    return build_dat_with_sections(
        data_section=data,
        relocations=[12, 72, 76],
        sections=[(0, True)],
        section_names=['test_texanim'],
    )


def test_parse_image_table_reads_all_frames():
    sections = parse_sections(_build_ta_dat(), dict(TA_SECTION), {})
    ta = sections[0].root_node
    assert ta.image_table_count == 2
    assert isinstance(ta.image_table, list) and len(ta.image_table) == 2
    assert (ta.image_table[0].width, ta.image_table[0].height) == (4, 4)
    assert (ta.image_table[1].width, ta.image_table[1].height) == (8, 8)
    assert ta.palette_table is None


def test_image_table_roundtrips_through_builder():
    sections = parse_sections(_build_ta_dat(), dict(TA_SECTION), {})
    out = io.BytesIO()
    DATBuilder(out, [s.root_node for s in sections],
               [s.section_name for s in sections]).build()
    rebuilt = out.getvalue()

    reparsed = parse_sections(rebuilt, dict(TA_SECTION), {})[0].root_node
    assert reparsed.image_table_count == 2
    assert isinstance(reparsed.image_table, list) and len(reparsed.image_table) == 2
    assert (reparsed.image_table[0].width, reparsed.image_table[0].height) == (4, 4)
    assert (reparsed.image_table[1].width, reparsed.image_table[1].height) == (8, 8)
    assert reparsed.image_table[0].format == 1
    assert reparsed.palette_table is None


def test_parse_does_not_mutate_class_fields():
    """Variable array bounds must not be baked into the class-level fields
    list — a second parse with different counts must see its own values."""
    from shared.Nodes.Classes.Texture.TextureAnimation import TextureAnimation
    before = [tuple(f) for f in TextureAnimation.fields]
    parse_sections(_build_ta_dat(), dict(TA_SECTION), {})
    after = [tuple(f) for f in TextureAnimation.fields]
    assert before == after
