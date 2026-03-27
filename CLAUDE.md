# DAT Plugin — Claude Context

## Project Overview

A Blender addon that imports and exports `.dat` 3D model files used in GameCube games (primarily Pokémon Colosseum and XD: Gale of Darkness). The format is based on the proprietary **SysDolphin** library, reverse-engineered by hobbyists.

**Target Blender version:** 4.5

**Supported file extensions:** `.dat`, `.fdat`, `.rdat`, `.pkx`, `.fsys`

**Reference implementation:** [Ploaj/HSDLib](https://github.com/Ploaj/HSDLib) — a C# Super Smash Bros. Melee model viewer/editor for the same SysDolphin format. **Caveat:** HSDLib targets Melee; this plugin targets Pokémon Colosseum/XD — struct fields, flag semantics, and node types may not match exactly.

---

## Architecture

### Import Pipeline (5 phases)

Each phase is a pure function: input → output, no shared mutable state. All phases live under `importer/phases/`. The entry point is `Importer.run()` in `importer/importer.py`.

```
Phase 1 (extract)        raw file bytes → DAT bytes (strip PKX/FSYS headers)
Phase 2 (route)          DAT bytes → {section_name: node_type} map
Phase 3 (parse)          DAT bytes + map → parsed node trees
Phase 4 (describe)       node trees → IRScene (Intermediate Representation)
Phase 5A (build_blender) IRScene → Blender scene objects
```

File reading happens at the entry points (`BlenderPlugin.py` / `CommandLineInterface.py`), not inside the pipeline. The pipeline takes `bytes` and a `filename`.

### Intermediate Representation (IR)

The IR is a platform-agnostic dataclass hierarchy (`shared/IR/`) that decouples parsing from Blender. It stores decoded data in generic formats — no raw binary nodes, no Blender-specific baked values.

- `IRScene` → `IRModel` → `IRBone`, `IRMesh`, `IRMaterial`, `IRBoneAnimationSet`, `IRMaterialAnimationSet`
- `IRKeyframe` stores decoded frame/value/interpolation/handles — not compressed HSD bytes
- Blender-specific baking (scale correction, Euler decomposition) happens in Phase 5A only

### Export Pipeline

`DATBuilder` in `shared/IO/dat_builder.py` writes `.dat` binaries from an in-memory node tree. Round-trip functional (0 value mismatches on re-parse). The exporter stub is in `legacy/exporter/`.

### Entry Points

| File | Purpose |
|---|---|
| `__init__.py` | Thin wrapper — imports `register`/`unregister` from `BlenderPlugin.py` |
| `BlenderPlugin.py` | Blender operators (`ImportHSD`, `ExportHSD`), file reading, Logger creation |
| `__main__.py` | Thin CLI wrapper — imports `main()` from `CommandLineInterface.py` |
| `CommandLineInterface.py` | CLI argument parsing, file reading |

### Key Directories

```
importer/
  importer.py                    # Importer.run() — pipeline entry point
  phases/
    extract/extract.py           # Phase 1: container detection + header stripping
      helpers/fsys.py            # FSYS archive parser (header, metadata, LZSS decompression)
      helpers/lzss.py            # LZSS decompression algorithm
    route/route.py               # Phase 2: section name → node type mapping
    parse/
      parse.py                   # Phase 3: wrapper around DATParser
      helpers/dat_parser.py      # DATParser — recursive node tree parser
    describe/
      describe.py                # Phase 4: node trees → IRScene
      helpers/                   # bones, meshes, materials, animations, constraints, lights, material_animations, keyframe_decoder
    build_blender/
      build_blender.py           # Phase 5A: IRScene → Blender objects
      helpers/                   # skeleton, meshes, materials, animations, constraints, lights, material_animations
      errors/build_errors.py     # ModelBuildError

shared/
  IR/                            # Intermediate Representation dataclasses
  Nodes/                         # Node classes (parsing + writing only, no bpy)
  Constants/                     # HSD/GX format constants
  helpers/
    binary.py                    # read/write helpers with descriptive type names
    file_io.py                   # BinaryReader / BinaryWriter (stream-based)
    logger.py                    # Logger / StubLogger
    math_shim.py                 # Matrix/Vector/Euler (mathutils or pure-Python fallback)
    srgb.py                      # sRGB ↔ linear conversion
  IO/dat_builder.py              # DATBuilder (export)
  ClassLookup/                   # Node type name → class resolution
  BlenderVersion.py              # Version comparison utility

legacy/                          # Pre-refactor code (functional, used when "Use Legacy" is checked)
documentation/                   # Pipeline docs, API reference, compatibility tables, IR spec
```

### Dependency Rules

- `importer/` → `shared/` (one-directional)
- `shared/` never imports from `importer/`
- No phase imports from any other phase
- `shared/Nodes/` has zero bpy/mathutils imports — pure parsing/writing

---

## Node System

### Defining a Node

```python
class MyNode(Node):
    class_name = "My Node"
    fields = [
        ('name',  'string'),
        ('flags', 'uint'),
        ('child', 'MyNode'),        # pointer to same type
        ('data',  'float[4]'),      # bounded array
        ('items', 'float[count]'),  # dynamic-length array
        ('nodes', 'OtherNode[]'),   # null-terminated array
    ]
```

### Node Lifecycle

- **Parse:** `Node(address, None)` → `loadFromBinary(parser)` → fields set
- **Write:** `allocationSize()` / `writePrimitivePointers()` / `writePrivateData()` / `writeBinary(builder)`
- **Describe:** Phase 4 reads parsed fields → creates IR dataclasses
- **Build:** Phase 5A reads IR → creates Blender objects (no Node access needed)

### Caching

Nodes are cached by file offset (`nodes_cache_by_offset`). Nodes with `is_cachable = False` skip caching.

---

## Current Status

| Feature | Status |
|---|---|
| Binary parsing (all node types) | ✅ Complete |
| Static model import (geometry + textures) | ✅ Working |
| Skeleton/armature import | ✅ Working |
| Joint animation import | ✅ Working |
| Material animation import | ✅ Working (color/alpha + texture UV + NLA) |
| Light import | ✅ Working (SUN, POINT, SPOT) |
| Bone constraints (IK, copy loc/rot, track-to, limits) | ✅ Working |
| Bone instances (JOBJ_INSTANCE) | ✅ Working |
| Shape animation import | ❌ Stubs only (not implemented in legacy either) |
| Camera / Fog import | ❌ Stubs only |
| Exporter (binary round-trip) | ✅ Functional (0 value mismatches) |
| IR pipeline | ✅ Default path (legacy available via toggle) |
| FSYS archive import | ✅ Working (multi-model extraction + LZSS decompression) |
| Unit tests | ✅ 280 passing |

---

## Testing Strategy

- Framework: **pytest**
- **No game files** in the repository — ever
- Test data: Python helper functions that build valid node binaries in memory
- All tests use `io.BytesIO` — no temp files
- Tests cover: node parsing round-trip, IR type instantiation, helper functions, phase stubs
- Round-trip test tool: `python3 test_dat_write.py <input_file>`

---

## Coordinate System

GameCube → Blender requires a π/2 rotation around the X-axis. Applied once at the armature level. Do not apply to individual bones or meshes.

---

## Coding Conventions

- **Logger parameter:** Functions default to `StubLogger()`, never `None`.
- **Imports:** Phase files use try/except for Blender (relative) vs pytest (absolute) imports.
- **Binary reads:** Use `shared/helpers/binary.py` helpers (`read('uint', data, offset)`) instead of raw `struct.unpack`.
- **Errors:** Use `ValueError("descriptive message")` instead of custom exception classes. Only `ModelBuildError` (in build phase) carries structured data.
- **No bpy in shared/:** All Blender-specific code lives in `importer/phases/build_blender/`.
