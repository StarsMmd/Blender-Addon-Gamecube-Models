"""Audit vertex format choices across a corpus of .dat / .pkx / .fsys models.

For every PObject in every model, decodes each Vertex descriptor and:

  - Tallies (attribute, attribute_type, component_type, component_count,
    component_frac) combinations per GX attribute (POS, NRM, CLR0/1,
    TEX0..7).
  - For s16/u16 fixed-point attributes, decodes the actual vertex values
    and reports the max absolute magnitude vs the headroom the chosen
    `component_frac` allows. Tightness = (used_range / max_representable).

The output informs the auto-pick heuristic in compose: which attribute
gets which (component_type, frac) by default, and whether the corpus
ever uses anything other than the most common choice.

Usage:
    python3 tools/vertex_format_audit.py [<dir>]

Default dir: ~/Documents/Projects/DAT plugin/models/
"""
import os
import struct
import sys
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from importer.phases.extract.extract import extract_dat
from importer.phases.route.route import route_sections
from importer.phases.parse.parse import parse_sections
from shared.helpers.logger import StubLogger


# GX attribute IDs we care about
_ATTR_NAMES = {
    0: 'PNMTXIDX',
    9: 'POS',
    10: 'NRM',
    11: 'CLR0',
    12: 'CLR1',
    13: 'TEX0',
    14: 'TEX1',
    15: 'TEX2',
    16: 'TEX3',
    25: 'NBT',
}
# 1-8 are TEX0..TEX7 matrix indices — skip in summary

# attribute_type
_ATYPE_NAMES = {0: 'NONE', 1: 'DIRECT', 2: 'INDEX8', 3: 'INDEX16'}

# component_type — context-dependent (POS/NRM/TEX use 0-4, CLR uses 0-5)
_NUMERIC_CTYPE_NAMES = {0: 'u8', 1: 's8', 2: 'u16', 3: 's16', 4: 'f32'}
_COLOR_CTYPE_NAMES = {0: 'RGB565', 1: 'RGB8', 2: 'RGBX8', 3: 'RGBA4', 4: 'RGBA6', 5: 'RGBA8'}

# component_count semantics by attribute family
# POS:  0 = XY, 1 = XYZ
# NRM:  0 = XYZ, 1 = NBT (3 normals)
# CLR:  0 = RGB, 1 = RGBA
# TEX:  0 = S,   1 = ST


def _ctype_label(attr_id, ctype):
    if attr_id in (11, 12):  # CLR0 / CLR1
        return _COLOR_CTYPE_NAMES.get(ctype, f'?{ctype}')
    return _NUMERIC_CTYPE_NAMES.get(ctype, f'?{ctype}')


def _walk_pobjects(node, found, seen=None):
    """Walk a parsed node tree collecting every PObject reachable.
    Tracks visited node ids to break cycles in shared subtrees."""
    if seen is None:
        seen = set()
    if node is None or id(node) in seen:
        return
    seen.add(id(node))
    cls = type(node).__name__
    if cls == 'PObject':
        found.append(node)
    for fname, _ftype in getattr(node, 'fields', []):
        v = getattr(node, fname, None)
        if hasattr(v, 'fields'):
            _walk_pobjects(v, found, seen)
        elif isinstance(v, list):
            for x in v:
                if hasattr(x, 'fields'):
                    _walk_pobjects(x, found, seen)


