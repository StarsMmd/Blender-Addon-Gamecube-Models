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
Phase 5 (build_blender)  IRScene → Blender scene objects
Phase 6 (post_process)   Reset poses, select animations, apply shiny filters
```

File reading happens at the entry points (`BlenderPlugin.py` / `CommandLineInterface.py`), not inside the pipeline. The pipeline takes `bytes` and a `filename`.

### Intermediate Representation (IR)

The IR is a platform-agnostic dataclass hierarchy (`shared/IR/`) that decouples parsing from Blender. It stores decoded data in generic formats — no raw binary nodes, no Blender-specific baked values.

- `IRScene` → `IRModel` → `IRBone`, `IRMesh`, `IRMaterial`, `IRBoneAnimationSet`, `IRMaterialAnimationSet`
- `IRKeyframe` stores decoded frame/value/interpolation/handles — not compressed HSD bytes
- Blender-specific baking (scale correction, Euler decomposition) happens in Phase 5 only
- **When modifying the IR**, update `documentation/ir_spec.md` to match

### Export Pipeline (pre-process + 4 phases)

The export pipeline reverses the import pipeline. All phases live under `exporter/phases/`. The entry point is `Exporter.run()` in `exporter/exporter.py`.

**Important:** The exporter must handle **arbitrary Blender models**, not just models that were originally imported from Colo/XD. Do not assume bone naming conventions (e.g. `Bone_N`), bone ordering, or any importer-specific metadata when reading Blender scenes. The describe_blender phase should work with any well-formed Blender armature and mesh setup. When converting between Blender and GX conventions (UV coordinates, coordinate systems, color spaces), always frame the conversion as Blender↔GX, never as "reversing what the importer did".

```
Pre-process (pre_process)    Validate output path + scene
Phase 1 (describe_blender)   Blender context → IRScene + shiny params
Phase 2 (compose)            IRScene → node trees + section names
Phase 3 (serialize)          node trees → DAT bytes (via DATBuilder)
Phase 4 (package)            DAT bytes → final output (.dat or .pkx)
```

`DATBuilder` in `exporter/phases/serialize/helpers/dat_builder.py` writes `.dat` binaries from an in-memory node tree. Round-trip functional (0 value mismatches on re-parse).

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
    extract/extract.py           # Phase 1: container detection + header stripping (uses PKXContainer)
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
      build_blender.py           # Phase 5: IRScene → Blender objects
      helpers/                   # skeleton, meshes, materials, animations, constraints, lights, material_animations
      errors/build_errors.py     # ModelBuildError
    post_process/
      post_process.py            # Phase 6: reset poses, select animations, apply shiny filters
      shiny_filter.py            # Shiny node group building, property setup, material insertion

shared/
  IR/                            # Intermediate Representation dataclasses
  Nodes/                         # Node classes (parsing + writing only, no bpy)
  Constants/                     # HSD/GX format constants
  helpers/
    binary.py                    # read/write helpers with descriptive type names
    file_io.py                   # BinaryReader / BinaryWriter (stream-based)
    logger.py                    # Logger / StubLogger
    math_shim.py                 # Matrix/Vector/Euler (mathutils or pure-Python fallback)
    pkx.py                       # PKXContainer — read/write PKX headers, DAT payloads, shiny params
    shiny_params.py              # ShinyParams dataclass (channel routing + brightness)
    srgb.py                      # sRGB ↔ linear conversion
  ClassLookup/                   # Node type name → class resolution
  BlenderVersion.py              # Version comparison utility

exporter/
  exporter.py                        # Exporter.run() — pipeline entry point
  phases/
    pre_process/
      pre_process.py                 # Pre-process: validate output path + scene
    describe_blender/
      describe_blender.py            # Phase 1 (export): Blender → IRScene
    compose/
      compose.py                     # Phase 2 (export): IRScene → node trees
      helpers/
        bones.py                     # IRBone list → Joint tree
    serialize/
      serialize.py                   # Phase 3 (export): node trees → DAT bytes
      helpers/
        dat_builder.py               # DATBuilder (binary serialization engine)
    package/
      package.py                     # Phase 4 (export): DAT bytes → final output

legacy/                          # Pre-refactor code (functional, used when "Use Legacy" is checked)
scripts/                         # Standalone Blender scripts (run from Scripting panel)
documentation/                   # Pipeline docs, API reference, compatibility tables, IR spec, scripts
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
| Exporter pipeline | ⚠️ Bones + meshes + materials + textures (CMPR) + bound box + placeholder animations working. Real animations/constraints TODO — see export pipeline plan |
| Exporter binary round-trip (DATBuilder) | ✅ Functional (0 value mismatches) |
| Exporter PKX packaging | ✅ Working (DAT injection, shiny write-back, trailer preserved) |
| IR pipeline | ✅ Default path (legacy available via toggle) |
| FSYS archive import | ✅ Working (multi-model extraction + LZSS decompression) |
| Shiny variant filter | ✅ Working (PKX color extraction, live-editable shader node group, per-parameter UI) |
| Unit tests | ✅ 475 passing (27 texture encoder, 5 DAT header/alignment) |
| Shader node auto-layout | ✅ Working (topological sort from output→inputs, left-to-right) |
| Scale inheritance (animation baking) | ⚠️ Partially resolved — hybrid approach, see below |

### Scale Inheritance (Animation Baking) — ⚠️ Ongoing Investigation

**Core problem:** Blender edit bones can't store scale (always normalized to unit length). HSD bones have real rest scales (e.g. 0.189). The delta formula `rest.inv() @ animated` computes ratios relative to each bone's own "unit 1", but these units differ between bones. Blender's scale inheritance compounds these mismatched ratios, producing cascading errors on deeply-nested bones with non-uniform scale.

**Current hybrid approach (per-bone):**
- **Uniform accumulated scale** (max/min ratio < 1.1): Uses the legacy `edit_scale_correction` sandwich formula + `inherit_scale='ALIGNED'`. Works correctly because uniform parent_scl creates no shear in `compile_srt_matrix`.
- **Non-uniform accumulated scale**: Uses direct SRT delta (quaternion rotation, per-axis scale ratio, matrix-free location) + `inherit_scale='NONE'`. Avoids shear from TRS decomposition but doesn't propagate parent scale.

**Phase 4 pre-processing:**
- `rest_local_matrix` on `IRBoneTrack` pre-bakes format-specific corrections (keeps Phase 5 generic)
- `_find_visible_scale_in_channels()` scans animation keyframes for bones hidden at rest (near-zero scale)
- `fix_near_zero_bone_matrices()` recomputes world matrices for near-zero bones and descendants using visible scales — **bug: descendant cascade may not be transitive (only direct children, not grandchildren), causing subame's left wing to remain collapsed**
- Path bone rotation applied symmetrically to both rest and animated matrices
- Edit bones use `normalized_world_matrix` for stable placement

**Known remaining issues:**
- **subame**: Left wing still missing (collapsed bone positions). Right wing bones overly long. The `fix_near_zero_bone_matrices` descendant detection likely needs to be transitive (grandchildren and beyond).
- **deoxys tentacles**: Greatly improved (no more 30,000x explosion) but still has some inaccuracy at the apex of extreme animations. The 3.7x scale ratio is mathematically correct per-bone but Blender's evaluation doesn't perfectly match HSD's scale composition for deeply-nested non-uniform chains.
- **Fundamental tension**: TRS decomposition can't represent shear. When non-uniform scale and rotation both change, the delta matrix has shear that gets absorbed as wrong scale/rotation. The direct SRT delta avoids this for scale and rotation but the location computation may still have edge cases.

**Key files:**
- `importer/phases/describe/helpers/animations.py` — Phase 4: `rest_local_matrix`, visible scale scanning
- `importer/phases/describe/helpers/bones.py` — Phase 4: `fix_near_zero_bone_matrices()`
- `importer/phases/build_blender/helpers/animations.py` — Phase 5: hybrid bake formula
- `importer/phases/build_blender/helpers/skeleton.py` — Phase 5: per-bone `inherit_scale`

**Next steps to investigate:**
1. Fix the descendant cascade in `fix_near_zero_bone_matrices()` — ensure grandchildren and deeper are also recomputed
2. The direct SRT location computation (`delta_pos.rotate(rest_quat_inv)`) may differ from the legacy matrix-based location for some models — compare outputs
3. For the "unit mismatch" problem on non-uniform bones: explore whether Blender's `inherit_scale='NONE'` mode can be combined with explicit scale compensation in the bake values
4. The per-frame hierarchy walk for animated parent scales was attempted but the conversion from world matrices to Blender pose-bone space couldn't be solved due to Blender's opaque ALIGNED evaluation. Reverse-engineering `armature.cc`'s `BKE_bone_parent_transform_calc_from_matrices` could enable this.

---

## Testing Strategy

- Framework: **pytest**
- **No game files** in the repository — ever
- Test data: Python helper functions that build valid node binaries in memory
- All tests use `io.BytesIO` — no temp files
- Tests cover: node parsing round-trip, IR type instantiation, helper functions, phase stubs
- Round-trip test runner: `python3 tests/round_trip/run_round_trips.py <model_file_or_dir>`

### Round-Trip Test Types

| Abbreviation | Name | Flow | Measures |
|---|---|---|---|
| **BNB** | Binary → Node → Binary | DAT bytes → parse → write → compare bytes | Binary-level fidelity (fuzzy word match) |
| **NBN** | Node → Binary → Node | Parse → write → reparse → compare fields | Node field preservation through serialization |
| **NIN** | Node → IR → Node | Parse → describe → compose → compare fields | IR round-trip fidelity |
| **IBI** | IR → Blender → IR | Build → describe_blender → compare IR fields | Blender round-trip fidelity |

NIN and IBI scores are computed against the **full** original data — not just the fields we've implemented export for — so percentages naturally increase as more export features are added.

See [Round-Trip Test Progress](documentation/round_trip_test_progress.md) for per-model scores across all test types. **When running round-trip tests and scores change**, update both the per-model percentages and the column header emojis (🔴 0-20% · 🟠 21-40% · 🟡 41-60% · 🔵 61-80% · ✅ 81-100%) in that document to reflect current averages.

### Test Models

Real `.pkx`/`.dat` model files are used for round-trip testing (not committed — gitignored). Source models are in `~/Documents/Projects/DAT plugin/models/`.

Available XD models: achamo, bohmander, cerebi, cokodora, frygon, gallop, haganeil, ken_a1, mage_0101, miniryu, rayquaza, runpappa, nukenin, usohachi.

Available Colosseum models: ghos, heracros, hinoarashi, hizuki_a1, koduck, showers.

---

## Naming Conventions for Exporter

The exporter requires certain Blender objects to follow naming conventions so it can distinguish model features during export. The importer must apply the same naming conventions when creating Blender objects, ensuring round-trip fidelity.

_(Conventions will be documented here as they are established for each feature.)_

---

## Coordinate System

GameCube → Blender requires a π/2 rotation around the X-axis. Applied once at the armature level. Do not apply to individual bones or meshes.

---

## Color Space Strategy

The IR stores all colors in **sRGB [0-1]** — normalized from u8 but not linearized. This keeps the IR platform-agnostic. Blender-specific linearization happens in **Phase 5 (build)** only:

- **Material colors** (diffuse, ambient, specular): Linearized via `srgb_to_linear()` when set on `ShaderNodeRGB` default values, because Blender treats those as scene-linear.
- **Material animation keyframes**: RGB channels linearized when inserting into fcurves. Alpha is not linearized.
- **Vertex colors**: Stored as `FLOAT_COLOR` (not `BYTE_COLOR`) so Blender does **not** auto-linearize them. The raw sRGB values pass through to the shader, matching the GameCube's gamma-space rendering.
- **Light colors**: Linearized when set on `bpy.data.lights[].color`.
- **Image pixels**: Raw u8 RGBA — Blender handles image color management internally.

Do not linearize colors in the IR, parsing, or describe phases.

---

## Shiny Filter Shader Nodes

The shiny filter is applied entirely in Phase 6 (post-processing), independent of the parsing/IR/build phases. Raw shiny parameters are extracted from PKX headers in Phase 1 and passed directly to Phase 6. There is no shiny data in the IR.

The filter inserts four named nodes into each material's node tree, split into two stages:

**Routing stage** (placed BEFORE vertex color multiply):
- **`shiny_route_shader`** — ShaderNodeGroup referencing `ShinyRoute_{model_name}` (channel swizzle + Gamma linearization)
- **`shiny_route_mix`** — MixRGB blending between normal and routed output

**Brightness stage** (placed AFTER vertex color multiply):
- **`shiny_bright_shader`** — ShaderNodeGroup referencing `ShinyBright_{model_name}` (per-channel brightness scaling)
- **`shiny_bright_mix`** — MixRGB blending between normal and brightness-adjusted output

This separation ensures channel routing only affects texture/material colors, not vertex colors. The vertex color multiply node is found by graph analysis (MixRGB MULTIPLY with ShaderNodeAttribute input), not by name.

The exporter **must skip these nodes** when reading back materials — they are display-only and not part of the original model data. Identify them by the node names above.

The shiny parameters are stored as registered `bpy.props` properties on the armature (`dat_shiny_route_r`, `dat_shiny_brightness_r`, etc.). When exporting to PKX, the exporter can read these properties from the armature to write updated shiny metadata back into the PKX header.

---

## Coding Conventions

- **Logger parameter:** Functions default to `StubLogger()`, never `None`. Always use `logger.info()`/`logger.debug()` instead of `print()` — logger output is written to log files on disk that persist after import and can be read directly for investigation. `print()` only goes to the Blender console which is transient.
- **Imports:** Phase files use try/except for Blender (relative) vs pytest (absolute) imports.
- **Binary reads/writes:** Use `shared/helpers/binary.py` helpers with descriptive type names (`read('uint', data, offset)`, `pack('float', value)`, `pack_many('uchar', r, g, b, a)`) instead of raw `struct.pack`/`struct.unpack` with format codes. For keyframe data that uses native byte order, use `read_native`/`pack_native`.
- **Errors:** Use `ValueError("descriptive message")` instead of custom exception classes. Only `ModelBuildError` (in build phase) carries structured data.
- **No bpy in shared/:** All Blender-specific code lives in `importer/phases/build_blender/`.
- **Do not modify `legacy/`:** The `legacy/` folder contains the pre-refactor importer and should not be changed unless explicitly asked to do so.
- **Fail loud over silent fallbacks:** When looking up Blender objects we created (nodes, bones, materials), raise `ValueError` with the actual names if the lookup fails — don't silently skip or fall back. Silent failures mask bugs and make debugging much harder.
- **Standalone scripts:** Any standalone Blender scripts (run from the Scripting panel) go in `scripts/` and must be documented in `documentation/scripts.md`.
- **Blender API tracking:** Whenever a `bpy` API call is added, moved, removed, or modified, update `documentation/blender_api_usage.md` to match.
- **Test count:** Whenever tests are added or removed, update the unit test count in the Current Status table above.

---

## Outstanding TODOs

- [ ] Code audit: identify opportunities to simplify and clean up code
- [x] Code audit: identify opportunities to reduce algorithmic complexity — see [complexity optimization plan](documentation/complexity_optimization_plan.md)
- [ ] Implement remaining complexity optimizations (items 1-3 in the plan above)
- [x] Shiny filter: split into separate routing and brightness shaders. The routing shader (channel swizzle) only applies to texture colors, not vertex colors. The brightness shader applies to the final result after vertex color multiplication.
- [x] Ambient lighting: approximated with per-material Emission node (`dat_ambient_emission`), read back on export. Scene-level `LOBJ_AMBIENT` lights still ignored.
- [ ] Bone inverse_bind_matrix: the HSD inverse bind matrix has a complex relationship to the bone hierarchy that depends on `_envelope_coord_system()` — it's NOT simply `world_matrix.inverted()`. Cannot be computed for arbitrary Blender models without fully reverse-engineering the HSD skeleton conventions. Only needed for true WEIGHTED/envelope skinning export (currently converted to SINGLE_BONE). Low priority until envelope export is implemented.
