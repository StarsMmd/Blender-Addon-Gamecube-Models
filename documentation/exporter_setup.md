# Exporter Setup

> **Status:** Work in progress — skeleton, mesh (including envelope skinning), material, texture, animation, constraint, light, and camera export functional. Supports both re-exported game models and arbitrary Blender models. In-game loading verified for re-exported models (BNB and NIN paths). Arbitrary models load in-game without crashing but need weight optimization tuning for visual quality.

The exporter writes a Blender scene to a `.dat` or `.pkx` binary that can be used in Pokemon Colosseum or Pokemon XD: Gale of Darkness. The output is not directly compatible with other games that use `.dat` models (e.g. Super Smash Bros. Melee).

**Important:** The exporter exports the **entire Blender scene**, not just selected objects. All armatures, their parented meshes, lights, and cameras in the scene are included in the output.

---

## Quick Start

1. [**Check compatibility**](#1-feature-compatibility) — confirm the exporter supports the Blender features your scene uses.
2. [**Scale and prepare the scene**](#2-scene-preparation--model-scale) — delete unwanted objects, scale your model to the correct size.
3. [**Run the preparation script**](#3-preparation-script) — run `scripts/prepare_for_export.py` to set up camera, lights, weights, textures, and PKX metadata.
4. [**Edit export properties**](#4-export-properties) — assign animations to PKX slots, adjust camera, set species ID.
5. [**Run the script again**](#5-refine-and-re-run) — re-run to auto-derive animation timing from your slot assignments.
6. [**Export**](#6-export) — File > Export > Gamecube model (.dat or .pkx).

---

## 1. Feature Compatibility

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
| Light (AMBIENT) | ✅ Exported | POINT light with `dat_light_type = "AMBIENT"` and `energy = 0` |
| Light (AREA) | ❌ Ignored | No GameCube equivalent |
| Empty | ❌ Ignored | Used internally as camera/light targets |
| Curves / Text / Volumes | ❌ Ignored | Convert to mesh first |

### Mesh data

| Blender feature | Export support | Notes |
|---|---|---|
| Vertices / Faces | ✅ Exported | Triangulated on export |
| Normals | ✅ Exported | Per-vertex normals |
| UV maps | ✅ Exported | Up to 8 UV layers (GX limit) |
| Vertex colors | ✅ Exported | FLOAT_COLOR attribute layers |
| Custom split normals | ✅ Exported | Read from mesh loops |
| Multi-material meshes | ✅ Auto-split | Automatically split per material slot on export |
| Shape keys | ❌ Not yet | |

### Skinning

| Blender feature | Export support | Notes |
|---|---|---|
| Vertex groups (multi-bone) | ✅ Envelope | The preparation script limits to 2 influences and quantizes to 10% steps |
| Vertex groups (single bone) | ✅ Single-bone | All verts in one group |
| No vertex groups | ✅ Rigid | Bound to parent bone |
| Armature modifier | ✅ Required | Must be present for skinning |

### Animations

| Blender feature | Export support | Notes |
|---|---|---|
| Bone actions (loc/rot/scale) | ✅ Exported | Euler and quaternion rotation supported |
| Material color/alpha actions | ✅ Exported | Animated material properties |
| Texture UV scroll/scale | ✅ Exported | Animated texture offset and scale |
| NLA strips | ✅ Read | Actions referenced by NLA are exported |
| Shape key actions | ❌ Not yet | |
| Camera animations | ❌ Not yet | Static camera only |
| Drivers | ❌ Ignored | Bake to keyframes first |

### Materials

| Blender feature | Export support | Notes |
|---|---|---|
| Principled BSDF base color | ✅ Exported | Diffuse color |
| Principled BSDF specular tint | ✅ Exported | Reverse-mapped to absolute specular color |
| Principled BSDF alpha | ✅ Exported | Material transparency |
| Image textures | ✅ Exported | All GX formats; auto-selected or set via `dat_gx_format` |
| `dat_ambient_emission` node | ✅ Exported | Per-material ambient color |
| Shiny filter nodes | ⏭️ Skipped | See [Shiny Filter](#shiny-filter) in notes |
| Procedural textures | ❌ Ignored | Bake to image first |
| Node groups (custom) | ❌ Ignored | Only named nodes recognized by the exporter are read |

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

## 2. Scene Preparation & Model Scale

### Clean up the scene

Delete any objects that should not be part of the model:

- **Default Cube** — delete it (`X` key)
- **Default Light** — delete it (the preparation script adds proper battle lights)
- **Default Camera** — delete it (the preparation script creates a `Battle_Camera`)

Only armatures and their parented meshes should remain, plus any lights and cameras you intentionally want in the game model.

**Overworld / standalone `.dat` models:** Delete or hide all lights after running the preparation script. Overworld models don't include their own lighting — it comes from the map scene. Hidden lights and cameras are automatically skipped by the exporter.

### Scale the model

The plugin uses real-world meters (matching Blender's default 1 unit = 1 meter). Scale your model to match the Pokémon's official dimensions:

1. Select the armature and press **N** to open the sidebar
2. In the **Item** tab, check the **Dimensions** values (X, Y, Z in meters)
3. Look up the Pokémon's official height (e.g. from Bulbapedia)
4. Scale the model so its **Z dimension** (height) matches the official height in meters
5. To scale: select the armature, press **S**, type the scale factor, press **Enter**

**Do not apply the scale** (`Ctrl+A`) — the exporter reads the armature's object scale and applies it automatically to bone positions, vertex positions, and animation values.

**Notes:**
- For serpentine/elongated Pokémon (e.g. Gyarados, Rayquaza), the official "height" is body length — use the **Y dimension** instead of Z
- Models imported from the game are already in meters but may not match official heights exactly
- For a visual reference, try importing an existing game model of a similar-sized Pokémon and comparing side by side

### GameCube constraints

The GameCube has limited memory (~24 MB shared). The preparation script optimizes models automatically, but manual optimization gives better results:

- **Bone weights:** The script limits to **2 influences per vertex** and quantizes to **10% steps** (matching game model precision). For higher quality, manually paint weights with discrete values (0.1, 0.2, ..., 1.0). Fewer unique weight combinations = smaller exported file.
- **Mesh splitting:** For best results, **split your model into separate body parts** (head, torso, arms, legs) before running the script. Game models use 12-20 separate mesh objects, each referencing only a few bones. This is the single most effective optimization.
- **Polygon count:** Up to ~10,000 faces is fine (Dark Lugia has 10,266). The poly count is rarely the bottleneck — bone weight complexity is.
- **Target file size:** Game Pokémon models range from 65-430 KB. Aim for under 500 KB.

---

## 3. Preparation Script

For models **not** imported through the DAT plugin, run **`scripts/prepare_for_export.py`** from Blender's Scripting panel:

1. Open the Scripting workspace
2. Open `scripts/prepare_for_export.py`
3. Click **Run Script**

The script:
- Creates a `Battle_Camera` with target empty
- Limits vertex bone weights to 2 per vertex and quantizes to 10% steps
- Sets up all 4 standard battle lights (ambient + 3 directional SUN)
- Auto-selects GX texture formats based on image content
- Applies default PKX metadata (species ID, animation slots, shiny params, body map)
- Inserts shiny filter preview nodes into all materials

Models imported through the DAT plugin already have these properties set.

---

## 4. Export Properties

These are custom properties the exporter reads from Blender objects. The [preparation script](#3-preparation-script) sets defaults for all of them.

### Camera

Every PKX model requires exactly **1 camera** named `Battle_Camera`. The preparation script creates one automatically.

| Setting | Value | Notes |
|---|---|---|
| Type | Perspective | Orthographic is not used by battle models |
| `dat_camera_aspect` | `1.18` | Standard battle viewport ratio |
| Near clip | `0.1` | |
| Far clip | `32768.0` | |

**FOV (lens)** varies by model size:

| Model size | Lens (mm) | Examples |
|---|---|---|
| Small | 24-34 | Eevee, Roselia |
| Medium | 37.5 | Most Pokémon (default) |
| Large | 46-60 | Deoxys, Rayquaza |
| Very large | 100-300+ | Kairyu, Houou |

**Adjusting the camera:** The script places the camera in front of the model at 2.5× the model's height. Select `Battle_Camera_target` and move it to adjust focus. Select `Battle_Camera` to adjust distance. Press **Numpad 0** to preview.

### Lighting

The game expects **4 lights** for battle models. The preparation script creates these automatically:

| Light | Type | Color (u8) | Purpose |
|---|---|---|---|
| Ambient | POINT (energy=0) | (76, 76, 76) | Scene-level fill |
| Main | SUN | (204, 204, 204) | Primary key light |
| Fill | SUN | (102, 102, 102) | Side fill |
| Back | SUN | (76, 76, 76) | Rim/back light |

Adjust the ambient light's color for more contrast (darker) or softer look (lighter).

### PKX metadata (armature properties)

Only needed for `.pkx` exports. Set these in the **PKX Metadata** panel on the armature.

| Property | Default | Description |
|---|---|---|
| `dat_pkx_format` | `"XD"` | Target game (`"XD"` or `"COLOSSEUM"`) |
| `dat_pkx_species_id` | `0` | Pokédex number |
| `dat_pkx_model_type` | `"POKEMON"` | `"POKEMON"` or `"TRAINER"` |
| `dat_pkx_head_bone` | _(auto-detected)_ | Head bone for camera targeting and head tracking |
| `dat_pkx_anim_NN_type` | `"action"` | Slot type: `"loop"`, `"action"`, `"hit_reaction"`, `"compound"` |
| `dat_pkx_anim_NN_sub_0_anim` | `""` | Blender Action name for this slot |
| `dat_pkx_shiny_route_r/g/b/a` | `0/1/2/3` | Shiny color channel routing (identity = no change) |
| `dat_pkx_shiny_brightness_r/g/b` | `0.0` | Shiny brightness offset per channel [-1.0, 1.0] |
| `dat_pkx_flag_flying` | `False` | Model floats above ground |

See the PKX Metadata panel for all properties including body map, timing, sub-animations, and distortion.

### Body map

The game uses 16 named bone slots for particle attachment, camera targeting, and head tracking. Set these in the **Body Map** section of the PKX Metadata panel.

| Slot | What to assign |
|------|----------------|
| Root | Root bone (always bone 0) |
| Head | Head bone — used for head tracking |
| Center | Center of mass — fallback attachment point |
| Neck | Neck bone — typically parent of Head |
| Head Top | Top of head — status effect particles (sleep Z's, confusion) |
| Limb Left/Right | Arm/wing/fin endpoints (from Pokémon's perspective) |
| Attach A-D | Effect attachment points (tail tip, horn, mouth) |

The script auto-fills Root and Head. Leave other slots empty if unknown.

---

## 5. Refine and Re-run

After the first script run:

1. **Assign animations:** In the PKX Metadata panel, assign Blender Actions to each animation slot (Idle, Physical, Special, Damage, Faint, etc.) using the action search dropdowns.
2. **Run the script again** — it auto-derives timing values (wind-up, hit, duration) from the assigned action durations.
3. **Fine-tune** timing values, camera position/FOV, body map bones, and shiny parameters as needed.

---

## 6. Export

**File > Export > Gamecube model (.dat)**

Choose the output file location and set the file extension:
- **`.dat`** — standalone model file
- **`.pkx`** — PKX container with game metadata (species ID, animation slots, shiny params). Built from scratch using the PKX metadata set via the preparation script.

---

## Notes

### Bone visibility

Hidden bones in Blender are exported as hidden bones in the DAT file.

### Mesh-to-bone binding

Each mesh must be parented to the armature. Bone assignments are determined from vertex groups:
- **Weighted skinning**: vertex groups assigned to multiple bones
- **Single-bone binding**: all vertices in one bone's group
- **No vertex groups**: bound to the root bone

### Ambient lighting

Per-material ambient color is read from a `dat_ambient_emission` Emission node. Use `scripts/add_ambient_lighting.py` to add these to all materials. Default: (0.5, 0.5, 0.5).

### Specular color

Computed automatically from Principled BSDF Specular Tint and diffuse color. No manual setup needed.

### Bound boxes

Generated automatically from mesh vertices. Each animation slot gets an axis-aligned bounding box.

### Shiny filter

The importer (or `scripts/add_shiny_filter.py`) inserts preview nodes into materials for the shiny variant. These are **not part of the model data** — the exporter skips them automatically. Shiny parameters are exported as PKX metadata.

---

## How to Use the New Model in Game

> This section is a work in progress.

For guidance on replacing model files in a game ISO, visit the community Discord: www.discord.gg/xCPjjnv
