#!/usr/bin/env python3
"""Dump a stable, diff-friendly structural summary of a .dat / .pkx model.

The goal is to let you eyeball what's *structurally different* between a
known-working re-export of a game model and an export that garbles in-game,
without needing in-game diagnostics. All addresses are stripped; counts
and flag histograms are used in place of enumerating hundreds of PObjects;
the output is line-based so two files can be compared with plain `diff`.

Usage:
    python3 tools/dat_summary.py <path.pkx|.dat>                  # single
    python3 tools/dat_summary.py <a.dat> <b.dat>                  # side-by-side
    python3 tools/dat_summary.py --detail <a.dat>                 # per-DObject lines
    python3 tools/dat_summary.py --diff <a.dat> <b.dat>           # unified diff

No Blender required — uses only the extract/route/parse phases.
"""
import argparse
import difflib
import os
import struct
import sys
from collections import Counter, defaultdict

# Make the addon importable
_ADDON = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _ADDON not in sys.path:
    sys.path.insert(0, _ADDON)

from importer.phases.extract.extract import extract_dat
from importer.phases.route.route import route_sections
from importer.phases.parse.parse import parse_sections
from shared.Constants.hsd import (
    POBJ_TYPE_MASK, POBJ_SKIN, POBJ_SHAPEANIM, POBJ_ENVELOPE,
    POBJ_CULLFRONT, POBJ_CULLBACK,
    JOBJ_SKELETON, JOBJ_SKELETON_ROOT, JOBJ_ENVELOPE_MODEL,
    JOBJ_CLASSICAL_SCALING, JOBJ_HIDDEN, JOBJ_PTCL, JOBJ_LIGHTING,
    JOBJ_INSTANCE, JOBJ_USE_QUATERNION, JOBJ_SPECULAR,
    JOBJ_OPA, JOBJ_XLU, JOBJ_TEXEDGE, JOBJ_TRSP_MASK,
    JOBJ_TYPE_MASK, JOBJ_NULL, JOBJ_JOINT1, JOBJ_JOINT2, JOBJ_EFFECTOR,
)
from shared.Constants.gx import (
    GX_VA_POS, GX_VA_NRM, GX_VA_CLR0, GX_VA_CLR1,
    GX_VA_TEX0, GX_VA_TEX1, GX_VA_TEX2, GX_VA_TEX3,
    GX_VA_TEX4, GX_VA_TEX5, GX_VA_TEX6, GX_VA_TEX7,
    GX_VA_PNMTXIDX, GX_VA_NBT, GX_VA_NULL,
)


# --- Name maps ---------------------------------------------------------------

_ATTR_NAMES = {
    GX_VA_PNMTXIDX: 'PNMTXIDX',
    GX_VA_POS: 'POS', GX_VA_NRM: 'NRM',
    GX_VA_CLR0: 'CLR0', GX_VA_CLR1: 'CLR1',
    GX_VA_TEX0: 'TEX0', GX_VA_TEX1: 'TEX1', GX_VA_TEX2: 'TEX2', GX_VA_TEX3: 'TEX3',
    GX_VA_TEX4: 'TEX4', GX_VA_TEX5: 'TEX5', GX_VA_TEX6: 'TEX6', GX_VA_TEX7: 'TEX7',
    GX_VA_NBT: 'NBT',
}

_ATTR_TYPE_NAMES = {0: 'NONE', 1: 'DIRECT', 2: 'INDEX8', 3: 'INDEX16'}

_TF_NAMES = {
    0x0: 'I4', 0x1: 'I8', 0x2: 'IA4', 0x3: 'IA8',
    0x4: 'RGB565', 0x5: 'RGB5A3', 0x6: 'RGBA8',
    0x8: 'C4', 0x9: 'C8', 0xA: 'C14X2', 0xE: 'CMPR',
}

_WRAP_NAMES = {0: 'CLAMP', 1: 'REPEAT', 2: 'MIRROR'}


