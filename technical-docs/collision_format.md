# CCD — Colosseum / XD map collision format

Research notes for the planned collision import/export feature. Everything below was
verified against the full dumped corpus (185 `.ccd` files across both games: the
XD dump in `~/Documents/GoD Tool/XD GoD Tool dumped/Game Files/` and the partial
Colosseum dump in `~/Documents/GoD Tool/Colo CM Tool/Game Files/`), the XD
disassembly (`~/Documents/Projects/GoD-Tool/scripts/Disassembly-XD/text1/GScolsys2*`),
and the GoD-Tool documentation (`Documentation/Assembly Analysis/Data Structures/CCD.md`,
which this file corrects in a few places — see § Corrections).

## Overview

Every map (`<name>.fsys`) pairs its room model (`.rdat`, FSYS type 0x02) with a
collision database (`<name>_col.ccd`, FSYS type 0x06 — renamed to `<name>.ccd` by the
GoD Tool dumper). The format is **byte-identical between Colosseum and XD** and is
consumed by the shared `GScolsys2` runtime. All values big-endian; coordinates are
world-space, **Y-up** (same GX convention as the models); all pointers are stored as
byte offsets from file start (0 = null) and are relocated in place on load by
`_offsetCCD`.

A CCD is a list of **entries** ("objects"): the static level geometry, plus one entry
per independently toggleable element (each door panel is its own entry). Each entry
carries up to six triangle meshes feeding six different collision subsystems.

## Structures

```
FILEHEAD (0x08):
  0x00  u32  entries offset (always 0x10 in practice)
  0x04  u32  entry count            (corpus range: 1..63)

ENTRY (0x40):
  0x00  f32[3]  position   ─┐ identity in all 2355 shipped entries;
  0x0C  f32[3]  rotation    ├ copied to the runtime object array at load,
  0x18  f32[3]  scale      ─┘ only meaningful for dynamic entries
  0x24  u32  -> WALK  mesh head   ground polys: height/layer lookup
  0x28  u32  -> HIT   mesh head   wall polys: hero blocking
  0x2C  u32  -> THRU  mesh head   walk-through trigger polys
  0x30  u32  -> CHECK mesh head   A-button / inspection trigger polys
  0x34  u32  -> HIT_NPC mesh head wall polys: NPC blocking
  0x38  u32  -> SUN   mesh head   lens-flare occluders
  0x3C  u16  flags (bit 0 = dynamic: per-frame transform)   — 0 in all shipped files
  0x3E  u16  pad

GRID MESH HEAD (0x24 — walk / hit / thru / hit_npc):
  0x00  u32  -> POLY array         0x04  u32  poly count
  0x08  u32  -> CELL array         0x0C  u32  -> u32 poly-index pool
  0x10  u16  grid width  (X)       0x12  u16  grid height (Z)
  0x14  f32  cell size X           0x18  f32  cell size Z
  0x1C  f32  origin X              0x20  f32  origin Z
CELL (0x08): u32 index-pool offset, u32 count.  cells[z * width + x].

SIMPLE MESH HEAD (0x08 — check / sun): u32 -> POLY array, u32 count.

POLY (0x34):  f32[3] v0, v1, v2, plane normal;  u16 meta0;  u16 meta1
SUN POLY (0x30): same minus the two meta halfwords
```

### Slot names vs plugin names

The runtime's own terms (used throughout this doc, and matching the `GScolsys2`
symbols) map to the plugin's behaviour-named `CollisionSubsystem` like this:

| Slot | Engine term | Plugin name | UI label |
|---|---|---|---|
| 0 | walk | `WALK` | Walk |
| 1 | hit | `WALL` | Wall |
| 2 | thru | `ZONE_TRIGGER` | Zone Trigger |
| 3 | check | `BUTTON_TRIGGER` | Button Trigger |
| 4 | hit_npc | `NPC_WALL` | NPC Wall |
| 5 | sun | `SUN` | Sun |

The stored normal is exactly `normalize(cross(v1-v0, v2-v0))` — verified bit-tolerant
on all 90 194 polys in the corpus (all same-direction, none flipped). It is derived
data and can be recomputed from winding on export.