def _decode_array_bounds(dat_bytes, v, all_bases):
    """Return (n_decoded, [min, max] per component) for a single Vertex
    descriptor's data array. Returns None if format isn't a fixed-point /
    float numeric we can decode.

    Bounds the array by the next attribute base in the file (we don't
    know vertex_count exactly without scanning all display lists)."""
    base = v.base_pointer
    ctype = v.component_type
    stride = v.stride
    ccount = v.component_count
    attr_id = v.attribute

    if stride == 0:
        return None
    if attr_id == 0:  # PNMTXIDX — direct, no array
        return None

    # Number of float components per vertex
    if attr_id == 9:  # POS
        dims = 2 if ccount == 0 else 3
    elif attr_id == 10:  # NRM
        dims = 9 if ccount == 1 else 3   # NBT (1) is 3 normals × 3 components
    elif attr_id in (11, 12):  # CLR
        return None   # decoded as packed pixels, separate path
    elif 13 <= attr_id <= 20:  # TEX
        dims = 1 if ccount == 0 else 2
    else:
        return None

    # Decode value at index 0..n-1
    end = next((b for b in all_bases if b > base), len(dat_bytes))
    max_n = (end - base) // stride if stride else 0
    max_n = min(max_n, 1000)

    if ctype == 4:  # f32
        fmt = '>%df' % dims
        size = 4 * dims
        scale = 1.0
    elif ctype == 3:  # s16
        fmt = '>%dh' % dims
        size = 2 * dims
        scale = 1.0 / (1 << v.component_frac) if v.component_frac else 1.0
    elif ctype == 2:  # u16
        fmt = '>%dH' % dims
        size = 2 * dims
        scale = 1.0 / (1 << v.component_frac) if v.component_frac else 1.0
    elif ctype == 1:  # s8
        fmt = '>%db' % dims
        size = 1 * dims
        scale = 1.0 / (1 << v.component_frac) if v.component_frac else 1.0
    elif ctype == 0:  # u8
        fmt = '>%dB' % dims
        size = 1 * dims
        scale = 1.0 / (1 << v.component_frac) if v.component_frac else 1.0
    else:
        return None

    mins = [float('inf')] * dims
    maxs = [float('-inf')] * dims
    n = 0
    for i in range(max_n):
        off = base + i * stride
        if off + size > len(dat_bytes):
            break
        try:
            vals = struct.unpack_from(fmt, dat_bytes, off)
        except struct.error:
            break
        for j, val in enumerate(vals):
            v_scaled = val * scale
            if v_scaled < mins[j]: mins[j] = v_scaled
            if v_scaled > maxs[j]: maxs[j] = v_scaled
        n += 1
    if n == 0:
        return None
    return n, mins, maxs


