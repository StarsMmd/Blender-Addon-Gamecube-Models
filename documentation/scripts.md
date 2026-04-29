# Standalone Scripts

Standalone Blender scripts that can be run from Blender's built-in text editor. These operate independently of the import pipeline and can be used on any model in a Blender scene.

All scripts require the DAT plugin addon to be enabled, since they depend on registered properties and UI panels from `BlenderPlugin.py`.

## How to Run a Script in Blender

1. Switch to the **Scripting** workspace (tabs at the top of the Blender window), or open a **Text Editor** area in any workspace
2. Click **Open** in the Text Editor header and navigate to the script file inside the `scripts/` folder
3. Click **Run Script** (play button icon) or press **Alt+P** with the cursor in the Text Editor
4. Check the **System Console** (Window > Toggle System Console on Windows, or launch Blender from a terminal on macOS/Linux) for any output or error messages

---

## add_shiny_filter.py

**Purpose:** Add a shiny color filter to any armature, including models that weren't imported from PKX files or that had default (unchanged) shiny parameters.

**Usage:**
1. Select an armature in the viewport
2. Open the Scripting workspace (or any Text Editor area)
3. Open `scripts/add_shiny_filter.py`
4. Click **Run Script**

**What it does:**
- Creates a `ShinyFilter_{armature_name}` node group with default parameters (no visible change)
- Inserts the filter into every material on the armature's child meshes
- Sets up the `dat_pkx_shiny` properties on the armature so the Shiny Variant panel appears
- Skips materials that already have a `shiny_filter_shader` node to avoid duplicates

**Initial parameters:**
- Channel routing: R→Red, G→Green, B→Blue, A→Alpha (each channel maps to itself)
- Brightness: 0.0 for all channels (no change)

After running, use the **Shiny Variant** panel in Object Properties to tweak parameters and toggle the filter on/off.

**Use cases:**
- Adding shiny colors to models before exporting
- Experimenting with color filters on models that don't have PKX shiny metadata
- Previewing how different shiny parameters would look on any model

**Errors:**
- "Select an armature object" — no armature is selected
- "Already has a shiny filter" — the armature already has shiny data (edit existing parameters instead)
- "DAT plugin addon must be enabled" — the addon isn't active, so shiny properties aren't registered

---

## remove_shiny_filter.py

**Purpose:** Strip every DAT shiny filter node from the file so the filter can be reapplied from scratch (e.g. after updating `add_shiny_filter.py` or the in-plugin shiny code).

**Usage:**
1. Open the Scripting workspace (or any Text Editor area)
2. Open `scripts/remove_shiny_filter.py`
3. Click **Run Script**

**What it does:**
- Removes the per-material shiny nodes (`shiny_route_shader`, `shiny_route_mix`, `shiny_bright_shader`, `shiny_bright_mix`) from every material in the file
- Reconnects each removed mix node's "normal path" input to whatever the mix was driving, so the underlying material wiring is restored
- Removes drivers on the mix Factor inputs first to avoid stale dependencies
- Deletes the shared `DATPlugin_ShinyRoute` and `DATPlugin_ShinyBright` node groups
- Leaves the armature's `dat_pkx_shiny*` properties untouched — reapply the filter to use them again
- Prints a one-line summary of how many nodes/materials/groups were touched

---

## prepare_for_export.py

**Purpose:** Prepare a Blender scene for Colosseum/XD export. Adds custom properties the exporter needs on cameras, armatures, and lights. Operates on all objects in the scene — no selection required. Only adds properties that don't already exist — not needed on models that were imported through the DAT plugin.

> **Scope of its optimisations:** prep applies only the optimisations needed to land within the game's **hard** limits — texture size ≤ 512×512, ≤ 3 bone weights per vertex, 10 % weight quantisation. It will not shrink a model beyond that. If the exported file is still too large, or the target is a heavier newer-game rip, reach for `optimize.py` (or the individual `optimize/*.py` passes) first — those are lossier but more aggressive (polycount decimation, 256 px textures, keyframe thinning, vertex merging).

**Usage:**
1. Open the Scripting workspace
2. Open `scripts/prepare_for_export.py`
3. Click **Run Script**

