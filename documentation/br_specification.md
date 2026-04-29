# Blender Representation (BR) Specification

The BR is a pure-Python dataclass hierarchy with every field pre-decided for Blender consumption — enum strings match Blender's own, matrices are in Blender's target space, shader graphs are fully specified node-by-node. It serves both pipeline directions:

- **Import side** — output of Phase 5a (`importer/phases/plan/`) and input to Phase 5b (`importer/phases/build_blender/`). Plan converts IR → BR; build mechanically walks the BR with no shader / geometry / bake decisions of its own.
- **Export side** — output of Phase 1 (`exporter/phases/describe/`) and input to Phase 2 (`exporter/phases/plan/`). Describe snapshots Blender into BR; the export `plan` converts BR → IR for the rest of the export pipeline. Materials and animations currently ride a `_ir_material` / `_ir_animation_set` side-channel on the BR object; the deep decoders that produce them live in `exporter/phases/describe/helpers/{materials,animations,material_animations}_decode.py` and will eventually shape into BR types directly.

**Design principles:**
- All types are `@dataclass` from the standard library — no `bpy` types, no `mathutils`.
- Matrices are `list[list[float]]` (4 rows of 4 floats), never `Matrix` instances.
- Enum-like values are **Blender's own strings** (`'ALIGNED'`, `'XYZ'`, `'OCTAHEDRAL'`, `'ShaderNodeMath'`, `'HASHED'`) — no re-encoding.
- BR is constructible and inspectable without Blender running — every test in `tests/test_plan_*.py` does exactly that.
- BR does **not** import from `shared/IR/` — it is downstream data, not a type alias. IRKeyframe objects may be held as opaque pass-through values in some places (see BRBoneTrack), but BR dataclasses never reference IR types in their field annotations.
- No mutable shared state — each BR instance is a self-contained snapshot.

---

## Top-level shape

```
BRScene
├── models: list[BRModel]
├── lights: list[BRLight]
└── cameras: list[BRCamera]

BRModel
├── name: str
├── armature: BRArmature
├── meshes: list[BRMesh]
├── mesh_instances: list[BRMeshInstance]
├── actions: list[BRAction]
├── materials: list[BRMaterial]       # deduped; BRMesh.material_index points here
├── constraints: BRConstraints        # pass-through wrapper around IR constraints
└── particles: BRParticleSummary | None
```

---

## BRArmature

`shared/BR/armature.py`

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Blender object + data block name. Derived from `options['filepath']` + `IRModel.name` + model index. |
| `bones` | `list[BRBone]` | In DFS order matching IR. |
| `display_type` | `str` | Blender armature display enum: `'OCTAHEDRAL'` / `'STICK'` / `'BBONE'` / `'ENVELOPE'` / `'WIRE'`. `'STICK'` when `options['ik_hack']` is set, else `'OCTAHEDRAL'`. |
| `matrix_basis` | `list[list[float]] \| None` | 4×4 transform for the armature *object*. Plan sets the π/2 X-rotation here so GC Y-up data lands in Blender Z-up automatically. |
| `custom_props` | `dict[str, object]` | Extra `armature["key"] = value` props. Empty by default; `build_skeleton` still stamps `dat_leniencies` from the logger separately. |

### BRBone

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Zero-padded `Bone_NN` plus optional body-map suffix (e.g. `Bone_062_Head`). |
| `parent_index` | `int \| None` | Index into `bones`. |
| `edit_matrix` | `list[list[float]]` | 4×4 world-space matrix assigned to `edit_bone.matrix`. Comes from IR's `normalized_world_matrix`. |
| `tail_offset` | `tuple[float, float, float]` | Relative head→tail offset. `(0, 0.01, 0)` by default; IK-effector shrink reduces the Y component. |
| `inherit_scale` | `str` | Blender's `bone.inherit_scale` enum: `'ALIGNED'` (uniform chain) or `'NONE'` (non-uniform). Decided by `choose_inherit_scale(accumulated_scale)` — threshold `mx/mn < 1.1` or `mn < 1e-3`. |
| `rotation_mode` | `str` | Blender's `pose_bone.rotation_mode` enum. Always `'XYZ'`. |
| `use_connect` | `bool` | Reserved; currently `False` everywhere. |
| `is_hidden` | `bool` | Mirrors `IRBone.is_hidden` for post-process consumption. |

---

