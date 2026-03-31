#!/usr/bin/env python3
"""
Round-trip test runner for real model files.

Runs all four round-trip test types (NBN, NIN, BNB, IBI) on one or more
real .dat/.pkx model files and reports per-model scores.

Usage:
    python3 tests/round_trip/run_round_trips.py <model_file_or_directory>

    # Single file
    python3 tests/round_trip/run_round_trips.py ~/models/nukenin.pkx

    # All models in a directory
    python3 tests/round_trip/run_round_trips.py ~/models/

Requires: bpy (standalone module), mathutils
    pip install bpy mathutils

Test types:
    NBN  Node tree -> Binary -> Node tree   (field-level serialization fidelity)
    NIN  Node tree -> IR -> Node tree        (describe/compose round-trip)
    BNB  Binary -> Node tree -> Binary       (byte-level fidelity)
    IBI  IR -> Blender -> IR                 (Blender round-trip)
"""
import sys
import os
import io
from collections import Counter

# Add the addon directory to the path
addon_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

# Verify real bpy is available (not mocked)
try:
    import bpy
    if not hasattr(bpy.data, 'armatures'):
        print("Error: bpy is mocked, not real. Install standalone bpy: pip install bpy")
        sys.exit(1)
except ImportError:
    print("Error: bpy not installed. Install with: pip install bpy")
    sys.exit(1)

from importer.phases.extract.extract import extract_dat
from importer.phases.route.route import route_sections
from importer.phases.parse.parse import parse_sections
from importer.phases.describe.describe import describe_scene
from importer.phases.build_blender.build_blender import build_blender_scene
from exporter.phases.describe_blender.describe_blender import describe_blender_scene
from exporter.phases.compose.compose import compose_scene
from exporter.phases.serialize.helpers.dat_builder import DATBuilder
from importer.phases.parse.helpers.dat_parser import DATParser
from shared.Nodes.Node import Node
from shared.helpers.logger import StubLogger


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def load_model(filepath):
    """Run import phases 1-3 on a model file. Returns (dat_bytes, sections)."""
    with open(filepath, 'rb') as f:
        raw_bytes = f.read()
    filename = os.path.basename(filepath)
    entries = extract_dat(raw_bytes, filename)
    dat_bytes, metadata = entries[0]

    section_map = route_sections(dat_bytes)
    sections = parse_sections(dat_bytes, section_map, {})
    return dat_bytes, sections


def describe_ir(sections, options=None):
    """Run import phase 4 (describe) on parsed sections. Returns IRScene."""
    if options is None:
        options = {}
    return describe_scene(sections, options)


def build_in_blender(ir_scene, options=None):
    """Run import phase 5 (build_blender). Returns build_results.

    Strips animations and constraints before building since those features
    are not yet implemented in the export describe_blender phase, and the
    standalone bpy module may not support all Blender 4.5 animation APIs.
    """
    if options is None:
        options = {"filepath": "test_model"}

    # Strip features not yet supported by the export pipeline
    for model in ir_scene.models:
        model.bone_animations = []
        model.shape_animations = []
        model.ik_constraints = []
        model.copy_location_constraints = []
        model.track_to_constraints = []
        model.copy_rotation_constraints = []
        model.limit_rotation_constraints = []
        model.limit_location_constraints = []

    return build_blender_scene(ir_scene, bpy.context, options)


def read_back_from_blender(build_results):
    """Run export phase 1 (describe_blender). Returns (IRScene, shiny_params).

    Selects the armatures created during build before calling describe_blender.
    """
    # Select all armatures from the build
    bpy.ops.object.select_all(action='DESELECT')
    for result in build_results:
        armature = result['armature']
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

    return describe_blender_scene(bpy.context)


def clear_blender_scene():
    """Remove all objects from the Blender scene."""
    bpy.ops.object.select_all(action='DESELECT')
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    # Purge orphan data
    for block in bpy.data.meshes:
        bpy.data.meshes.remove(block)
    for block in bpy.data.armatures:
        bpy.data.armatures.remove(block)
    for block in bpy.data.materials:
        bpy.data.materials.remove(block)
    for block in bpy.data.images:
        bpy.data.images.remove(block)
    for block in bpy.data.actions:
        bpy.data.actions.remove(block)


