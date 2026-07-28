"""Deep CCD corpus analysis: coverage map, disk order, grid validation,
up-axis, metadata stats, entry composition patterns.

Standalone (no plugin imports). Run against the dumped corpus:
  python3 deep_analysis.py
Also importable — `analyze(path, game)` returns (res, bytes) and is reused by
interaction_xcheck.py. Verified findings from this script are written up in
technical-docs/collision_format.md; re-run after any exporter change.
"""
import struct, glob, os, math
from collections import Counter, defaultdict

def u32(b, o): return struct.unpack_from(">I", b, o)[0]
def u16(b, o): return struct.unpack_from(">H", b, o)[0]
def f32(b, o): return struct.unpack_from(">f", b, o)[0]
def f3(b, o): return struct.unpack_from(">3f", b, o)

ROOTS = [
    ("XD", "/Users/stars/Documents/GoD Tool/XD GoD Tool dumped/Game Files"),
    ("Colo", "/Users/stars/Documents/GoD Tool/Colo CM Tool/Game Files"),
]
SLOT_NAMES = ["walk", "hit", "thru", "check", "hit_npc", "sun"]
GRID_SLOTS = {0, 1, 2, 4}   # walk/hit/thru/hit_npc have grids
POLY_SIZE = {0: 0x34, 1: 0x34, 2: 0x34, 3: 0x34, 4: 0x34, 5: 0x30}  # sun = 0x30

class Cov:
    """Byte coverage tracker."""
    def __init__(self, size):
        self.size = size
        self.spans = []  # (start, end, label)
    def claim(self, start, end, label):
        self.spans.append((start, end, label))
    def gaps(self):
        merged = sorted((s, e) for s, e, _ in self.spans if e > s)
        out, pos = [], 0
        for s, e in merged:
            if s > pos:
                out.append((pos, s))
            pos = max(pos, e)
        if pos < self.size:
            out.append((pos, self.size))
        return out

def analyze(path, game):
    b = open(path, "rb").read()
    name = os.path.basename(path)
    res = {"name": name, "game": game, "size": len(b), "entries": [],
           "gaps": [], "order": [], "grid_bad": [],
           "walk_norm_up": 0, "walk_norm_other": 0}
    cov = Cov(len(b))
    list_off, count = u32(b, 0), u32(b, 4)
    cov.claim(0, 8, "filehead")
    cov.claim(list_off, list_off + count * 0x40, "entrytable")
    order = []  # (offset, label) for disk-order analysis

    for e in range(count):
        eo = list_off + e * 0x40
        ptrs = [u32(b, eo + 0x24 + 4 * i) for i in range(6)]
        ent = {"slots": [], "tris": {}, "meta": {}}
        for i, ptr in enumerate(ptrs):
            if not ptr:
                continue
            ent["slots"].append(i)
            sname = SLOT_NAMES[i]
            head_size = 0x24 if i in GRID_SLOTS else 0x08
            cov.claim(ptr, ptr + head_size, f"head:{sname}")
            order.append((ptr, f"e{e}:{sname}:head"))
            tri_ptr, tri_count = u32(b, ptr), u32(b, ptr + 4)
            psize = POLY_SIZE[i]
            cov.claim(tri_ptr, tri_ptr + tri_count * psize, f"polys:{sname}")
            order.append((tri_ptr, f"e{e}:{sname}:polys"))
            metas = []
            for t in range(tri_count):
                to = tri_ptr + t * psize
                if psize == 0x34:
                    metas.append((u16(b, to + 0x30), u16(b, to + 0x32)))
                if i == 0:  # walk normal up-axis
                    n = f3(b, to + 0x24)
                    if n[1] > 0.7:
                        res["walk_norm_up"] += 1
                    else:
                        res["walk_norm_other"] += 1
            ent["tris"][sname] = tri_count
            ent["meta"][sname] = metas
            if i in GRID_SLOTS:
                cells_ptr, idx_ptr = u32(b, ptr + 8), u32(b, ptr + 0xC)
                gw, gh = u16(b, ptr + 0x10), u16(b, ptr + 0x12)
                csx, csz = f32(b, ptr + 0x14), f32(b, ptr + 0x18)
                ox, oz = f32(b, ptr + 0x1C), f32(b, ptr + 0x20)
                ncells = gw * gh
                cov.claim(cells_ptr, cells_ptr + ncells * 8, f"cells:{sname}")
                order.append((cells_ptr, f"e{e}:{sname}:cells"))
                pool_end = 0
                ok = True
                for c in range(ncells):
                    co = cells_ptr + c * 8
                    ioff, icnt = u32(b, co), u32(b, co + 4)
                    pool_end = max(pool_end, ioff + icnt)
                    for k in range(icnt):
                        idx = u32(b, idx_ptr + (ioff + k) * 4)
                        if idx >= tri_count:
                            ok = False
                cov.claim(idx_ptr, idx_ptr + pool_end * 4, f"idxpool:{sname}")
                order.append((idx_ptr, f"e{e}:{sname}:idxpool"))
                if not ok:
                    res["grid_bad"].append((e, sname, "index out of range"))
                if tri_count and gw and gh:
                    minx = min(min(f32(b, tri_ptr + t * psize + j * 0xC) for j in range(3)) for t in range(tri_count))
                    minz = min(min(f32(b, tri_ptr + t * psize + j * 0xC + 8) for j in range(3)) for t in range(tri_count))
                    maxx = max(max(f32(b, tri_ptr + t * psize + j * 0xC) for j in range(3)) for t in range(tri_count))
                    maxz = max(max(f32(b, tri_ptr + t * psize + j * 0xC + 8) for j in range(3)) for t in range(tri_count))
                    span_ok = (ox <= minx + 1e-3 and oz <= minz + 1e-3
                               and ox + gw * csx >= maxx - 1e-3
                               and oz + gh * csz >= maxz - 1e-3)
                    if not span_ok:
                        res["grid_bad"].append(
                            (e, sname, f"grid [{ox:.1f},{oz:.1f}]+{gw}x{gh}*[{csx:.1f},{csz:.1f}] "
                                       f"vs aabb [{minx:.1f},{minz:.1f}]..[{maxx:.1f},{maxz:.1f}]"))
        res["entries"].append(ent)

    res["gaps"] = [(s, e) for s, e in cov.gaps() if e - s > 0]
    res["order"] = sorted(order)
    return res, b