### Per-subsystem poly metadata (verified from GScolsys2 code + corpus)

| Subsystem | meta0 (+0x30) | meta1 (+0x32) |
|---|---|---|
| walk | byte 0x30 = two 4-bit **layer** IDs (hi/lo; 0xF = "any", surfaced as 0xFFFF); byte 0x31 = two 4-bit **attribute** nibbles (surface/effect, returned raw) | unused (0) |
| hit / hit_npc | low 3 bits = **edge-enable mask**: bit0 = edge v0→v1, bit1 = v1→v2, bit2 = v2→v0 (gates the edge/vertex tests in `checkHitMdl`) | unused (0) |
| thru | low 3 bits = edge-enable mask, **poly skipped entirely if 0** | **event/region ID** |
| check | **event/region ID** | unused (0) |
| sun | — (no metadata) | — |

Corrections to the GoD-Tool `CCD.md` doc: thru meta0 is *not* an "enter event ID" —
it is the same edge mask as hit (the enter/exit distinction comes from crossing
direction vs the plane normal inside `GScolsys2ThruGetEventID` / `ThruPassEventID`,
both reading meta1). Its three open questions are also resolved: the index-pool
reading is correct (validated on ~3 500 grids, zero inconsistencies), byte 0x30 is the
layer byte (sentinel handling confirmed in `GScolsys2WalkGetHeight`), and the disk
ordering is deterministic (below).

### Spatial grid — fully derivable

For each gridded mesh (validated on all ~3 500 grids in the corpus):

- `origin = AABB min` of the mesh's triangles, exactly (3500/3500).
- Cell size is fixed **40×40** units unless the axis extent exceeds `32 × 40`;
  then the axis is capped at **32 cells** and `cell = extent / 32`.
- `grid_dims = ceil(extent / cell)` (plain ceil, no epsilon), capped at 32.
- Cells are row-major `cells[z * width + x]`; each cell's slice of the shared
  u32 index pool lists the polys overlapping that cell (a poly spanning several
  cells appears in each). The pool is packed tightly in cell order.

This means the grid never needs to be stored in Blender — export recomputes it.

### Deterministic disk layout

Verified corpus-wide (zero violations): file head, entry table at 0x10, then mesh
sections grouped **by subsystem type** in entry-pointer order
`walk → hit → thru → check → hit_npc → sun`, ascending entry index within each
group, and each mesh emitting `head | polys | cells | index pool` contiguously.
**Coverage is total:** every non-padding byte of all 185 files is claimed by these
structures — there is no other hidden metadata in the format.

## How the game uses it

The `GScolsys2` module (`GScolsys.a`, identical sources both games) queries per frame:

- **Walk** (`GScolsys2WalkGetHeight` / `WalkGetLayer`): vertical ray vs walk polys →
  ground height + layer/attr. Layers implement multi-level maps (bridges): the hero's
  current layer (`GScolsys2GetCurFloor`, `HumanAddCurrentFloor`) filters candidate
  floors; 0xF nibbles mean "matches any layer". Attribute nibbles surface to gameplay
  (footstep/surface effects) via `WalkGetLayer`.
- **Hit / Hit_NPC** (`checkHitFixedMdl` / `checkHitMdl` / `GScolsys2HitCollision`):
  hero (resp. NPC) cylinder vs wall polys, with per-edge tests gated by the edge mask.
  In shipped data hit_npc is a near-exact duplicate of hit (14 610 vs 14 611 polys
  corpus-wide) — occasionally NPCs get extra/fewer walls.
- **Thru** (`GScolsys2ThruGetEventID` / `ThruPassEventID`): movement segment vs
  trigger polys → the crossed poly's meta1 event ID (crossing direction vs the normal
  distinguishes enter/exit). Used for warp zones, door approach triggers, area events.
- **Check** (`GScolsys2CheckGetEventID`): the A-button/inspection ray vs check polys →
  meta0 event ID (signs, PCs, examinable objects).
- **Sun** (`GScolsys2Sun`): sun-visibility raycast for lens flares. Geometry only.

### Runtime enable/disable — doors, blocked boundaries

