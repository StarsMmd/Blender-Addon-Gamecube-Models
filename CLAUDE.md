# DAT Plugin — Claude Context

## Project Overview

A Blender addon that imports and exports `.dat` 3D model files used in GameCube games (primarily Pokémon Colosseum and XD: Gale of Darkness). The format is based on the proprietary **SysDolphin** library, reverse-engineered by hobbyists.

**Main addon directory:** `Blender-Addon-Gamecube-Models/`

**Target Blender version:** 3.1 (a contributor is working on a version bump — merge carefully when it lands)

**Supported file extensions:** `.dat`, `.fdat`, `.rdat`, `.pkx`

---

## Architecture

### Import Pipeline (3 phases)

1. **Binary Parsing** — `DATParser` (inherits `BinaryReader`) reads the binary, resolves the relocation table, and recursively parses the node tree using the type system.
2. **Node Tree** — Each parsed struct becomes a `Node` subclass instance. 90+ node classes across 13 categories.
3. **Blender Integration** — `ModelBuilder` calls `prepareForBlender()` then `build()` on the root node, which recursively builds Blender objects.

### Export Pipeline (stub — not yet implemented)

1. Walk Blender scene → build in-memory node tree
2. Pre-allocate addresses: DFS traversal of tree, then **reverse** the list (children written before parents — matches official model convention)
3. Write nodes, relocation table, section info, ArchiveHeader

### Key Files

| File | Purpose |
|---|---|
| `shared/IO/DAT_io.py` | `DATParser` + `DATBuilder` — high-level binary I/O |
| `shared/IO/file_io.py` | `BinaryReader` + `BinaryWriter` — low-level binary I/O |
| `shared/IO/ModelBuilder.py` | Blender object construction orchestration |
| `shared/Nodes/Node.py` | Abstract base class for all nodes |
| `shared/Nodes/NodeTypes.py` | Type resolution, class lookup, alignment |
| `shared/Constants/RecursiveTypes.py` | Type string parsing (pointers, arrays, brackets) |
| `shared/Constants/PrimitiveTypes.py` | Primitive type sizes, struct formats, alignment |
| `shared/Constants/hsd.py` | HSD format bit-flag constants |
| `shared/Constants/gx.py` | GameCube GX graphics API constants |

### Reference Code

`shared/reference/import_hsd old.py` (~3011 lines) — the original monolithic importer. **Development strategy: port one function at a time** into the appropriate node class or builder method.

---

## Node System

### Defining a Node

```python
class MyNode(Node):
    class_name = "My Node"
    fields = [
        ('name',  'string'),
        ('flags', 'uint'),
        ('child', 'MyNode'),        # pointer to same type — automatically followed
        ('next',  'MyNode'),
        ('data',  '[4]float'),      # bounded array of 4 floats
        ('items', 'OtherNode[]'),   # unbounded array (null-terminated)
    ]
```

Fields are parsed generically by `DATParser.parseNode()`. Override `loadFromBinary()` to do post-processing (e.g. reading `property` field as a typed pointer based on flags — see `Joint.loadFromBinary()`).

### Type System Rules

Precedence: `() > * > [] > primitive > NodeClass`

- `Joint` → implicitly becomes `*Joint` (pointer, auto-followed)
- `*Joint[]` → pointer to array of Joints
- `[count]Type` — bounded array; `count` can reference another field name and is resolved by a two-pass parse
- `@TypeName` — prefix `@` prevents automatic pointer wrapping

### Node Lifecycle

- **Parse path:** `Node(address, None)` → `loadFromBinary(parser)` → fields set
- **Build path:** `prepareForBlender(builder)` → `build(builder)` → Blender objects created
- **Write path:** `allocationSize()` / `allocationOffset()` → `writePrimitivePointers()` / `writeStringPointers()` → `writeBinary(builder)`

### Caching

Nodes are cached by file offset (`nodes_cache_by_offset`). Cache before parsing sub-nodes to handle cycles. Nodes with `is_cachable = False` skip this.

---

## Current Status

| Feature | Status |
|---|---|
| Binary parsing (all node types) | ✅ Complete |
| Static model import (geometry + textures) | ✅ Working for most models |
| Skeleton/armature import | ✅ Working |
| Joint animation import | ❌ Stubs only — no `build()` |
| Material/shape animation import | ❌ Stubs only |
| Camera / Light / Fog import | ❌ Stubs only |
| Exporter | ❌ Stub only — `DATBuilder` infrastructure exists |
| Unit tests | ❌ Not written yet |

---

## Known Bugs (fix before adding features)

- `ExportHSD.execute()` in `__init__.py:81` references `path` (undefined) — should be `self.filepath`
- `DATBuilder.build()` at `DAT_io.py:279` is missing `self` parameter
- `DATBuilder._currentRelativeAddress()` at `DAT_io.py:277` references `DAT_header_length` without `self.`
- `DATBuilder.build()` references `data_size` (undefined) — should be `data_section_length`
- `DATBuilder.__init__()` calls `.toList().reverse()` — `list.reverse()` returns `None`; should be `reversed(root_node.toList())` or assign then reverse
- `Joint.writeBinary()` references `isHidden` (undefined) — should be `self.isHidden`

---

## Implementation Priorities

### Priority 1 — Animation (all missing)
Reference: `shared/reference/import_hsd old.py` lines 204–658

- Frame/keyframe data parsing → `Frame.py` / `Animation.py`
- Bone animation traversal → `AnimationJoint.build()`
- Blender fcurve/keyframe generation → `ModelSet.build()` or `AnimationJoint.build()`
- Animation looping (CYCLES modifier)
- Matrix decomposition for animated bones

### Priority 2 — Geometry Details (partially done)
Reference: lines 2214–2575

- Bone weights / envelope deformation → `PObject.build()` / `Joint`
- Shape keys / morph targets → `ShapeSet.build()`
- Custom normals assignment → `PObject.build()`
- sRGB → linear colour conversion utility
- IK constraints → `ModelSet.build()` (commented out)
- Bone instances (`JOBJ_INSTANCE`) → `Joint.build()` (commented out)

### Priority 3 — Advanced Materials (partially done)
Reference: lines 750–1627

- TEV colour multiply / comparison ops / environment mapping → `MaterialObject.build()`
- Pixel engine blending → `PixelEngine.build()`

### Priority 4 — Lights, Cameras, Fog (all stubs)
Reference: lines 1629–1711

### Priority 5 — Exporter (not started)
`DATBuilder` infrastructure exists. Needs:
1. Blender scene → node tree (inverse of import Phase 3)
2. Address pre-allocation (DFS then reverse)
3. Binary write + relocation table + section info + ArchiveHeader

Round-trip goal: parse → write → **identical binary**.

---

## Testing Strategy

- Framework: **pytest**
- **No game files** (copyrighted ROMs) in the repository — ever
- Test data: Python helper functions that programmatically build valid node binaries
- Cover: round-trip parse (build binary → parse → verify fields) and round-trip write (parse synthetic tree → write → compare bytes)
- Test small sub-trees (e.g. a Joint with one child Mesh)

---

## Coordinate System

GameCube → Blender requires a π/2 rotation around the X-axis. Applied once at the armature level in `ModelSet.translate_coordinate_system()`. Do not apply it to individual bones or meshes.

---

## Blender API Notes

- Currently targeting **Blender 3.1**
- `bpy.ops.object.mode_set()` must be called to switch between EDIT / POSE / OBJECT modes when building armatures
- `armature.data.edit_bones` is only accessible in EDIT mode
- `armature.pose.bones` is only accessible in POSE mode
- `bpy.context.view_layer.update()` needed after structural scene changes