def _analyse_model(path, name):
    """Return per-attribute records for one parsed model."""
    raw = open(path, 'rb').read()
    try:
        items = extract_dat(raw, name)
    except Exception as e:
        return [], f'extract failed: {e}'
    records = []
    for dat_bytes, _meta in items:
        try:
            sections = parse_sections(dat_bytes, route_sections(dat_bytes), {})
        except Exception as e:
            return records, f'parse failed: {e}'
        all_bases = set()
        # Collect every vertex array base across the whole file so the
        # bounded decode doesn't read past the end of one array.
        pobjects = []
        for s in sections:
            _walk_pobjects(s.root_node, pobjects)
        for p in pobjects:
            for v in p.vertex_list.vertices:
                if getattr(v, 'base_pointer', 0):
                    all_bases.add(v.base_pointer)
        all_bases.add(len(dat_bytes))
        sorted_bases = sorted(all_bases)

        for p in pobjects:
            n_vertices_via_dl = p.display_list_chunk_count * 32 // max(1, p.vertex_list.vertices[0].stride if p.vertex_list.vertices else 1)
            for v in p.vertex_list.vertices:
                attr_id = v.attribute
                if attr_id == 0xff:
                    continue
                rec = {
                    'model': name,
                    'attr_id': attr_id,
                    'attr_name': _ATTR_NAMES.get(attr_id, f'attr{attr_id}'),
                    'attribute_type': v.attribute_type,
                    'attr_type_name': _ATYPE_NAMES.get(v.attribute_type, f'?{v.attribute_type}'),
                    'component_type': v.component_type,
                    'component_count': v.component_count,
                    'component_frac': v.component_frac,
                    'stride': v.stride,
                    'pobject_flags': p.flags,
                    'dl_chunk_count': p.display_list_chunk_count,
                }
                bounds = _decode_array_bounds(dat_bytes, v, sorted_bases)
                if bounds is not None:
                    n, mins, maxs = bounds
                    rec['decoded_n'] = n
                    rec['max_abs'] = max(abs(x) for x in mins + maxs)
                rec['ctype_label'] = _ctype_label(attr_id, v.component_type)
                records.append(rec)
    return records, None


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/Documents/Projects/DAT plugin/models/')
    if not os.path.isdir(root):
        print(f'Not a directory: {root}', file=sys.stderr)
        sys.exit(1)

    files = []
    for entry in sorted(os.listdir(root)):
        full = os.path.join(root, entry)
        if not os.path.isfile(full):
            continue
        ext = entry.rsplit('.', 1)[-1].lower() if '.' in entry else ''
        if ext in ('pkx', 'dat', 'rdat', 'fdat', 'fsys'):
            files.append((entry, full))

    print(f'Scanning {len(files)} model(s) under {root}\n')

    all_records = []
    failed = []
    for name, path in files:
        records, err = _analyse_model(path, name)
        if err:
            failed.append((name, err))
        all_records.extend(records)

    if failed:
        print(f'!! {len(failed)} model(s) failed to parse:')
        for n, e in failed[:10]:
            print(f'  {n}: {e}')
        print()

    print(f'Total PObject vertex descriptors decoded: {len(all_records)}')
    print(f'Across {len({r["model"] for r in all_records})} model(s)\n')

    # ---- Per-attribute format tally ----
    by_attr = defaultdict(list)
    for r in all_records:
        by_attr[r['attr_name']].append(r)

    for attr_name in sorted(by_attr.keys()):
        recs = by_attr[attr_name]
        print(f'==== {attr_name} ({len(recs)} descriptors) ====')

        # Format combo distribution
        combos = Counter()
        for r in recs:
            key = (r['attr_type_name'], r['ctype_label'], r['component_count'], r['component_frac'])
            combos[key] += 1

        print(f'  Format (attribute_type, component_type, component_count, frac):')
        for (atype, ctype, ccount, frac), n in combos.most_common():
            pct = 100.0 * n / len(recs)
            print(f'    {atype:7s} {ctype:7s} ccount={ccount} frac={frac:<2d}  → {n:5d} ({pct:5.1f}%)')

        # Breakdown by source model — flag any model deviating from the
        # corpus-dominant format choice for this attribute.
        models_per_combo = defaultdict(set)
        for r in recs:
            key = (r['attr_type_name'], r['ctype_label'], r['component_count'], r['component_frac'])
            models_per_combo[key].add(r['model'])
        if len(models_per_combo) > 1:
            print(f'  Models per format combo:')
            for (atype, ctype, ccount, frac), models in sorted(models_per_combo.items(), key=lambda kv: -len(kv[1])):
                sample = ', '.join(sorted(models)[:5])
                more = '' if len(models) <= 5 else f' …(+{len(models)-5})'
                print(f'    {atype:7s} {ctype:7s} ccount={ccount} frac={frac:<2d}  → {len(models):3d} model(s): {sample}{more}')
        print()

    # ---- PObject flags ----
    flag_counts = Counter()
    for r in all_records:
        flag_counts[r['pobject_flags']] += 1
    # Dedup per PObject (each has many descriptors)
    pobj_flags = Counter()
    seen = set()
    for r in all_records:
        key = (r['model'], r['pobject_flags'], r.get('dl_chunk_count'))
        if key in seen:
            continue
        seen.add(key)
        pobj_flags[r['pobject_flags']] += 1
    print(f'==== PObject flags (across {sum(pobj_flags.values())} unique PObjects) ====')
    for flags, n in pobj_flags.most_common(10):
        pct = 100.0 * n / sum(pobj_flags.values())
        print(f'  flags=0x{flags:04x}  → {n:5d} ({pct:5.1f}%)')


if __name__ == '__main__':
    main()