At load, `GScolsys2LoadCCD` copies each entry's SRT into a runtime object array
(0x28-byte records) and clears a per-entry **enable flag** (bit 0 of runtime
object +0x24 — a *different* halfword from the file entry's dynamic flag).
`GScolsys2SetObjEnable(index, enable)` toggles it; disabled entries are skipped by
every subsystem.

- **XD script access:** XDS class 46 `Collision`, method 16
  `setEnabled(id, bool)` → native `scriptSetCol` (0x801c8274 US) →
  `GScolsys2SetObjEnable`. Also methods 17/18 `getEventCollision`/`setEventCollision`
  (→ `scriptGetEventColID` / `scriptSetEventCol`). This is the known "enable/disable
  boundaries on the fly" script function.
- **Colosseum** has the same engine path but exposes no named script builtin for it
  (candidate: builtin 191 `mapTransformElement`, unconfirmed).
- **Doors:** common.rel's Doors table (XD pointer index 60/61; 0x18 bytes per door:
  +0x00/+0x01 open/close anim indices, +0x07 sound type, **+0x0A s16 CCD entry
  index**, +0x0C u16 room ID, +0x0E u16 GSflag, +0x14 u32 model ref) drives
  `floorEventCtrlDoor`: opening a door calls `scriptSetCol(entry, 0)` (collision
  off) and sets the flag; closing re-enables. Verified: **all 154 XD door records
  (and all 7 checkable Colosseum ones) point at valid CCD entries, every one a
  small hit-only mesh** — i.e. each door panel is its own dedicated entry.
- **Elevators** are not moving collision: they are interaction points of the
  Elevator type (target room / target elevator / direction) — effectively warps —
  and in Colosseum some elevator states are whole alternate map archives
  (`D1_garage_B2_2_ev_1` / `_ev_2`). No shipped file sets the dynamic entry flag;
  moving collision is engine capability that the retail data never uses.

### Trigger → script linkage (common.rel)

`InteractionPoints` (XD pointer index 62/63; Colosseum 86/87; 0x1C bytes each):

```
0x00 u8   interaction method (0 none, 1 WalkThrough, 2 WalkInFront,
                              3 PressAButton, 4 PressAButton2 (Colo))
0x02 u16  room ID
0x04 u32  collision region index  ← matches the CCD event ID
0x08 u16  script marker (current map script vs common script)
0x0A u16  script function index
0x0C u32[4] parameters
```

The pair `(room ID, region index)` is the key: a thru poly's meta1 (WalkThrough) or
a check poly's meta0 (PressAButton / WalkInFront) selects the interaction point,
which invokes the referenced script function (typed payloads: Warp, Door, Text,
Elevator, CutsceneWarp, PC — see legacy `XGInteractionPoint.swift`). Thru and check
IDs share one namespace per room. Verified numerically: **152/152 XD rooms and 7/7
checkable Colosseum rooms** have every interaction-point region index present among
the room's CCD event IDs. (The reverse isn't required — a few CCD event IDs have no
interaction point; scripts can read them directly.)

Room ↔ map file resolution: common.rel Rooms table (XD index 58/59, 0x40-byte
entries: room ID u16 at +0x02, fsys IDs at +0x2C), fsys ID = u32 at offset 0x08 of
the map's `.fsys` header.

## Blender import mapping

The plugin imports a `.ccd` on its own path — `extract → parse → describe →
plan → build` over the collision structures, `IRCollisionScene` and
`BRCollisionScene` — sharing only the container-extraction step with models
(FSYS type `0x06`, or a `.ccd` opened directly). Every decision below is
verified against the full corpus.

**Scene graph.** One collection per file, `Collision_{name}`, with a child
collection per collision type in use (`Collision_{name}_Wall`, `_Zone Trigger`,
…). Visibility is why the collections exist: hiding a *parent object* does not
hide its children in Blender, so the Empty alone could not hide the overlay —
collections can, and they also let one type be soloed.

