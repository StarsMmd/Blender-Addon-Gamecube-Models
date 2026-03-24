# Phased Import Pipeline Plan

## Context

The importer currently couples binary parsing with Blender object creation — each Node subclass has a `build()` method that directly calls ~865 `bpy` API calls across 11 files. This makes it impossible to test without Blender, hard to debug, and prevents reuse for export (which needs to go in reverse). The goal is to introduce clearly separated phases with defined inputs/outputs, and a new **Intermediate Representation (IR)** that decouples the DAT format from Blender.

---

## Pipeline Overview

Each phase is a pure function: input -> output, no shared state between phases. Each phase has its own subfolder under `phases/` for multi-file organization. Shared pure logic lives under `shared/` in subfolders.

```
         Phase 1             Phase 2              Phase 3               Phase 4              Phase 5A
Binary ---------> list  ------------> DAT +   ------------> Node   ------------> IR     ------------> Blender
file    extract   of     route       type map  parse        trees   describe     Scene   build         Scene
                  DATs                                                             |
                  (1+)   <--- phases 2-5 run per DAT entry --->                    +----> Phase 5B
                                                                                   blend   .blend file
```

| Phase | Name | Input | Output | Entry folder | bpy? | Testable? |
|-------|------|-------|--------|--------------|------|-----------|
| 1 | Container Extraction | Binary file (.dat/.pkx/.fsys) | List of (DAT bytes, metadata) | `phases/extract/` | No | Yes |
| 2 | Section Routing | DAT bytes | DAT bytes + `{name: NodeType}` map | `phases/route/` | No | Yes |
| 3 | Node Tree Parsing | DAT bytes + type map | List of node trees | `phases/parse/` | No | Yes (existing) |
| 4 | Scene Description | Node tree(s) | `IRScene` dataclass hierarchy | `phases/describe/` | No\* | Yes |
| 5A | Blender Build | `IRScene` | Blender scene (side effects) | `phases/build_blender/` | Yes | Manual |
| 5B | Blend Export (future) | `IRScene` | `.blend` file | `phases/build_blend/` | Headless | Yes |

\* Phase 4 uses `mathutils` (Matrix/Vector) which is available in Blender Python. A thin shim enables testing outside Blender.

**No shared mutable state between phases.** Each phase receives its input as arguments and returns its output. Shared pure logic (math helpers, sRGB conversion, keyframe decoding, IR types) lives under `shared/` organized into subfolders.

---

## Phase Descriptions

### Phase 1 — Container Extraction

**Current:** `DATParser.__init__()` lines 39-51 detect PKX headers and set `file_start_offset`.

**Target:** Standalone function in `phases/extract/`:
```python
def extract_dat(filepath: str) -> list[tuple[bytes, ContainerMetadata]]:
    """Returns a list of (dat_bytes, metadata) from any supported container.
    A .dat or .pkx yields one entry. A .fsys yields one per embedded model."""
```

**Containers to support:**
- `.dat` — pass through, returns single entry (offset 0)
- `.pkx` — detect Colosseum vs XD by byte pattern, skip PKX header (0x40 or 0xE60+GPT1), returns single entry
- `.fsys` — unpack FSYS archive, extract all embedded .dat model entries, returns multiple entries

**Files:** `phases/extract/` (new), refactored from `shared/IO/DAT_io.py`. FSYS unpacking reference code already exists in the project.

### Phase 2 — Section Routing

**Current:** `SectionInfo.readNodeTree()` lines 23-43 use hardcoded string matching.

**Target:** Standalone function in `phases/route/`:
```python
def resolve_sections(dat_bytes: bytes, user_overrides: dict | None = None) -> dict[str, str]:
    """Returns {section_name: node_type_name} map."""
```

Default mapping:
```python
DEFAULT_SECTION_MAP = {
    "scene_data": "SceneData",
    "bound_box": "BoundBox",
    "scene_camera": "CameraSet",
    "*shapeanim_joint*": "ShapeAnimationJoint",
    "*matanim_joint*": "MaterialAnimationJoint",
    "*_joint*": "Joint",
}
```

User can override via import dialog. Phase 2 output is the resolved map.

**Files:** `phases/route/` (new), refactored from `SectionInfo.readNodeTree()`

### Phase 3 — Node Tree Parsing

**Current:** `DATParser.parseSections()` + `parseNode()` — already bpy-free.

**Target:** Standalone function in `phases/parse/`:
```python
def parse_node_trees(dat_bytes: bytes, section_map: dict[str, str], options: dict) -> list[SectionInfo]:
    """Parses DAT binary into node trees using the section->type map."""
```

Wraps existing `DATParser`. No major changes needed — this phase is already clean.