def _pobj_kind(flags):
    t = flags & POBJ_TYPE_MASK
    return {POBJ_SKIN: 'SKIN', POBJ_SHAPEANIM: 'SHAPE', POBJ_ENVELOPE: 'ENV'}.get(t, 'SKIN')


def _pobj_cull(flags):
    front = bool(flags & POBJ_CULLFRONT)
    back = bool(flags & POBJ_CULLBACK)
    if front and back: return 'BOTH'
    if back: return 'BACK'
    if front: return 'FRONT'
    return 'NONE'


_JOBJ_FLAG_BITS = [
    (JOBJ_SKELETON, 'SKEL'),
    (JOBJ_SKELETON_ROOT, 'SKEL_ROOT'),
    (JOBJ_ENVELOPE_MODEL, 'ENV_MODEL'),
    (JOBJ_CLASSICAL_SCALING, 'CLASSICAL'),
    (JOBJ_HIDDEN, 'HIDDEN'),
    (JOBJ_PTCL, 'PTCL'),
    (JOBJ_LIGHTING, 'LIGHTING'),
    (JOBJ_INSTANCE, 'INSTANCE'),
    (JOBJ_USE_QUATERNION, 'QUAT'),
    (JOBJ_SPECULAR, 'SPECULAR'),
]


def _jobj_flag_str(flags):
    parts = [name for bit, name in _JOBJ_FLAG_BITS if flags & bit]
    trsp = flags & JOBJ_TRSP_MASK
    if trsp == JOBJ_OPA: parts.append('OPA')
    elif trsp == JOBJ_XLU: parts.append('XLU')
    elif trsp == JOBJ_TEXEDGE: parts.append('TEXEDGE')
    jtype = flags & JOBJ_TYPE_MASK
    parts.append({JOBJ_NULL: 'NULL', JOBJ_JOINT1: 'JOINT1',
                  JOBJ_JOINT2: 'JOINT2', JOBJ_EFFECTOR: 'EFFECTOR'}.get(jtype, 'TYPE?'))
    return '|'.join(parts) if parts else '-'


# --- Tree walkers ------------------------------------------------------------

def _walk_joint_chain(joint):
    """Yield every joint in a joint tree (depth-first, including siblings)."""
    if joint is None:
        return
    node = joint
    while node is not None:
        yield node
        yield from _walk_joint_chain(node.child)
        node = node.next


def _walk_mesh_chain(mesh):
    while mesh is not None:
        yield mesh
        mesh = mesh.next


def _walk_pobj_chain(pobj):
    while pobj is not None:
        yield pobj
        pobj = pobj.next


def _walk_tex_chain(tex):
    while tex is not None:
        yield tex
        tex = tex.next


# --- Extractors --------------------------------------------------------------

def _vtx_desc_signature(pobj):
    """Compact, stable string identifying a PObject's attribute layout.

    Encodes each vertex attribute as NAME[type,comp=N,frac=F,stride=S].
    Two PObjects with the same signature have identical binary layouts.
    """
    if pobj.vertex_list is None or not pobj.vertex_list.vertices:
        return '(no-attrs)'
    parts = []
    for v in pobj.vertex_list.vertices:
        if v.attribute == GX_VA_NULL:
            continue
        name = _ATTR_NAMES.get(v.attribute, 'ATTR%d' % v.attribute)
        atype = _ATTR_TYPE_NAMES.get(v.attribute_type, '?%d' % v.attribute_type)
        parts.append('%s[%s,c=%d,ct=%d,f=%d,s=%d]' % (
            name, atype, v.component_count, v.component_type,
            v.component_frac, v.stride))
    return ' '.join(parts)


def _pobj_envelope_count(pobj):
    """Number of matrix slots the PObject binds (1-10 for ENVELOPE, else 0).

    For POBJ_ENVELOPE the `property` field is a list of EnvelopeList
    pointers — one per GX matrix slot used by this draw call. GX caps this
    at 10 per PObject, so values near 10 indicate the compose phase is
    using envelope splitting aggressively.
    """
    if pobj.flags & POBJ_TYPE_MASK != POBJ_ENVELOPE:
        return 0
    prop = getattr(pobj, 'property', None)
    if prop is None or isinstance(prop, int):
        return 0
    if isinstance(prop, list):
        return len(prop)
    try:
        return len(prop.envelopes) if prop.envelopes else 0
    except AttributeError:
        return 0