def main():
    files = []
    for game, root in ROOTS:
        for p in sorted(glob.glob(os.path.join(root, "*", "*.ccd"))):
            files.append((game, p))

    gap_examples = []
    order_patterns = Counter()
    walk_meta = Counter(); hit_meta = Counter(); thru_meta = Counter()
    check_meta = Counter(); npc_meta = Counter()
    comp_patterns = Counter()
    up, other = 0, 0
    grid_bad_all = []
    entry0_comp = Counter()

    for game, p in files:
        res, b = analyze(p, game)
        real_gaps = [(s, e) for s, e in res["gaps"]
                     if e - s >= 4 and not all(x == 0 for x in b[s:e])]
        if real_gaps:
            gap_examples.append((res["name"], real_gaps[:5],
                                 [(b[s:min(s+16, e)].hex()) for s, e in real_gaps[:3]]))
        kinds = [lbl.split(":", 1)[1] for _, lbl in res["order"]]
        order_patterns["|".join(kinds[:14])] += 1
        up += res["walk_norm_up"]; other += res["walk_norm_other"]
        grid_bad_all += [(res["name"],) + g for g in res["grid_bad"]]
        for i, ent in enumerate(res["entries"]):
            comp = tuple(SLOT_NAMES[s] for s in ent["slots"])
            comp_patterns[comp] += 1
            if i == 0:
                entry0_comp[comp] += 1
            for sname, metas in ent["meta"].items():
                tgt = {"walk": walk_meta, "hit": hit_meta, "thru": thru_meta,
                       "check": check_meta, "hit_npc": npc_meta}.get(sname)
                if tgt is None:
                    continue
                for m in metas:
                    tgt[m] += 1

    print(f"=== corpus: {len(files)} files ===")
    print(f"walk normals: {up} up (+Y), {other} other -> "
          f"{100.0*up/max(1,up+other):.1f}% up")
    print(f"\nfiles with real (nonzero, >=4B) coverage gaps: {len(gap_examples)}")
    for name, gaps, hexes in gap_examples[:10]:
        print(f"  {name}: {[(hex(s), hex(e)) for s, e in gaps]} first-bytes={hexes}")
    print(f"\ngrid problems: {len(grid_bad_all)}")
    for g in grid_bad_all[:10]:
        print("  ", g)
    print("\nentry slot-composition histogram (top 15):")
    for comp, c in comp_patterns.most_common(15):
        print(f"  {c:5d}  {'+'.join(comp) if comp else '(empty)'}")
    print("\nentry[0] composition (top 5):")
    for comp, c in entry0_comp.most_common(5):
        print(f"  {c:5d}  {'+'.join(comp) if comp else '(empty)'}")
    print("\nwalk meta0 as (attr_hi, attr_lo, layer_hi, layer_lo) nibble stats:")
    nib = Counter()
    for (m0, m1), c in walk_meta.items():
        nib[(m0 >> 12 & 0xF, m0 >> 8 & 0xF, m0 >> 4 & 0xF, m0 & 0xF)] += c
    for k, c in nib.most_common(12):
        print(f"  {c:6d}  nibbles={k}")
    print("walk meta1 nonzero:", sum(c for (m0, m1), c in walk_meta.items() if m1))
    print("\nhit meta0 histogram:", dict(Counter({m0: c for (m0, m1), c in hit_meta.items()}).most_common(10)))
    print("hit meta1 nonzero:", sum(c for (m0, m1), c in hit_meta.items() if m1))
    print("\nthru (meta0=edge mask, meta1=event) top pairs:", thru_meta.most_common(10))
    print("\ncheck meta0 (event id) top:", Counter({m0: c for (m0, m1), c in check_meta.items()}).most_common(10),
          " meta1 nonzero:", sum(c for (m0, m1), c in check_meta.items() if m1))
    print("\nnpc-hit meta0 top:", Counter({m0: c for (m0, m1), c in npc_meta.items()}).most_common(8),
          " meta1 nonzero:", sum(c for (m0, m1), c in npc_meta.items() if m1))
    print("\ndisk-order first-14-sections patterns (top 5):")
    for pat, c in order_patterns.most_common(5):
        print(f"  {c:4d}  {pat}")

if __name__ == "__main__":
    main()