**What it does:**
1. **Bakes loc/rot/scale** on every armature and its child meshes via Blender's `transform_apply`, so each `matrix_world` is identity. The exporter rejects any armature or child mesh whose `matrix_world` is not identity — without this, the bone path's SRT decompose drops shear introduced by non-uniform armature scale, while the vertex path's matmul keeps it, and the two drift apart further down the chain.
2. Creates a `Debug_Camera` with target if none exists, and sets `dat_camera_aspect` on all cameras (the camera section in a PKX appears to be unused by the game engine — see `exporter_setup.md` Camera section)
3. Applies default PKX metadata to the selected armature (if it doesn't already have it)
4. Auto-derives animation timing from action durations for any animation slot that has an action assigned. Uses even splits: action types get 33%/66%/100% for wind-up/hit/duration, loops get full duration, hit reactions get 50%/100%
5. Auto-selects GX texture formats for textures that don't have one set — analyzes each texture's pixel content and picks the most efficient format (CMPR, I8, C8, etc.). Skips textures that already have a format. The auto-selected format is usually optimal, but you can override it per-texture in the Image Editor's properties if needed
6. Adds an ambient light if none exists — creates a no-op POINT light with `energy=0` (no visible change in Blender) and `dat_light_type = "AMBIENT"`. The light's color controls scene-level fill lighting in-game. Lower values (darker gray) produce more contrast and deeper shadows; higher values (lighter gray) produce a flatter, softer look. Default is `(76, 76, 76)` — the most common ambient color across Pokémon models

**Tip:** After assigning actions to animation slots in the PKX Metadata panel, run the script again to auto-fill timing values based on the action durations. The script always re-derives timing for any slot with an action assigned.

See [Exporter Setup](exporter_setup.md) for a full reference of every property, what it does, and how to choose the right values.

---

## set_texture_formats.py

**Purpose:** Set the GX texture format on all textures of the selected armature. The exporter uses this property to determine which format to encode each texture in.

**Usage:**
1. Select an armature in the viewport
2. Open the Scripting workspace
3. Open `scripts/set_texture_formats.py`
4. Click **Run Script**

**What it does:**
- Finds all textures on the armature's child mesh materials
- Analyzes each texture's pixel content (grayscale, alpha, color count)
- Sets the `dat_gx_format` property to the recommended format
- Prints a summary showing each texture's dimensions, analysis, and selected format

**Formats:**
- **CMPR** — S3TC/DXT1 compressed (default for most textures)
- **I8** — 8-bit grayscale (for grayscale textures with alpha)
- **RGBA8** — full quality 32-bit RGBA
- **C4/C8** — palette-indexed (for textures with few unique colors)
- Other formats available via manual override in Blender's Image properties

The format can also be set manually per-texture by selecting the image in the Image Editor and changing the `dat_gx_format` dropdown in its properties.

---

## add_ambient_lighting.py

**Purpose:** Add ambient lighting nodes to all materials on the selected armature. The exporter reads the ambient color from these nodes when writing the DAT file.

**Usage:**
1. Select an armature in the viewport
2. Open the Scripting workspace
3. Open `scripts/add_ambient_lighting.py`
4. Click **Run Script**

**What it does:**
- For each material on the armature's child meshes:
  - Adds a `dat_ambient_emission` Emission node (default: mid-gray at 0.1 strength)
  - Adds a `dat_ambient_add` Add Shader node to mix the ambient with the main shader
  - Skips materials that already have ambient nodes
- Materials will appear slightly self-illuminated, approximating the game's per-material ambient lighting

**Adjusting ambient:**
- Select the material in the Shader Editor
- Find the `dat_ambient_emission` node
- Change the **Color** to set the ambient color
- Change the **Strength** to control how visible the ambient contribution is

**Errors:**
- "Select an armature object" — no armature is selected

---

## optimize.py

**Purpose:** Run every lossy optimisation pass in one go to shrink oversized models from newer games. Lossy — intended for rips/imports that are too heavy to fit the GameCube budget.

> **When to use:** `prepare_for_export.py` already enforces the game's hard limits (≤ 512×512 textures, ≤ 3 weights per vertex, 10 % weight quantisation). Reach for these scripts when prep isn't enough — e.g. when the exported file is too large, when the source is a newer-gen rip with dense geometry / long animations, or when you want a smaller in-memory footprint than the hardware ceiling. Run `optimize.py` before `prepare_for_export.py`; prep then picks up the already-optimised scene and adds the export-specific metadata.

**Usage:**
1. Open the Scripting workspace
2. Open `scripts/optimize.py`
3. Click **Run Script**

**What it does (in order):**
1. **Merge verts** — welds duplicate vertices within 0.0001 units on every mesh
2. **Polycount** — if the scene has more than 10 000 triangles, applies a DECIMATE modifier to every mesh at a ratio that brings the total down to the target
3. **Weights** — caps each vertex at 3 bone influences (drops lowest, re-normalises)
4. **Weight quantization** — rounds bone weights to 1/10 steps (matches game-model precision), normalises and rounds again to stay on the grid
5. **Textures** — downscales any image larger than 256×256 to the largest power of two that fits, preserving aspect ratio
6. **Keyframes** — on every F-curve, drops interior keys within 5 % of their neighbours' linear interp, then keeps every Nth remaining key (N = 2 → halves; 3 → thirds; 1 disables)

Tune the constants at the top of the file: `TARGET_TRIS`, `MAX_WEIGHTS_PER_VERTEX`, `QUANT_STEPS`, `MAX_TEX_DIM`, `MERGE_DISTANCE`, `KEYFRAME_ERROR_TOLERANCE`, `KEEP_EVERY_NTH_KEYFRAME`.

Each pass also ships as its own standalone script under `scripts/optimize/` for one-off use — constants at the top of each file.

---

## optimize/optimize_polycount.py

**Purpose:** Decimate all meshes in the scene down to a target triangle count (default 10 000). No-op if the scene is already at or below the target.

**Constants:** `TARGET_TRIS`

Meshes with shape keys are skipped (the DECIMATE modifier cannot apply to them).

---

## optimize/optimize_keyframes.py

**Purpose:** Thin out F-curve keyframes on every action. First pass drops keys within `ERROR_TOLERANCE` (5 % by default) of their neighbours' linear interp; second pass keeps every Nth remaining key. First and last keys are always preserved.

**Constants:** `ERROR_TOLERANCE`, `KEEP_EVERY_NTH_KEYFRAME` (default 2 — halve; set to 1 to disable, 3 for a third, etc.)

---

## optimize/optimize_textures.py

**Purpose:** Clamp oversized images to a maximum dimension (default 256 px). Longer side rounds down to the largest power of two ≤ `MAX_DIM`; shorter side scales to match, also rounded down to a power of two.

**Constants:** `MAX_DIM`

The GameCube hardware ceiling is 512×512; the 256 default halves memory footprint without visible loss on most assets.

---

## optimize/optimize_weights.py

**Purpose:** Cap bone weights per vertex on every mesh parented to an armature. Uses Blender's `vertex_group_limit_total` op — lowest-weighted influences are dropped, remaining weights are re-normalised.

**Constants:** `MAX_WEIGHTS_PER_VERTEX` (default 3; hardware max is 4)

---

## optimize/optimize_weight_quantization.py

**Purpose:** Quantise bone weights to fixed steps (default 1/10), matching game-model precision. Normalises, rounds, normalises again, and rounds once more to keep every weight on the grid. Run this after `optimize_weights.py` — fewer influences means less rounding error per vertex.

**Constants:** `QUANT_STEPS` (default 10 → 0.1 step)

---

## optimize/optimize_merge_verts.py

**Purpose:** Weld coincident vertices on every mesh in the scene. Cleans up duplicate geometry common in GLB / FBX rips that split verts on every UV / normal seam.

**Constants:** `MERGE_DISTANCE` (default 0.0001)

Averaging UVs / normals at merged points can introduce minor seam artefacts — skip on assets where exact shading boundaries matter.

---

## utilities/deduplicate_images.py

**Purpose:** Merge image datablocks that share the same on-disk filepath into one canonical datablock per file. Clears Blender's "can't save multiple images to the same path" warning on save.

**What it does:**
- Groups every `bpy.data.images` entry by its absolute filepath (ignores packed images and images with no filepath).
- For each group of 2+, keeps the datablock with the shortest name (the one without a `.001` / `.002` / ... suffix) and remaps every user of the duplicates to it.
- Deletes the orphaned duplicates.

**When to run:** Immediately after importing a glTF / GLB. The glTF importer creates a fresh Image datablock for every texture *reference* rather than per unique URI, so a PNG sampled from several material slots ends up as `name`, `name.001`, `name.002`, ... all pointing at the same file on disk.

**Safety:** Pixel data comes from the same file, so no image content is lost. Every duplicate typically has `users=1`, and `user_remap` rewires shader nodes before deletion.