## BRMesh

`shared/BR/meshes.py`

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | `{model_name}_mesh_{ir_mesh.name}`. |
| `mesh_key` | `str` | Stable id `mesh_NN_{parent_bone_name}` used to link material-animation tracks to this mesh. Zero-padded to the digit width needed for the total mesh count. |
| `vertices` | `list[tuple[float, float, float]]` | World-space positions (IR convention). |
| `faces` | `list[list[int]]` | Triangle index lists. |
| `uv_layers` | `list[BRUVLayer]` | Per-corner UV data, name + coords. |
| `color_layers` | `list[BRColorLayer]` | Per-corner sRGB RGBA; build stores as `FLOAT_COLOR`. |
| `normals` | `list[tuple[float, float, float]] \| None` | Per-loop custom normals. When present, build marks all polygons `use_smooth=True`. |
| `vertex_groups` | `list[BRVertexGroup]` | Flattened from IR's three SkinType variants — every variant produces the same (name, assignments) shape. |
| `parent_bone_name` | `str \| None` | Name of the owning bone. Written to `mesh_object.parent_bone` for round-trip preservation. |
| `is_hidden` | `bool` | Mirrors GX hidden-render flag; build sets `hide_render` + `hide_set(True)`. |
| `shape_keys` | `list` | IRShapeKey pass-through until a dedicated shape-key stage lands. |
| `material_index` | `int \| None` | Index into `BRModel.materials`. `None` means the mesh gets a placeholder material. |

### BRVertexGroup

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Bone name. |
| `assignments` | `list[tuple[int, float]]` | `(vertex_index, weight)` pairs. For WEIGHTED skin, one entry per weighted vertex; for SINGLE_BONE / RIGID, every vertex at weight 1.0. |

### BRMeshInstance

| Field | Type | Notes |
|---|---|---|
| `source_mesh_index` | `int` | Index into `BRModel.meshes`. |
| `target_parent_bone_name` | `str` | Bone the copy attaches to. |
| `matrix_local` | `list[list[float]]` | 4×4 transform for the copy in the armature's local space. |

Instances model `JOBJ_INSTANCE` bones: Plan expands one source bone with `instance_child_bone_index=M` into one BRMeshInstance per mesh owned by bone M.

---

## BRAction

`shared/BR/actions.py`

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Blender Action name; mirrors `IRBoneAnimationSet.name`. |
| `bone_tracks` | `list[BRBoneTrack]` | One per animated bone. |
| `material_tracks` | `list[BRMaterialTrack]` | Pass-through wrappers for IR material tracks. |
| `loop` | `bool` | |
| `is_static` | `bool` | |

### BRBoneTrack

| Field | Type | Notes |
|---|---|---|
| `bone_name` | `str` | |
| `bone_index` | `int` | |
| `rotation` / `location` / `scale` | `list[list[IRKeyframe]]` | Three channels each; IRKeyframe instances carried through as opaque data so Blender's fcurve interpolator can evaluate them at integer frames. |
| `rest_rotation` / `rest_position` / `rest_scale` | tuples of 3 floats | Constants used when a channel has no keyframes (build fills with these). |
| `end_frame` | `float` | |
| `bake_context` | `BRBakeContext` | Pre-computed rest data for the per-frame basis formula. |
| `spline_path` | `object` | IRSplinePath pass-through for FOLLOW_PATH-animated bones. |

### BRBakeContext

Everything the pose-basis formula needs at each frame, as plain data.

| Field | Type | Notes |
|---|---|---|
| `strategy` | `'aligned'` \| `'direct'` | Chosen by `choose_bake_strategy(accumulated_scale)` — uniform → `aligned` (sandwich formula), non-uniform → `direct` (SRT delta). |
| `rest_base` | `list[list[float]]` | 4×4 `rest_local_matrix` with path-rotation baked in for FOLLOW_PATH bones. |
| `rest_base_inv` | `list[list[float]]` | Fallback for aligned when the sandwich's edit-matrix inversion fails. |
| `has_path` | `bool` | |
| `rest_translation` | `tuple[float, float, float]` | Direct-path pre-decomposed rest translation. |
| `rest_rotation_quat` | `tuple[float, float, float, float]` | `(w, x, y, z)` rest quaternion. |
| `rest_scale` | `tuple[float, float, float]` | |
| `local_edit` | `list[list[float]] \| None` | Aligned-path only: bone's `normalized_local_matrix`. |
| `edit_scale_correction` | `list[list[float]] \| None` | Aligned-path only. |
| `parent_edit_scale_correction` | `list[list[float]] \| None` | Aligned-path only; resolved via a second pass (`attach_parent_edit_scale_corrections`) once all bone tracks have been created. |