def _collect_model_stats(scene_data):
    """Build a dict of stable, diff-friendly stats for one scene."""
    stats = {
        'models': [],
        'lights': 0,
        'has_camera': False,
        'has_fog': False,
    }
    stats['lights'] = len(getattr(scene_data, 'lights', []) or [])
    stats['has_camera'] = scene_data.camera is not None
    stats['has_fog'] = getattr(scene_data, 'fog', None) is not None

    for model_set in (scene_data.models or []):
        m = _collect_one_model(model_set)
        stats['models'].append(m)
    return stats


def _collect_one_model(model_set):
    root = model_set.root_joint
    m = {
        'bone_count': 0,
        'max_depth': 0,
        'jobj_flags': Counter(),
        'bones_with_mesh': 0,
        'bones_with_instance': 0,
        'dobjects': [],
        'pobj_kind': Counter(),
        'pobj_cull': Counter(),
        'pobj_buf_verts': [],
        'pobj_envelope_counts': [],
        'pobj_dl_bytes': [],
        'vtx_signatures': Counter(),
        'texture_formats': Counter(),
        'texture_sizes': Counter(),
        'texture_wrap': Counter(),
        'anim_joint_count': len(model_set.animated_joints or []),
        'anim_mat_joint_count': len(model_set.animated_material_joints or []),
    }

    # Walk joint tree
    def walk(joint, depth):
        m['bone_count'] += 1
        m['max_depth'] = max(m['max_depth'], depth)
        m['jobj_flags'][_jobj_flag_str(joint.flags)] += 1
        if joint.flags & JOBJ_INSTANCE:
            m['bones_with_instance'] += 1
        if joint.property is not None and not isinstance(joint.property, int):
            # property is the DObject (Mesh) chain when JOBJ_INSTANCE is clear
            if not (joint.flags & JOBJ_INSTANCE):
                m['bones_with_mesh'] += 1
                for mesh in _walk_mesh_chain(joint.property):
                    _collect_dobject(mesh, m)
        c = joint.child
        while c is not None:
            walk(c, depth + 1)
            c = c.next

    if root is not None:
        walk(root, 0)

    return m


def _collect_dobject(mesh, m):
    mobj = mesh.mobject
    render_mode = getattr(mobj, 'render_mode', 0) if mobj is not None else 0
    pobjs = list(_walk_pobj_chain(mesh.pobject))
    textures = list(_walk_tex_chain(getattr(mobj, 'texture', None))) if mobj else []

    for tex in textures:
        img = getattr(tex, 'image', None)
        if img is not None:
            fmt = _TF_NAMES.get(img.format, 'TF?%d' % img.format)
            m['texture_formats'][fmt] += 1
            m['texture_sizes'][f'{img.width}x{img.height}'] += 1
        m['texture_wrap'][
            '%s/%s' % (_WRAP_NAMES.get(tex.wrap_s, '?'),
                       _WRAP_NAMES.get(tex.wrap_t, '?'))
        ] += 1

    for p in pobjs:
        m['pobj_kind'][_pobj_kind(p.flags)] += 1
        m['pobj_cull'][_pobj_cull(p.flags)] += 1
        # Vertex buffer size (total verts in the shared VertexList, not the
        # per-PObject draw-call vertex count — that would require parsing
        # the display list). Useful as a structural fingerprint: two models
        # that both split the same mesh should have the same buffer size.
        buf_verts = 0
        if p.vertex_list and p.vertex_list.vertices:
            for v in p.vertex_list.vertices:
                if (v.attribute == GX_VA_POS
                        and v.attribute_type in (2, 3)
                        and v.stride > 0
                        and hasattr(v, 'raw_vertex_data')
                        and v.raw_vertex_data):
                    buf_verts = len(v.raw_vertex_data) // v.stride
                    break
        m['pobj_buf_verts'].append(buf_verts)
        m['pobj_envelope_counts'].append(_pobj_envelope_count(p))
        m['pobj_dl_bytes'].append(p.display_list_chunk_count * 32)
        m['vtx_signatures'][_vtx_desc_signature(p)] += 1

    m['dobjects'].append({
        'render_mode': render_mode,
        'num_pobjects': len(pobjs),
        'num_textures': len(textures),
        'tex_formats': ','.join(sorted(
            _TF_NAMES.get(t.image.format, 'TF?%d' % t.image.format)
            for t in textures if t.image is not None
        )),
    })


