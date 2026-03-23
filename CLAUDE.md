# DAT Plugin — Claude Context

## Project Overview

A Blender addon that imports and exports `.dat` 3D model files used in GameCube games (primarily Pokémon Colosseum and XD: Gale of Darkness). The format is based on the proprietary **SysDolphin** library, reverse-engineered by hobbyists.

**Main addon directory:** `Blender-Addon-Gamecube-Models/`

**Target Blender version:** 4.5

**Supported file extensions:** `.dat`, `.fdat`, `.rdat`, `.pkx`

**Reference implementation:** [Ploaj/HSDLib](https://github.com/Ploaj/HSDLib) — a C# Super Smash Bros. Melee model viewer/editor for the same SysDolphin format. Useful for understanding struct layouts and rendering behaviour. **Caveat:** HSDLib targets Melee; this plugin targets Pokémon Colosseum/XD. Different games ship slightly different versions of the SysDolphin library, so struct fields, flag semantics, and node types may not match exactly.

**Legacy reference:** The `legacy-importer` branch contains the original monolithic importer before the refactor. Useful for checking how something was originally implemented.

---

## Architecture

### Import Pipeline (4 phases)

1. **Binary Parsing** — `DATParser` (inherits `BinaryReader`) reads the binary, resolves the relocation table, and recursively parses the node tree using the type system.
2. **Node Tree** — Each parsed struct becomes a `Node` subclass instance. 90+ node classes across 13 categories.
3. **Scene Descriptor** *(planned)* — An intermediary text-based scene description generated from the node tree. This is a plain-data representation (no Blender dependency) that describes the full scene: meshes, materials, armatures, animations, lights, cameras. Benefits:
   - **Testable without Blender** — unit tests can verify the descriptor directly
   - **Convertible to .blend** — a standalone script can produce a `.blend` file from the descriptor without opening Blender's GUI
   - **Debuggable** — human-readable text format makes it easy to inspect what the importer parsed
4. **Blender Integration** — `ModelBuilder` (or a new `SceneBuilder`) reads the scene descriptor and creates Blender objects. Currently Phase 3 and 4 are merged — `ModelBuilder` calls `prepareForBlender()` then `build()` on the root node, which recursively builds Blender objects directly.

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

### Export Pipeline (4 phases)

`DATBuilder.build()` writes a `.dat` binary from an in-memory node tree.

1. **Phase 1 — Shared data** — Write vertex buffers (deduplicated), image pixels, palette data. These are shared across multiple nodes and written once at the start. Handled by `writePrimitivePointers()` on VertexList, Image, Palette.
2. **Phase 2 — DFS traversal: private data + allocate** — Traverse the node tree and for each node: write its private raw data (display lists, matrices, strings, keyframe data, pointer arrays) then allocate the node's struct space. Private data appears immediately before its owning node. Handled by `writePrivateData()`.
3. **Phase 3 — Write structs** — Write each node's struct fields at its pre-allocated address. Handled by `writeBinary()`.
4. **Phase 4 — Finalize** — 16-byte align data section, write relocation table, section info, archive header.

### DFS Traversal Order (SysDolphin convention)

The traversal in Phase 2 follows a modified DFS that matches the SysDolphin compiler's layout:

**Rule: `child`/`next`/`link` fields are written AFTER the node. All other Node-typed fields are written BEFORE (DFS into them first).** Inline `@`-prefixed structs are skipped (they're part of the parent's allocation).

This means for a Joint with fields `[name, flags, child, next, property, ...]`:
- `property` (Mesh) is visited **before** the Joint → material chain appears first
- `child` and `next` (Joints) are visited **after** the Joint → sibling/child joints come later

This produces the grouping seen in original binaries: all material chains → envelope lists → vertex lists → geometry pairs → joints → animations → lights → root nodes → BoundBox.

**Verified against nukenin.pkx:** 359/360 field-child relationships match this rule (99.7%). The single exception is `Texture.next` which is BEFORE instead of AFTER — likely because Texture chains are short and the compiler treats them as a single unit.

### Data Classification for Export

| Category | Examples | Written in | Deduplicated? |
|----------|----------|------------|---------------|
| **Shared** | Vertex buffers, image pixels, palette data | Phase 1 | Yes, by original address |
| **Private** | Display lists (32B aligned), matrices, frame `ad`, light floats, strings, pointer arrays | Phase 2 (before owning node) | No |
| **Inline** | BoundBox AABB data, EnvelopeList entries | Part of node's `allocationSize()` | No |

### Round-Trip Test Results

| Model | Input | Output | Diff | Status |
|-------|-------|--------|------|--------|
| nukenin.pkx | 67,072 | 67,072 | 0 | ✅ Exact size |
| darklugia.pkx | 392,416 | 392,752 | +336 | ⚠️ 99.9% |
| bohmander.pkx | 367,840 | 368,880 | +1,040 | ⚠️ 99.7% |
| houou.pkx | 430,080 | 432,352 | +2,272 | ⚠️ 99.5% |
| achamo.pkx | 296,192 | 301,680 | +5,488 | ⚠️ 98.1% |
| mage_0101.pkx | 295,552 | 271,280 | -24,272 | ❌ 91.8% (missing nodes) |

All models re-parse both sections with 0 value mismatches. Size differences come from:
- Extra EnvelopeList allocations (duplicate Python objects for `is_cachable=False` nodes)
- Alignment padding differences from traversal order variations
- mage_0101 has 155 animation sets with a traversal pattern that doesn't fully match

### Future Traversal Investigations

- **Leaf joints without properties** — Currently written before their subtree's material chains; may need to be deferred until after the full subtree
- **EnvelopeList dedup** — Multiple PObjects reference overlapping EnvelopeLists; need address-based dedup that doesn't break the PObject envelope pointer arrays
- **mage_0101 missing data** — Model has 155 animation sets; some nodes may not be reachable via the current DFS, or the animation set count causes different compiler behaviour
- **Texture.next exception** — The only field that breaks the child/next=AFTER rule; investigate whether it's a special case for short linked lists or a different compiler heuristic

---

## Node System

### Defining a Node

```python
class MyNode(Node):
    class_name = "My Node"
    fields = [
        ('name',  'string'),
        ('flags', 'uint'),
        ('count', 'uint'),          # integer field used as array bound below
        ('child', 'MyNode'),        # pointer to same type — automatically followed
        ('next',  'MyNode'),
        ('data',  'float[4]'),      # bounded array of 4 floats
        ('items', 'float[count]'),  # bounded array whose length comes from the 'count' field
        ('nodes', 'OtherNode[]'),   # unbounded array (null-terminated)
    ]
```

Fields are parsed generically by `DATParser.parseNode()`. Override `loadFromBinary()` to do post-processing (e.g. reading `property` field as a typed pointer based on flags — see `Joint.loadFromBinary()`).

### Type System Rules

Precedence: `() > * > [] > primitive > NodeClass`

- `Joint` → implicitly becomes `*Joint` (pointer, auto-followed)
- `*Joint[]` → pointer to array of Joints
- `Type[count]` — bounded array; `count` can reference another field name and is resolved by a two-pass parse
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
| Joint animation import | ✅ Working |
| Material animation import | ⚠️ Implemented (color/alpha tracks + NLA), needs bug fixes |
| Texture animation import | ⚠️ Partially implemented |
| Shape animation import | ❌ Stubs only |
| Scene descriptor (intermediary format) | ❌ Not started |
| Light import | ✅ Working (SUN, POINT, SPOT; animation stubbed) |
| Camera / Fog import | ❌ Stubs only |
| Exporter | ⚠️ Round-trip functional (0 value mismatches, exact size match on nukenin, 98-100% on other models) |
| Unit tests | ✅ Passing |

---

## Known Bugs (fix before adding features)

- ~~`ExportHSD.execute()` in `__init__.py:81` references `path` (undefined) — should be `self.filepath`~~ ✅ Fixed
- ~~`DATBuilder.build()` at `DAT_io.py:279` is missing `self` parameter~~ ✅ Fixed
- ~~`DATBuilder._currentRelativeAddress()` at `DAT_io.py:277` references `DAT_header_length` without `self.`~~ ✅ Fixed
- ~~`DATBuilder.build()` references `data_size` (undefined) — should be `data_section_length`~~ ✅ Fixed
- ~~`DATBuilder.__init__()` calls `.toList().reverse()` — `list.reverse()` returns `None`; should be `reversed(root_node.toList())` or assign then reverse~~ ✅ Fixed
- ~~`Joint.writeBinary()` references `isHidden` (undefined) — should be `self.isHidden`~~ ✅ Fixed
- ~~`ShapeSet.writeBinary()` references `vertex_set`/`normal_set` without `self.` prefix~~ ✅ Fixed
- ~~`ArchiveHeader.allocationSize()` nested inside `loadFromBinary()` — dedented to class level~~ ✅ Fixed
- ~~`Light.writeBinary()` calls `.address` on a float — fixed to write float via builder~~ ✅ Fixed
- ~~`BinaryWriter.write()` string missing null terminator~~ ✅ Fixed
- ~~`Joint.writeBinary()` crashes when `property` is `None`~~ ✅ Fixed
- ~~`DATBuilder.writeNode()` second loop doesn't mark up field types, crashes writing null pointers~~ ✅ Fixed
- ~~`DATBuilder.write()` doesn't handle `None` for pointer types~~ ✅ Fixed
- ~~`DATBuilder.__init__()` uses `seek()` to reserve header space — breaks with BytesIO~~ ✅ Fixed
- ~~`DAT_io.py:277` — `# TODO: Look at EnvelopeList` — needs investigation for special node handling~~ ✅ Fixed (EnvelopeList now has allocationSize + writeBinary)
- ~~`DATBuilder` archive header missing `external_nodes_count` field at offset 16~~ ✅ Fixed
- ~~`DATBuilder.writeNode()` second loop doesn't record relocations for pointer fields~~ ✅ Fixed
- ~~`DATBuilder` section info hardcoded to only SceneData/BoundBox~~ ✅ Fixed (now accepts section_names parameter)
- ~~`DATBuilder` Phase 1/2/3 ordering: pointer-to-primitive data (matrices, strings) written in Phase 3 overlapped with Phase 2 node allocations~~ ✅ Fixed (moved to base `Node.writePrimitivePointers()`)
- ~~Raw binary data (display lists, images, vertices, frames, palettes) not preserved during parse for round-trip~~ ✅ Fixed (added `raw_*` storage + `writePrimitivePointers` overrides)
- ~~`DATBuilder` round-trip re-parse fails on Light node — RGBA color pointer fields written incorrectly~~ ✅ Fixed (Light.loadFromBinary used exact flag comparison instead of masking; flags were being overwritten)
- ~~`DATBuilder.write()` for unbounded arrays double-wrote pointer data~~ ✅ Fixed
- ~~`DATBuilder.write()` for node class types re-wrote already-addressed nodes~~ ✅ Fixed
- ~~Missing relocations for `uint` fields that hold pointer addresses~~ ✅ Fixed (added `_raw_pointer_fields` tracking mechanism)
- ~~Vertex `base_pointer=0` treated as invalid (is valid, points to start of data section)~~ ✅ Fixed
- ~~`DATBuilder` round-trip had ~652B data gap from write order differences~~ ✅ Fixed (refactored to 4-phase pipeline with DFS traversal matching SysDolphin conventions — see Export Pipeline section)
- Traversal order produces exact size match for nukenin.pkx but 1-2% overhead on some other models — see investigation notes below
- Extra EnvelopeList nodes (9 for nukenin) due to `is_cachable=False` creating duplicate Python objects for the same binary address; needs dedup that doesn't break re-parse
- `mage_0101.pkx` round-trip outputs smaller file (-8%) — some nodes not visited by DFS, needs investigation

---

## Implementation Priorities

### Priority 1 — Animation

- ~~Frame/keyframe data parsing → `Frame.py` / `Animation.py`~~ ✅ Done
- ~~Bone animation traversal → `AnimationJoint.build()`~~ ✅ Done
- ~~Blender fcurve/keyframe generation → `ModelSet.build()` or `AnimationJoint.build()`~~ ✅ Done
- ~~Material animation import → `MaterialAnimationJoint` / `MaterialAnimation`~~ ✅ Done (color/alpha tracks, sRGB conversion, NLA tracks)
- ~~Texture animation import → `TextureAnimation`~~ ⚠️ Partially done (UV mapping animation)
- ~~Animation looping (CYCLES modifier)~~ ✅ Done
- Shape animation import → `ShapeAnimationJoint` / `ShapeAnimation`
- Matrix decomposition for animated bones

### Priority 2 — Scene Descriptor (intermediary format)

Introduce a Blender-independent, text-based scene description between the node tree and Blender object creation. This decouples parsing from Blender, enabling headless `.blend` generation and unit testing without `bpy`.

**Design:**
- A plain Python data structure (dataclasses or dicts) describing the scene: armatures, meshes, materials, animations, lights, cameras
- Serializable to/from a human-readable text format (e.g. JSON or YAML)
- Each node class gets a `describe(descriptor)` method (analogous to `build(builder)`) that populates the descriptor instead of calling Blender APIs
- A new `SceneBuilder` reads the descriptor and creates Blender objects — replacing the current direct `build()` → `bpy` calls
- A standalone CLI script converts a descriptor file to `.blend` without opening Blender's GUI (using Blender's `--background --python` mode)