### BRMaterialTrack

Pass-through wrapper for IR material-animation track. Build's material-animation helpers still consume IR-shaped fields from it.

| Field | Type | Notes |
|---|---|---|
| `material_mesh_name` | `str` | Matches `BRMesh.mesh_key`. |
| `diffuse_r` / `_g` / `_b` / `alpha` | `list[IRKeyframe] \| None` | |
| `texture_uv_tracks` | `list` | IRTextureUVTrack pass-through. |
| `loop` | `bool` | |

---

## BRMaterial

`shared/BR/materials.py`

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Blender material name (`{model}_mat_{first_using_mesh_index}`). |
| `node_graph` | `BRNodeGraph` | Fully-baked shader graph. |
| `use_backface_culling` | `bool` | True if the mesh had either cull flag set. |
| `blend_method` | `str \| None` | `'OPAQUE'` / `'HASHED'` / `'BLEND'` / `None` (leave Blender default). |
| `dedup_key` | `object` | `(id(ir_material), cull_front, cull_back)` triple; Plan emits one BRMaterial per unique key so multiple meshes can share a bpy material. |

### BRNodeGraph

| Field | Type | Notes |
|---|---|---|
| `nodes` | `list[BRNode]` | Output node (`ShaderNodeOutputMaterial`) is an explicit entry. |
| `links` | `list[BRLink]` | Socket-to-socket connections. |

### BRNode

A direct mirror of `bpy.types.ShaderNode`.

| Field | Type | Notes |
|---|---|---|
| `node_type` | `str` | Blender `bl_idname`, e.g. `'ShaderNodeMath'`. |
| `name` | `str` | Stable identifier for intra-graph references and material-animation fcurve binding (`DiffuseColor`, `AlphaValue`, `TexMapping_N`, `dat_ambient_emission`, etc.). Plan auto-generates `_nN` names for unnamed nodes. |
| `properties` | `dict[str, object]` | Type-specific attributes set via `setattr`. Special key `_output_default` is used by build to set `outputs[0].default_value` on `ShaderNodeRGB` / `ShaderNodeValue` (which store their constant on the output, not an input). |
| `input_defaults` | `dict[object, object]` | `default_value` to set per input socket. Keys are index (`int`) or name (`str`); linked inputs override. |
| `image_ref` | `BRImage \| None` | Populated only on `ShaderNodeTexImage`. |
| `location` | `tuple[float, float] \| None` | Editor canvas position. Plan's `_plan_auto_layout` assigns columns via BFS from the output node. |

### BRLink

| Field | Type | Notes |
|---|---|---|
| `from_node` | `str` | BRNode name. |
| `from_output` | `int \| str` | Socket index or name. |
| `to_node` | `str` | |
| `to_input` | `int \| str` | |

### BRImage

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | |
| `width` / `height` | `int` | |
| `pixels` | `bytes` | Raw u8 RGBA. |
| `cache_key` | `tuple` | `(image_id, palette_id)` identity. Build dedups bpy images across materials via this key. |
| `alpha_mode` | `str` | `'CHANNEL_PACKED'` default. |
| `pack` | `bool` | Whether to call `bpy_image.pack()`. |
| `gx_format_override` | `str \| None` | Written to `bpy_image.dat_gx_format` for round-trip export. |

---

## BRLight

`shared/BR/lights.py`

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | |
| `blender_type` | `str` | `'POINT'` / `'SUN'` / `'SPOT'`. Ambient lights become `'POINT'` with zero energy plus `is_ambient=True`. |
| `color` | `tuple[float, float, float]` | **Linear** RGB — Plan applied sRGB conversion. |
| `energy` | `float` | 0.0 for ambient. |
| `location` | `tuple[float, float, float] \| None` | Blender Z-up space — Plan applied the Y-up→Z-up rotation `(x, y, z) → (x, -z, y)`. |
| `target_location` | `tuple[float, float, float] \| None` | Same space. If set, build creates a target empty and adds a `TRACK_TO` constraint. |
| `is_ambient` | `bool` | Triggers `lamp["dat_light_type"] = "AMBIENT"` stamp on the build side. |

