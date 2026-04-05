# Export Pipeline Implementation Plan

## Context

The import pipeline is complete and working well. The exporter is the remaining major feature — it reverses the import pipeline to write Blender scenes back to `.dat` binaries. The `DATBuilder` already handles node tree → binary serialization, so the main work is building the new phases that bridge Blender ↔ node trees through the IR.

The approach: implement incrementally by feature (skeleton/mesh first, then materials, etc.), validating each feature with round-trip tests before moving to the next.

---

## Export Pipeline Architecture

The import pipeline flows:
```
raw bytes → DAT bytes → section map → node trees → IRScene → Blender
  Phase 1     Phase 2     Phase 3      Phase 4      Phase 5
```

The export pipeline reverses this (pre-process + 4 phases):
```
validate → Blender → IRScene → node trees → DAT bytes → output file
pre-process  Phase 1   Phase 2    Phase 3      Phase 4
```

| Step | Name | Input | Output | Status |
|------|------|-------|--------|--------|
| Pre | Pre-process | filepath + context | validation pass/fail | ✅ Implemented |
| 1 | Describe Blender Scene | Blender context | IRScene + ShinyParams | ✅ Bones + meshes + materials |
| 2 | Compose | IRScene | Node trees (root nodes) | ✅ Skeleton + meshes + materials + envelope skinning |
| 3 | Serialize | Root nodes → DAT bytes (via DATBuilder) | DAT bytes | ✅ Implemented |
| 4 | Package | DAT bytes + target filepath | Final output bytes | ✅ Implemented |

Section naming is hardcoded: the scene data root is always written as `"scene_data"`, with an optional `"bound_box"` section.

### Directory Structure

```
exporter/
  __init__.py
  exporter.py                        # Exporter.run() entry point
  phases/
    pre_process/
      pre_process.py                 # Pre-process: validate output path + scene       ✅
    describe_blender/
      describe_blender.py            # Phase 1: Blender → IRScene + ShinyParams        ✅
      helpers/
        skeleton.py                  # Armature → IRBone list (+ IBM)                  ✅
        meshes.py                    # Mesh objects → IRMesh list (+ envelope weights) ✅
        materials.py                 # Blender materials → IRMaterial                  ✅
        animations.py                # Actions → IRBoneAnimationSet list                ✅
        constraints.py               # Bone constraints → IR constraint lists
        lights.py                    # Light objects → IRLight list
        material_animations.py       # NLA tracks → IRMaterialAnimationSet list
    compose/
      compose.py                     # Phase 2: IRScene → root node trees              ✅
      helpers/
        bones.py                     # IRBone list → Joint tree                        ✅
        meshes.py                    # IRMesh → Mesh/PObject/EnvelopeList chains       ✅
        materials.py                 # IRMaterial → MaterialObject chain                ✅
        animations.py                # IRBoneAnimationSet → AnimationJoint tree         ✅
        constraints.py               # IR constraints → Reference objects on Joints
        lights.py                    # IRLight → Light/LightSet nodes
        material_animations.py       # IRMaterialAnimationSet → MatAnimJoint tree
    serialize/
      serialize.py                   # Phase 3: node trees → DAT bytes                 ✅
      helpers/
        dat_builder.py               # DATBuilder (binary serialization engine)         ✅
    package/
      package.py                     # Phase 4: DAT bytes → final output (.dat/.pkx)   ✅

shared/helpers/
  pkx.py                             # PKXContainer — shared by extract + package      ✅
  shiny_params.py                    # ShinyParams dataclass                            ✅
```

### DATBuilder Relocation — ✅ Done

`DATBuilder` now lives at `exporter/phases/serialize/helpers/dat_builder.py`. The `shared/IO/` directory has been removed.

### Pipeline Entry Point (`exporter/exporter.py`)

```python
class Exporter:
    @staticmethod
    def run(context, filepath, options=None, logger=StubLogger()):
        # Pre-process — Validate output path and scene
        pre_process(context, filepath, options, logger)

        # Phase 1: Describe Blender Scene
        ir_scene, shiny_params = describe_blender_scene(context, options, logger)

        # Phase 2: Compose node trees
        root_nodes, section_names = compose_scene(ir_scene, options, logger)

        # Phase 3: Serialize via DATBuilder
        dat_bytes = serialize(root_nodes, section_names, logger)

        # Phase 4: Package output
        final_bytes = package_output(dat_bytes, filepath, options, logger,
                                     shiny_params=shiny_params)

        with open(filepath, 'wb') as f:
            f.write(final_bytes)

        return {'FINISHED'}
```

---

## IR Changes: Optional Name Fields

Several HSD node types have `name` string fields that go unused in Colo/XD but could store names from the Blender model. Changes needed:

| IR Type | New Field | Source (export) | Populated From (import) |
|---------|-----------|-----------------|------------------------|
| `IRBone` | `original_name: str \| None = None` | Already has `name` — use it as-is | Currently "Bone_N" — change to use Joint.name if non-empty, else "Bone_N" |
| `IRMesh` | `pobj_name: str \| None = None` | Blender mesh object name | PObject.name if non-empty |
| `IRMesh` | `dobj_name: str \| None = None` | Blender mesh data name | Mesh(DObject).name if non-empty |
| `IRTextureLayer` | `texture_name: str \| None = None` | Blender image name | Texture.name if non-empty |
| `IRLight` | Already has `name` | Use as-is | Already populated |
| `IRMaterial` | `class_type: str \| None = None` | Material name | MaterialObject.class_type if non-empty |

### Import-side changes (describe phase)
- `describe_bones()`: Set `IRBone.original_name = joint.name` if non-empty (keep auto-generated `name` for Blender bone names since Joint names may collide or be empty)
- `describe_meshes()`: Set `pobj_name = pobj.name`, `dobj_name = mesh_node.name`
- `describe_material()`: Set `class_type = mobj.class_type`
- `_describe_texture()`: Set `texture_name = texture.name`

### Export-side (compose phase)
- When building nodes, populate the `name` field from the IR's name/original_name fields
- If the Blender entity has a user-assigned name, use it; otherwise leave empty

**Files to modify:**
- `shared/IR/skeleton.py` — add `original_name` to IRBone
- `shared/IR/geometry.py` — add `pobj_name`, `dobj_name` to IRMesh
- `shared/IR/material.py` — add `class_type` to IRMaterial, `texture_name` to IRTextureLayer
- `importer/phases/describe/helpers/bones.py` — populate original_name
- `importer/phases/describe/helpers/meshes.py` — populate pobj_name, dobj_name
- `importer/phases/describe/helpers/materials.py` — populate class_type, texture_name

---

## Feature Implementation Order

### Feature 1: Skeleton + Mesh (Geometry Only)

This is the foundation — everything else depends on a working skeleton and mesh export.

#### Phase 1: Describe Blender Scene — ✅ Bones + Meshes Implemented

**Important design principle:** The exporter handles **arbitrary Blender models**, not just models imported from Colo/XD. No assumptions are made about bone naming conventions, bone ordering, or import-specific metadata.

**`describe_blender/helpers/skeleton.py`** — Armature → IRBone list ✅

Implementation:
1. Exports only the **currently selected armature(s)** — each becomes one IRModel
2. Enter EDIT mode, walk the bone hierarchy in **depth-first order** (parents before children)
3. For each edit bone:
   - Undo the pi/2 X-axis coordinate rotation to get GameCube Y-up world matrix
   - Compute local matrix from `parent_world.inverted() @ child_world`
   - Decompose local matrix to position (translation), rotation (Euler XYZ), scale
   - Compute accumulated_scale (product with all ancestor scales)
