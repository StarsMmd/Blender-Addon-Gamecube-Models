# DAT Plugin — Claude Context

## Project Overview

A Blender addon that imports and exports `.dat` 3D model files used in GameCube games (primarily Pokémon Colosseum and XD: Gale of Darkness). The format is based on the proprietary **SysDolphin** library, reverse-engineered by hobbyists.

**Target Blender version:** 4.5

**Supported file extensions:** `.dat`, `.fdat`, `.rdat`, `.pkx`, `.fsys`, `.wzx`, `.cam`

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
    extract/extract.py           # Phase 1: container detection + header stripping (uses PKXContainer, WZX extractor)
      helpers/fsys.py            # FSYS archive parser (header, metadata, LZSS decompression)
      helpers/lzss.py            # LZSS decompression algorithm
    route/route.py               # Phase 2: section name → node type mapping
    parse/
      parse.py                   # Phase 3: wrapper around DATParser
      helpers/dat_parser.py      # DATParser — recursive node tree parser
    describe/
      describe.py                # Phase 4: node trees → IRScene
      helpers/                   # bones, meshes, materials, animations, constraints, lights, cameras, material_animations, keyframe_decoder
    build_blender/
      build_blender.py           # Phase 5: IRScene → Blender objects
      helpers/                   # skeleton, meshes, materials, animations, constraints, lights, cameras, material_animations
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
    wzx.py                       # WZX effect container — extract DATs and GPT1 particles from WazaSequence files
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
| Light import | ✅ Working (AMBIENT, SUN, POINT, SPOT) |
| Bone constraints (IK, copy loc/rot, track-to, limits) | ✅ Working |
| Bone instances (JOBJ_INSTANCE) | ✅ Working |
| Shape animation import | ❌ Stubs only (not implemented in legacy either) |
| Particle import (GPT1) | ⚠️ Disabled — `build_particles` is a stub that only records `dat_particle_gen_count`/`dat_particle_tex_count` on the armature. Blocker: cannot find the generator→bone binding. Ruled out: `JOBJ_PTCL` flag (unset on all 15 particle models), `_particleJObjCallback` path, PKX body-map slots (just a bone lookup table), WZX move files (move effects only), common.rel unknown indexes 106/107/116/117/132-135, DOL data section around `PKXPokemonModels` (only WazaSequence animation ID tables there). Remaining leads: script bytecode in `data0`/`data7`, full `fightPokemon*` sweep, raw-read common.rel indexes 132–135. All the plumbing (parser, disassembler, IR, assembler, opcode specs, compose helper) stays in place |
| Particle export (GPT1) | ❌ Disabled — `compose_particles` is unit-tested for IR→bytes→IR round-trip but not wired into the export pipeline. Re-exported `.pkx` files drop the original GPT1 data. Blocked on the same generator→bone binding question as import |
| Camera import | ✅ Working (static + animated: position, target, FOV, roll, near/far) |
| Fog import | ❌ Not supported (no fog data found in tested models) |
| Exporter pipeline | ✅ Bones + meshes (RIGID/SINGLE_BONE/ENVELOPE, multi-material split) + materials + textures (all GX formats) + bound box + animations (Euler + quaternion) + material animations + lights + cameras + constraints working. Supports arbitrary Blender models (GLB/FBX) with armature object scale + coordinate rotation applied automatically. |
| Exporter binary round-trip (DATBuilder) | ✅ Functional (0 value mismatches) |
| Exporter PKX packaging | ✅ Working (from-scratch via PKX metadata OR DAT injection into existing, shiny write-back, trailer preserved) |
| In-game loading (re-exported) | ✅ Working — all three paths (BNB, NIN, IBI) produce correct geometry + textures in both Blender and in-game simultaneously |
| In-game loading (arbitrary models) | ⚠️ Loads without crashing but geometry garbled at aggressive optimization — see "Arbitrary Model Export" section below |
| IR pipeline | ✅ Default path (legacy available via toggle) |
| FSYS archive import | ✅ Working (multi-model extraction + LZSS decompression) |
| Shiny variant filter | ✅ Working (PKX color extraction, live-editable shader node group, per-parameter UI) |
| Unit tests | ✅ 874 passing (35 texture encoder (incl. 5 uniform-block yellow regression + 3 transparency/greatest-range quality upgrades), 14 DAT serialization/alignment/relocation/vertex-space, 26 PKX header (incl. 2 body-map slot 8-15 tests), 24 GPT1 particle, 22 GPT1 assembler, 10 GPT1 opcode specs, 8 compose_particles, 15 WZX extraction, 2 material animation scale, 18 camera describe, 22 camera animation, 12 camera compose, 4 coordinate conversion, 20 bezier sparsification, 16 light describe, 16 envelope display list splitting, 2 PObject iterative parsing, 3 envelope weight dedup, 4 motion type derivation, 5 idle name compaction, 5 PKX referenced action filter, 16 strict mirror mode, 3 compose material dedup, 3 mesh-bone SKEL exclusion, 21 compose pre-scale, 9 material-anim export, 5 bone-anim frame range, 5 compose TextureAnimation (incl. multi-frame eye-blink V-flip), 7 compose material-anim DObj alignment (incl. empty MA placeholders on non-animated mesh-bones and bone-with-no-DObjs None guard), 4 blend-mode detection (ALPHA_MASK/RGB_MASK via fac-socket origin), 3 compose pre-scale matrix aliasing, 3 mesh→bone parent round-trip, 7 compose quad-primitive DL encoding, 1 SINGLE_BONE inverse uses parent_bone, 11 compose envelope consistency (undeform ↔ stored envelope round-trip, minor-weight preservation) + 4 compose-importer skel-bone-search parity (Greninja GLB regression: both sides must match SKELETON\|SKELETON_ROOT), 12 unbaked-transform validation + 7 vertex-weight-count validation + 8 texture-size validation (rejects non-identity armature/mesh matrix_world, >4 bone influences per vertex, and textures larger than 512×512 before any decompose path runs), 2 build-mesh smooth-shading (importer marks polygons use_smooth=True when ir_mesh.normals is set, otherwise Blender 4.1+ ignores custom split normals — Greninja tongue/scarf flat-shading regression), 2 build-pixel-engine HASHED fallback (translucent materials with no explicit fragment_blending now use HASHED instead of BLEND, avoiding EEVEE depth-sort artefacts that look like back-faces showing through), 10 bone-anim slot-order (exporter enumerates actions in PKX slot order so DAT[i] matches `anim_entries[i].sub_anims[0].anim_index`; alphabetical fallback for armatures with no PKX metadata; `apply_pkx_metadata` now seeds every slot with the first bone-animating action so every `anim_index` resolves to 0 deterministically instead of relying on the empty-slot fallback — Greninja GLB regression: every slot's anim_index resolved to DAT[0]=basic_anim_0 because bpy.data.actions sorts alphabetically AND slots were uninitialised), 2 translucency-is-unsupported regression (materials with `is_translucent=True` still get JOBJ_OPA, never JOBJ_XLU; ROOT_OPA propagates for every mesh-owning descendant regardless of material claim. Reason: the XD runtime *does* run render pass 1 in battle (verified in disassembly: `_modelRenderModelSub` calls HSD_JObjDispAll with mask=0x6), but empirically every material we routed into XLU stayed invisible; flipping the Greninja scarf back to opaque restored it instantly. We treat material translucency as an unsupported feature and always ship opaque — see documentation/exporter_setup.md), 8 pre_process anim-timing validator (rejects exports where a PKX slot assigns a real action but all four `timing_1..4` are 0.0 — game's battle state machine divides-by-zero on idle-loop modulo and immediately advances through entry states, reliably crashing on send-out)) |
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