**Steps:**
1. Define the scene descriptor schema (dataclasses for Armature, Mesh, Material, Animation, etc.)
2. Implement `describe()` on core node classes: `ModelSet`, `Joint`, `Mesh`/`PObject`, `MaterialObject`
3. Implement `SceneBuilder` that creates Blender objects from the descriptor
4. Migrate existing `build()` logic to go through the descriptor path
5. Add descriptor-level unit tests (no `bpy` dependency)
6. Add CLI script for `.blend` generation from descriptor files

### Priority 3 — Refactor Helper Functions in Node Classes

Duplicated logic across animation node classes should be consolidated:

- **Extract parallel tree traversal helper** — `AnimationJoint.build()` and `MaterialAnimationJoint.build()` share nearly identical child/next recursion with tree-mismatch warnings. Extract `_walk_parallel_trees(anim_node, joint, callback, logger)` or create a shared `AnimationTreeNode` base class
- **Consolidate animation track mappings** — `MaterialAnimation._mat_color_map`, `TextureAnimation` type mappings, and `Frame._interpolation_dict` could move to a shared animation constants/utilities module
- **Extract shader node builder methods** — `MaterialObject.build()` has complex conditional logic for diffuse/alpha rendering modes that should be split into smaller methods
- **Standardize temp attribute pattern** — nodes use ad-hoc `temp_name`, `temp_matrix`, `edit_scale_correction` attributes during build. Consider a formal build-context object passed through the tree instead