4. **Flags**: Initially set from Blender state (`JOBJ_HIDDEN` from `edit_bone.hide`), then refined by `_refine_bone_flags()` after meshes are described: `JOBJ_SKELETON_ROOT` on root bones, `JOBJ_SKELETON` on deformation bones, `JOBJ_ENVELOPE_MODEL` on bones owning WEIGHTED meshes, `JOBJ_ROOT_OPA` on all ancestor bones of mesh-owning bones
5. `inverse_bind_matrix` = `srt_world.inverted()` — SRT-accumulated world matrix inverse, cleared for non-deformation bones by `_refine_bone_flags()`
6. `scale_correction` is identity (edit bones don't carry scale)

**`describe_blender/helpers/meshes.py`** — Mesh objects → IRMesh list ✅

Implementation:
1. Finds all mesh objects parented to the armature via `obj.parent`
2. For each mesh:
   - Vertices from `mesh_data.vertices`, faces from `mesh_data.polygons`
   - UV layers from `mesh_data.uv_layers` (per-loop data)
   - Color layers from `mesh_data.color_attributes` (FLOAT_COLOR, read as-is — already sRGB)
   - Custom split normals if `mesh_data.has_custom_normals`
   - `material=None` (material export not yet implemented)
3. **Bone weight classification** from vertex groups:
   - Filter vertex groups to only those matching bone names
   - SINGLE_BONE: all vertices reference exactly one bone (same bone)
   - WEIGHTED: vertices reference multiple different bones → preserves per-vertex assignments for EnvelopeList encoding
   - No vertex groups → `bone_weights=None`, bound to root bone
4. **Parent bone index**: SINGLE_BONE → the named bone. WEIGHTED → bone 0 (root, SKELETON_ROOT). See "Envelope Skinning" section.
5. `cull_back` from `material.use_backface_culling` on first material slot
6. `is_hidden` from `mesh_obj.hide_render`

**Envelope skinning solution (WEIGHTED meshes):** See "Envelope Skinning" section below.

#### Phase 2: Compose IR → Node Trees

**`compose/helpers/bones.py`** — IRBone list → Joint tree

Steps (reverse of `describe_bones()`):
1. Create Joint nodes from IRBone list
2. Reconstruct child/next sibling tree from flat parent_index list:
   - Group bones by parent_index
   - First child of a parent → parent.child
   - Subsequent children → previous_sibling.next
3. Set Joint fields:
   - `name` = bone.original_name or bone.name (populate name field for Colo/XD even if originally empty)
   - `flags` = bone.flags
   - `position` = bone.position (vec3)
   - `rotation` = bone.rotation (vec3)
   - `scale` = bone.scale (vec3)
   - `inverse_bind` = bone.inverse_bind_matrix (3x4 matrix) or None
   - `property` = Mesh node (set later when meshes are composed)
   - `reference` = None (set later for constraints)
4. Return root Joint, and a bone_index → Joint mapping for mesh attachment

**`compose/helpers/meshes.py`** — IRMesh list → Mesh/PObject chains

Steps (reverse of `describe_meshes()`):
1. Group IRMeshes by parent_bone_index
2. For each bone's mesh group:
   - Create Mesh (DObject) linked list
   - For each IRMesh:
     - Create PObject with:
       - `name` = mesh.pobj_name or empty
       - Build VertexList with vertex attribute descriptors (position, normals, UVs, colors)
       - Encode display list (GX commands) from vertices and faces
       - Set skin property based on bone_weights.type:
         - RIGID → property = None, flags = 0
         - SINGLE_BONE → property = target Joint, flags = POBJ_SKIN
         - WEIGHTED → property = EnvelopeList[], flags = POBJ_ENVELOPE
     - Create Mesh node: `name` = mesh.dobj_name, `mobject` = None (materials later), `pobject` = pobj
   - Attach first Mesh to parent Joint's `property` field

**`compose/helpers/display_list_encoder.py`** — Vertices/faces → GX display list

This is the most complex single piece of new code:
1. Build vertex attribute table from mesh data (which attributes are present: POS, NRM, TEX0-7, CLR0-1)
2. For each attribute: build vertex buffer (indexed array of unique values)
3. Triangulate faces (Blender may have quads → need to split to tris)
4. Encode as GX_DRAW_TRIANGLES commands:
   - Opcode byte (GX_DRAW_TRIANGLES = 0x90)
   - Vertex count (ushort)
   - For each vertex: index per attribute (based on attribute format type)
5. Pad to 32-byte alignment
6. Return: raw_display_list bytes, VertexList with vertex descriptors, vertex buffers

**Simplification for v1:** Use GX_DRAW_TRIANGLES only (no strips/fans). Triangle strips are an optimization that can be added later.

#### Phase 3: Serialize

Call `DATBuilder(stream, root_nodes, ["scene_data"]).build()`. The section name is always `"scene_data"`, with an optional `"bound_box"` section when bound box data is present.
DATBuilder lives at `exporter/phases/serialize/helpers/dat_builder.py`.

#### Phase 4: Package Output

**`package/package.py`**:
1. If target path doesn't exist or extension is `.dat`/`.fdat`/`.rdat`: write raw DAT bytes
2. If target path is an existing `.pkx` file:
   - Read existing PKX file
   - Detect format (Colosseum 0x40 header vs XD 0xE60 header)
   - Copy header bytes from existing file
   - Replace DAT payload with new DAT bytes
   - Write: original_header + new_dat_bytes

#### Custom Properties Strategy

The exporter deduces HSD values from Blender state rather than relying on custom properties stored during import. This allows it to work with arbitrary Blender models, not just re-exported imports.

**Current flag deduction** (set by `_refine_bone_flags()` in `describe_blender.py`):
- `JOBJ_SKELETON_ROOT` — root bones (parent_index is None)
- `JOBJ_SKELETON` — bones referenced by mesh bone weights (deformation bones)
- `JOBJ_ENVELOPE_MODEL` — bones owning WEIGHTED (envelope) meshes
- `JOBJ_LIGHTING` / `JOBJ_OPA` — bones owning any meshes
- `JOBJ_ROOT_OPA` — all bones in the hierarchy above mesh-owning bones
- `JOBJ_HIDDEN` — bones with `edit_bone.hide` True, or bones where all attached meshes are hidden

**Flags not yet deduced:** `JOBJ_SPLINE`, `JOBJ_EFFECTOR`, `JOBJ_INSTANCE`. These may be exposed as custom properties in the future for users who need fine-grained control.

**Skin type classification:**
- SINGLE_BONE — all vertices reference exactly one bone (same bone) via vertex groups
- WEIGHTED — vertices reference multiple different bones via vertex groups → encoded as EnvelopeList (HSD ENVELOPE)
- No vertex groups → `bone_weights=None`, bound to root bone (index 0)
- RIGID — not produced by the exporter (RIGID requires bone-local vertex positions set via `matrix_local`, which is an import-only concept)

---

### Feature 2: Materials + Textures

#### Phase 1: Describe Blender Scene

**`describe_blender/helpers/materials.py`** — Blender material → IRMaterial

Steps (reverse of `importer/phases/build_blender/helpers/materials.py`):
1. Read material node tree (Principled BSDF or custom node setup)
2. Extract:
   - diffuse_color, ambient_color, specular_color (with linear→sRGB conversion for storage)
   - alpha, shininess
   - color_source, alpha_source, lighting model (from custom properties or heuristics)
   - is_translucent (from blend mode)
3. For each connected image texture node:
   - Extract image pixels (bpy.data.images → RGBA bytes, flip V for GameCube bottom-to-top)
   - Extract UV mapping settings (wrap, repeat, interpolation)
   - Extract blend mode settings
4. Build IRTextureLayer list
5. Extract fragment blending settings

**Key challenge:** Blender's shader nodes are far more expressive than HSD materials. For round-trip fidelity, the import phase should store the original HSD values as custom properties on the Blender material. For user-created materials, we'll need reasonable mapping heuristics.

#### Phase 2: Compose IR → Nodes

**`compose/helpers/materials.py`** — IRMaterial → MaterialObject chain

Steps (reverse of `describe_material()`):
1. Create Material node with colors and alpha
2. Create MaterialObject with render_mode flags reconstructed from IR enums:
   - Map ColorSource → RENDER_DIFFUSE_* flags
   - Map LightingModel → RENDER_DIFFUSE flag
   - Map enable_specular → RENDER_SPECULAR flag
   - Map is_translucent → RENDER_XLU flag
   - Set texture enable bits
3. For each IRTextureLayer:
   - Create Texture node with transform, wrap, source settings
   - Map IR enums back to TEX_* flags
   - Create Image node (needs image encoding)
   - Create Palette node if needed
   - Create LOD node for filtering
   - Create TEV node if combiner is present
4. Create PixelEngine from FragmentBlending

**`compose/helpers/image_encoder.py`** — RGBA pixels → GX texture format

This is substantial new code:
1. Accept RGBA u8 bytes + width + height
2. Encode to a suitable GameCube texture format
3. **Simplest approach for v1:** Encode as RGBA8 (format 0x06) — lossless, simple tile encoding
   - 4x4 tile layout, AR then GB half-tiles
   - Every pixel preserved exactly
4. **Future optimization:** Support CMPR (DXT1-like) for smaller files, I4/I8/IA8 for grayscale
5. Build raw image data bytes + format metadata

#### Attach to Mesh Nodes

After materials are composed, attach them to the Mesh (DObject) nodes:
- `mesh_node.mobject = material_object`

---

### Feature 3: Lights

#### Phase 1: Describe Blender Scene

**`describe_blender/helpers/lights.py`** — Blender lights → IRLight list

Steps (reverse of `build_blender/helpers/lights.py`):
1. Find all light objects in the scene
2. For each light:
   - Map type: SUN → LOBJ_INFINITE, POINT → LOBJ_POINT, SPOT → LOBJ_SPOT
   - Extract color (0-1 → 0-255 range)
   - Extract position from object location
   - Extract target_position (from track-to constraint target, or computed from rotation)

#### Phase 2: Compose IR → Nodes

**`compose/helpers/lights.py`** — IRLight → Light/LightSet nodes

Steps (reverse of `describe_light()`):
1. Create Light node with flags, color, position, interest
2. Create appropriate property (PointLight, SpotLight, or float for infinite)
3. Wrap in LightSet if using SceneData root

---

### Feature 4: Constraints

#### Phase 1: Describe Blender Scene

**`describe_blender/helpers/constraints.py`** — Bone constraints → IR constraint lists

Steps (reverse of `build_blender/helpers/constraints.py`):
1. For each pose bone with constraints:
   - IK constraint → IRIKConstraint (chain_length, target, pole)
   - COPY_LOCATION → IRCopyLocationConstraint
   - TRACK_TO → IRTrackToConstraint
   - COPY_ROTATION → IRCopyRotationConstraint
   - LIMIT_ROTATION → IRLimitConstraint
   - LIMIT_LOCATION → IRLimitConstraint

#### Phase 2: Compose IR → Nodes

**`compose/helpers/constraints.py`** — IR constraints → Reference objects on Joints

Steps (reverse of `describe_constraints()`):
1. For IK constraints: set JOBJ_EFFECTOR flag on bone, create reference chain
2. For other constraints: create Reference objects with appropriate property types and sub_types
3. Attach references to Joint.reference field

---

### Feature 5: Bone Animations

#### Phase 1: Describe Blender Scene

**`describe_blender/helpers/animations.py`** — Actions → IRBoneAnimationSet

Steps (reverse of `build_blender/helpers/animations.py`):
1. For each Action on the armature:
   - Read all fcurves
   - Group fcurves by bone name
   - For each bone: extract rotation/location/scale keyframes
   - **Reverse the baking:** The import bakes HSD SRT → Blender local space. To reverse:
     - For each frame: read Blender local rotation/location/scale from fcurves
     - Reconstruct the SRT matrix: `mtx = local_edit_matrix @ Bmtx @ edit_scale_correction`
     - Decompose back to HSD rotation/location/scale
   - Build IRBoneTrack with decoded keyframes
   - Detect loop flag from action properties
2. Handle spline paths:
   - Find FOLLOW_PATH constraints on bones
   - Read curve object → control points
   - Read offset fcurve → parameter keyframes

**Key challenge:** The import bakes keyframes frame-by-frame with scale correction. The reverse needs to undo this. Since the baked keyframes are sampled at integer frames, we lose the original keyframe positions and interpolation types. The exported animation will have one keyframe per frame (fully baked) rather than the sparse original keyframes. This is acceptable for v1 — optimizing to fewer keyframes with smart interpolation is a future goal.

#### Phase 2: Compose IR → Nodes

**`compose/helpers/animations.py`** — IRBoneAnimationSet → AnimationJoint tree

Steps (reverse of `describe_bone_animations()`):
1. Create AnimationJoint tree parallel to Joint tree (same child/next structure)
2. For each IRBoneTrack:
   - Create Animation node (flags, end_frame)
   - For each non-empty channel (rot X/Y/Z, loc X/Y/Z, scale X/Y/Z):
     - Create Frame node with encoded keyframe data
     - Set type from channel map (HSD_A_J_ROTX, etc.)
3. Attach AnimationJoint tree to ModelSet.animated_joints

**`compose/helpers/keyframe_encoder.py`** — IRKeyframe list → HSD compressed bytes

Reverse of `keyframe_decoder.py`:
1. Accept list of IRKeyframe
2. Choose encoding format (float values → HSD_A_FRAC_FLOAT is simplest for v1)
3. For each keyframe:
   - Encode opcode byte (interpolation type → HSD_A_OP_LIN / HSD_A_OP_SPL / HSD_A_OP_CON)
   - Pack node count
   - Encode value (float → 4 bytes native order)
   - Encode slope if bezier (float → 4 bytes)
   - Encode wait count (frame delta to next keyframe)
4. Return raw_ad bytes, data_length, frac_value, frac_slope settings

---

### Feature 6: Material Animations

#### Phase 1: Describe Blender Scene

**`describe_blender/helpers/material_animations.py`** — NLA tracks → IRMaterialAnimationSet

Steps (reverse of `build_blender/helpers/material_animations.py`):
1. Read NLA tracks for material properties
2. For each animated material:
   - Extract diffuse R/G/B/alpha keyframes (with linear→sRGB conversion)
   - Extract texture UV animation keyframes
3. Build IRMaterialTrack and IRMaterialAnimationSet

#### Phase 2: Compose IR → Nodes

**`compose/helpers/material_animations.py`** — IRMaterialAnimationSet → MatAnimJoint tree

Steps (reverse of `describe_material_animations()`):
1. Create MaterialAnimationJoint tree parallel to Joint tree
2. For each IRMaterialTrack:
   - Create MaterialAnimation node
   - Encode material color/alpha keyframes into Frame nodes
   - Encode texture UV keyframes into Frame nodes

---

## Round-Trip Testing Strategy

### Terminology

| Abbreviation | Name | Flow | Measures |
|---|---|---|---|
| **BNB** | Binary → Node → Binary | DAT bytes → parse → write → compare bytes | Binary-level fidelity (fuzzy 4-byte word match) |
| **NBN** | Node → Binary → Node | Parse → write → reparse → compare fields | Node field preservation through serialization |
| **NIN** | Node → IR → Node | Parse → describe → compose → compare fields | IR round-trip fidelity |

BNB uses `compute_binary_match()` which splits both binaries into 4-byte words and counts matching words by value (not position) using `Counter` intersection. This tolerates layout differences from DATBuilder's alignment/ordering.

### Current Scores (20-model average)

| Test | Average | Range | Notes |
|---|---|---|---|
| NBN | ~92% | 89.6–97.1% | Pointer resolution edge cases |
| NIN | ~59% | 44.1–82.2% | Display list size (no tri-strip), palette encoding |
| IBI | ~60% | 48.9–66.6% | Animations/constraints/lights not yet implemented |
| BNB | ~79% | 56.1–94.0% | Layout/alignment differences |

See [round_trip_test_progress.md](round_trip_test_progress.md) for per-model scores.

### Phase-Level Round-Trip Tests

Each adjacent phase pair should be tested independently:

| Test | Status |
|------|--------|
| NBN: Node → Binary → Node | ✅ Implemented (`tests/test_write_roundtrip.py`) |
| BNB: Binary → Node → Binary | ✅ Implemented (`tests/test_write_roundtrip.py`) |
| NIN: Node → IR → Node | ✅ Implemented (score reflects full node tree) |
| IBI: IR → Blender → IR | ✅ Implemented (bones + meshes + materials) |

See [Round-Trip Test Progress](round_trip_test_progress.md) for per-model scores.

### Test File Strategy

Since game files cannot be committed:
1. **Synthetic tests** (in `tests/`): Build valid node trees in memory, round-trip through IR and back, verify field equality
2. **Real-file tests** (opt-in with `--dat-file`): Run full round-trip on user-provided .dat files, report match percentage
3. **Results tracking**: Store match percentages in `documentation/round_trip_results.md` as a manual-updated table

### New Test Files

```
tests/
  test_export_skeleton.py       # IRBone → Joint tree → IRBone round-trip
  test_export_meshes.py         # IRMesh → PObject → IRMesh round-trip
  test_export_materials.py      # IRMaterial → MaterialObject → IRMaterial round-trip
  test_export_animations.py     # IRKeyframe encode/decode round-trip
  test_export_display_list.py   # Vertex/face → GX display list → vertex/face round-trip
  test_export_image.py          # RGBA → GX texture → RGBA round-trip
  test_export_pipeline.py       # Full pipeline round-trip with synthetic data
  test_export_roundtrip.py      # Real-file round-trip (opt-in, --dat-file)
```

---

### Feature 7: Bound Box

Automatically generate and write the `"bound_box"` section.

The BoundBox section contains per-animation-set, per-frame axis-aligned bounding boxes (AABBs) — not mesh geometry. Each AABB is a min/max vec3 pair (24 bytes) representing the model's spatial extent at a given animation frame. The game uses these for culling and collision. The goal is to compute meaningful AABBs automatically from the animated mesh geometry — there is no user-facing setup required.

**Depends on:** Step E (Bone Animations) — AABB computation requires evaluating the skeleton pose at each animation frame.

#### Implementation
1. For each animation set, evaluate the skeleton + mesh at each frame to compute a world-space AABB
2. Build a BoundBox node with `anim_set_count` and the concatenated AABB data
3. Write as a `"bound_box"` section alongside `"scene_data"` in the serialize phase

---

## Envelope Skinning (WEIGHTED meshes) — ✅ Solved

Envelope skinning was the hardest part of mesh export. Three pieces must be correct simultaneously, and getting any one wrong causes severe mesh deformation.

### The problem

HSD's envelope vertex deformation formula (in the importer's `_extract_envelope_weights`):
```
deform = (bone_world @ bone_IBM) [@ coord]
vertex_final = deform @ vertex_original
```