# ---------------------------------------------------------------------------
# Scoring: NBN (Node -> Binary -> Node)
# ---------------------------------------------------------------------------

def compute_nbn_score(filepath):
    """Parse a file, serialize via DATBuilder, reparse, compare node fields."""
    dat_bytes, sections = load_model(filepath)

    # Serialize
    root_nodes = [s.root_node for s in sections]
    section_names = [s.section_name for s in sections]
    out_buf = io.BytesIO()
    builder = DATBuilder(out_buf, root_nodes, section_names)
    builder.build()
    rebuilt_bytes = out_buf.getvalue()

    # Reparse both (DATBuilder mutates nodes, so reparse originals too)
    dat_bytes2, sections_orig = load_model(filepath)
    buf2 = io.BytesIO(rebuilt_bytes)
    parser2 = DATParser(buf2, {"section_map": None})
    parser2.parseSections()
    sections_rebuilt = parser2.sections
    parser2.close()

    total, mismatches = 0, 0
    for orig, rebuilt in zip(sections_orig, sections_rebuilt):
        t, m = _compare_node_trees(orig.root_node, rebuilt.root_node)
        total += t
        mismatches += m

    matched = total - mismatches
    pct = (matched / total * 100) if total > 0 else 100.0
    return matched, total, pct


# ---------------------------------------------------------------------------
# Scoring: BNB (Binary -> Node -> Binary)
# ---------------------------------------------------------------------------

def compute_bnb_score(filepath):
    """Parse a file, write back, compare bytes with fuzzy word matching."""
    dat_bytes, sections = load_model(filepath)

    root_nodes = [s.root_node for s in sections]
    section_names = [s.section_name for s in sections]
    out_buf = io.BytesIO()
    builder = DATBuilder(out_buf, root_nodes, section_names)
    builder.build()
    rebuilt_bytes = out_buf.getvalue()

    # Compare DAT content (skip first 32 bytes = header)
    return _fuzzy_binary_match(dat_bytes[32:], rebuilt_bytes[32:])


# ---------------------------------------------------------------------------
# Scoring: NIN (Node -> IR -> Node)
# ---------------------------------------------------------------------------

def compute_nin_score(filepath):
    """Parse a file, describe to IR, compose back to nodes, compare."""
    _, sections = load_model(filepath)

    # Describe (phase 4)
    ir_scene = describe_ir(sections, options={})

    # Compose (phase 2 export)
    composed_nodes, _ = compose_scene(ir_scene, {})

    # Compare original root nodes against composed root nodes
    # The compose phase only produces scene_data roots, so match by section
    total, mismatches = 0, 0
    for section in sections:
        orig_root = section.root_node
        # Find corresponding composed node (compose outputs one root per model)
        comp_root = None
        if composed_nodes:
            comp_root = composed_nodes[0] if len(composed_nodes) > 0 else None

        t, m = _compare_node_trees_nin(orig_root, comp_root)
        total += t
        mismatches += m

    matched = total - mismatches
    pct = (matched / total * 100) if total > 0 else 100.0
    return matched, total, pct


# ---------------------------------------------------------------------------
# Scoring: IBI (IR -> Blender -> IR)
# ---------------------------------------------------------------------------

def compute_ibi_score(filepath):
    """Parse through phase 4 to get IR, build in Blender, read back, compare."""
    clear_blender_scene()

    _, sections = load_model(filepath)
    ir_original = describe_ir(sections, options={"filepath": filepath})

    # Build in Blender (phase 5)
    build_results = build_in_blender(ir_original, options={"filepath": filepath})

    # Read back from Blender (export phase 1)
    ir_roundtripped, _ = read_back_from_blender(build_results)

    # Compare IR scenes
    total, mismatches, details = _compare_ir_scenes(ir_original, ir_roundtripped)

    matched = total - mismatches
    pct = (matched / total * 100) if total > 0 else 100.0

    clear_blender_scene()
    return matched, total, pct, details