**Files:** `phases/parse/` (new thin wrapper around existing `DATParser`)

### Phase 4 — Scene Description (NEW)

**Target:** Standalone function in `phases/describe/`:
```python
def describe_scene(sections: list[SectionInfo], options: dict) -> IRScene:
    """Converts node trees into an IRScene — pure dataclasses, no bpy."""
```

This is where all the `build()` / `prepareForBlender()` logic gets decomposed: data extraction stays here, bpy calls move to Phase 5A. The IR specification is documented separately in [ir_specification.md](ir_specification.md).

### Phase 5A — Blender Build

Entry point in `phases/build_blender/`:
```python
def build_blender_scene(ir_scene: IRScene, context, options: dict) -> None:
    """Consumes an IRScene and creates Blender objects via bpy API."""
```

No shared state with other phases — receives the complete `IRScene` and the Blender `context`.

### Phase 5B — Blend Export (future, low priority)

Entry point in `phases/build_blend/`. Takes an `IRScene` and produces a `.blend` file using `blender --background --python`.

---

## Blender API Calls That Phase 5A Must Make

| Category | Calls | Current source files |
|----------|-------|---------------------|
| **Armature** | `bpy.data.armatures.new()`, `bpy.data.objects.new()`, `.matrix_basis`, `.display_type`, `scene.collection.objects.link()`, `.select_set()` | ModelSet.py |
| **Bones** | `armature_data.edit_bones.new()`, `.head`, `.tail`, `.parent`, `.matrix`, `.inherit_scale` | Joint.py |
| **Mode switching** | `bpy.ops.object.mode_set(mode='EDIT'/'POSE'/'OBJECT')`, `view_layer.objects.active`, `view_layer.update()` | ModelSet.py, Joint.py, Mesh.py |
| **Meshes** | `bpy.data.meshes.new()`, `bpy.data.objects.new()`, `.from_pydata()`, `.update()`, `.validate()` | PObject.py |
| **UV/Color** | `mesh.uv_layers.new()`, `mesh.vertex_colors.new()`, `.data[i].uv`, `.data[i].color` | PObject.py |
| **Normals** | `mesh.normals_split_custom_set()` | Mesh.py |
| **Shape keys** | `ob.shape_key_add()`, `shapekey.data[i].co` | PObject.py |
| **Vertex groups** | `mesh.vertex_groups.new()`, `group.add()` | Mesh.py |
| **Armature mod** | `mesh.modifiers.new('ARMATURE')`, `mod.object`, `mod.use_vertex_groups` | Mesh.py |
| **Materials** | `bpy.data.materials.new()`, `.use_nodes`, `nodes.new()` (~20 types), `links.new()`, `.default_value` | MaterialObject.py |
| **Images** | `bpy.data.images.new()`, `.pixels`, `.alpha_mode`, `.pack()`, `.save()` | Image.py |
| **Actions** | `bpy.data.actions.new()`, `.use_fake_user`, `.slots.new()` (4.5+), `animation_data_create()`, `.action` | ModelSet.py, MaterialAnimation.py |
| **Fcurves** | `action.fcurves.new()`, `keyframe_points.insert()`, `.interpolation`, `.handle_left/right` | AnimationJoint.py, Frame.py |
| **NLA** | `animation_data.nla_tracks.new()`, `track.strips.new()`, `.extrapolation`, `.mute` | MaterialAnimation.py |
| **Modifiers** | `curve.modifiers.new('CYCLES')` | AnimationJoint.py |
| **Constraints** | `pose.bones[].constraints.new(type=...)` — IK, COPY_LOCATION, TRACK_TO, COPY_ROTATION, LIMIT_\* | ModelSet.py |
| **Lights** | `bpy.data.lights.new()`, `bpy.data.objects.new()`, `.color`, `.constraints.new('TRACK_TO')` | Light.py |
| **Curves** | `bpy.data.curves.new()`, `.splines.new()`, `.points.add()`, `.points[i].co` | Spline.py |
| **Pose** | `bone.location/rotation_euler/scale`, `bone.rotation_mode` | ModelSet.py |
| **Scene** | `bpy.context.scene.frame_set(0)` | ModelSet.py |

---

## Implementation Steps

### Step 0 — Project Setup

1. Move current `importer/`, `exporter/`, `shared/` into `legacy/`
2. Update `__init__.py` to import from `legacy/` paths so the addon still works
3. Create fresh directory structure for the new implementation:

```
phases/
  extract/                # Phase 1: container -> DAT bytes
    __init__.py
  route/                  # Phase 2: section name -> node type map
    __init__.py
  parse/                  # Phase 3: DAT bytes -> node trees
    __init__.py
  describe/               # Phase 4: node trees -> IRScene
    __init__.py
    bones.py              # bone description logic
    meshes.py             # mesh/geometry description
    materials.py          # material description
    animations.py         # animation description
    constraints.py        # constraint extraction
    lights.py             # light description
  build_blender/          # Phase 5A: IRScene -> Blender scene
    __init__.py
    skeleton.py           # armature + bone creation
    meshes.py             # mesh + weights + modifiers
    materials.py          # shader node tree construction
    animations.py         # actions, fcurves, NLA
    constraints.py        # bone constraints
    lights.py             # light objects
  build_blend/            # Phase 5B: IRScene -> .blend file (future)
    __init__.py

shared/
  IR/                     # Intermediate Representation dataclasses
    __init__.py
    enums.py
    scene.py, skeleton.py, geometry.py, material.py
    animation.py, constraints.py, lights.py, camera.py, fog.py
  helpers/                # Shared pure logic (no bpy, no phase-specific state)
    __init__.py
    math_shim.py          # Matrix/Vector/Euler
    srgb.py               # sRGB <-> linear
    keyframe_decoder.py   # pure-data keyframe decoding
  Nodes/                  # (copied from legacy) Node system for binary parsing
  IO/                     # (copied from legacy) Binary reader/writer
  Constants/              # (copied from legacy) HSD/GX constants
```

5. Copy `shared/Nodes/`, `shared/IO/`, `shared/Constants/` from `legacy/` — the node system and binary parser are still needed by Phases 1-3 and are largely unchanged
6. Wire `__init__.py` to call the new `phases/` pipeline (with fallback to `legacy/` if needed)

### Step 1 — Geometry (minimum viable IR)

1. `phases/describe.py` — `_describe_bones()`: walk Joint tree -> flat `IRBone` list with transforms
2. `phases/describe.py` — `_describe_meshes()`: walk Mesh->PObject -> `IRMesh` with verts/faces/UVs/colors/normals/weights
3. `phases/build_blender.py` — `_build_skeleton()`: armature + edit bones
4. `phases/build_blender.py` — `_build_meshes()`: meshes + vertex groups + armature modifier

**Code to port:**
- `Joint.py:64-117` -> `phases/describe.py` (bone data extraction + matrix computation)
- `PObject.py:141-281` -> `phases/build_blender.py` (geometry creation from IR)
- `Mesh.py:22-154` -> `phases/build_blender.py` (weight application + material assignment)

### Step 2 — Materials

1. `phases/describe.py` — `_describe_material()`: extract render_mode, colors, textures, TEV, PE
2. `phases/describe.py` — `_describe_image()`: extract decoded pixels (dedup by image_id + palette_id)
3. `phases/build_blender.py` — `_build_material()`: port MaterialObject.build() (~550 LOC)

Shader construction sub-methods:
- `_build_base_color()` — diffuse/alpha from render flags
- `_build_texture_chain()` — per-texture UV->image->blend ops
- `_build_tev()` — TEV combiner nodes
- `_build_pixel_engine()` — blend mode
- `_build_output_shader()` — Principled BSDF assembly

### Step 3 — Animation

1. `shared/helpers/keyframe_decoder.py` — `decode_fobjdesc()`: pure-data version of `Frame.read_fobjdesc()` returning `list[IRKeyframe]`
2. `phases/describe.py` — `_describe_bone_animations()`: decode HSD keyframes, bake SRT->Blender-space
3. `phases/describe.py` — `_describe_material_animations()`: color/alpha/UV tracks with sRGB->linear
4. `phases/build_blender.py` — `_build_bone_animations()`: actions, fcurves, keyframes, CYCLES
5. `phases/build_blender.py` — `_build_material_animations()`: material actions, NLA tracks

**Key refactor:** `AnimationJoint.py:74-211` split into:
- (a) `decode_fobjdesc()` -> raw keyframe data (pure Python, in helpers)
- (b) `bake_bone_animation()` -> Blender-space keyframes (mathutils, in describe.py)
- (c) Phase 5A -> insert into bpy fcurves (in build_blender.py)

### Step 4 — Constraints, Lights, Instances

1. `phases/describe.py` — `_describe_constraints()`: extract from Reference chain into typed IR constraint dataclasses
2. `phases/describe.py` — `_describe_lights()`: extract Light type/color/position/target
3. `phases/build_blender.py` — `_build_constraints()`: create typed Blender constraints
4. `phases/build_blender.py` — `_build_lights()`: create light objects
5. `phases/build_blender.py` — `_build_instances()`: copy meshes for JOBJ_INSTANCE

### Step 5 — Cleanup

