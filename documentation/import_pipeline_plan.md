# Import Pipeline

## Overview

The import pipeline converts GameCube `.dat` binary files into Blender scene objects through 5 sequential phases. Each phase is a pure function with defined inputs and outputs. No shared mutable state crosses phase boundaries.

```
Phase 1 (extract)        raw file bytes + filename → list[(DAT bytes, metadata)]
Phase 2 (route)          DAT bytes → {section_name: node_type_name}
Phase 3 (parse)          DAT bytes + section_map → list[SectionInfo]
Phase 4 (describe)       sections → IRScene
Phase 5A (build_blender) IRScene → Blender scene objects
```

**Entry point:** `Importer.run(context, raw_bytes, filename, options, logger)` in `importer/importer.py`

Phase 5A only runs when `context is not None`. The CLI can run phases 1–4 without Blender installed, producing an IRScene for inspection or testing.

File reading happens at the entry points (`BlenderPlugin.py` / `CommandLineInterface.py`), not inside the pipeline. The pipeline receives `bytes` and a `filename`.

---

## Phase 1: Container Extraction

**Files:** `importer/phases/extract/extract.py`, `helpers/fsys.py`, `helpers/lzss.py`

### Function

```python
def extract_dat(raw_bytes: bytes, filename: str) -> list[tuple[bytes, ContainerMetadata]]
```

### Purpose

GameCube model data is often wrapped in container formats (PKX archives, FSYS archives). This phase detects the container format, strips headers, decompresses LZSS payloads, and exposes the raw DAT binaries.

### Container Detection

Routes by file extension or magic bytes:

| Extension / Magic | Behavior |
|-----------|----------|
| `.dat`, `.fdat`, `.rdat` | Pass-through unchanged |
| `.pkx` | Strip PKX header (see below) |
| `.fsys` or `FSYS` magic at offset 0 | Parse FSYS archive, extract model entries (see below) |

Returns a list of `(dat_bytes, ContainerMetadata)` tuples. A `.dat`/`.pkx` yields one entry. An FSYS archive yields one entry per model file inside.

### FSYS Archive Parsing

**Files:** `helpers/fsys.py`, `helpers/lzss.py`

FSYS is a custom archive format used by Pokémon Colosseum and XD — a bundle of multiple files, optionally LZSS-compressed. The parser extracts model-relevant files (dat, mdat, pkx) and skips non-model types (scripts, textures, sounds, etc.).

**FSYS header** (big-endian, 0x60 bytes):

| Offset | Size | Field |
|--------|------|-------|
| 0x00 | 4 | Magic `"FSYS"` |
| 0x0C | 4 | `entry_count` (uint32) |
| 0x40 | 4 | `file_metadata_list` pointer (uint32) |

**Pointer table** at `file_metadata_list`: array of `entry_count` uint32 offsets, each pointing to a file metadata entry.

**File metadata entry** (at each pointer offset):

| Offset | Size | Field |
|--------|------|-------|
| 0x02 | 1 | `file_type` (uint8) — determines file extension |
| 0x04 | 4 | `data_address` (uint32) — absolute offset to file data |
| 0x0C | 4 | `flags` (uint32) — bit 31 = LZSS compressed |
| 0x14 | 4 | `file_size` (uint32) |
| 0x1C | 4 | `full_filename_pointer` (uint32) — complete filename if debug flag set |
| 0x24 | 4 | `filename_pointer` (uint32) — short entry name |

**Model-relevant file type IDs:**

| ID | Extension | Handling |
|----|-----------|----------|
| 0x02 | mdat (→ dat) | Pass-through |
| 0x04 | dat | Pass-through |
| 0x1E | pkx | Strip PKX header after extraction |