Where:
- `bone_world` = bone's world matrix from SRT accumulation
- `bone_IBM` = inverse bind matrix stored on the Joint node
- `coord` = coordinate system from `_envelope_coord_system(parent_bone)`, depends on parent bone flags

At rest pose, `deform` must equal identity so vertices stay at their original positions.

### The solution (three interdependent parts)

**1. IBM = `srt_world.inverted()`** (`describe_blender/helpers/skeleton.py`)

The inverse bind matrix is the inverse of the bone's SRT-accumulated world matrix. This world matrix is computed by accumulating `compile_srt_matrix(scale, rotation, position)` through the parent chain **without coordinate rotation** — producing a matrix in HSD's native Y-up space. This matches HSDLib's convention (`WorldTransform.Inverted()` in `LiveJObj.RecalculateInverseBinds`).

**2. WEIGHTED meshes attach to bone 0 (root, SKELETON_ROOT)** (`describe_blender/helpers/meshes.py`)

When the parent bone has `JOBJ_SKELETON_ROOT`, `_envelope_coord_system()` returns `None`. This eliminates the coord factor and simplifies deformation to `bone_world @ IBM @ vertex`. Since `IBM = srt_world.inv` and the reimporter computes `bone_world` from the same SRT values, `bone_world @ IBM = identity`.

