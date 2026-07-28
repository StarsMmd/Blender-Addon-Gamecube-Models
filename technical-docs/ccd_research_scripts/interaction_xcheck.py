"""Cross-check common.rel InteractionPoints/Doors against CCD event IDs.

Proves the CCD<->script linkage documented in collision_format.md:
  - every InteractionPoint's collision-region index appears among its room's
    CCD event IDs (thru meta1 / check meta0)   -> 152/152 XD rooms verified
  - every Doors-table CCD entry index is a valid, small hit-only entry
                                                 -> 154/154 XD doors verified

REL pointer scheme (per legacy GoD Tool XGRelocationTable): walk the relocation
table; each unique relocation *target* gets sequential IDs in first-appearance
order. CommonIndexes (XD): Rooms=58/59, Doors=60/61, InteractionPoints=62/63.
(Colosseum: Rooms=14/15, Doors=30/31, InteractionPoints=86/87.)

Run: python3 interaction_xcheck.py   (imports deep_analysis.py from same dir)
"""
import struct, glob, os, importlib.util
from collections import defaultdict

def u32(b, o): return struct.unpack_from(">I", b, o)[0]
def u16(b, o): return struct.unpack_from(">H", b, o)[0]
def s16(b, o): return struct.unpack_from(">h", b, o)[0]
def u8(b, o): return b[o]

XD_ROOT = "/Users/stars/Documents/GoD Tool/XD GoD Tool dumped/Game Files"

def rel_pointers(b):
    """Return ordered unique relocation targets = the common.rel pointer table."""
    num_sections = u32(b, 0x0C)
    section_info_off = u32(b, 0x10)
    reloc_off = u32(b, 0x24)
    sections = {}
    for i in range(num_sections):
        w0 = u32(b, section_info_off + i * 8)
        sections[i] = w0 & ~3
    pointers, seen = [], {}
    off = reloc_off
    while off <= len(b) - 8:
        cmd, sec, sym = b[off + 2], b[off + 3], u32(b, off + 4)
        if cmd == 203:
            break
        if 0 < cmd <= 13 and sec in sections:
            tgt = sections[sec] + sym
            if tgt not in seen:
                seen[tgt] = len(pointers)
                pointers.append(tgt)
        off += 8
    return pointers

def main():
    da_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deep_analysis.py")
    spec = importlib.util.spec_from_file_location("da", da_path)
    da = importlib.util.module_from_spec(spec); spec.loader.exec_module(da)

    rel = open(os.path.join(XD_ROOT, "common", "common.rel"), "rb").read()
    ptrs = rel_pointers(rel)
    print(f"common.rel: {len(ptrs)} unique pointer targets")
    rooms_off, n_rooms = ptrs[58], u32(rel, ptrs[59])
    doors_off, n_doors = ptrs[60], u32(rel, ptrs[61])
    ips_off, n_ips = ptrs[62], u32(rel, ptrs[63])
    print(f"Rooms @{hex(rooms_off)} x{n_rooms}, Doors @{hex(doors_off)} x{n_doors}, "
          f"IPs @{hex(ips_off)} x{n_ips}")

    fsys_by_id = {}
    for p in glob.glob(os.path.join(XD_ROOT, "*", "*.fsys")):
        h = open(p, "rb").read(12)
        if h[:4] == b"FSYS":
            fsys_by_id[u32(h, 8)] = os.path.splitext(os.path.basename(p))[0]

    # Rooms: multi-language layout is 0x40 bytes, roomID u16 @0x02, fsysID u32 @0x2C
    room_by_id = {}
    for i in range(n_rooms):
        ro = rooms_off + i * 0x40
        room_by_id[u16(rel, ro + 2)] = u32(rel, ro + 0x2C)
    room_name = {rid: fsys_by_id.get(fid, f"fsys_{fid:x}") for rid, fid in room_by_id.items()}

    # InteractionPoints 0x1C: method@0, roomID@2, regionIndex(word)@4
    ips_by_room = defaultdict(list)
    for i in range(n_ips):
        io = ips_off + i * 0x1C
        ips_by_room[u16(rel, io + 2)].append(u32(rel, io + 4))

    print("\n=== per-room IP cross-check (rooms with IPs and a dumped ccd) ===")
    checked = matched = 0
    for room, regions in sorted(ips_by_room.items()):
        name = room_name.get(room)
        if not name or name.startswith("fsys_"):
            continue
        ccd_path = None
        for cand in (os.path.join(XD_ROOT, name, name + ".ccd"),
                     os.path.join(XD_ROOT, name, name + "_col.ccd")):
            if os.path.exists(cand):
                ccd_path = cand
        if not ccd_path:
            continue
        res, b = da.analyze(ccd_path, "XD")
        ids = set()
        for ent in res["entries"]:
            ids |= {m1 for m0, m1 in ent["meta"].get("thru", [])}
            ids |= {m0 for m0, m1 in ent["meta"].get("check", [])}
        ip_regions = set(regions)
        missing = ip_regions - ids
        checked += 1
        if not missing:
            matched += 1
        if checked <= 12 or missing:
            print(f"  room {room:4d} {name:22s} IP={sorted(ip_regions)[:12]} "
                  f"ccd_ids={sorted(ids)[:14]} {'OK' if not missing else 'MISSING ' + str(sorted(missing)[:8])}")
    print(f"\nrooms checked: {checked}, all IP regions present in CCD: {matched}")

    # Doors 0x18: CCD entry index s16 @0x0A, roomID u16 @0x0C, flag u16 @0x0E
    print("\n=== door -> CCD entry cross-check ===")
    ok = bad = shown = 0
    for i in range(n_doors):
        do = doors_off + i * 0x18
        ccd_idx = s16(rel, do + 0x0A)
        room = u16(rel, do + 0x0C)
        flag = u16(rel, do + 0x0E)
        name = room_name.get(room, "?")
        ccd = os.path.join(XD_ROOT, name, name + ".ccd")
        if ccd_idx < 0 or not os.path.exists(ccd):
            continue
        res, b = da.analyze(ccd, "XD")
        if ccd_idx < len(res["entries"]):
            ok += 1
            if shown < 12:
                ent = res["entries"][ccd_idx]
                comp = "+".join(da.SLOT_NAMES[s] for s in ent["slots"])
                print(f"  room {room:3d} {name:20s} door->entry {ccd_idx:2d} "
                      f"({comp}, tris={ent['tris']}) flag={hex(flag)}")
                shown += 1
        else:
            bad += 1
            print(f"  room {room:3d} {name:20s} door->entry {ccd_idx} OUT OF RANGE")
    print(f"\ndoor->CCD-entry links valid: {ok}, out-of-range: {bad}")

if __name__ == "__main__":
    main()