### Priority 4 — Material Animation Bug Fixes

Material animation is implemented but needs hardening:

- **RenderAnimation** — completely empty stub, needs implementation
- **TextureAnimation** — partially implemented, missing animation track types beyond UV mapping
- **Tree mismatch handling** — currently logs warnings but continues silently when animation/joint trees don't align; should handle gracefully (skip subtree or fall back)
- **Test coverage** — no unit tests for material/texture animation keyframe generation; add round-trip tests using synthetic animation data
- **NLA track stacking** — verify correct behavior when multiple material animations target the same material (track ordering, muting)

### Priority 5 — Geometry Details (partially done)

- Bone weights / envelope deformation → `PObject.build()` / `Joint`
- Shape keys / morph targets → `ShapeSet.build()`
- Custom normals assignment → `PObject.build()`
- sRGB → linear colour conversion utility
- IK constraints → `ModelSet.build()` (commented out)
- Bone instances (`JOBJ_INSTANCE`) → `Joint.build()` (commented out)

### Priority 6 — Advanced Materials (partially done)

- TEV colour multiply / comparison ops / environment mapping → `MaterialObject.build()`
- Pixel engine blending → `PixelEngine.build()`

### Priority 7 — Cameras, Fog, Light Animation (stubs)

### Priority 8 — Exporter