1. Remove `build()` / `prepareForBlender()` from Node subclasses in `shared/`
2. Remove `import bpy` from Node files in `shared/`
3. Delete `legacy/` directory entirely
4. Clean up any remaining references to legacy paths

---

## Testing Strategy

Unit tests for every testable phase (all except 5A):

| Phase | Test | bpy? | Verifies |
|-------|------|------|----------|
| 1 | `test_extract_dat_from_dat` | No | .dat passes through unchanged |
| 1 | `test_extract_dat_from_pkx` | No | PKX header stripped, correct offset |
| 2 | `test_route_default_sections` | No | Known section names resolve to correct types |
| 2 | `test_route_user_override` | No | User override takes precedence |
| 3 | (existing 158 tests) | No | Node parsing round-trip |
| 4 | `test_describe_bones` | No\* | Joint tree -> IRBone: parent indices, transforms, names |
| 4 | `test_describe_mesh` | No | PObject -> IRMesh: vertex/face/UV counts |
| 4 | `test_describe_material` | No | MaterialObject -> IRMaterial: flags, colors, texture count |
| 4 | `test_describe_bone_animation` | No\* | AnimationJoint -> IRBoneAnimationSet: baked keyframes |
| 4 | `test_describe_constraints` | No | Reference chain -> typed IRConstraint instances |
| 4 | `test_describe_lights` | No | Light node -> IRLight: type, color, position |
| helpers | `test_decode_fobjdesc_constant` | No | Known bytes -> expected keyframes |
| helpers | `test_decode_fobjdesc_linear` | No | Known bytes -> expected keyframes |
| helpers | `test_decode_fobjdesc_bezier` | No | Known bytes -> expected keyframes + handles |
| helpers | `test_srgb_to_linear` | No | Known values round-trip correctly |
| IR | `test_ir_dataclass_instantiation` | No | All IR types instantiate with valid data |
| IR | `test_ir_enum_values` | No | Enum values match HSD constants |
| Regression | `test_ir_vs_old_path` | Yes | Same bone/mesh/material counts for real models |

\* Uses mathutils shim for matrix math.

**mathutils shim** (`shared/helpers/math_shim.py`): imports from `mathutils` when available, falls back to minimal pure-Python implementation. Operations needed: Matrix multiply, inverse, decompose, to_euler, Scale/Rotation/Translation constructors.

---

## File Organization

```
phases/
  extract/                  # Phase 1
    __init__.py
  route/                    # Phase 2
    __init__.py
  parse/                    # Phase 3
    __init__.py
  describe/                 # Phase 4
    __init__.py             #   entry point: describe_scene()
    bones.py
    meshes.py
    materials.py
    animations.py
    constraints.py
    lights.py
  build_blender/            # Phase 5A
    __init__.py             #   entry point: build_blender_scene()
    skeleton.py
    meshes.py
    materials.py
    animations.py
    constraints.py
    lights.py
  build_blend/              # Phase 5B (future)
    __init__.py

shared/
  IR/                       # Intermediate Representation dataclasses
    __init__.py
    enums.py
    scene.py, skeleton.py, geometry.py, material.py
    animation.py, constraints.py, lights.py, camera.py, fog.py
  helpers/                  # Shared pure logic
    __init__.py
    math_shim.py
    srgb.py
    keyframe_decoder.py
  Nodes/                    # Node system (from legacy)
  IO/                       # Binary reader/writer (from legacy)
  Constants/                # HSD/GX constants (from legacy)

documentation/
  import_pipeline_plan.md
  compatibility_table.md
  ir_specification.md
```

---

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Phase organization | Subfolder per phase | Multi-file phases, grouped logic |
| Shared logic | `shared/helpers/` | Pure functions, no state; usable by any phase |
| IR material format | Abstract HSD params | Preserves fidelity for export; shader tree is Blender-specific |
| Animation keyframes | Fully baked (frame->value) | Eliminates bpy dependency; testable |
| Bone hierarchy | Flat list with parent_index | Simpler to serialize; matches Blender model |
| Migration | Move to `legacy/`, build fresh | Clean start, easy fallback, clear completion signal |
| Strings vs enums | Python `Enum` everywhere | Type safety, IDE completion, self-documenting |
| Constraint types | Separate dataclass per type | No `dict` params; explicit typed fields |

---

## Verification

After each step:
1. `python3 -m pytest tests/ -x -q` — all existing + new tests pass
2. Import a test model (e.g. nukenin.pkx) with `use_ir=True`, compare visually to `use_ir=False`
3. `test_dat_write.py` round-trip unaffected (IR is read-only)
4. After Step 5: old path fully removed, all imports work