---

## BRCamera

`shared/BR/cameras.py`

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | |
| `projection` | `str` | `'PERSP'` / `'ORTHO'`. |
| `lens` | `float` | For `'PERSP'`: focal length in mm (Plan converts from vertical FOV via `sensor_height / (2·tan(fov/2))`). For `'ORTHO'`: ortho_scale. |
| `sensor_height` | `float` | `18.0` mm — Plan's constant, mirrors the old build-phase value. |
| `clip_start` / `clip_end` | `float` | |
| `aspect` | `float` | Written to `cam_obj["dat_camera_aspect"]`. |
| `location` | `tuple[float, float, float] \| None` | Blender Z-up. |
| `target_location` | `tuple[float, float, float] \| None` | Blender Z-up. |
| `animations` | `list[BRCameraAnimation]` | |

### BRCameraAnimation

Keyframes are already in Blender space — Plan applies coord flips and FOV→lens to every keyframe value.

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | |
| `loc_x` / `loc_y` / `loc_z` | `list[IRKeyframe]` | IR `eye_z` → BR `loc_y` with sign flip; IR `eye_y` → BR `loc_z`. |
| `roll` | `list[IRKeyframe]` | Writes to `rotation_euler[2]`. |
| `lens` | `list[IRKeyframe]` | Per-keyframe FOV→lens conversion already applied. |
| `clip_start` / `clip_end` | `list[IRKeyframe]` | |
| `target_loc_x` / `_y` / `_z` | `list[IRKeyframe]` | Same coord-flip rules as eye position. |
| `end_frame` | `float` | |
| `loop` | `bool` | |

---

## BRConstraints

`shared/BR/constraints.py`

Pass-through wrapper — the IR constraint dataclasses already mirror Blender's constraint API (target_bone, track_axis, owner_space, etc.) one-to-one, so this wrapper exists purely to satisfy the architectural boundary. No reinterpretation happens.

| Field | Type | Notes |
|---|---|---|
| `ik` | `list` | `IRIKConstraint` instances. |
| `copy_location` | `list` | |
| `track_to` | `list` | |
| `copy_rotation` | `list` | |
| `limit_rotation` | `list` | |
| `limit_location` | `list` | |

Helpers: `is_empty` (bool) and `total` (int) are computed from field lengths.

## BRParticleSummary

| Field | Type | Notes |
|---|---|---|
| `generator_count` | `int` | |
| `texture_count` | `int` | |

Build writes these to `armature["dat_particle_gen_count"]` / `["dat_particle_tex_count"]`. Full particle instantiation awaits the generator→bone binding mechanism research (see `importer/phases/build_blender/helpers/particles.py` header note).

---

## Invariants

These are enforceable dependency / purity rules. Grep-auditable.

- No `import bpy`, `import mathutils`, or `from bpy` / `from mathutils` anywhere under `shared/BR/` or `importer/phases/plan/`.
- No `from shared.IR` or `import shared.IR` under `importer/phases/build_blender/` on the planned path (material_animations is a helper library carrying IRKeyframe values through unchanged and is exempt).
- No `from shared.IR` or `import shared.IR` under `shared/BR/`.
- `BRNode.properties` keys must be valid bpy node attribute names, with two special cases: `_output_default` (for RGB/Value nodes that store their constant on an output socket).
- `BRNode.node_type` must be a valid Blender bl_idname.
- `BRBone.inherit_scale`, `BRArmature.display_type`, `BRBone.rotation_mode`, `BRLight.blender_type`, `BRCamera.projection`, `BRMaterial.blend_method` — all must be Blender's own enum strings as consumed by `setattr` on the corresponding bpy object.

---

## Adding new BR types

When a new stage moves from IR-direct to BR:

1. Add the dataclass(es) under `shared/BR/`. Keep field types plain Python. Blender enums as strings.
2. Add a Plan helper under `importer/phases/plan/helpers/` that takes IR input and returns the BR dataclass. Pure — no bpy.
3. Wire it into `plan_scene` in `importer/phases/plan/plan.py`.
4. Rewrite the matching `build_blender/helpers/` function to consume the BR dataclass. Remove its IR import.
5. Add a column to this spec.
6. Add unit tests under `tests/test_plan_<thing>.py` using in-memory IR fixtures.
