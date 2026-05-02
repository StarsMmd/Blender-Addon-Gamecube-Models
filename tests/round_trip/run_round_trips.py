#!/usr/bin/env python3
"""
Round-trip test runner for real model files.

Runs all five round-trip test types (NBN, NIN, BNB, BBB, IBI) on one or more
real .dat/.pkx model files and reports per-model scores.

Usage:
    python3 tests/round_trip/run_round_trips.py <model_file_or_directory>

    # Single file
    python3 tests/round_trip/run_round_trips.py ~/models/model.pkx

    # All models in a directory
    python3 tests/round_trip/run_round_trips.py ~/models/

Requires: bpy (standalone module), mathutils
    pip install bpy mathutils

Test types:
    NBN  Node tree -> Binary -> Node tree    (field-level serialization fidelity)
    NIN  Node tree -> IR -> Node tree         (describe/compose round-trip)
    BNB  Binary -> Node tree -> Binary        (byte-level fidelity)
    BBB  BR -> Blender -> BR                  (build/describe round-trip; bounds the
                                              Blender-facing leg only — no IR↔BR involvement)
    IBI  IR -> BR -> Blender -> BR -> IR      (full Blender round-trip; bounds Plan
                                              on both sides plus build/describe)
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
from importer.phases.plan.plan import plan_scene as plan_ir_to_br
from importer.phases.build_blender.build_blender import build_blender_scene
from exporter.phases.describe.describe import describe_scene as describe_blender_to_br
from exporter.phases.plan.plan import plan_scene as plan_br_to_ir
from exporter.phases.compose.compose import compose_scene
from exporter.phases.serialize.helpers.dat_builder import DATBuilder
from importer.phases.parse.helpers.dat_parser import DATParser
from shared.Nodes.Node import Node
from shared.helpers.logger import StubLogger, Logger

# Register custom bpy properties needed for round-trip tests
# (normally registered by BlenderPlugin.register())
if not hasattr(bpy.types.Image, 'dat_gx_format'):
    from bpy.props import EnumProperty
    bpy.types.Image.dat_gx_format = EnumProperty(
        name="GX Texture Format",
        items=[
            ('AUTO', 'Auto', ''), ('CMPR', 'CMPR', ''), ('RGBA8', 'RGBA8', ''),
            ('RGB565', 'RGB565', ''), ('RGB5A3', 'RGB5A3', ''),
            ('I4', 'I4', ''), ('I8', 'I8', ''), ('IA4', 'IA4', ''), ('IA8', 'IA8', ''),
            ('C4', 'C4', ''), ('C8', 'C8', ''),
        ],
        default='AUTO',
    )


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


def describe_ir(sections, options=None, logger=None):
    """Run import phase 4 (describe) on parsed sections. Returns IRScene."""
    if options is None:
        options = {}
    if logger is None:
        logger = StubLogger()
    return describe_scene(sections, options, logger=logger)


def plan_to_br(ir_scene, options=None, logger=None):
    """Run import phase 5a (plan). Returns BRScene."""
    if options is None:
        options = {"filepath": "test_model"}
    if logger is None:
        logger = StubLogger()
    return plan_ir_to_br(ir_scene, options=options, logger=logger)


def build_in_blender(br_scene, options=None):
    """Run import phase 5b (build_blender). Returns build_results."""
    if options is None:
        options = {"filepath": "test_model"}
    # Enable all optional features for round-trip testing. Without
    # import_cameras=True, build_blender skips the camera build entirely
    # (default False) and the IBI camera category scores 0%(0/100) — not
    # because readback is broken, but because no cameras ever entered
    # the scene to read back.
    options.setdefault("import_lights", True)
    options.setdefault("import_cameras", True)
    # Round-trip tests measure pure build → describe → BR fidelity, so
    # we deliberately skip the import-side bake here. The describe
    # phase no longer validates baked transforms (validation lives in
    # pre_process and plan), and IBI passes the BR-side check via
    # `skip_baked_transforms_validation=True` in `read_back_from_blender`.
    return build_blender_scene(br_scene, bpy.context, options)


def describe_back_to_br():
    """Run export phase 1 (describe). Returns (BRScene, shiny_params, pkx_header)."""
    return describe_blender_to_br(bpy.context)


def read_back_from_blender(build_results):
    """Run export phases 1-2 (describe → plan). Returns (IRScene, shiny_params, pkx_header).

    Describes all armatures in the scene (no selection needed).
    """
    br_scene, shiny_params, pkx_header = describe_blender_to_br(bpy.context)
    # Round-trip BRs come from importer-built scenes that intentionally
    # carry the Y-up→Z-up viewing rotation in armature.matrix_basis;
    # production exports require identity matrix_basis (caught by
    # pre_process + plan), but the test fidelity check should pass that
    # data through unchanged.
    ir_scene = plan_br_to_ir(
        br_scene,
        options={'skip_baked_transforms_validation': True},
    )
    return ir_scene, shiny_params, pkx_header


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

    total, errors, misses = 0, 0, 0
    for orig, rebuilt in zip(sections_orig, sections_rebuilt):
        t, e, m = _compare_node_trees(orig.root_node, rebuilt.root_node)
        total += t
        errors += e
        misses += m

    pct = ((total - errors - misses) / total * 100) if total > 0 else 100.0
    err_pct = (errors / total * 100) if total > 0 else 0.0
    miss_pct = (misses / total * 100) if total > 0 else 0.0
    return pct, err_pct, miss_pct


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
    matched, total, errors, misses = _fuzzy_binary_match(dat_bytes[32:], rebuilt_bytes[32:])
    pct = (matched / total * 100) if total > 0 else 100.0
    err_pct = (errors / total * 100) if total > 0 else 0.0
    miss_pct = (misses / total * 100) if total > 0 else 0.0
    return pct, err_pct, miss_pct


# ---------------------------------------------------------------------------
# Scoring: NIN (Node -> IR -> Node)
# ---------------------------------------------------------------------------

def compute_nin_score(filepath, logger=None):
    """Parse a file, describe to IR, compose back to nodes, compare."""
    _, sections = load_model(filepath)

    # Describe (phase 4)
    ir_scene = describe_ir(sections, options={}, logger=logger)

    # Compose (phase 2 export)
    composed_nodes, _ = compose_scene(ir_scene, {'strip_names': True})

    # Compare original root nodes against composed root nodes.
    # Match by node type — each original section finds the composed node
    # of the same class (SceneData↔SceneData, BoundBox↔BoundBox, etc.).
    total, errors, misses = 0, 0, 0
    all_details = []
    comp_by_type = {}
    for node in composed_nodes:
        comp_by_type[type(node).__name__] = node

    for section in sections:
        orig_root = section.root_node
        orig_type = type(orig_root).__name__
        comp_root = comp_by_type.get(orig_type)

        t, e, m, details = _compare_node_trees_nin(orig_root, comp_root)
        total += t
        errors += e
        misses += m
        all_details.extend(details)

    pct = ((total - errors - misses) / total * 100) if total > 0 else 100.0
    err_pct = (errors / total * 100) if total > 0 else 0.0
    miss_pct = (misses / total * 100) if total > 0 else 0.0
    return pct, err_pct, miss_pct, all_details


# ---------------------------------------------------------------------------
# Scoring: IBI (IR -> Blender -> IR)
# ---------------------------------------------------------------------------

def compute_ibi_score(filepath, logger=None):
    """Parse through phase 4 to get IR, build in Blender, read back, compare.

    Uses category-weighted scoring: each IR category (bones, meshes,
    materials, animations, constraints, lights) is scored independently,
    then the scores are averaged across categories that have data. This
    prevents large vertex arrays from drowning out other features.
    """
    clear_blender_scene()

    _, sections = load_model(filepath)
    options = {"filepath": filepath}
    ir_original = describe_ir(sections, options=options, logger=logger)

    # Plan IR → BR (phase 5a), then build (phase 5b)
    br_scene = plan_to_br(ir_original, options={"filepath": filepath}, logger=logger)
    build_results = build_in_blender(br_scene, options={"filepath": filepath})

    # Read back from Blender (export phase 1 → phase 2)
    ir_roundtripped, _, _ = read_back_from_blender(build_results)

    # Compare IR scenes by category
    categories, details = _compare_ir_by_category(ir_original, ir_roundtripped)

    # Average across categories that have data
    scored = {k: v for k, v in categories.items() if v['total'] > 0}
    if scored:
        pct = sum(v['pct'] for v in scored.values()) / len(scored)
        err_pct = sum(v['errors'] / v['total'] * 100 for v in scored.values()) / len(scored)
        miss_pct = sum(v['misses'] / v['total'] * 100 for v in scored.values()) / len(scored)
    else:
        pct, err_pct, miss_pct = 100.0, 0.0, 0.0

    clear_blender_scene()
    return pct, err_pct, miss_pct, details, categories


# ---------------------------------------------------------------------------
# Scoring: BBB (BR -> Blender -> BR)
# ---------------------------------------------------------------------------

def compute_bbb_score(filepath, logger=None):
    """Plan a BR from the file, build in Blender, describe back to BR, compare.

    Bounds the Blender-facing leg of the pipeline (build + describe) without
    re-crossing the BR↔IR boundary. The reference BR is the one produced by
    the importer's Plan phase from the on-disk model; the read-back BR is
    what the exporter's describe phase recovers from the built scene.
    """
    clear_blender_scene()

    _, sections = load_model(filepath)
    options = {"filepath": filepath}
    ir_original = describe_ir(sections, options=options, logger=logger)
    br_original = plan_to_br(ir_original, options={"filepath": filepath}, logger=logger)

    build_in_blender(br_original, options={"filepath": filepath})
    br_roundtripped, _, _ = describe_back_to_br()

    categories, details = _compare_br_by_category(br_original, br_roundtripped)

    scored = {k: v for k, v in categories.items() if v['total'] > 0}
    if scored:
        pct = sum(v['pct'] for v in scored.values()) / len(scored)
        err_pct = sum(v['errors'] / v['total'] * 100 for v in scored.values()) / len(scored)
        miss_pct = sum(v['misses'] / v['total'] * 100 for v in scored.values()) / len(scored)
    else:
        pct, err_pct, miss_pct = 100.0, 0.0, 0.0

    clear_blender_scene()
    return pct, err_pct, miss_pct, details, categories


def _compare_br_by_category(br_a, br_b):
    """Compare two BRScenes with per-category scoring.

    Categories mirror the BR structure rather than the IR structure: bones
    come from each model's armature, materials live as a top-level list on
    BRModel (not per-mesh), and constraints share one BRConstraints holder.
    """
    categories = {}
    all_details = []

    models_a = br_a.models if br_a else []
    models_b = br_b.models if br_b else []

    for mi in range(max(len(models_a), len(models_b))):
        ma = models_a[mi] if mi < len(models_a) else None
        mb = models_b[mi] if mi < len(models_b) else None
        if ma is None:
            continue

        bones_a = ma.armature.bones if ma.armature else []
        bones_b = mb.armature.bones if (mb and mb.armature) else []
        _score_category(categories, all_details, 'bones',
                        bones_a, bones_b, f"model[{mi}].armature.bones")

        _score_category(categories, all_details, 'meshes',
                        ma.meshes, mb.meshes if mb else [],
                        f"model[{mi}].meshes")

        _score_category(categories, all_details, 'materials',
                        ma.materials, mb.materials if mb else [],
                        f"model[{mi}].materials")

        _score_category(categories, all_details, 'actions',
                        ma.actions, mb.actions if mb else [],
                        f"model[{mi}].actions")

        cons_a = ma.constraints
        cons_b = mb.constraints if mb else None
        cons_list_a = (cons_a.ik + cons_a.copy_location + cons_a.track_to +
                       cons_a.copy_rotation + cons_a.limit_rotation +
                       cons_a.limit_location) if cons_a else []
        cons_list_b = (cons_b.ik + cons_b.copy_location + cons_b.track_to +
                       cons_b.copy_rotation + cons_b.limit_rotation +
                       cons_b.limit_location) if cons_b else []
        _score_category(categories, all_details, 'constraints',
                        cons_list_a, cons_list_b,
                        f"model[{mi}].constraints")

    _score_category(categories, all_details, 'lights',
                    br_a.lights if br_a else [],
                    br_b.lights if br_b else [],
                    "scene.lights")

    _score_category(categories, all_details, 'cameras',
                    br_a.cameras if br_a else [],
                    br_b.cameras if br_b else [],
                    "scene.cameras")

    return categories, all_details


# ---------------------------------------------------------------------------
# IR comparison — category-weighted scoring
# ---------------------------------------------------------------------------

# Fields to skip during comparison (internal/computed, not meaningful for round-trip)
_SKIP_FIELDS = {
    # Pre-computed matrices — derived from position/rotation/scale, not independent data
    'world_matrix', 'local_matrix', 'normalized_world_matrix',
    'normalized_local_matrix', 'scale_correction', 'accumulated_scale',
    # Pre-computed deformed geometry — derived from bone weights + vertices
    'deformed_vertices', 'deformed_normals',
    # Convenience/metadata — DAT file offsets used as cache keys, not model data
    'image_id', 'palette_id',
    # Internal IDs — opaque foreign-key targets that cross-reference entities
    # within a single pipeline run. Importer and exporter mint these
    # independently for their own binding purposes; identity across a
    # build → describe round-trip is not a fidelity concern, only that
    # the bindings work *within* each side.
    'mesh_key',           # BRMesh: binds material-anim tracks
    'cache_key',          # BRImage: dedup identity for build-side image reuse
    'dedup_key',          # BRMaterial: dedup identity for build-side material reuse
    'material_mesh_name', # IR/BRMaterialTrack: foreign key into mesh list
}

# Maximum number of detail lines per category
_MAX_DETAILS_PER_CAT = 10


def _compare_ir_by_category(ir_a, ir_b):
    """Compare two IRScenes with per-category scoring.

    Categories:
        bones      — IRBone list (SRT, flags, hierarchy, inverse_bind)
        meshes     — IRMesh list (geometry, UVs, colors, normals, weights)
        materials  — IRMaterial on each mesh
        animations — IRBoneAnimationSet list
        constraints — all constraint lists
        lights     — IRLight list

    Returns:
        (categories_dict, details_list)
        categories_dict maps category name → {total, mismatches, pct}
    """
    categories = {}
    all_details = []

    # Compare per-model
    models_a = ir_a.models if ir_a else []
    models_b = ir_b.models if ir_b else []

    for mi in range(max(len(models_a), len(models_b))):
        ma = models_a[mi] if mi < len(models_a) else None
        mb = models_b[mi] if mi < len(models_b) else None
        if ma is None:
            continue

        # Bones
        _score_category(categories, all_details, 'bones',
                        ma.bones, mb.bones if mb else [],
                        f"model[{mi}].bones")

        # Meshes (geometry only, material scored separately)
        meshes_a_no_mat = []
        meshes_b_no_mat = []
        for m in ma.meshes:
            meshes_a_no_mat.append(_strip_material(m))
        if mb:
            for m in mb.meshes:
                meshes_b_no_mat.append(_strip_material(m))
        _score_category(categories, all_details, 'meshes',
                        meshes_a_no_mat, meshes_b_no_mat,
                        f"model[{mi}].meshes")

        # Materials (from each mesh's .material field)
        mats_a = [m.material for m in ma.meshes]
        mats_b = [m.material for m in mb.meshes] if mb else []
        _score_category(categories, all_details, 'materials',
                        mats_a, mats_b,
                        f"model[{mi}].materials")

        # Animations
        _score_category(categories, all_details, 'animations',
                        ma.bone_animations,
                        mb.bone_animations if mb else [],
                        f"model[{mi}].bone_animations")

        # Constraints (combine all constraint lists)
        cons_a = (ma.ik_constraints + ma.copy_location_constraints +
                  ma.track_to_constraints + ma.copy_rotation_constraints +
                  ma.limit_rotation_constraints + ma.limit_location_constraints)
        cons_b = []
        if mb:
            cons_b = (mb.ik_constraints + mb.copy_location_constraints +
                      mb.track_to_constraints + mb.copy_rotation_constraints +
                      mb.limit_rotation_constraints + mb.limit_location_constraints)
        _score_category(categories, all_details, 'constraints',
                        cons_a, cons_b,
                        f"model[{mi}].constraints")

    # Lights
    _score_category(categories, all_details, 'lights',
                    ir_a.lights if ir_a else [],
                    ir_b.lights if ir_b else [],
                    "scene.lights")

    # Cameras
    _score_category(categories, all_details, 'cameras',
                    ir_a.cameras if ir_a else [],
                    ir_b.cameras if ir_b else [],
                    "scene.cameras")

    return categories, all_details


def _strip_material(mesh):
    """Create a shallow copy of an IRMesh-like object without the material field."""
    class MeshNoMat:
        pass
    m = MeshNoMat()
    m.__dataclass_fields__ = {k: v for k, v in mesh.__dataclass_fields__.items()
                               if k != 'material'}
    for k in m.__dataclass_fields__:
        setattr(m, k, getattr(mesh, k))
    return m


def _score_category(categories, all_details, cat_name, list_a, list_b, path_prefix):
    """Score a single category by comparing two lists of IR objects.

    Categories where the original data is empty (no items to test) are
    recorded with total=0 so they're excluded from the average.
    """
    if cat_name not in categories:
        categories[cat_name] = {'total': 0, 'errors': 0, 'misses': 0, 'pct': 0.0}

    # Skip categories where the original has no data — nothing to test
    orig_items = list_a if isinstance(list_a, (list, tuple)) else [list_a]
    if not any(item is not None for item in orig_items):
        return

    cat = categories[cat_name]
    details = []

    total, errors, misses = _compare_ir_values(list_a, list_b, path_prefix, details)
    cat['total'] += total
    cat['errors'] += errors
    cat['misses'] += misses
    cat['pct'] = ((cat['total'] - cat['errors'] - cat['misses']) / cat['total'] * 100
                  if cat['total'] > 0 else 0.0)

    all_details.extend(details[:_MAX_DETAILS_PER_CAT])


def _compare_ir_values(orig, comp, path, details):
    """Compare two IR values recursively.

    Returns (total, errors, misses) where:
        total  — number of comparable fields in the original
        errors — fields present in both but with different values
        misses — fields present in original but missing/None in round-tripped
    """
    total = [0]
    errors = [0]
    misses = [0]

    def _add_error(p, msg):
        errors[0] += 1
        details.append(f"{p}: {msg}")

    def _add_miss(p, msg):
        misses[0] += 1
        details.append(f"{p}: [MISS] {msg}")

    def _add_miss_count(count):
        """Bulk-add misses for missing subtree fields."""
        misses[0] += count

    def _is_missing(val):
        """Check if a round-tripped value is missing (None or wrong type)."""
        return val is None

    def _walk(orig_val, comp_val, p):
        if orig_val is None:
            return

        # Dataclass: walk all fields
        if _is_dataclass(orig_val):
            for field_name in _dataclass_field_names(orig_val):
                if field_name in _SKIP_FIELDS:
                    continue
                val_orig = getattr(orig_val, field_name, None)
                val_comp = getattr(comp_val, field_name, None) if comp_val is not None else None
                _walk(val_orig, val_comp, f"{p}.{field_name}")
            return

        # List/tuple
        if isinstance(orig_val, (list, tuple)):
            total[0] += 1
            comp_list = comp_val if isinstance(comp_val, (list, tuple)) else []
            if len(orig_val) != len(comp_list):
                if len(comp_list) == 0 and len(orig_val) > 0:
                    _add_miss(p, f"length {len(orig_val)} vs {len(comp_list)}")
                else:
                    _add_error(p, f"length {len(orig_val)} vs {len(comp_list)}")
                if len(comp_list) < len(orig_val):
                    for i in range(len(comp_list), len(orig_val)):
                        count = _count_fields(orig_val[i])
                        total[0] += count
                        _add_miss_count(count)
                for i in range(min(len(orig_val), len(comp_list))):
                    _walk(orig_val[i], comp_list[i], f"{p}[{i}]")
            else:
                for i in range(len(orig_val)):
                    _walk(orig_val[i], comp_list[i], f"{p}[{i}]")
            return

        # bytes
        if isinstance(orig_val, bytes):
            total[0] += 1
            if orig_val != comp_val:
                if _is_missing(comp_val):
                    _add_miss(p, f"{len(orig_val)} bytes vs None")
                else:
                    _add_error(p, f"{len(orig_val)} bytes vs {len(comp_val) if isinstance(comp_val, bytes) else type(comp_val).__name__}")
            return

        # Enum
        if hasattr(orig_val, 'value') and hasattr(type(orig_val), '__members__'):
            total[0] += 1
            if comp_val is None or not hasattr(comp_val, 'value'):
                _add_miss(p, f"{orig_val!r} vs {comp_val!r}")
            elif orig_val.value != comp_val.value:
                _add_error(p, f"{orig_val!r} vs {comp_val!r}")
            return

        # Float
        if isinstance(orig_val, float):
            total[0] += 1
            if _is_missing(comp_val):
                _add_miss(p, f"{orig_val:.6f} vs None")
            elif not isinstance(comp_val, (int, float)) or abs(orig_val - comp_val) > 1e-4:
                _add_error(p, f"{orig_val:.6f} vs {comp_val}")
            return

        # Other primitives
        total[0] += 1
        if _is_missing(comp_val):
            _add_miss(p, f"{orig_val!r} vs None")
        elif orig_val != comp_val:
            _add_error(p, f"{orig_val!r} vs {comp_val!r}")

    _walk(orig, comp, path)
    return total[0], errors[0], misses[0]


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
    """Recursively compare two node trees. Returns (total, errors, misses)."""
    total = 0
    errors = 0
    misses = 0
    visited = set()

    def _walk(a, b):
        nonlocal total, errors, misses
        if a is None and b is None:
            return
        if a is None or b is None:
            total += 1
            misses += 1
            return
        if id(a) in visited:
            return
        visited.add(id(a))

        if not hasattr(a, 'fields'):
            return

        for field_name, _ in a.fields:
            if field_name in _NODE_SKIP_FIELDS:
                continue
            val_a = getattr(a, field_name, None)
            val_b = getattr(b, field_name, None)

            if isinstance(val_a, Node):
                total += 1
                if not isinstance(val_b, Node):
                    misses += 1
                else:
                    _walk(val_a, val_b)
            elif isinstance(val_a, (list, tuple)):
                total += 1
                if not isinstance(val_b, (list, tuple)) or len(val_a) != len(val_b):
                    errors += 1
                else:
                    for i, (ia, ib) in enumerate(zip(val_a, val_b)):
                        if isinstance(ia, Node):
                            total += 1
                            if not isinstance(ib, Node):
                                misses += 1
                            else:
                                _walk(ia, ib)
                        else:
                            total += 1
                            if isinstance(ia, float) and isinstance(ib, float):
                                if abs(ia - ib) > 1e-5:
                                    errors += 1
                            elif ia != ib:
                                errors += 1
            else:
                total += 1
                if isinstance(val_a, float) and isinstance(val_b, float):
                    if abs(val_a - val_b) > 1e-5:
                        errors += 1
                elif val_a != val_b:
                    errors += 1

    _walk(node_a, node_b)
    return total, errors, misses


# Node fields to skip in NIN/NBN comparisons — file offsets and
# address-like fields that change between builds but aren't model data
_NODE_SKIP_FIELDS = {'address', 'data_address', 'display_list_address', 'base_pointer'}


def _is_inactive_tev(field_name, node):
    """Return True if this is a TEV node with no active stages (dead data)."""
    if field_name != 'tev':
        return False
    return (type(node).__name__ == 'TextureTEV'
            and getattr(node, 'active', None) == 0)


def _compare_node_trees_nin(orig, composed):
    """NIN comparison: walk the ORIGINAL tree to count all fields.

    When the composed side is missing a subtree, all fields in that
    original subtree count as misses.
    """
    total = 0
    errors = 0
    misses = 0
    details = []
    visited = set()

    def _node_label(node):
        cls = type(node).__name__
        addr = getattr(node, 'address', None)
        return f"{cls}@{addr:#x}" if addr is not None else cls

    def _walk(orig_node, comp_node, path="root"):
        nonlocal total, errors, misses
        if orig_node is None:
            return
        if id(orig_node) in visited:
            return
        visited.add(id(orig_node))

        if not hasattr(orig_node, 'fields'):
            return

        node_path = f"{path}({_node_label(orig_node)})"
        for field_name, _ in orig_node.fields:
            if field_name in _NODE_SKIP_FIELDS:
                continue

            val_orig = getattr(orig_node, field_name, None)
            val_comp = getattr(comp_node, field_name, None) if comp_node is not None else None
            fp = f"{node_path}.{field_name}"

            if isinstance(val_orig, Node):
                # Skip TEV nodes with no active stages — dead data
                if _is_inactive_tev(field_name, val_orig):
                    continue
                total += 1
                comp_child = val_comp if isinstance(val_comp, Node) else None
                if comp_child is None:
                    misses += 1
                    details.append(f"MISS {fp}: {_node_label(val_orig)} vs None")
                _walk(val_orig, comp_child, fp)
            elif isinstance(val_orig, (list, tuple)):
                comp_list = val_comp if isinstance(val_comp, (list, tuple)) else []
                total += 1
                if len(val_orig) != len(comp_list):
                    if len(comp_list) == 0:
                        misses += 1
                        details.append(f"MISS {fp}: len={len(val_orig)} vs empty")
                    else:
                        errors += 1
                        details.append(f"ERR  {fp}: len={len(val_orig)} vs {len(comp_list)}")
                for i, item in enumerate(val_orig):
                    comp_item = comp_list[i] if i < len(comp_list) else None
                    if isinstance(item, Node):
                        total += 1
                        comp_node_item = comp_item if isinstance(comp_item, Node) else None
                        if comp_node_item is None:
                            misses += 1
                            details.append(f"MISS {fp}[{i}]: {_node_label(item)} vs None")
                        _walk(item, comp_node_item, f"{fp}[{i}]")
                    else:
                        total += 1
                        if comp_item is None:
                            misses += 1
                            details.append(f"MISS {fp}[{i}]: {item} vs None")
                        elif isinstance(item, float) and isinstance(comp_item, float):
                            if abs(item - comp_item) > 1e-5:
                                errors += 1
                                details.append(f"ERR  {fp}[{i}]: {item} vs {comp_item}")
                        elif item != comp_item:
                            errors += 1
                            details.append(f"ERR  {fp}[{i}]: {item} vs {comp_item}")
            else:
                total += 1
                if val_comp is None and val_orig is not None:
                    misses += 1
                    details.append(f"MISS {fp}: {repr(val_orig)[:60]} vs None")
                elif isinstance(val_orig, float) and isinstance(val_comp, float):
                    if abs(val_orig - val_comp) > 1e-5:
                        errors += 1
                        details.append(f"ERR  {fp}: {val_orig} vs {val_comp}")
                elif val_orig != val_comp:
                    errors += 1
                    details.append(f"ERR  {fp}: {repr(val_orig)[:60]} vs {repr(val_comp)[:60]}")

    _walk(orig, composed)
    return total, errors, misses, details


def _fuzzy_binary_match(data_a, data_b):
    """Compare two byte sequences using 4-byte word frequency matching.

    Returns (matched, total, errors, misses) where errors are words present
    in both but different, and misses are words in one but not the other.
    For binary matching, all non-matches are errors (the data exists but differs).
    """
    if len(data_a) < 4 and len(data_b) < 4:
        return 0, 0, 0, 0

    words_a = Counter()
    words_b = Counter()
    for i in range(0, len(data_a) - 3, 4):
        words_a[data_a[i:i+4]] += 1
    for i in range(0, len(data_b) - 3, 4):
        words_b[data_b[i:i+4]] += 1

    matched = sum((words_a & words_b).values())
    total = max(sum(words_a.values()), sum(words_b.values()))
    # For binary comparison, all non-matches are errors (layout differences)
    errors = total - matched
    return matched, total, errors, 0


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
            stem, ext = os.path.splitext(f)
            if ext.lower() in SUPPORTED_EXTENSIONS and not stem.endswith('_output'):
                files.append(os.path.join(path, f))
        return files
    return []


def run_all_tests(filepath):
    """Run all round-trip tests on a single model file. Returns dict of scores."""
    name = os.path.splitext(os.path.basename(filepath))[0]
    scores = {'name': name}

    # NBN
    try:
        pct, err_pct, miss_pct = compute_nbn_score(filepath)
        scores['nbn'] = pct
        scores['nbn_err'] = err_pct
        scores['nbn_miss'] = miss_pct
    except Exception as e:
        scores['nbn'] = f"ERROR: {e}"
        scores['nbn_err'] = 0.0
        scores['nbn_miss'] = 0.0

    # BNB
    try:
        pct, err_pct, miss_pct = compute_bnb_score(filepath)
        scores['bnb'] = pct
        scores['bnb_err'] = err_pct
        scores['bnb_miss'] = miss_pct
    except Exception as e:
        scores['bnb'] = f"ERROR: {e}"
        scores['bnb_err'] = 0.0
        scores['bnb_miss'] = 0.0

    # NIN
    try:
        pct, err_pct, miss_pct, nin_details = compute_nin_score(filepath)
        scores['nin'] = pct
        scores['nin_err'] = err_pct
        scores['nin_miss'] = miss_pct
        scores['nin_details'] = nin_details
    except Exception as e:
        scores['nin'] = f"ERROR: {e}"
        scores['nin_err'] = 0.0
        scores['nin_miss'] = 0.0

    # BBB
    try:
        pct, err_pct, miss_pct, details, categories = compute_bbb_score(filepath)
        scores['bbb'] = pct
        scores['bbb_err'] = err_pct
        scores['bbb_miss'] = miss_pct
        scores['bbb_details'] = details
        scores['bbb_categories'] = categories
    except Exception as e:
        scores['bbb'] = f"ERROR: {e}"
        scores['bbb_err'] = 0.0
        scores['bbb_miss'] = 0.0
        import traceback
        scores['bbb_details'] = [traceback.format_exc()]
        scores['bbb_categories'] = {}

    # IBI
    try:
        pct, err_pct, miss_pct, details, categories = compute_ibi_score(filepath)
        scores['ibi'] = pct
        scores['ibi_err'] = err_pct
        scores['ibi_miss'] = miss_pct
        scores['ibi_details'] = details
        scores['ibi_categories'] = categories
    except Exception as e:
        scores['ibi'] = f"ERROR: {e}"
        scores['ibi_err'] = 0.0
        scores['ibi_miss'] = 0.0
        import traceback
        scores['ibi_details'] = [traceback.format_exc()]
        scores['ibi_categories'] = {}

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
        for key in ('nbn', 'nin', 'bbb', 'ibi'):
            val = scores.get(key)
            if isinstance(val, float):
                err = scores.get(f'{key}_err', 0.0)
                miss = scores.get(f'{key}_miss', 0.0)
                parts.append(f"{key.upper()}={val:.1f}%({err:.0f}/{miss:.0f})")
            else:
                parts.append(f"{key.upper()}={val}")
        # BNB without error/miss (binary matching has no meaningful miss distinction)
        bnb_val = scores.get('bnb')
        if isinstance(bnb_val, float):
            parts.append(f"BNB={bnb_val:.1f}%")
        else:
            parts.append(f"BNB={bnb_val}")
        print('  '.join(parts))

        # Show BBB / IBI category breakdowns with error/miss rates
        for label, cat_key in (('BBB', 'bbb_categories'), ('IBI', 'ibi_categories')):
            cats = scores.get(cat_key, {})
            cat_parts = []
            for cat_name in ('bones', 'meshes', 'materials', 'animations', 'actions',
                             'constraints', 'lights', 'cameras'):
                cat = cats.get(cat_name)
                if cat and cat['total'] > 0:
                    err_pct = cat['errors'] / cat['total'] * 100
                    miss_pct = cat['misses'] / cat['total'] * 100
                    cat_parts.append(f"{cat_name}={cat['pct']:.0f}%({err_pct:.0f}/{miss_pct:.0f})")
            if cat_parts:
                print(f"    {label} breakdown: {', '.join(cat_parts)}")

        if verbose and scores.get('nin_details'):
            for detail in scores['nin_details'][:20]:
                print(f"    NIN: {detail}")

        if verbose and scores.get('bbb_details'):
            for detail in scores['bbb_details'][:20]:
                print(f"    BBB: {detail}")

        if verbose and scores.get('ibi_details'):
            for detail in scores['ibi_details'][:20]:
                print(f"    IBI: {detail}")

    # Summary table
    col_w = 18
    print(f"\n{'='*(20 + col_w * 4 + 8 + 5)}")
    print(f"{'Model':<20} {'NBN':>{col_w}} {'NIN':>{col_w}} {'BBB':>{col_w}} {'IBI':>{col_w}} {'BNB':>8}")
    print(f"{'-'*20} {'-'*col_w} {'-'*col_w} {'-'*col_w} {'-'*col_w} {'-'*8}")
    for scores in all_scores:
        row = f"{scores['name']:<20}"
        for key in ('nbn', 'nin', 'bbb', 'ibi'):
            val = scores.get(key)
            if isinstance(val, float):
                err = scores.get(f'{key}_err', 0.0)
                miss = scores.get(f'{key}_miss', 0.0)
                cell = f"{val:.1f}%({err:.0f}/{miss:.0f})"
                row += f" {cell:>{col_w}}"
            else:
                row += f" {'ERR':>{col_w}}"
        bnb_val = scores.get('bnb')
        if isinstance(bnb_val, float):
            row += f" {bnb_val:>7.1f}%"
        else:
            row += f" {'ERR':>7}%"
        print(row)

if __name__ == '__main__':
    main()