**LZSS decompression** (ported from GoD-Tool's `LZSSCompressor.swift`): Sliding-window algorithm with 4096-byte ring buffer. 16-byte header: magic `"LZSS"` + uncompressed_size + compressed_size + unknown. Flags byte processed LSB-first: bit=1 → literal byte, bit=0 → 2-byte (position, length) back-reference.

**Entry filename resolution** (matches GoD-Tool logic):
1. If `full_filename_pointer` is non-zero → use it (includes extension)
2. Otherwise → short name from `filename_pointer` + file type extension (e.g., `.dat`, `.pkx`)
3. Fallback → `{archive_name}_entry_{index}.dat`

The pipeline sets `options["filepath"]` to each entry's filename before processing, so downstream phases (skeleton naming, logging) use the correct per-model name.

### PKX Header Parsing

PKX files contain a single DAT preceded by a game-specific header. The header format differs between Colosseum and XD.

**XD vs Colosseum detection:**
```python
val_0  = read('uint', raw, 0x00)
val_40 = read('uint', raw, 0x40)
is_xd  = (val_0 != val_40)
```

**Colosseum format:**
- Fixed header size: `0x40` bytes (64 bytes)
- DAT data starts immediately after

**XD format:**
- Base header size: `0xE60` bytes
- Optional GPT1 chunk: size read as `uint` from offset `0x08`
- If GPT1 is present: `header_size = 0xE60 + gpt1_size + padding`
- Padding aligns to 0x20-byte boundary: `padding = (0x20 - (gpt1_size % 0x20)) % 0x20`

DAT data is everything after the header: `raw_bytes[header_size:]`

---

## Phase 2: Section Routing

**File:** `importer/phases/route/route.py`

### Function

```python
def route_sections(dat_bytes: bytes, user_overrides: dict | None = None) -> dict[str, str]
```

### Purpose

DAT files contain named sections, each with a root node. This phase reads the section names from the DAT archive header and maps each to a Node class name, determining how Phase 3 will parse it.

### DAT Archive Header Structure

The first 32 bytes of a DAT file:

| Offset | Size | Field |
|--------|------|-------|
| 0x00 | 4 | `file_size` |
| 0x04 | 4 | `data_size` |
| 0x08 | 4 | `reloc_count` (relocation table entries) |
| 0x0C | 4 | `pub_count` (public/exported sections) |
| 0x10 | 4 | `ext_count` (external/imported sections) |
| 0x14 | 12 | padding |

### Section Name Extraction

Section info entries follow the relocation table:

```
section_info_offset = 32 + data_size + reloc_count * 4
```

Each section info entry is 8 bytes:
- Bytes 0–3: root node offset (within data block)
- Bytes 4–7: name string offset (relative to names block)

The names block starts after all section info entries:
```
names_block_offset = section_info_offset + (pub_count + ext_count) * 8
```

Section names are null-terminated ASCII strings read from the names block.

### Routing Rules

Applied in order; first match wins:

| Mode | Pattern | Node Type |
|------|---------|-----------|
| exact | `scene_data` | `SceneData` |
| exact | `bound_box` | `BoundBox` |
| exact | `scene_camera` | `CameraSet` |
| contains | `shapeanim_joint` | `ShapeAnimationJoint` |
| contains | `matanim_joint` | `MaterialAnimationJoint` |
| contains | `_joint` | `Joint` |
| fallback | — | `Dummy` |

- `exact` mode: case-insensitive full match
- `contains` mode: case-insensitive substring match
- User overrides (passed as `user_overrides` dict) take precedence over all default rules

---

## Phase 3: Node Tree Parsing

**Files:** `importer/phases/parse/parse.py`, `helpers/dat_parser.py`

### Function

```python
def parse_sections(dat_bytes: bytes, section_map: dict, options: dict, logger) -> list[SectionInfo]
```

### Purpose

Reads the DAT binary into a hierarchy of Node objects — Python class instances that mirror the C structs in the SysDolphin library. Each section's root node is resolved to the correct Node subclass via the `section_map` from Phase 2.

### DATParser

`DATParser` inherits from `BinaryReader` and adds:

- **Relocation table**: Built from the DAT header. Maps file offsets that contain valid pointers. A uint32 value of `0` at a pointer field is only treated as null if that offset is NOT in the relocation table (offset 0 could be a valid pointer target).
- **Node cache** (`nodes_cache_by_offset`): Keyed by absolute file offset. Prevents re-parsing shared nodes (multiple pointers to the same struct) and breaks infinite recursion on circular references. Nodes with `is_cachable = False` bypass caching.
- **Type resolution**: `get_class_from_name(type_name)` in `shared/ClassLookup/` resolves a string class name to a Python Node subclass.

### Field Type Dispatch

The `read(field_type, address, ...)` method dispatches based on type syntax:

| Type Syntax | Example | Behavior |
|-------------|---------|----------|
| Primitive | `uint`, `float`, `ushort`, `uchar` | Read bytes at offset, unpack via struct |
| Node class | `Joint`, `Material` | Instantiate node, call `loadFromBinary(parser)`, cache by offset |
| Pointer | `*Joint` (or just `Joint` as a field type) | Read uint32 pointer value, if non-null (or in reloc table) follow it and parse the target |
| Null-terminated array | `AnimationJoint[]` | Read elements sequentially until a block of zero bytes is encountered |
| Bounded array | `float[4]`, `float[count]` | Read exactly N elements (N from literal or another field's value) |

### Node Lifecycle

1. `node = NodeClass(address, None)` — instantiate with file offset
2. `nodes_cache_by_offset[address] = node` — cache before parsing (breaks cycles)
3. `node.loadFromBinary(parser)` — read each field in `fields` list by calling `parser.read(field_type, ...)`
4. Node instance now has all fields populated as Python attributes

### SectionInfo Output

Each successfully parsed section becomes a `SectionInfo` with:
- `section_name`: ASCII name from the DAT header
- `root_node`: Parsed Node subclass instance (or `None` / `Dummy` for unrecognized types)

Sections with `Dummy` root nodes are filtered out. Only successfully parsed sections are returned.

---

## Phase 4: Scene Description

**File:** `importer/phases/describe/describe.py`

### Function

```python
def describe_scene(sections: list[SectionInfo], options: dict, logger) -> IRScene
```

### Purpose

Converts the parsed Node trees into the Intermediate Representation — a hierarchy of platform-agnostic dataclasses (`shared/IR/`). This is where Node-specific field names, flag patterns, and linked-list structures are normalized into clean, flat data structures.

### Section Classification

Iterates all parsed sections and classifies each by its root node type:

| Root Node Type | Action |
|---------------|--------|
| `Joint` | Set as disjoint root joint |
| `AnimationJoint` | Append to disjoint animation list |
| `MaterialAnimationJoint` | Append to disjoint material animation list |
| `SceneData` | Extract `.models` (list of ModelSet) and `.lights` (list of LightSet) |
| `LightSet` | Extract `.light` and append to light nodes |
| `Light` | Append directly to light nodes |

**Disjoint section assembly:** Some DAT files store the Joint tree, AnimationJoints, and MaterialAnimationJoints as separate top-level sections rather than bundled inside a SceneData container. When this happens, the describe phase assembles them into a synthetic ModelSet object — matching the same structure that SceneData would provide.

### Per-Model Description Pipeline

For each ModelSet, calls helpers in strict sequence:

---

### bones.py — Joint Tree → IRBone List

```python
def describe_bones(root_joint, options) -> (list[IRBone], dict[int, int])
```

Walks the Joint tree recursively (child-first, then sibling) and produces a flat, indexed list of `IRBone` dataclasses. The second return value is `joint_to_bone_index`: a dict mapping `joint.address` → index in the bones list, used by all other helpers to resolve Node pointers to bone indices.

For each Joint:

**1. Scale accumulation** (aligned scale inheritance):
```python
accumulated_scale[i] = joint.scale[i] * parent_accumulated_scale[i]
```
Parent scales are tracked through the hierarchy for animation baking later.

**2. Local SRT matrix:**
```python
local_matrix = compile_srt_matrix(scale, rotation, position, parent_scale)
```
Builds a 4×4 matrix from scale, Euler XYZ rotation, and translation. When `parent_scale` is provided, applies aligned scale inheritance correction: the matrix accounts for the parent's scale so that children scale correctly in Blender's `ALIGNED` mode.

**3. World matrix:**
```python
world_matrix = parent_world @ local_matrix  # (or just local for root)
```

**4. Normalized matrices** (for rest-pose binding):
```python
normalized_world = world_matrix.normalized()   # strips scale
normalized_local = parent_edit_matrix.inverted() @ normalized_world
```
Blender edit bones use normalized (scale-free) matrices. The normalization removes scale from the world matrix, matching what Blender stores internally.

**5. Scale correction matrix:**
```python
scale_correction = parent_scale_correction @ local.normalized().inverted() @ local
```
Encodes the scale that was stripped during normalization. This matrix is critical for animation baking — it allows the build phase to reconstruct the original SRT transform from Blender's normalized bone space.

**6. IK shrink:** Bones flagged as `JOBJ_EFFECTOR` or `JOBJ_SPLINE` (when `ik_hack` option is set) get a tiny tail vector (`1e-3 / bone_scale`) so they're nearly invisible in the viewport but still functional as IK targets.

---

### meshes.py — PObject Chains → IRMesh List

```python
def describe_meshes(root_joint, bones, joint_to_bone_index, image_cache, logger) -> list[IRMesh]
```

Walks the Joint tree, finds Mesh (DObject) nodes via `joint.property`, and processes each PObject in the linked list.

For each PObject:

**1. Face validation:** Creates a copy of `pobj.face_lists` and removes degenerate faces (faces with repeated vertex indices). This validation is critical — the validated face lists must be used consistently for all subsequent attribute extraction.

**2. Vertex extraction:** Position data from `pobj.sources[pos_idx]` where `pos_idx` is the index of the `GX_VA_POS` vertex attribute.

**3. UV layers:** Per-loop UV coordinates extracted from texture vertex attributes (`GX_VA_TEX0` through `GX_VA_TEX7`). V coordinate is flipped (`1.0 - v`) to convert from GameCube's top-left origin to Blender's bottom-left origin.

**4. Color layers:** CLR0 and CLR1 as per-loop RGBA tuples. If no color attribute is present, a default white color layer and full-alpha layer are added (required by many material setups).

**5. Normals:** Per-loop normals extracted and normalized to unit length. NBT (normal-binormal-tangent) attributes are reduced to normal-only (first 3 components).

**6. Bone weight classification** by PObject type:

| PObject Flags | Skin Type | Behavior |
|--------------|-----------|----------|
| `POBJ_SKIN` | RIGID | Single parent bone, weight 1.0 |
| `POBJ_SHAPEANIM` | RIGID | Treated as rigid (shape key extraction not yet implemented) |
| `POBJ_ENVELOPE` | WEIGHTED | Envelope weight arrays decoded from face_lists matrix indices |
| Default | SINGLE_BONE | Single parent bone, weight 1.0 |

**Envelope deformation (WEIGHTED):** The most complex path. Each face vertex has a matrix index (`GX_VA_PNMTXIDX`) that indexes into the PObject's envelope array. Each envelope entry maps to a list of (bone, weight) pairs via inverse bind matrices. Vertex positions are deformed by the weighted sum of bone transforms. The deformed positions replace the original mesh vertices.

**Critical invariant:** Envelope weight extraction uses the **validated** face_lists (post-degenerate-face removal), not the original `pobj.face_lists`. A past bug where the original face lists were used caused vertex-to-bone weight misalignment — mesh indices shifted after validation but weights still read from unvalidated indices.

**7. Material:** Each DObject (Mesh node) has one MaterialObject. All PObjects within a DObject share the same material. `describe_material()` is called once per DObject.

---

### materials.py — MaterialObject → IRMaterial

```python
def describe_material(mobj, image_cache) -> IRMaterial
```

Extracts material parameters from a MaterialObject node.

**1. Render mode decomposition:**

The `render_mode` uint32 is decomposed into discrete IR fields:

| Bits | IR Field | Values |
|------|----------|--------|
| 0–1 | `color_source` | MATERIAL, VERTEX, BOTH |
| 2 | `lighting` | LIT / UNLIT |
| 3 | `enable_specular` | bool |
| 4–11 | (per-texture enable) | Checked per texture in chain |
| 13–14 | `alpha_source` | MATERIAL, VERTEX, BOTH |
| 30 | `is_translucent` | bool |

**2. Material colors:** Read directly from `material.diffuse.asRGBAList()`, `ambient.asRGBAList()`, `specular.asRGBAList()`. These values are already linearized during `Material.loadFromBinary()` which calls `transform()` → `linearize()`. No additional sRGB conversion is applied.

**3. Texture chain:** Walk the texture linked list (`mobj.texture → .next → .next ...`). For each texture at position N, check if enabled: `render_mode & (1 << (N + 4))`. Enabled textures get full extraction:

- **Image decoding:** `texture.image.decodeFromRawData(palette)` decodes the GX-format pixel data (stored as `raw_image_data` during Phase 3 parsing) into RGBA u8 bytes. The decoded data is cropped to actual dimensions (GX textures are tile-padded) and vertically flipped (GX is top-to-bottom, Blender is bottom-to-top).
- **Image caching:** By `(image.data_address, palette.address)` tuple. Multiple textures sharing the same image data get the same `IRImage` instance.
- **Texture parameters:** coord type (UV or REFLECTION), UV source index, wrap modes (REPEAT/CLAMP/MIRROR), repeat counts, interpolation (from LOD settings), color/alpha blend modes, lightmap channel, bump flag.
- **TEV combiner:** If present, extracts color and alpha stages with 4 inputs each (A, B, C, D), operation (ADD/SUBTRACT), bias, scale, and clamp settings. Combiner inputs can reference texture color/alpha, constant registers, or special values (ZERO, ONE, HALF).

**4. Pixel engine / fragment blending:** Maps `pe.type` + blend factors to `OutputBlendEffect`:

| PE Type | Source/Dest Factors | Effect |
|---------|-------------------|--------|
| `GX_BM_NONE` | — | OPAQUE |
| `GX_BM_BLEND` | SRC_ALPHA / INV_SRC_ALPHA | ALPHA_BLEND |
| `GX_BM_BLEND` | ONE / ONE | ADDITIVE |
| `GX_BM_BLEND` | DST_COLOR / ZERO | MULTIPLY |
| `GX_BM_LOGIC` | various ops | BLACK, WHITE, INVERT, INVISIBLE, OPAQUE |
| `GX_BM_SUBTRACT` | — | CUSTOM |
| (other combinations) | — | CUSTOM (best-effort in build phase) |

---

### animations.py — AnimationJoint Tree → IRBoneAnimationSet List

```python
def describe_bone_animations(model_set, joint_to_bone_index, bones, options, logger) -> list[IRBoneAnimationSet]
```

Walks each AnimationJoint tree in parallel with the Joint tree. The two trees have identical structure — each AnimationJoint corresponds to the Joint at the same position in the hierarchy.

For each AnimationJoint that has an Animation object (and `AOBJ_NO_ANIM` flag is not set):

**Channel decoding:** Walk the Frame linked list (`animation.frame → .next → ...`). Each Frame has a `type` field identifying the channel:

| Type | Channel |
|------|---------|
| `HSD_A_J_ROTX/Y/Z` | Rotation X/Y/Z |
| `HSD_A_J_TRAX/Y/Z` | Translation X/Y/Z |
| `HSD_A_J_SCAX/Y/Z` | Scale X/Y/Z |
| `HSD_A_J_PATH` | Path animation parameter |

**SRT channels** are decoded by `keyframe_decoder.decode_fobjdesc(fobj)` into `list[IRKeyframe]`.

**PATH channels** are handled differently: the parameter keyframes are decoded normally, but the spline control points are extracted from the Joint's property (a Spline node) as a list of 3D points.

**IRBoneTrack assembly:**
```python
IRBoneTrack(
    bone_name, bone_index,
    rotation=[X_keyframes, Y_keyframes, Z_keyframes],
    location=[X_keyframes, Y_keyframes, Z_keyframes],
    scale=[X_keyframes, Y_keyframes, Z_keyframes],
    rest_rotation, rest_position, rest_scale,  # from Joint SRT
    end_frame=animation.end_frame,  # declared duration, NOT last keyframe position
    path_keyframes, spline_points,  # for PATH channel (mutually exclusive with SRT)
)
```

The `end_frame` field is critical: it comes from the Animation object's declared duration, not from the position of the last keyframe. A bone might have keyframes at frames 0 and 10 but the animation runs for 59 frames — the build phase must bake all 59 frames.

---

### keyframe_decoder.py — Compressed Keyframe Stream → IRKeyframe List

```python
def decode_fobjdesc(fobj, bias=0, scale=1) -> list[IRKeyframe]
```

Decodes HSD's opcode-packed binary keyframe format. The raw data is a byte stream where each segment begins with an opcode byte:

| Opcode | Interpolation | Data |
|--------|--------------|------|
| `CON` | CONSTANT | value only |
| `LIN` | LINEAR | value only |
| `SPL0` | BEZIER | value + left slope |
| `SPL` | BEZIER | value + right slope |
| `KEY` | LINEAR | value (standalone key) |
| `SLP` | — | slope only (modifies previous key) |

**Value encoding** varies by `frac_value` / `frac_slope` fields on the Frame node:

| Encoding | Size | Range |
|----------|------|-------|
| `HSD_A_FRAC_FLOAT` | 4 bytes | Full float32 |
| `HSD_A_FRAC_S16` | 2 bytes | Signed 16-bit, scaled |
| `HSD_A_FRAC_U16` | 2 bytes | Unsigned 16-bit, scaled |
| `HSD_A_FRAC_S8` | 1 byte | Signed 8-bit, scaled |
| `HSD_A_FRAC_U8` | 1 byte | Unsigned 8-bit, scaled |

**Wait duration** (frame advance per segment) is encoded in the opcode byte's lower bits, with optional extension bytes.

**Bezier handle computation** from slope values:
```
handle_left  = (frame - duration/3, value - slope * duration/3)
handle_right = (frame + duration/3, value + slope * duration/3)
```

Values have bias and scale applied: `final_value = raw_value * scale + bias`

---

### material_animations.py — MaterialAnimationJoint → IRMaterialAnimationSet

```python
def describe_material_animations(model_set, joint_to_bone_index, bones, options, logger) -> list[IRMaterialAnimationSet]
```

Walks MaterialAnimationJoint trees parallel to the Joint tree. Extracts:

- **Color/alpha tracks:** Decoded keyframes for diffuse R, G, B, and alpha channels. sRGB→linear conversion is baked into keyframe values during description (the IR stores linear values).
- **Texture UV tracks:** Per-texture-index tracks for translation U/V, scale U/V, and rotation X/Y/Z.

---

### constraints.py — Joint References → IR Constraint Types

```python
def describe_constraints(root_joint, bones, joint_to_bone_index) -> tuple[6 lists]
```

Walks Joint Reference chains (linked list via `joint.reference → .next`). Each Reference has type flags and a sub_type that determine the constraint kind:

| Reference Type | Sub-type | IR Constraint |
|---------------|----------|---------------|
| `REFTYPE_JOBJ` | 1 | `IRCopyLocationConstraint` (weighted 1/count for multi-source) |
| `REFTYPE_JOBJ` | 2 | `IRTrackToConstraint` (TRACK_X, UP_Y) |
| `REFTYPE_JOBJ` | 4 | `IRCopyRotationConstraint` (LOCAL if joint flag 0x8) |
| `REFTYPE_LIMIT` | 1–12 | `IRLimitConstraint` (per-axis min/max) |
| `JOBJ_EFFECTOR` | — | `IRIKConstraint` (chain 2 or 3, with pole target + bone repositioning) |

**IK constraints** are detected by `JOBJ_EFFECTOR` joint type. Chain length is 2 (JOINT1 parent) or 3 (JOINT2 parent). Target and pole bones are resolved from Reference objects. Bone repositioning data (bone_length for IK chain members) comes from BoneReference nodes.

---

### lights.py — Light Nodes → IRLight

```python
def describe_light(light_node, light_index) -> IRLight | None
```

Maps HSD light types to IR:
- `LOBJ_INFINITE` → `LightType.SUN`
- `LOBJ_POINT` → `LightType.POINT`
- `LOBJ_SPOT` → `LightType.SPOT`
- `LOBJ_AMBIENT` → returns `None` (no Blender equivalent)

Extracts color (normalized to 0–1 float), position, and target position from the light node's sub-objects.

---

## Phase 5A: Blender Build

**File:** `importer/phases/build_blender/build_blender.py`

### Function

```python
def build_blender_scene(ir_scene: IRScene, context, options: dict, logger) -> None
```

Only runs when `context is not None` (skipped in CLI mode without bpy). Mutates the Blender scene via bpy API calls.

### Build Order (sequential, order matters)

For each IRModel:
1. **Skeleton** — must be first (meshes and animations reference the armature)
2. **Meshes** — creates geometry, materials, bone weights; returns `material_lookup` dict
3. **Bone animations** — creates Actions with fcurves (requires armature)
4. **Material animations** — creates material Actions with NLA (requires `material_lookup`)
5. **Constraints** — adds IK, copy, track-to, limit constraints to pose bones

Then for all lights: create light objects.

---

### skeleton.py — IRBone List → Blender Armature

```python
def build_skeleton(ir_model, context, options, logger) -> armature
```

1. Create armature data and object
2. Apply **coordinate system rotation**: `Matrix.Rotation(π/2, 4, X)` on the armature's `matrix_basis`. This single rotation converts the entire model from GameCube Y-up to Blender Z-up. All child bones and meshes inherit it — no per-bone rotation needed.
3. Enter EDIT mode and create edit bones:
   - `bone.matrix = Matrix(world_matrix)` — rest pose from IR
   - `bone.inherit_scale = 'ALIGNED'` — matches HSD's scale inheritance behavior
   - `bone.parent` set by `parent_index`
   - IK hack: effector/spline bones get a tiny tail (1e-3 / scale_y)
4. Switch to POSE mode, set `rotation_mode = 'XYZ'` on all pose bones

---

### meshes.py — IRMesh List → Blender Mesh Objects

```python
def build_meshes(ir_model, armature, context, options, logger) -> material_lookup
```

For each IRMesh:
1. Create mesh data via `from_pydata(vertices, [], faces)`
2. Apply UV layers, vertex color layers, and custom normals
3. Create material via `build_material()` and append to mesh
4. Apply bone weights based on skin type:
   - **RIGID / SINGLE_BONE:** Create vertex group for parent bone, add all vertices with weight 1.0
   - **WEIGHTED:** Overwrite vertex positions with deformed positions from IR, create per-vertex bone/weight assignments from `IRBoneWeights.assignments`
5. Add ARMATURE modifier pointing to the armature
6. Copy meshes for JOBJ_INSTANCE bones (shallow copy with new matrix_local)

Returns `material_lookup` dict (`{mesh_name: bpy.types.Material}`) for material animation targeting.

---

### materials.py — IRMaterial → Blender Shader Node Tree

```python
def build_material(ir_material, image_cache) -> bpy.types.Material
```

Constructs a complete shader node tree:

**1. Base color/alpha:** Determined by `color_source` and `alpha_source`:
- MATERIAL: ShaderNodeRGB with diffuse color / ShaderNodeValue with alpha
- VERTEX: ShaderNodeAttribute ('color_0') / ShaderNodeAttribute ('alpha_0')
- BOTH: Both nodes combined via MixRGB ADD or Math MULTIPLY

**2. Texture chain:** For each IRTextureLayer:
- UV source: ShaderNodeUVMap (for UV coords) or ShaderNodeTexCoord output 6 (for reflection)
- ShaderNodeMapping with rotation, scale, translation; V-coordinate flipped for Blender's bottom-left origin
- Repeat scaling via ShaderNodeVectorMath MULTIPLY (if repeat_s or repeat_t > 1)
- ShaderNodeTexImage with wrap mode (REPEAT/EXTEND) and interpolation
- TEV combiner (if present): implements `lerp(A, B, C) ± D` formula using MixRGB/Math nodes with bias, scale, and clamp
- Layer blend: MIX, MULTIPLY, ADD, SUBTRACT, ALPHA_MASK, RGB_MASK, REPLACE

**3. Post-texture vertex color multiply:** For LIT materials with VERTEX or BOTH color source, multiplies the textured result by vertex color.

**4. Pixel engine effects:** Maps `OutputBlendEffect` to Blender shader configuration:

| Effect | Shader Setup |
|--------|-------------|
| OPAQUE | Default (no alpha) |
| ALPHA_BLEND | `blend_method = 'HASHED'`, alpha to Principled BSDF |
| ADDITIVE | Emission shader + Transparent add |
| MULTIPLY | Transparent BSDF with color |
| INVISIBLE | Alpha = 0 |
| BLACK/WHITE | Override color to solid |
| INVERT | ShaderNodeInvert |

**5. Output shader:** Principled BSDF for lit materials. Unlit materials use Emission + AddShader to bypass shading.

**Image creation:** Uses numpy for fast pixel conversion:
```python
bpy_image.pixels = np.frombuffer(ir_image.pixels, dtype=np.uint8).astype(np.float32) / 255.0
```

---

### animations.py — IRBoneAnimationSet → Blender Actions

```python
def build_bone_animations(ir_model, armature, options, logger) -> None
```

For each IRBoneAnimationSet, creates a Blender Action with fcurves.

**Path animation:** For bones with path keyframes, spline positions are directly baked into location keyframes. The path parameter curve controls interpolation along the spline. No SRT matrix computation is needed.

**SRT animation — two-pass baking:**

**Pass 1: Insert decoded keyframes into temporary fcurves**
- Create temp fcurves with data paths like `pose.bones["name"].r` (rotation), `.l` (location), `.s` (scale)
- Insert IRKeyframe values with interpolation type and bezier handles
- Fill missing channels with rest-pose constants (from `rest_rotation`, `rest_position`, `rest_scale`)

**Pass 2: Frame-by-frame sampling with scale correction**
- For each frame from 0 to `end_frame`:
  1. Evaluate all 9 temp fcurves at the current frame
  2. Build SRT matrix: `mtx = compile_srt_matrix(scale, rotation, location)`
  3. Apply scale correction to convert from HSD world space to Blender bone-local space:
     ```
     if has_parent:
         Bmtx = local_edit_matrix⁻¹ @ parent_edit_scale_correction @ mtx @ edit_scale_correction⁻¹
     else:
         Bmtx = local_edit_matrix⁻¹ @ mtx @ edit_scale_correction⁻¹
     ```
  4. Decompose `Bmtx` → (translation, quaternion, scale)
  5. Convert quaternion to Euler XYZ
  6. Clamp scale to ±100 (safety for near-singular bones)
  7. Insert final keyframe values into permanent fcurves (`rotation_euler`, `location`, `scale`)
- Remove all temporary fcurves

**Static pose detection:** After baking, if all fcurve values are identical across all frames, the action is renamed from "Anim" to "Pose".

**Action slots:** For Blender 4.5+, creates action slots and assigns them to the armature's animation data.

---

### material_animations.py — IRMaterialAnimationSet → Material Actions + NLA

```python
def build_material_animations(ir_model, material_lookup, options, logger) -> None
```

For each IRMaterialAnimationSet:
1. Create a material Action targeting shader node inputs
2. Apply color/alpha keyframes to `DiffuseColor` and `AlphaValue` node default values
3. Apply texture UV keyframes to mapping node translation/scale/rotation inputs
4. Create NLA track (muted by default) with strip referencing the action

---

### constraints.py — IR Constraints → Blender Bone Constraints

```python
def build_constraints(ir_model, armature, logger) -> None
```

Applies all constraint types from IR data:

- **IK:** `chain_count`, target/pole bones, `pole_angle`. Bone repositioning computes new head/tail positions from parent bone direction × `bone_length`.
- **Copy Location:** Weighted `influence = 1/count` for multi-source averaging.
- **Track To:** `track_axis = 'TRACK_X'`, `up_axis = 'UP_Y'`.
- **Copy Rotation:** `LOCAL` owner/target space if joint flag 0x8 is set.
- **Limits:** Per-axis min/max values, `LOCAL_WITH_PARENT` owner space.

---

### lights.py — IRLight → Blender Light Objects

```python
def build_lights(ir_lights, logger) -> None
```

For each IRLight:
1. Create light data (SUN/POINT/SPOT) with color
2. Position with dual rotation: `Translation(pos) @ Rotation(-π/2, X)` then `@= Rotation(π/2, X)`. The pre-rotation and post-rotation cancel for the orientation but correctly transform the position from GameCube Y-up to Blender Z-up coordinates.
3. SPOT lights with a target position get a target empty + TRACK_TO constraint (`TRACK_NEGATIVE_Z`, `UP_Y`).

---

## Feature Status

| Feature | Describe | Build | Notes |
|---------|----------|-------|-------|
| Bones (Joint tree → IRBone) | ✅ | ✅ | Scale correction pre-computed |
| Meshes (PObject → IRMesh) | ✅ | ✅ | Envelope deformation in describe |
| Materials (→ IRMaterial) | ✅ | ✅ | Full shader node tree |
| Textures + Images | ✅ | ✅ | Decoded during parse, bytes in IR |
| Bone Animations | ✅ | ✅ | Keyframes in IR, baking in build |
| Material Animations | ✅ | ✅ | sRGB conversion in describe |
| Constraints (IK, copy, track-to, limits) | ✅ | ✅ | |
| Lights (SUN, POINT, SPOT) | ✅ | ✅ | |
| Bone Instances (JOBJ_INSTANCE) | ✅ | ✅ | |
| Shape Animation | ❌ | ❌ | Stub only |
| Camera | ❌ | ❌ | Stub only |
| Fog | ❌ | ❌ | Stub only |

## Cleanup Status

- [x] shared/Nodes/ stripped of all bpy/build code
- [x] shared/Errors/ removed (replaced with ValueError)
- [x] shared/IO/ModelBuilder.py removed
- [x] Logger/file_io moved to shared/helpers/
- [x] DATParser moved to parse phase helpers
- [x] Keyframe decoder moved to describe phase helpers
- [x] No cross-phase imports
- [x] No circular dependencies
- [ ] Legacy path still available via toggle (intentional)
- [ ] Delete legacy/ directory (when ready)