Attaching to any other bone type produces a non-None coord that requires IBM values matching the original game tools' computation — which we can't reproduce from Blender data.

**3. IBM always participates in deformation** (`importer/phases/describe/helpers/meshes.py`)

The importer's `_extract_envelope_weights` was previously skipping IBM when `coord=None`:
```python
# OLD (broken for exported models):
if coord:
    matrix = entry_world @ entry_invbind
else:
    matrix = entry_world  # IBM skipped!
```

This caused exported models (with SKELETON_ROOT mesh parents) to have raw world transforms applied to vertices instead of identity. Fixed to always include IBM:
```python
# NEW (correct):
matrix = entry_world @ entry_invbind  # IBM always applied
```

This doesn't affect original game models because their envelope meshes are never on SKELETON_ROOT bones — they use dedicated ENVELOPE_MODEL container bones where coord is always set.

### Why IBM values don't match the original

The original DAT file stores precomputed IBM values from the game's authoring tools. These correspond to a specific skeleton state that may differ from what SRT decomposition→recomposition produces through Blender. The important property is **internal consistency**: our exported IBM is the exact inverse of our exported world matrix, so `bone_world @ IBM = identity` after serialize→reparse.

### Compose phase structure

The compose phase (`compose/helpers/meshes.py`) groups IRMeshes sharing a material under one DObject (Mesh node) with PObjects chained via `.next`, matching HSD convention. Each ENVELOPE PObject gets:
- `property` = list of EnvelopeList nodes (one per unique bone weight combination)
- `flags` = `POBJ_ENVELOPE | POBJ_CULLBACK | 0x1`
- PNMTXIDX vertex descriptor with `component_type = GX_F32`
- Display list with `env_idx * 3` as PNMTXIDX direct values