Inside that collection sits an Empty, also `Collision_{name}`, carrying the
same Y-up→Z-up π/2 rotation the armature import uses so the overlay lands on
the room model. Every mesh parents to it for transform, while living in its
type's collection for visibility. Meshes are named
`Col_{name}_{entry:02d}_{type}` — `type` being the lowercased plugin name —
plus `_r{region}` where regions split. An entry with no meshes (8 corpus-wide)
becomes a bare Empty in the root collection so its index survives.

**Materials.** One shared `DATPlugin_Collision_{TYPE}` per type, colour-coded
and translucent, with opacity graded by how much the type needs to be read
through: walk and sun 0.3, walls 0.5, triggers 0.7.

**Object properties** — `dat_col_type` (the six-value enum), `dat_col_entry`
(the grouping key on export; doors and `Collision.setEnabled` address entries
by index), `dat_col_region` (area/button triggers), `dat_col_npc_blocks`
(wall), `dat_col_dynamic`. The entry SRT rides the object's own transform.

**Per-face INT attributes**, for what genuinely varies within a mesh:
`col_edge_mask` (wall / NPC wall / zone trigger — 2 to 8 distinct values per
mesh, so it cannot be an object property), and `col_layer_a/b`,
`col_surface_a/b` on walk.

**NPC walls are stored as a difference.** Of the 973 entries carrying both
wall meshes, 952 are poly-for-poly identical, 21 are supersets adding 2–4
polys, and *none* is ever a subset or a reordering — so the IR keeps a
`npc_shares_hit` flag plus whatever the NPC mesh adds. That collapses 1 150
NPC objects to 198. Two of the 21 supersets interleave their extras rather
than appending them, so re-composing those changes poly *order* (harmless —
the grid is rebuilt from whatever order is emitted).

**Region IDs become objects, not face attributes.** 610/613 zone-trigger and
178/208 button-trigger meshes already carry exactly one region ID, and in every multi-ID mesh
the polys are contiguous *and* ascending by ID, so splitting on import and
merging in ascending order reproduces the original poly order exactly. 33
objects gain an `_r{N}` suffix.

**Geometry normalisation.** The three independent corners each poly stores
weld to an indexed mesh (437 442 → 139 837 vertices corpus-wide, ~32%); no
poly anywhere has a repeated corner, so welding always yields a valid
triangle. 82 polys duplicate another face in the same mesh, which Blender's
validate would eat, so those keep private vertices. Positions are scaled by
`GC_TO_METERS` like every other IR position.

**Reconstruction is lossless.** Rebuilding all 145 814 polys from the IR
across all 185 files reproduces the parsed data exactly, with the 2 NPC-wall
reorderings above as the only difference. Four collinear walk polys store NaN
normals in the shipped data; the naive `normalize(cross(...))` an exporter
would use reproduces them bit-for-bit, so they need no special case.

## Open questions

- **Edge-mask generation rule.** Bit↔edge assignment is confirmed (identity), but
  the original tool's rule for *choosing* the mask is only partially reproducible:
  "edge disabled iff shared with a coplanar triangle" predicts 56.3% of hit-poly
  masks exactly (plain boundary-edge rule: 33.9%). Preserving imported masks as face
  attributes sidesteps this; the heuristic is only a default for newly authored
  faces. Gameplay impact of an imperfect mask is subtle (corner-sliding feel).
- **Index-pool within-cell ordering** (assumed ascending poly index) — confirm
  during exporter round-trip work.
- **Colosseum script-side toggle** — identify the builtin (if any) wrapping the
  engine's enable path; XD's `Collision.setEnabled` is confirmed.

## Corpus facts useful for tooling

- 185 files, 2355 entries; slot usage: walk 566, hit 1171, thru 613, check 208,
  hit_npc 1150, sun 32. All entry SRTs identity, all entry flags 0.
- Entry compositions cluster by role: `hit+hit_npc` (walls, 722), `walk` (floors,
  562), `thru` (triggers, 398), `hit+check+hit_npc` (solid examinables, 201),
  `hit` alone (198 — door panels among them), `thru+hit_npc` (NPC-blocking
  triggers, 168), `sun` (32).
- Walk normals: 88% within 45° of +Y (rest are ramps/stairs).
- Cell size 40×40 in 3475/3500 grids (the rest are the 32-cap cases).