### Arbitrary Model Export — ⚠️ Experimental

**Status:** Models from external sources (GLB/FBX) can be exported to .dat/.pkx. A Greninja model (Sun/Moon GLB) loads in-game without crashing but geometry is garbled at aggressive optimization levels. Needs tuning.

**What works:**
- Multi-material meshes auto-split by material slot on export
- Quaternion rotation fcurves (from GLB) converted to Euler for HSD
- Armature loc/rot/scale baked into geometry by `bake_transforms()` in `prepare_for_export.py`; the exporter rejects any armature or child mesh with non-identity `matrix_world` so the bone (decompose) and vertex (matmul) paths stay in the same frame
- SUN light direction derived from object rotation when no TRACK_TO constraint
- PKX files can be created from scratch (no existing .pkx required)
- Motion_type derived from slot type (loop→2, active→1, empty→0)
- Standard 4-light battle setup (ambient + 3 directional SUN)

**Weight optimization pipeline (`prepare_for_export.py`):**
1. Limit vertex weights to `MAX_WEIGHTS_PER_VERTEX` per vertex (currently 3, game's hardware cap is 4)
2. Quantize weights to 10% steps (matching game model precision)

Weight limiting and quantisation are the prepare script's job — compose only renormalises against floating-point drift so the viewport preview of weights in Blender matches what ships to the .dat. `exporter/phases/pre_process/pre_process.py:_validate_vertex_weight_count` rejects any vertex with more than 4 non-zero weights (hardware envelope limit).

**Known limitations:**
- Game models have 15-40 PObjects and 65-430 KB DAT size. Arbitrary models with smooth weight painting produce many more unique weight combinations → more PObjects → larger files
- The compose phase's triangle partitioning creates more PObjects than `unique_combos / 10` due to boundary vertex duplication
- Game models are hand-crafted with separate mesh objects per body part, each referencing few bones. Arbitrary models with one large mesh + many bones are inherently harder to optimize

**Key files:**
- `scripts/prepare_for_export.py` — `bake_transforms()` (must run first), weight limiting, quantization, texture formats, lights, PKX metadata
- `exporter/phases/pre_process/pre_process.py` — `_validate_vertex_weight_count` rejects >4 influences per vertex
- `exporter/phases/describe_blender/describe_blender.py` — `_validate_baked_transforms` rejects unbaked armatures/meshes
- `exporter/phases/describe_blender/helpers/skeleton.py` — coord conversion only (no obj_transform; armature is identity)
- `exporter/phases/describe_blender/helpers/meshes.py` — multi-material split, vertex/normal coord conversion
- `exporter/phases/describe_blender/helpers/animations.py` — quaternion support, `loc_scale` for fcurve values
- `exporter/phases/compose/helpers/meshes.py` — envelope map uses weights as-is (only renormalises)

**Next steps to investigate:**
1. Current setting: 3 weights + 10% quantisation in the prepare script, no compose-phase quantisation. Validate in-game.
2. If quality is still off, try tuning `MAX_WEIGHTS_PER_VERTEX` (up to 4) or the quantisation step in the prepare script alone — compose trusts whatever the viewport shows.
3. Explore mesh splitting by body region to reduce per-mesh bone count (the key metric game models optimize for)
4. Compare envelope list structure between exported and original game models for subtle format differences

---

## Testing Strategy

- Framework: **pytest**
- **No game files** in the repository — ever
- Test data: Python helper functions that build valid node binaries in memory
- All tests use `io.BytesIO` — no temp files
- Tests cover: node parsing round-trip, IR type instantiation, helper functions, phase stubs
- Round-trip test runner: `python3.11 tests/round_trip/run_round_trips.py <model_file_or_dir>`
- **Use `python3.11`** for round-trip tests (has `bpy==4.5.7`). The default `python3` (3.10) has an old `bpy==3.4.0` that lacks required APIs like `action.slots`.

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

**Character / Pokémon models** (primary focus — run during regular score updates):

Available XD models: achamo, bohmander, cerebi, frygon, gallop, haganeil, ken_a1, mage_0101, miniryu, rayquaza, runpappa, nukenin, usohachi.

Available Colosseum models: ghos, hinoarashi, hizuki_a1, showers.

**Map / scene models** (stretch goal — only run as part of full status reports, not during regular updates):

Available XD models: D6_out_all, M1_out, M3_out.

---

## Naming Conventions for Exporter

The exporter requires certain Blender objects to follow naming conventions so it can distinguish model features during export. The importer must apply the same naming conventions when creating Blender objects, ensuring round-trip fidelity.

**Particles (GPT1):**
- `Particles_{model_name}` — Empty, default parent of generator meshes at the armature origin.
- `Particles_{model_name}_G{NN}` — Mesh per generator. Header fields (`gen_type`, `lifetime`, `max_particles`, `flags`, `params`) on object custom props (`flags` is reinterpreted from uint32 to signed int32 for Blender's ID storage). Carries a `dat_gpt1_attach_slot` Enum (`NONE` or `0`-`15`); setting it reparents the mesh to `armature` / `parent_bone = body_map_bones[slot]`. Default is `NONE` (armature origin) — the correct generator→slot mapping is not derivable from the model.
- `DATPlugin_Particles_{model_name}_G{NN}` — GeometryNodeTree. Contains per-instruction `NodeFrame`s plus a behavioral sub-graph.
- `gpt1_{MNEMONIC}_i{NNN}` — NodeFrame per bytecode instruction. `label` is JSON-encoded args; custom props `age_threshold`, `mnemonic`, `instr_index`.
- `DATPlugin_ParticleAtlas_{model_name}_G{NN}` — Texture atlas image. Custom props `gpt1_tex_widths`, `gpt1_tex_heights`, `gpt1_tex_formats`.
- `DATPlugin_ParticleMat_{model_name}_G{NN}` — Material assigned to the generator mesh, references the atlas.

**PKX body map (shared 16-slot key list):** `root, head, center, body_3, neck, head_top, limb_a, limb_b, secondary_8, secondary_9, secondary_10, secondary_11, attach_a, attach_b, attach_c, attach_d` — surfaced as `dat_pkx_body_<suffix>` on the armature. Slot indices 0-7 are well-known body parts (game accesses them via `GSmodelCenterNull`/head-tracking/etc.); slots 8-15 are extended attachment points used by particle generators. All three code locations that reference this key list (`importer/phases/post_process/post_process.py`, `exporter/phases/describe_blender/describe_blender.py`, `BlenderPlugin.py`) must stay in sync.

_(Conventions will be documented here as they are established for each feature.)_

---

## Game Rendering Pipeline Limits (XD)

Limits confirmed from the XD disassembly (`~/Documents/Projects/GoD-Tool/scripts/Disassembly-XD/text1/`) that the exporter and pre_process phase must respect. Violating any of these produces silent garbage (release build) or an assert trap (debug build) in-game — none of them show up in our round-trip tests because the importer tolerates them.

| Limit | Value | Enforcing function | Our invariant |
|---|---|---|---|
| Matrix-palette entries per PObject | ≤ **10** | `HSD_Index2PosNrmMtx` — `cmplwi r3, 0x9; bgt __assert` | `_build_envelope_map` caps each PObject at 10 unique weight combos; must not relax. |
| Palette index in `GX_VA_PNMTXIDX` byte | must be `slot * 3` ∈ {0, 3, …, 27} | same | Display list writer must emit `idx * 3`. Never > 27. |
| Palette index actually referenced by DL | must be `< palette_size_for_this_PObject` | `SetupEnvelopeModelMtx` iterates 0..N-1 | Every PObject's display list must only reference slots that its own envelope list populates — otherwise the vertex reads a STALE matrix from whatever ran before. |
| `sub_anim_count` per AnimMetadataEntry | ≤ **8** (`_MAX_SUB_ANIMS`) | PKX header writer | Clamped in `AnimMetadataEntry.from_bytes/to_bytes`. |
| `anim_index_ref` / `anim_index` | must land inside `animated_joints[]` | `GSmodelSetAnimIndex` null-checks the array entry but NOT the index bounds | Compose must not emit indices > len(animated_joints). |
| Envelope joint IBM | non-NULL when referenced by any envelope entry | `SetupEnvelopeModelMtx` — `__assert r0 != 0` | `_refine_bone_flags` clears IBM on non-deformation bones; compose must ensure every envelope-referenced joint is tagged SKEL (keeps its IBM). |
| Matrix-pool allocation failure | returns NULL | `HSD_ObjAlloc` returns 0 when pool full | Each SKEL joint's IBM takes one pool slot; too many SKEL joints can theoretically exhaust pool. Unknown what happens in release — likely hard crash. |
| `display_list_chunk_count` | `ushort` (≤ 65,535 chunks of 32 bytes each = ~2 MB) | PObject field size | Nowhere near — max observed is ~135 chunks. |
| Bone tree recursion depth | implicit stack budget (~384 bytes/frame) | `HSD_JObjDispAll` stack frame | Unbounded in code; model convention keeps ≤ ~15 levels. |

When the compose phase gains a new feature that could touch any of these, add or update a test in `tests/` that exercises the boundary (see `test_compose_envelope_split.py` for the 10-palette cap test pattern).

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

The shiny filter is applied entirely in Phase 6 (post-processing). Raw shiny parameters are extracted from PKX headers in Phase 1 and stored as `dat_pkx_shiny_route` (list of 4 ints) and `dat_pkx_shiny_brightness` (list of 3 floats) on the armature. There is no shiny data in the IR.

The filter inserts four named nodes into each material's node tree at the shader input:

- **`shiny_route_shader`** — ShaderNodeGroup referencing `ShinyRoute_{model_name}` (RGB channel swizzle via Separate→Combine, matching `GXSetTevSwapModeTable`)
- **`shiny_route_mix`** — MixRGB blending between normal and routed output
- **`shiny_bright_shader`** — ShaderNodeGroup referencing `ShinyBright_{model_name}` (per-channel RGB brightness scaling, multiply factor = brightness + 1.0 → [0.0, 2.0], matching TEV modulation with 2x scale)
- **`shiny_bright_mix`** — MixRGB blending between normal and brightness-adjusted output

Both stages are inserted at the Principled BSDF Base Color input (after all texture + vertex color processing), applied globally to ALL materials. This matches the game where `GSmodelEnableColorSwap` and `GSmodelEnableModulation` iterate all materials. Only RGB channels are routed — alpha route is always identity (3) and has no visual effect since the game forces brightness alpha to 0xFF.

The exporter **must skip these nodes** when reading back materials — they are display-only and not part of the original model data. Identify them by the node names above.

The shiny parameters are stored as custom properties on the armature (`dat_pkx_shiny_route`, `dat_pkx_shiny_brightness`). The `dat_pkx_shiny` toggle (registered `BoolProperty`) controls viewport preview via drivers on the MixRGB nodes. When toggled on, the node groups are rebuilt from the current custom property values, enabling live editing.

---

## Coding Conventions

- **Logger parameter:** Functions default to `StubLogger()`, never `None`. Always use `logger.info()`/`logger.debug()` instead of `print()` — logger output is written to log files on disk that persist after import and can be read directly for investigation. `print()` only goes to the Blender console which is transient.
- **Imports (READ THIS — the exporter keeps crashing on this):** Inside the addon package (`importer/`, `exporter/`, `shared/` when importing from sibling modules) **every** `from shared.…` / `from exporter.…` / `from importer.…` import **must** be wrapped in a try/except with the relative import first and the absolute import as the fallback. Blender loads this folder as a package, so bare absolute imports (`from shared.helpers.logger import …`) raise `ModuleNotFoundError` at runtime even though they work under pytest. Pytest only resolves the absolute form, so the relative form alone breaks the test suite. The required shape is:

  ```python
  try:
      from .....shared.helpers.logger import StubLogger   # relative — for Blender
  except (ImportError, SystemError):
      from shared.helpers.logger import StubLogger         # absolute — for pytest
  ```

  Rules:
  - **Applies everywhere**, including deferred imports inside functions and inside `except` blocks — not only module-level imports.
  - Count the dots: each `.` climbs one package level. A helper at `exporter/phases/describe_blender/helpers/animations.py` needs `.....shared.` (five dots) to reach `shared/`.
  - Never shortcut with a plain `from shared.…` at module scope — it's the single most common cause of exporter crashes when loaded as an addon.
  - When in doubt, mirror the import block of a neighbouring file in the same directory.
- **Binary reads/writes:** Use `shared/helpers/binary.py` helpers with descriptive type names (`read('uint', data, offset)`, `pack('float', value)`, `pack_many('uchar', r, g, b, a)`) instead of raw `struct.pack`/`struct.unpack` with format codes. For keyframe data that uses native byte order, use `read_native`/`pack_native`.
- **Errors:** Use `ValueError("descriptive message")` instead of custom exception classes. Only `ModelBuildError` (in build phase) carries structured data.
- **No bpy in shared/:** All Blender-specific code lives in `importer/phases/build_blender/`.
- **Do not modify `legacy/`:** The `legacy/` folder contains the pre-refactor importer and should not be changed unless explicitly asked to do so.
- **Fail loud over silent fallbacks:** When looking up Blender objects we created (nodes, bones, materials), raise `ValueError` with the actual names if the lookup fails — don't silently skip or fall back. Silent failures mask bugs and make debugging much harder.
- **Standalone scripts:** Any standalone Blender scripts (run from the Scripting panel) go in `scripts/` and must be documented in `documentation/scripts.md`. Scripts must be fully self-contained — no imports from the plugin codebase or other scripts. All code must be inlined in the single file. The only allowed imports are `bpy`, `math`, and Python standard library modules.
- **Blender API tracking:** Whenever a `bpy` API call is added, moved, removed, or modified, update `documentation/blender_api_usage.md` to match.
- **Test count:** Whenever tests are added or removed, update the unit test count in the Current Status table above.
- **Bug fix tests:** Whenever a bug is successfully fixed, add a unit test case that covers the fixed logic to prevent regressions.
- **No import metadata in the IR for round-trip fidelity:** Never add fields to the IR or custom properties to Blender objects solely to shuttle import-side metadata (channel ordering, quantization format, etc.) through to the compose/export phase. The IR must be derivable from the Blender scene or deterministic algorithms. If a round-trip mismatch comes from format details, investigate whether the original compiler's behavior can be reproduced algorithmically. If no deterministic pattern exists, accept the mismatch.

---

## Outstanding TODOs

- [ ] Code audit: identify opportunities to simplify and clean up code
- [x] Code audit: identify opportunities to reduce algorithmic complexity
- [x] Shiny filter: split into separate routing and brightness shaders. The routing shader (channel swizzle) only applies to texture colors, not vertex colors. The brightness shader applies to the final result after vertex color multiplication.
- [x] Ambient lighting: per-material stored in Emission node (`dat_ambient_emission`, strength=0 by default). Scene-level `LOBJ_AMBIENT` lights imported as no-op POINT light with `dat_light_type = "AMBIENT"` and `energy = 0`. Sorted first (LightSet[0]) on export.
- [x] Bone inverse_bind_matrix: computed as `srt_world.inverted()` — the inverse of the SRT-accumulated world matrix (no coordinate rotation). Only set on skinning target bones, cleared on others.
- [x] GPT1 particle export (compose + serialize phases) — Phase 1 of 19 core opcodes done; see exporter_setup.md Particles section
- [x] Blender particle visualization from IRParticleSystem — Simulation Nodes scene layout, one mesh + GeometryNodeTree per generator
- [ ] GPT1 Phase 2 opcodes: trails (`SET_TRAIL`), sub-emitters (`SPAWN_*`, `SPAWN_*_REF`), material-color animation (`MAT_COLOR`, `AMB_COLOR`), texture interpolation, callbacks. Currently raise `ValueError` on import
- [ ] GPT1 behavioral simulation: current node tree shows static particles; add Age-driven timeline switches for PrimCol/Scale/Rotation so the viewport matches in-game visuals
- [x] Envelope matrix index overflow: meshes with >10 unique weight combos are now split into multiple PObjects, each with ≤10 envelopes and its own display list. Greedy best-fit bin-packing minimizes the number of splits.
- [ ] MIRROR wrap mode round-trip: the importer now implements GX MIRROR via PINGPONG shader math nodes (Blender has no native mirror texture extension). The exporter could detect PINGPONG Math nodes in the texture UV chain to recover MIRROR wrap mode. Currently MIRROR round-trips as CLAMP.
- [ ] Arbitrary model optimization: current settings are 3 weights + 10% quantisation in the prepare script, compose no longer re-quantises. Validate in-game; if quality is still off, the knob to tune is `MAX_WEIGHTS_PER_VERTEX` (up to the 4-weight hardware cap) or the 10% quant step — both live in `scripts/prepare_for_export.py`. Pre-process enforces the 4-influence cap via `_validate_vertex_weight_count`. The bottleneck is still unique weight combinations causing PObject proliferation (each PObject duplicates boundary vertices).
- [ ] Importer Y-up bone storage: the importer stores Y-up bone data in edit bones with a π/2 X rotation on armature.matrix_basis. This is a shortcut — ideally edit bones should always be in Z-up (Blender native). The exporter handles both cases via `obj_rotation` normalization, but this design creates confusion. Low priority since changing it would affect all existing imported models.
- [ ] `bake_transforms` armature translation drop: `scripts/prepare_for_export.py:_apply_world_to_data` calls `arm.data.transform(world)` to bake the armature object's `matrix_world` into bone head/tail. In Blender 4.5 this applies rotation and scale correctly but silently drops the translation column, so a rig moved off-origin in object mode ends up with the mesh at the moved-to position and the bones still at their pre-move position. Workaround: position the rig at world origin before running the prepare script. Fix paths to evaluate: (a) replace the armature branch with `bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)` — canonical, also handles child meshes; (b) keep `Armature.transform()` and add a small edit-mode pass that adds `world.to_translation()` to every `EditBone.head/tail`.
- [ ] Confirm whether the PKX camera is actually needed. Both XD and Colosseum disassemblies show no consumer of a Pokémon model PKX's embedded camera — `scene_data` cameras are only read out of floor/waza/effect archives, never out of a Pokémon model. The importer currently names it `Debug_Camera` and the exporter still emits it for format fidelity. Once re-exported models load consistently in-game, try building a PKX with the camera section omitted (skip the camera root section in compose/serialize). If the model still loads and renders correctly, remove the camera path from the importer and exporter entirely — it's dead format overhead.