# --- Rendering ---------------------------------------------------------------

def _fmt_counter(c, top=None):
    items = c.most_common(top) if top else sorted(c.items())
    return ', '.join('%s=%d' % (k, v) for k, v in items) or '-'


def _stats(seq):
    if not seq:
        return 'n=0'
    s = sorted(seq)
    return 'n=%d min=%d p50=%d p90=%d max=%d sum=%d' % (
        len(s), s[0], s[len(s) // 2], s[int(len(s) * 0.9)], s[-1], sum(s),
    )


def render_summary(filepath, stats, detail=False):
    lines = []
    name = os.path.basename(filepath)
    lines.append('== %s ==' % name)
    lines.append('scene lights=%d camera=%s fog=%s' % (
        stats['lights'],
        'yes' if stats['has_camera'] else 'no',
        'yes' if stats['has_fog'] else 'no',
    ))

    for i, m in enumerate(stats['models']):
        lines.append('')
        lines.append('model[%d]' % i)
        lines.append('  bones total=%d max_depth=%d with_mesh=%d instance=%d' % (
            m['bone_count'], m['max_depth'],
            m['bones_with_mesh'], m['bones_with_instance']))
        lines.append('  jobj_flags  %s' % _fmt_counter(m['jobj_flags']))
        lines.append('  anim  joint_sets=%d material_joint_sets=%d' % (
            m['anim_joint_count'], m['anim_mat_joint_count']))
        lines.append('  dobjects    count=%d' % len(m['dobjects']))
        lines.append('  pobjects    count=%d' % sum(m['pobj_kind'].values()))
        lines.append('    kind      %s' % _fmt_counter(m['pobj_kind']))
        lines.append('    cull      %s' % _fmt_counter(m['pobj_cull']))
        lines.append('    buf_verts %s' % _stats(m['pobj_buf_verts']))
        lines.append('    envs/p    %s' % _stats(m['pobj_envelope_counts']))
        lines.append('    dl_bytes  %s' % _stats(m['pobj_dl_bytes']))
        lines.append('  textures    count=%d' % sum(m['texture_formats'].values()))
        lines.append('    formats   %s' % _fmt_counter(m['texture_formats']))
        lines.append('    sizes     %s' % _fmt_counter(m['texture_sizes']))
        lines.append('    wrap      %s' % _fmt_counter(m['texture_wrap']))
        lines.append('  vtx signatures (count: layout)')
        for sig, count in m['vtx_signatures'].most_common():
            lines.append('    %4d  %s' % (count, sig))
        if detail:
            lines.append('  dobjects (per DObject):')
            for j, d in enumerate(m['dobjects']):
                lines.append('    [%3d] rm=0x%08X pobjs=%d tex=%d fmts=%s' % (
                    j, d['render_mode'], d['num_pobjects'],
                    d['num_textures'], d['tex_formats'] or '-'))
    return '\n'.join(lines)


# --- Bound box ---------------------------------------------------------------

def _collect_bound_box_stats(bb_node):
    """Extract structural stats from a BoundBox node.

    The BoundBox stores one 24-byte AABB (big-endian ffffff) per frame,
    packed in raw_aabb_data across all animation sets. Game originals
    typically animate this box per frame; our exporter currently emits
    a single static AABB replicated for every frame.
    """
    raw = bb_node.raw_aabb_data
    total_frames = len(raw) // 24
    distinct = set()
    merged_min = [float('inf')] * 3
    merged_max = [float('-inf')] * 3
    for i in range(total_frames):
        block = raw[i * 24:(i + 1) * 24]
        distinct.add(block)
        vals = struct.unpack('>ffffff', block)
        for j in range(3):
            if vals[j] < merged_min[j]: merged_min[j] = vals[j]
            if vals[j + 3] > merged_max[j]: merged_max[j] = vals[j + 3]
    return {
        'anim_sets': bb_node.anim_set_count,
        'first_set_frames': getattr(bb_node, 'first_anim_frame_count',
                                    getattr(bb_node, 'unknown', 0)),
        'total_frames': total_frames,
        'distinct_aabbs': len(distinct),
        'merged_min': tuple(merged_min) if total_frames else (0, 0, 0),
        'merged_max': tuple(merged_max) if total_frames else (0, 0, 0),
    }


def render_bound_box(stats):
    lines = ['bound_box']
    lines.append('  anim_sets=%d total_frames=%d distinct_aabbs=%d first_set_frames=%d' % (
        stats['anim_sets'], stats['total_frames'],
        stats['distinct_aabbs'], stats['first_set_frames']))
    lines.append('  range min=(%.2f,%.2f,%.2f) max=(%.2f,%.2f,%.2f)' % (
        *stats['merged_min'], *stats['merged_max']))
    return '\n'.join(lines)


# --- Pipeline ----------------------------------------------------------------

def summarize_file(filepath, detail=False):
    with open(filepath, 'rb') as f:
        raw = f.read()
    entries = extract_dat(raw, os.path.basename(filepath))
    out = []
    for entry_idx, (dat_bytes, _meta) in enumerate(entries):
        section_map = route_sections(dat_bytes)
        sections = parse_sections(dat_bytes, section_map, {})
        label = filepath if len(entries) == 1 else '%s#%d' % (filepath, entry_idx)
        scene_out = None
        bb_out = None
        for s in sections:
            if s.section_name == 'scene_data':
                stats = _collect_model_stats(s.root_node)
                scene_out = render_summary(label, stats, detail=detail)
            elif s.section_name == 'bound_box':
                bb_out = render_bound_box(_collect_bound_box_stats(s.root_node))
        if scene_out is not None:
            parts = [scene_out]
            if bb_out is not None:
                parts.append(bb_out)
            out.append('\n\n'.join(parts))
    return '\n\n'.join(out) if out else '(no scene_data in %s)' % filepath


# --- CLI ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+', help='One or two .dat/.pkx files')
    ap.add_argument('--detail', action='store_true',
                    help='Also emit per-DObject lines')
    ap.add_argument('--diff', action='store_true',
                    help='With two files, emit a unified diff instead of side-by-side')
    args = ap.parse_args()

    if len(args.files) == 1:
        print(summarize_file(args.files[0], detail=args.detail))
        return

    if len(args.files) != 2:
        print('Error: pass 1 or 2 files', file=sys.stderr)
        sys.exit(2)

    a_text = summarize_file(args.files[0], detail=args.detail)
    b_text = summarize_file(args.files[1], detail=args.detail)

    if args.diff:
        for line in difflib.unified_diff(
                a_text.splitlines(keepends=True),
                b_text.splitlines(keepends=True),
                fromfile=args.files[0], tofile=args.files[1]):
            sys.stdout.write(line)
    else:
        a_lines = a_text.splitlines()
        b_lines = b_text.splitlines()
        width = max((len(l) for l in a_lines), default=0) + 2
        for a, b in zip(a_lines + [''] * (len(b_lines) - len(a_lines)),
                        b_lines + [''] * (len(a_lines) - len(b_lines))):
            marker = '   ' if a == b else ' | '
            print('%-*s%s%s' % (width, a, marker, b))


if __name__ == '__main__':
    main()