# ---------------------------------------------------------------------------
# IR comparison — generic dataclass walker
# ---------------------------------------------------------------------------

# Fields to skip during comparison (internal/computed, not meaningful for round-trip)
_SKIP_FIELDS = {
    # Pre-computed matrices — derived from position/rotation/scale, not independent data
    'world_matrix', 'local_matrix', 'normalized_world_matrix',
    'normalized_local_matrix', 'scale_correction', 'accumulated_scale',
    # Pre-computed deformed geometry — derived from bone weights + vertices
    'deformed_vertices', 'deformed_normals',
}

# Maximum number of detail lines to keep per mismatch category to avoid
# flooding output on large meshes
_MAX_DETAILS = 50


def _compare_ir_scenes(ir_a, ir_b):
    """Walk the ORIGINAL IR to count every field as the denominator.

    When the round-tripped side is missing data (None, empty list, etc.),
    all fields in the original subtree count as mismatches. This ensures
    the score reflects overall export completeness, not just the subset
    of features currently implemented.

    Returns (total, mismatches, details).
    """
    total = [0]
    mismatches = [0]
    details = []

    def _add_mismatch(path, msg):
        mismatches[0] += 1
        if len(details) < _MAX_DETAILS:
            details.append(f"{path}: {msg}")

    def _walk(orig, comp, path):
        """Recursively compare an original value against its round-tripped counterpart."""
        if orig is None:
            return

        # Dataclass: walk all fields
        if _is_dataclass(orig):
            for field_name in _dataclass_field_names(orig):
                if field_name in _SKIP_FIELDS:
                    continue
                val_orig = getattr(orig, field_name, None)
                val_comp = getattr(comp, field_name, None) if comp is not None else None
                _walk(val_orig, val_comp, f"{path}.{field_name}")
            return

        # List/tuple: compare length then elements
        if isinstance(orig, (list, tuple)):
            total[0] += 1
            comp_list = comp if isinstance(comp, (list, tuple)) else []
            if len(orig) != len(comp_list):
                _add_mismatch(path, f"length {len(orig)} vs {len(comp_list)}")
                # Count all elements in the original as mismatches for the missing portion
                if len(comp_list) < len(orig):
                    for i in range(len(comp_list), len(orig)):
                        count = _count_fields(orig[i])
                        total[0] += count
                        mismatches[0] += count
                # Walk elements that exist in both
                for i in range(min(len(orig), len(comp_list))):
                    _walk(orig[i], comp_list[i], f"{path}[{i}]")
            else:
                for i in range(len(orig)):
                    _walk(orig[i], comp_list[i], f"{path}[{i}]")
            return

        # bytes: compare as a single field
        if isinstance(orig, bytes):
            total[0] += 1
            if orig != comp:
                _add_mismatch(path, f"{len(orig)} bytes vs {len(comp) if isinstance(comp, bytes) else type(comp).__name__}")
            return

        # Enum: compare by value
        if hasattr(orig, 'value') and hasattr(type(orig), '__members__'):
            total[0] += 1
            if comp is None or not hasattr(comp, 'value') or orig.value != comp.value:
                _add_mismatch(path, f"{orig!r} vs {comp!r}")
            return

        # Float: compare with tolerance
        if isinstance(orig, float):
            total[0] += 1
            if not isinstance(comp, (int, float)) or abs(orig - comp) > 1e-4:
                _add_mismatch(path, f"{orig:.6f} vs {comp}")
            return

        # int, bool, str, other primitives
        total[0] += 1
        if orig != comp:
            _add_mismatch(path, f"{orig!r} vs {comp!r}")

    _walk(ir_a, ir_b, "scene")

    matched = total[0] - mismatches[0]
    return total[0], mismatches[0], details


def _is_dataclass(obj):
    """Check if an object is a dataclass instance (not a class)."""
    return hasattr(obj, '__dataclass_fields__')


def _dataclass_field_names(obj):
    """Get field names for a dataclass instance."""
    return list(obj.__dataclass_fields__.keys())


