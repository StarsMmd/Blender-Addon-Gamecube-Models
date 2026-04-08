# Exporter Setup

> **Status:** Work in progress — skeleton, mesh (including envelope skinning), material, texture, animation, constraint, light, and camera export functional. In-game loading verified (BNB and NIN paths produce correct results; IBI path has known mesh-bone assignment issues).

The exporter writes a Blender scene to a `.dat` or `.pkx` binary that can be used in Pokemon Colosseum or Pokemon XD: Gale of Darkness. The output is not directly compatible with other games that use `.dat` models (e.g. Super Smash Bros. Melee).

**Important:** The exporter exports the **entire Blender scene**, not just selected objects. All armatures, their parented meshes, lights, and cameras in the scene are included in the output.

---

## Quick Start

1. **Check compatibility** — review the [feature compatibility table](#feature-compatibility) to confirm the exporter supports the Blender features your scene uses.
2. **Prepare the scene** — if the model was **not** imported through the DAT plugin, run [`scripts/prepare_for_export.py`](#preparation-script) to add required custom properties. Delete any unwanted objects (default cube, extra lights/cameras).
3. **Review export properties** — check the [custom properties](#export-properties) on your armature and cameras. Set species ID, animation mappings, and camera aspect as needed.
4. **Export** — **File > Export > Gamecube model (.dat)**. Choose the output file location and set the file extension to `.dat` or `.pkx`. If no extension is specified, the exporter defaults to `.dat`.
   - **`.dat`** — standalone model file, can be created from scratch
   - **`.pkx`** — PKX container; requires an existing `.pkx` at the output path (the exporter injects the new model into the existing container)

---

## Feature Compatibility

What the exporter can and cannot read from your Blender scene.

### Scene objects

| Blender feature | Export support | Notes |
|---|---|---|
| Armature | ✅ Exported | Each armature becomes one model in the DAT file |
| Mesh (parented to armature) | ✅ Exported | Must be parented to an armature |
| Mesh (not parented) | ❌ Ignored | Parent it to an armature first |
| Camera (PERSP) | ✅ Exported | Position, FOV, clip planes, target (via TRACK_TO constraint) |
| Camera (ORTHO) | ✅ Exported | Ortho scale exported as FOV field |
| Camera (PANO) | ❌ Ignored | No GameCube equivalent |
| Light (SUN) | ✅ Exported | Color + direction + brightness |
| Light (POINT) | ✅ Exported | Color + position |
| Light (SPOT) | ✅ Exported | Color + position + target |
| Light (AMBIENT) | ✅ Exported | POINT light with `dat_light_type = "AMBIENT"` custom property and `energy = 0`. No visible effect in Blender — controls scene-level fill lighting in-game |
| Light (AREA) | ❌ Ignored | No GameCube equivalent |
| Empty | ❌ Ignored | Used internally as camera/light targets, not exported as objects |
| Curves / Text / Volumes | ❌ Ignored | Convert to mesh first if needed |

### Mesh data

| Blender feature | Export support | Notes |
|---|---|---|
| Vertices / Faces | ✅ Exported | Triangulated on export |
| Normals | ✅ Exported | Per-vertex normals |
| UV maps | ✅ Exported | Up to 8 UV layers (GX limit) |
| Vertex colors | ✅ Exported | FLOAT_COLOR attribute layers |
| Shape keys | ❌ Not yet | Shape animation stubs only |
| Custom split normals | ✅ Exported | Read from mesh loops |

### Skinning

| Blender feature | Export support | Notes |
|---|---|---|
| Vertex groups (multi-bone) | ✅ Envelope | Weighted/envelope skinning |
| Vertex groups (single bone) | ✅ Single-bone | All verts in one group |
| No vertex groups | ✅ Rigid | Bound to parent bone |
| Armature modifier | ✅ Required | Must be present for skinning |

### Materials

| Blender feature | Export support | Notes |
|---|---|---|
| Principled BSDF base color | ✅ Exported | Diffuse color |
| Principled BSDF specular tint | ✅ Exported | Reverse-mapped to absolute specular color |
| Principled BSDF alpha | ✅ Exported | Material transparency |
| Image textures | ✅ Exported | All GX formats supported. Format auto-selected by `prepare_for_export` or set manually via `dat_gx_format` on each image |
| `dat_ambient_emission` node | ✅ Exported | Per-material ambient color |
| Shiny filter nodes | ⏭️ Skipped | See [Shiny Filter](#shiny-filter) below |
| Procedural textures | ❌ Ignored | Bake to image first |
| Multiple materials per mesh | ✅ Exported | Split into separate display lists |
| Node groups (custom) | ❌ Ignored | Only named nodes recognized by the exporter are read |

### Animations

| Blender feature | Export support | Notes |
|---|---|---|
| Bone actions (loc/rot/scale) | ✅ Exported | Keyframed bone transforms |
| Material color/alpha actions | ✅ Exported | Animated material properties |
| Texture UV scroll/scale | ✅ Exported | Animated texture offset and scale |
| Shape key actions | ❌ Not yet | |
| Camera animations | ❌ Not yet | Static camera only |
| NLA strips | ✅ Read | Actions referenced by NLA are exported |
| Drivers | ❌ Ignored | Bake to keyframes first |

### Constraints

| Blender feature | Export support | Notes |
|---|---|---|
| Inverse Kinematics (IK) | ✅ Exported | Chain length + pole target |
| Copy Location | ✅ Exported | |
| Copy Rotation | ✅ Exported | |
| Track To | ✅ Exported | |
| Limit Rotation | ✅ Exported | Min/max per axis |
| Limit Location | ✅ Exported | Min/max per axis |
| Other constraints | ❌ Ignored | No GameCube equivalent |

---

## Preparation Script

Before exporting a model that was **not** imported through the DAT plugin (i.e. built from scratch or imported from another format), run **`scripts/prepare_for_export.py`** from Blender's Scripting panel. The script only adds properties that don't already exist.

1. Open the Scripting workspace
2. Open `scripts/prepare_for_export.py`
3. Click **Run Script**

The script operates on all objects in the scene — no selection required.

---

## Scene Preparation

Delete any objects that should not be part of the model. Blender's default scene includes objects that will cause issues if left in:

- **Default Cube** — delete it (`X` key)
- **Default Light** — delete it (the exporter will include it as a game light, which may not be desired). The `prepare_for_export` script adds a proper ambient light automatically
- **Default Camera** — delete it if you don't want it in the game model, or keep it and set `dat_camera_aspect`

Only armatures and their parented meshes should remain in the scene, plus any lights and cameras you intentionally want in the game model.

---

## Model Scale

The plugin uses real-world meters for all positions (matching Blender's default 1 unit = 1 meter). Before exporting, ensure your model is scaled to match the Pokémon's official dimensions:

1. Select the armature and press **N** to open the sidebar
2. In the **Item** tab, check the **Dimensions** values (X, Y, Z in meters)
3. Look up the Pokémon's official height (e.g. from Bulbapedia)
4. Scale the model so its **Z dimension** (height) matches the official height in meters
5. To scale: select the armature, press **S** then **Z**, type the scale factor, press **Enter**
   - Or type the desired value directly into the Z Dimensions field in the N-panel

**Notes:**
- For serpentine/elongated Pokémon (e.g. Gyarados, Rayquaza), the official "height" is body length — use the **Y dimension** instead of Z
- Coiled or curled poses will appear shorter than the official stretched-out measurement — this is expected
- Some Pokémon (e.g. those with long tails, wings, or unusual poses) may not fit neatly to a single axis — use your judgment on the overall scale rather than trying to match a specific dimension exactly
- Models imported from the game are already in meters but may not match official heights exactly (game models are artist-scaled for visual appeal in battle)

---

## Export Properties

These are custom properties the exporter reads from Blender objects. The [preparation script](#preparation-script) sets defaults for all of them. On models imported through the DAT plugin, they are already set.

### Camera properties

Every PKX model requires exactly **1 camera** named `Battle_Camera` for the default battle framing. The [preparation script](#preparation-script) creates one automatically. All game models use these constant values:

| Setting | Value | Notes |
|---|---|---|
| Type | Perspective | Orthographic is not used by battle models |
| `dat_camera_aspect` | `1.18` | Standard battle viewport ratio. Use 1.333 for fullscreen/map cameras |
| Near clip | `0.1` | |
| Far clip | `32768.0` | |

**FOV (lens)** varies by model size. Adjust the camera's focal length in Blender:

| Model size | Lens (mm) | Vertical FOV | Examples |
|---|---|---|---|
| Small | 24-34 | 30-40° | Eevee, Roselia, Hinoarashi |
| Medium | 37.5 | 27° | Most Pokémon (default) |
| Large | 46-60 | 17-22° | Deoxys, Rayquaza, trainers |
| Very large | 100-300+ | 3-10° | Kairyu, Houou, Lizardon |

Camera position, FOV, and clip planes are read directly from Blender's camera settings. Camera target is read from a TRACK_TO constraint pointing at `Battle_Camera_target`.

### Scene lights

The exporter reads all light objects in the scene. Each light becomes a separate LightSet in the DAT file. Colosseum/XD models typically have 1 ambient light + 3 directional (SUN) lights.

**Ambient lights** are represented in Blender as POINT lights with `energy = 0` and a `dat_light_type = "AMBIENT"` custom property. They have no visible effect in Blender — their color controls scene-level fill lighting in-game, applied uniformly to all materials.

| Property | Set on | Default | Description |
|---|---|---|---|
| `dat_light_type` | Light objects | _(not set)_ | Set to `"AMBIENT"` to mark a light as an ambient light. The `prepare_for_export` script adds one automatically. |

**Choosing an ambient color:**
- The ambient color acts as a minimum brightness floor for all surfaces in the scene
- Lower values (darker gray like `0.1, 0.1, 0.1`) produce more contrast and deeper shadows
- Higher values (lighter gray like `0.5, 0.5, 0.5`) produce a flatter, softer look with less shadow contrast
- Most Pokémon models use `(0.3, 0.3, 0.3)` (= 76/255 per channel). Some special models use black `(0, 0, 0)` for full contrast
- The ambient light is sorted first (LightSet[0]) in the exported file, matching the standard Colo/XD convention

SUN, POINT, and SPOT lights export their Blender color (de-linearized to sRGB), position, and `energy` value as brightness.

### PKX metadata (armature properties)

These are only needed when exporting to `.pkx` format. The preparation script sets them on the active armature if it doesn't already have `dat_pkx_format`.

| Property | Default | Description |
|---|---|---|
| `dat_pkx_format` | `"XD"` | Target game. Set to `"COLOSSEUM"` for Colosseum models. Affects animation entry format and sub-animation layout. |
| `dat_pkx_species_id` | `0` | Pokédex number. Set to the species' national dex ID (e.g. 291 for Shedinja). Used by the game to identify the model. |
| `dat_pkx_model_type` | `"POKEMON"` | Model category. `"POKEMON"` for Pokémon, change for trainer models. |
| `dat_pkx_head_bone` | _(auto-detected)_ | Name of the head bone. The script looks for bones with "head" in the name, then falls back to the first child of the root. Used for camera targeting and head tracking in battle. |
| `dat_pkx_body_*` | _(see below)_ | Body map bone mappings — see [Body Map](#body-map) for details. |
| `dat_pkx_anim_count` | `17` | Number of animation metadata entries. Standard Pokémon models use 17 (idle + 16 action slots). |
| `dat_pkx_anim_00_type` | `"loop"` | Animation slot 0 type. Set to `"loop"` for idle animation. Other slots default to `"action"`. Valid types: `"loop"`, `"hit_reaction"`, `"action"`, `"compound"`. |
| `dat_pkx_anim_NN_sub_0_anim` | `""` | Blender Action name for slot N. Maps PKX animation slots to actions by name (resolved to DAT indices at export time). Use the action search dropdown in the PKX Metadata panel to set this. |
| `dat_pkx_anim_NN_sub_count` | `1` | Number of sub-animations per slot. Usually 1. |
| `dat_pkx_anim_NN_damage_flags` | `0` | Bit flags for hit reaction behavior. Only relevant for `"hit_reaction"` type entries. |
| `dat_pkx_anim_NN_timing_1` … `_4` | `0.0` | Timing parameters (seconds). Control animation blend/transition timing. The `prepare_for_export` script auto-derives these from action durations: action types use 33%/66%/100% splits for wind-up/hit/duration; re-run the script after assigning actions to update. |
| `dat_pkx_shiny_route_r/g/b/a` | `0/1/2/3` | Shiny color channel routing. Identity mapping (no color change). The Shiny Variant section appears in the PKX Metadata panel when these differ from identity. |
| `dat_pkx_shiny_brightness_r/g/b` | `0.0` | Shiny brightness offset per channel. 0.0 = no change, positive = brighter, negative = darker. Range [-1.0, 1.0]. |
| `dat_pkx_sub_anim_N_type` | `"none"` | Sub-animation type (sleep on/off, extra). `"none"` = inactive, `"simple"` = basic, `"targeted"` = bone-targeted. |
| `dat_pkx_flag_flying` | `False` | Model floats above ground in battle. |
| `dat_pkx_flag_skip_frac_frames` | `False` | Skip fractional frame interpolation. |
| `dat_pkx_flag_no_root_anim` | `False` | Disable root bone animation playback. |
| `dat_pkx_particle_orientation` | `0` | Default particle emission orientation. |
| `dat_pkx_distortion_param` | `0` | Screen distortion effect parameter. |
| `dat_pkx_distortion_type` | `0` | Screen distortion effect type. |

---

## Body Map

The game uses 16 named bone slots per model for particle attachment, camera targeting, hit detection, and head tracking. Set these in the **Body Map** section of the PKX Metadata panel using the bone name dropdowns. Right/left are from the **Pokémon's perspective**, not the viewer's.

| Slot | Property suffix | What to assign |
|------|----------------|----------------|
| Root | `_root` | The root bone of the armature (always bone 0) |
| Head | `_head` | The head bone — used for head tracking in battle (the game rotates this bone to follow the opponent) |
| Center | `_center` | A bone at the model's center of mass — fallback attachment point for effects |
| Body 3 | `_body_3` | Generic body attachment point (torso/chest area) |
| Neck | `_neck` | Neck bone — typically the parent of the head bone |
| Head Top | `_head_top` | Top of head — typically a child of the head bone. Used for status effect particles (sleep Z's, confusion stars) |
| Limb Left | `_limb_a` | Left arm/wing/fin endpoint (from the Pokémon's perspective) |
| Limb Right | `_limb_b` | Right arm/wing/fin endpoint (from the Pokémon's perspective) |
| Secondary 8-11 | `_secondary_8` … `_11` | Less commonly used attachment points. Leave empty if unknown |
| Attach A-D | `_attach_a` … `_d` | Particle and effect attachment points (e.g. tail tip, horn, mouth). Used by battle move particle effects |

**Tips:**
- The preparation script auto-fills Root and Head. Everything else defaults to empty.
- Leave slots empty if your model doesn't have an obvious bone for that role — the game falls back gracefully.
- For simple models, filling Root, Head, Center, and Neck is usually sufficient.
- Imported models from the game already have all slots filled correctly.

---

## Other Export Settings

### Bone Visibility

Hidden bones in Blender are exported as hidden bones in the DAT file. Toggle bone visibility in the armature to control this.

### Mesh-to-Bone Binding

Each mesh must be parented to the armature. Bone assignments are determined from vertex groups:

- **Weighted skinning**: Meshes with vertex groups assigned to multiple bones
- **Single-bone binding**: Meshes where all vertices belong to one bone's vertex group
- **No vertex groups**: Meshes with no vertex groups are bound to the root bone

### Ambient Lighting

The game uses per-material ambient colors to control how materials respond to ambient light. In Blender, this is approximated with an Emission node.

To set up ambient lighting for export:
1. Add an Emission node named `dat_ambient_emission` to the material
2. Set its Color to the desired ambient color
3. Add an Add Shader node named `dat_ambient_add` to mix it with the main shader
4. Connect: `main_shader → Add Shader input 0`, `Emission → Add Shader input 1`, `Add Shader → Material Output`

The exporter reads the ambient color from the `dat_ambient_emission` node. If no such node exists, a default of (0.5, 0.5, 0.5) is used.

Use the standalone script `scripts/add_ambient_lighting.py` to add ambient nodes to all materials at once.

### Specular Color

The exporter computes the specular color from Blender's Principled BSDF Specular Tint and diffuse color. No manual setup is needed — the exporter reads the Specular Tint value and reverse-maps it to the game's absolute specular color.

### Model Scale

_TODO: Document recommended model scale for in-game use. What units does the game expect? How tall should a typical Pokémon be in Blender units? How does model scale interact with the camera, battle stage, and particle effects? Include reference measurements from existing models._

### Base Model

_WIP_

### Bound Boxes

Bound boxes are generated automatically from the model's mesh vertices. Each animation slot gets an axis-aligned bounding box (AABB) encompassing the full model extent.

### Shiny Filter

The importer (or the `scripts/add_shiny_filter.py` script) inserts four shader nodes into each material to preview the Pokémon's shiny coloring in the viewport:

- `shiny_route_shader` / `shiny_route_mix` — channel swizzle (which color channels map to which)
- `shiny_bright_shader` / `shiny_bright_mix` — per-channel brightness adjustment

These nodes are **not part of the model data** — they are a viewport preview of parameters stored in the PKX header. The exporter automatically skips them when reading materials back. The shiny parameters themselves are exported as PKX metadata from the `dat_pkx_shiny_route_*` and `dat_pkx_shiny_brightness_*` properties on the armature (see [PKX metadata](#pkx-metadata-armature-properties)).

---

## How to Use the New Model in Game

> This section is a work in progress.

For guidance on replacing model files in a game ISO, visit the community Discord: www.discord.gg/xCPjjnv