### Key files
- `exporter/phases/describe_blender/helpers/skeleton.py` — `srt_world` accumulation + `inverse_bind = srt_world.inverted()`
- `exporter/phases/describe_blender/helpers/meshes.py` — `_determine_parent_bone()` returns 0 for WEIGHTED; `_extract_bone_weights()` classifies multi-bone as WEIGHTED
- `exporter/phases/compose/helpers/meshes.py` — `_build_envelope_map()`, `_build_envelope_lists()`, DObject grouping
- `importer/phases/describe/helpers/meshes.py` — `_extract_envelope_weights()` deformation formula fix

---

## Implementation Sequence

### Step A: Foundation (Skeleton + Mesh geometry)
1. ~~Move DATBuilder to `exporter/phases/serialize/helpers/`~~ ✅ Done
2. Add optional name fields to IR types
3. Store HSD custom properties during import (flags, skin type)
4. ~~Implement `describe_blender/helpers/skeleton.py`~~ ✅ Done
5. ~~Implement `compose/helpers/bones.py` (IRBone → Joint tree)~~ ✅ Done
6. Implement `display_list_encoder.py` (the hardest single piece)
7. ~~Implement `describe_blender/helpers/meshes.py`~~ ✅ Done
8. ~~Implement `compose/helpers/meshes.py` (IRMesh → Mesh/PObject)~~ ✅ Done
9. ~~Implement `serialize/serialize.py` (DATBuilder wrapper)~~ ✅ Done
10. ~~Wire up `exporter.py`, `describe_blender.py`, `compose.py`~~ ✅ Done
11. ~~Implement `package.py` (raw DAT + PKX injection + shiny write-back)~~ ✅ Done
12. ~~Implement `pre_process.py` (PKX validation + scene validation stub)~~ ✅ Done
13. Update `BlenderPlugin.py` to use new exporter
14. Write skeleton + mesh round-trip tests
15. Test with real .dat files