def _count_fields(obj):
    """Count the total number of comparable fields in an IR value (for scoring missing subtrees)."""
    if obj is None:
        return 0
    if _is_dataclass(obj):
        count = 0
        for name in _dataclass_field_names(obj):
            if name in _SKIP_FIELDS:
                continue
            count += _count_fields(getattr(obj, name, None))
        return count
    if isinstance(obj, (list, tuple)):
        return 1 + sum(_count_fields(item) for item in obj)
    # Primitive (float, int, str, bool, bytes, enum)
    return 1


# ---------------------------------------------------------------------------
# Node tree comparison helpers
# ---------------------------------------------------------------------------

def _compare_node_trees(node_a, node_b):
    """Recursively compare two node trees. Returns (total_fields, mismatches)."""
    total = 0
    mismatches = 0
    visited = set()

    def _walk(a, b):
        nonlocal total, mismatches
        if a is None and b is None:
            return
        if a is None or b is None:
            total += 1
            mismatches += 1
            return
        if id(a) in visited:
            return
        visited.add(id(a))

        if not hasattr(a, 'fields'):
            return

        for field_name, _ in a.fields:
            if field_name == 'address':
                continue
            val_a = getattr(a, field_name, None)
            val_b = getattr(b, field_name, None)

            if isinstance(val_a, Node):
                total += 1
                if not isinstance(val_b, Node):
                    mismatches += 1
                else:
                    _walk(val_a, val_b)
            elif isinstance(val_a, (list, tuple)):
                total += 1
                if not isinstance(val_b, (list, tuple)) or len(val_a) != len(val_b):
                    mismatches += 1
                else:
                    for i, (ia, ib) in enumerate(zip(val_a, val_b)):
                        if isinstance(ia, Node):
                            total += 1
                            if not isinstance(ib, Node):
                                mismatches += 1
                            else:
                                _walk(ia, ib)
                        else:
                            total += 1
                            if isinstance(ia, float) and isinstance(ib, float):
                                if abs(ia - ib) > 1e-5:
                                    mismatches += 1
                            elif ia != ib:
                                mismatches += 1
            else:
                total += 1
                if isinstance(val_a, float) and isinstance(val_b, float):
                    if abs(val_a - val_b) > 1e-5:
                        mismatches += 1
                elif val_a != val_b:
                    mismatches += 1

    _walk(node_a, node_b)
    return total, mismatches


def _compare_node_trees_nin(orig, composed):
    """NIN comparison: walk the ORIGINAL tree to count all fields.

    When the composed side is missing a subtree, all fields in that
    original subtree count as mismatches.
    """
    total = 0
    mismatches = 0
    visited = set()

    def _walk(orig_node, comp_node):
        nonlocal total, mismatches
        if orig_node is None:
            return
        if id(orig_node) in visited:
            return
        visited.add(id(orig_node))

        if not hasattr(orig_node, 'fields'):
            return

        for field_name, _ in orig_node.fields:
            if field_name == 'address':
                continue

            val_orig = getattr(orig_node, field_name, None)
            val_comp = getattr(comp_node, field_name, None) if comp_node is not None else None

            if isinstance(val_orig, Node):
                total += 1
                comp_child = val_comp if isinstance(val_comp, Node) else None
                if comp_child is None:
                    mismatches += 1
                _walk(val_orig, comp_child)
            elif isinstance(val_orig, (list, tuple)):
                comp_list = val_comp if isinstance(val_comp, (list, tuple)) else []
                total += 1
                if len(val_orig) != len(comp_list):
                    mismatches += 1
                for i, item in enumerate(val_orig):
                    comp_item = comp_list[i] if i < len(comp_list) else None
                    if isinstance(item, Node):
                        total += 1
                        comp_node_item = comp_item if isinstance(comp_item, Node) else None
                        if comp_node_item is None:
                            mismatches += 1
                        _walk(item, comp_node_item)
                    else:
                        total += 1
                        if isinstance(item, float) and isinstance(comp_item, float):
                            if abs(item - comp_item) > 1e-5:
                                mismatches += 1
                        elif item != comp_item:
                            mismatches += 1
            else:
                total += 1
                if isinstance(val_orig, float) and isinstance(val_comp, float):
                    if abs(val_orig - val_comp) > 1e-5:
                        mismatches += 1
                elif val_orig != val_comp:
                    mismatches += 1

    _walk(orig, composed)
    return total, mismatches