Round-trip (parse → write → re-parse) is functional with 0 value mismatches. Binary-level size match achieved for nukenin.pkx; 98-100% for other tested models. Remaining work:

- **Blender scene → node tree** (inverse of import Phase 3) — not started, `Exporter.writeDAT()` is a stub
- **Traversal order refinement** — close remaining size gaps on models other than nukenin (see Export Pipeline section)
- **EnvelopeList dedup** — eliminate duplicate allocations from `is_cachable=False` nodes
- **Byte-identical output** — match internal data layout, not just file size

---

## Testing Strategy

- Framework: **pytest**
- **No game files** (copyrighted ROMs) in the repository — ever
- Test data: Python helper functions that programmatically build valid node binaries
- Cover: round-trip parse (build binary → parse → verify fields) and round-trip write (parse synthetic tree → write → compare bytes)
- Test small sub-trees (e.g. a Joint with one child Mesh)
- **Round-trip test tool:** `python3 test_dat_write.py <input_file>` — parses a `.dat`/`.pkx` model, writes it back as `_output.dat` in the same directory, re-parses and compares fields + bytes. For `.pkx` files, byte comparison skips the PKX container header and only compares the DAT section.

---

## Coordinate System

GameCube → Blender requires a π/2 rotation around the X-axis. Applied once at the armature level in `ModelSet.translate_coordinate_system()`. Do not apply it to individual bones or meshes.

---

## Blender API Notes

- Currently targeting **Blender 4.5**
- `bpy.ops.object.mode_set()` must be called to switch between EDIT / POSE / OBJECT modes when building armatures
- `armature.data.edit_bones` is only accessible in EDIT mode
- `armature.pose.bones` is only accessible in POSE mode
- `bpy.context.view_layer.update()` needed after structural scene changes

---

## Coding Conventions

- **Logger parameter:** Functions that accept a `logger` parameter must default to `NullLogger()` (from `shared/IO/Logger.py`), never `None`. This avoids needing `if logger:` guards throughout the code — just call `logger.debug(...)` unconditionally. All levels on `NullLogger` are no-ops.
- **Logging output:** All log messages are written to a file in the system temp directory regardless of the `verbose` setting. `verbose` only controls whether messages are also printed to the Blender console. Verbose defaults to off.
