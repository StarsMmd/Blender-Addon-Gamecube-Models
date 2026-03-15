#!/usr/bin/env python3
"""
Standalone round-trip validation tool for DAT/PKX binary files.

Usage:
    python3 test_dat_write.py <input.dat> <output.dat>

Parses the input file with DATParser, writes it back with DATBuilder,
then re-parses the output and compares field values. Optionally reports
byte-level differences.

This is NOT a pytest test — it requires real (copyrighted) model files
that the user provides. For automated testing with synthetic data, see
tests/test_write_roundtrip.py.
"""
import sys
import os

# Add the addon directory to the path so shared modules are importable
addon_dir = os.path.abspath(os.path.dirname(__file__))
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

# Mock Blender modules so imports don't fail outside Blender
from unittest.mock import MagicMock
for mod in ('bpy', 'bpy.types', 'bpy.props', 'bpy_extras', 'bpy_extras.io_utils', 'mathutils'):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from shared.IO.DAT_io import DATParser, DATBuilder
from shared.Nodes.Node import Node


def compare_nodes(node_a, node_b, path="root", mismatches=None):
    """Recursively compare fields of two node trees. Returns list of mismatches."""
    if mismatches is None:
        mismatches = []

    if type(node_a) != type(node_b):
        mismatches.append(f"{path}: type mismatch {type(node_a).__name__} vs {type(node_b).__name__}")
        return mismatches

    if not hasattr(node_a, 'fields'):
        return mismatches

    for field_name, _ in node_a.fields:
        val_a = getattr(node_a, field_name, None)
        val_b = getattr(node_b, field_name, None)
        field_path = f"{path}.{field_name}"

        if isinstance(val_a, Node) and isinstance(val_b, Node):
            compare_nodes(val_a, val_b, field_path, mismatches)
        elif isinstance(val_a, (list, tuple)) and isinstance(val_b, (list, tuple)):
            if len(val_a) != len(val_b):
                mismatches.append(f"{field_path}: list length {len(val_a)} vs {len(val_b)}")
            else:
                for i, (a, b) in enumerate(zip(val_a, val_b)):
                    if isinstance(a, Node) and isinstance(b, Node):
                        compare_nodes(a, b, f"{field_path}[{i}]", mismatches)
                    elif isinstance(a, float) and isinstance(b, float):
                        if abs(a - b) > 1e-5:
                            mismatches.append(f"{field_path}[{i}]: {a} vs {b}")
                    elif a != b:
                        mismatches.append(f"{field_path}[{i}]: {a!r} vs {b!r}")
        elif isinstance(val_a, float) and isinstance(val_b, float):
            if abs(val_a - val_b) > 1e-5:
                mismatches.append(f"{field_path}: {val_a} vs {val_b}")
        elif val_a != val_b:
            # Skip address comparisons — they will differ
            if field_name not in ('address',):
                mismatches.append(f"{field_path}: {val_a!r} vs {val_b!r}")

    return mismatches


def byte_diff(data_a, data_b, max_diffs=20):
    """Return a list of (offset, byte_a, byte_b) for the first max_diffs differing bytes."""
    diffs = []
    for i in range(min(len(data_a), len(data_b))):
        if data_a[i] != data_b[i]:
            diffs.append((i, data_a[i], data_b[i]))
            if len(diffs) >= max_diffs:
                break
    return diffs


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    if not os.path.exists(input_path):
        print(f"Error: input file not found: {input_path}")
        sys.exit(1)

    options = {
        "verbose": False,
        "print_tree": False,
        "section_names": [],
    }

    # Phase 1: Parse input
    print(f"Parsing: {input_path}")
    parser = DATParser(input_path, options)
    parser.parseSections()

    sections = parser.sections
    print(f"  Parsed {len(sections)} section(s)")
    for s in sections:
        print(f"    - {s.section_name} ({s.root_node.class_name})")

    # Phase 2: Write output
    print(f"Writing: {output_path}")
    root_nodes = [s.root_node for s in sections]
    builder = DATBuilder(output_path, root_nodes)
    builder.build()
    builder.close()

    # Phase 3: Re-parse output
    print(f"Re-parsing: {output_path}")
    re_parser = DATParser(output_path, options)
    re_parser.parseSections()
    re_sections = re_parser.sections

    print(f"  Re-parsed {len(re_sections)} section(s)")

    # Phase 4: Compare
    print("\n--- Field Comparison ---")
    all_mismatches = []
    for i, (orig, rewritten) in enumerate(zip(sections, re_sections)):
        mismatches = compare_nodes(orig.root_node, rewritten.root_node, path=orig.section_name)
        all_mismatches.extend(mismatches)

    if all_mismatches:
        print(f"Found {len(all_mismatches)} field mismatch(es):")
        for m in all_mismatches[:50]:
            print(f"  {m}")
        if len(all_mismatches) > 50:
            print(f"  ... and {len(all_mismatches) - 50} more")
    else:
        print("All parsed fields match!")

    # Phase 5: Byte comparison
    print("\n--- Byte Comparison ---")
    with open(input_path, 'rb') as f:
        input_bytes = f.read()
    with open(output_path, 'rb') as f:
        output_bytes = f.read()

    print(f"  Input size:  {len(input_bytes)} bytes")
    print(f"  Output size: {len(output_bytes)} bytes")

    if input_bytes == output_bytes:
        print("  Byte-level match: YES")
    else:
        print("  Byte-level match: NO")
        diffs = byte_diff(input_bytes, output_bytes)
        if diffs:
            print(f"  First {len(diffs)} differing byte(s):")
            for offset, a, b in diffs:
                print(f"    0x{offset:08X}: 0x{a:02X} vs 0x{b:02X}")
        if len(input_bytes) != len(output_bytes):
            print(f"  Size difference: {len(output_bytes) - len(input_bytes):+d} bytes")

    parser.close()
    re_parser.close()


if __name__ == "__main__":
    main()