def _fuzzy_binary_match(data_a, data_b):
    """Compare two byte sequences using 4-byte word frequency matching."""
    if len(data_a) < 4 and len(data_b) < 4:
        return 0, 0, 100.0

    words_a = Counter()
    words_b = Counter()
    for i in range(0, len(data_a) - 3, 4):
        words_a[data_a[i:i+4]] += 1
    for i in range(0, len(data_b) - 3, 4):
        words_b[data_b[i:i+4]] += 1

    matched = sum((words_a & words_b).values())
    total = max(sum(words_a.values()), sum(words_b.values()))
    pct = (matched / total * 100) if total > 0 else 100.0
    return matched, total, pct


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {'.dat', '.fdat', '.rdat', '.pkx'}


def find_model_files(path):
    """Find all supported model files at the given path."""
    if os.path.isfile(path):
        return [path]
    if os.path.isdir(path):
        files = []
        for f in sorted(os.listdir(path)):
            if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS:
                files.append(os.path.join(path, f))
        return files
    return []


def run_all_tests(filepath):
    """Run all round-trip tests on a single model file. Returns dict of scores."""
    name = os.path.splitext(os.path.basename(filepath))[0]
    scores = {'name': name}

    # NBN
    try:
        matched, total, pct = compute_nbn_score(filepath)
        scores['nbn'] = pct
    except Exception as e:
        scores['nbn'] = f"ERROR: {e}"

    # BNB
    try:
        matched, total, pct = compute_bnb_score(filepath)
        scores['bnb'] = pct
    except Exception as e:
        scores['bnb'] = f"ERROR: {e}"

    # NIN
    try:
        matched, total, pct = compute_nin_score(filepath)
        scores['nin'] = pct
    except Exception as e:
        scores['nin'] = f"ERROR: {e}"

    # IBI
    try:
        matched, total, pct, details = compute_ibi_score(filepath)
        scores['ibi'] = pct
        scores['ibi_details'] = details
    except Exception as e:
        scores['ibi'] = f"ERROR: {e}"
        import traceback
        scores['ibi_details'] = [traceback.format_exc()]

    return scores


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    flags = [a for a in sys.argv[1:] if a.startswith('-')]

    if not args:
        print(__doc__)
        sys.exit(1)

    files = []
    for path in args:
        files.extend(find_model_files(path))

    if not files:
        print(f"No supported model files found at: {args}")
        sys.exit(1)

    verbose = '--verbose' in flags or '-v' in flags

    print(f"Running round-trip tests on {len(files)} model(s)...\n")

    all_scores = []
    for filepath in files:
        name = os.path.splitext(os.path.basename(filepath))[0]
        print(f"  {name}...", end=' ', flush=True)
        scores = run_all_tests(filepath)
        all_scores.append(scores)

        parts = []
        for key in ('nbn', 'nin', 'ibi', 'bnb'):
            val = scores.get(key)
            if isinstance(val, float):
                parts.append(f"{key.upper()}={val:.1f}%")
            else:
                parts.append(f"{key.upper()}={val}")
        print('  '.join(parts))

        if verbose and scores.get('ibi_details'):
            for detail in scores['ibi_details'][:20]:
                print(f"    {detail}")

    # Summary table
    print(f"\n{'='*70}")
    print(f"{'Model':<20} {'NBN':>8} {'NIN':>8} {'IBI':>8} {'BNB':>8}")
    print(f"{'-'*20} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for scores in all_scores:
        row = f"{scores['name']:<20}"
        for key in ('nbn', 'nin', 'ibi', 'bnb'):
            val = scores.get(key)
            if isinstance(val, float):
                row += f" {val:>7.1f}%"
            else:
                row += f" {'ERR':>7}%"
        print(row)


if __name__ == '__main__':
    main()