### Step B: Materials + Textures
1. Implement `image_encoder.py` (RGBA8 format)
2. Implement `describe_blender/helpers/materials.py`
3. Implement `compose/helpers/materials.py`
4. Wire materials to mesh composition
5. Write material round-trip tests

### Step C: Lights
1. Implement `describe_blender/helpers/lights.py`
2. Implement `compose/helpers/lights.py`
3. Wire to scene composition (SceneData or standalone)
4. Write light round-trip tests

### Step D: Constraints
1. Implement `describe_blender/helpers/constraints.py`
2. Implement `compose/helpers/constraints.py`
3. Write constraint round-trip tests

### Step E: Bone Animations
1. Implement `keyframe_encoder.py`
2. Implement `describe_blender/helpers/animations.py` (with reverse baking)
3. Implement `compose/helpers/animations.py`
4. Wire AnimationJoint trees to ModelSet
5. Write animation round-trip tests

### Step F: Material Animations
1. Implement `describe_blender/helpers/material_animations.py`
2. Implement `compose/helpers/material_animations.py`
3. Wire MaterialAnimationJoint trees to ModelSet
4. Write material animation round-trip tests

### Step G: Bound Box
1. Implement per-frame AABB computation by evaluating skeleton poses + mesh geometry at each animation frame
2. Build BoundBox node with `anim_set_count` and concatenated AABB data
3. Update serialize to include `"bound_box"` as a second section when AABB data is present
4. Write bound box round-trip tests (compare computed AABBs against original file's AABBs)

### Step H: Round-Trip Scoring System
1. Build match percentage scoring utility
2. Run against test file corpus
3. Document results and known gaps
4. Iterate on fidelity improvements

---

## Key Files to Modify (Existing)

| File | Change |
|------|--------|
| ~~`shared/IO/dat_builder.py`~~ | ✅ Moved to `exporter/phases/serialize/helpers/dat_builder.py` |
| `shared/IR/skeleton.py` | Add `original_name` to IRBone |
| `shared/IR/geometry.py` | Add `pobj_name`, `dobj_name` to IRMesh |
| `shared/IR/material.py` | Add `class_type` to IRMaterial, `texture_name` to IRTextureLayer |
| `importer/phases/describe/helpers/bones.py` | Populate `original_name` |
| `importer/phases/describe/helpers/meshes.py` | Populate `pobj_name`, `dobj_name` |
| `importer/phases/describe/helpers/materials.py` | Populate `class_type`, `texture_name` |
| `importer/phases/build_blender/helpers/skeleton.py` | Store `hsd_flags` custom property |
| `importer/phases/build_blender/helpers/meshes.py` | Store `hsd_skin_type` custom property |
| `BlenderPlugin.py` | Wire ExportHSD to new exporter pipeline |
| `documentation/exporter_usage.md` | Update feature status as features are implemented |
| ~~`test_dat_write.py`~~ | Removed — functionality moved to `tests/round_trip/run_round_trips.py` |

## Key Files Created

| File | Status |
|------|--------|
| `exporter/exporter.py` | ✅ Pipeline entry point |
| `exporter/phases/pre_process/pre_process.py` | ✅ PKX validation + scene validation stub |
| `exporter/phases/describe_blender/describe_blender.py` | ✅ Bones + meshes + materials + flag refinement |
| `exporter/phases/describe_blender/helpers/skeleton.py` | ✅ Armature → IRBone list + IBM (srt_world.inv) |
| `exporter/phases/describe_blender/helpers/meshes.py` | ✅ Mesh objects → IRMesh list + envelope weights |
| `exporter/phases/describe_blender/helpers/materials.py` | ✅ Blender materials → IRMaterial |
| `exporter/phases/describe_blender/helpers/animations.py` | ✅ Fcurve reading + unbaking |
| `exporter/phases/compose/compose.py` | ✅ Full scene composition |
| `exporter/phases/compose/helpers/bones.py` | ✅ IRBone → Joint tree |
| `exporter/phases/compose/helpers/meshes.py` | ✅ IRMesh → Mesh/PObject/EnvelopeList chains |
| `exporter/phases/compose/helpers/materials.py` | ✅ IRMaterial → MaterialObject chain |
| `exporter/phases/compose/helpers/animations.py` | ✅ Keyframe encoding |
| `exporter/phases/serialize/serialize.py` | ✅ DATBuilder wrapper |
| `exporter/phases/package/package.py` | ✅ .dat passthrough + .pkx injection |
| `shared/helpers/pkx.py` | ✅ PKXContainer (shared by extract + package) |
| `shared/helpers/shiny_params.py` | ✅ ShinyParams dataclass |
| ~~`utilities/dat_to_json.py`~~ | Removed — round-trip tests now use real model files directly |
| ~~`utilities/json_to_ir.py`~~ | Removed — round-trip tests now use real model files directly |
| `tests/round_trip/run_round_trips.py` | ✅ All round-trip tests (NBN, NIN, IBI, BNB) |

---

## Verification

For each phase:
1. Write unit tests with synthetic data (no game files)
2. Run `pytest` to verify all tests pass
3. Test with real .dat files via round-trip:
   - Import a .dat file into Blender
   - Export from Blender to new .dat
   - Re-import the exported .dat
   - Compare IR scenes field-by-field
   - Compare binary output with `tests/round_trip/run_round_trips.py`
4. Verify in Blender: exported model should render identically to the original import
