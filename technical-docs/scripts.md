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
- Creates the `ShinyRoute` / `ShinyBright` node groups and inserts them into every material on the armature's child meshes
- Sets up the `dat_pkx_shiny` properties on the armature so the Shiny Variant panel appears
- Skips materials that already have a shiny node to avoid duplicates

**Initial parameters:** The addon's registered shiny defaults are identity/neutral (so a model with no real shiny round-trips as non-shiny). When the selected armature has no shiny params yet, this script seeds a visible starting variant (channel-swap routing R←Blue, G←Red, B←Green plus a small R/G brightness boost) so the preview shows an effect. An armature that already carries real shiny params (e.g. from a PKX import) is left untouched.

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

## prepare_for_pkx_export.py

**Purpose:** Prepare a Blender scene for **PKX** export (Pokémon model containers). Adds the custom properties the exporter needs on cameras, armatures, and lights, plus the PKX-only metadata: animation slots, body map, derived timings, shiny filter shader nodes, and a four-light battle preview. Operates on all objects in the scene — no selection required. Only adds properties that don't already exist — not needed on models that were imported through the DAT plugin.

> **Pick the right prep script for the output kind.** Use this one when the export target is `.pkx`. For bare `.dat` output (maps, scene archives, anything without a PKX header) use [`prepare_for_dat_export.py`](#prepare_for_dat_exportpy) instead — same bake + weight + texture steps, but skips the PKX-only ones (metadata, timing, shiny, test anims, battle lights).

> **Scope of its optimisations:** prep applies the optimisations needed to land within the game's **hard** limits — ≤ 4 bone weights per vertex (`MAX_WEIGHTS_PER_VERTEX`, the GX hardware max), 10 % weight quantisation, and a `MAX_TEXTURE_DIM` (default **512** px on the longer axis) downscale. The defaults favour fidelity; **lower the constants at the top of the script to shrink the output** — an over-large file can crash the game in battle as it loads. `MAX_TEXTURE_DIM` is the highest-leverage knob (battle-model size is dominated by texture pixels): try 256 / 128 / 64. If the file is still too large, or the target is a heavier newer-game rip, reach for `optimize.py` (or the individual `optimize/*.py` passes) — those are lossier but more aggressive (polycount decimation, keyframe thinning, vertex merging). See the constant table in [exporter_setup.md → Tuning the script](exporter_setup.md#tuning-the-script).

**Usage:**
1. Open the Scripting workspace
2. Open `scripts/prepare_for_pkx_export.py`
3. Click **Run Script**

**What it does:**
1. **Returns any armature left in Edit/Pose mode to Object mode** before anything else. A rig built from scratch is often left mid-edit; the global mode is then not Object mode, which makes the first operator the script runs (`bpy.ops.object.select_all`) fail its poll with "context is incorrect", and would make the data-level bake below get discarded when the edit session is flushed. Then **bakes loc/rot/scale** on every armature and its child meshes (direct data mutation), so each `matrix_world` is identity. The exporter rejects any armature or child mesh whose `matrix_world` is not identity — without this, the bone path's SRT decompose drops shear introduced by non-uniform armature scale, while the vertex path's matmul keeps it, and the two drift apart further down the chain.
2. Stamps `dat_camera_aspect = 1.18` on any scene camera missing it (camera creation is not part of prep — use [`add_debug_camera.py`](#add_debug_camerapy) if you want a viewport preview)
3. Limits vertex bone weights to `MAX_WEIGHTS_PER_VERTEX` per vertex (default 4) and quantises to 10 % steps
4. Culls unused material slots
5. **Normalises the root bone orientation** so the exporter emits an **identity root JOBJ rotation**. A from-scratch rig whose root bone isn't axis-aligned (e.g. carries a non-zero roll) exports a rotated root joint; the game applies that rotation as the model's base orientation and does *not* cancel it the way a full skinning solve does, so the whole model renders turned (typically 90°) in-game even though Blender looks correct. The step reorients the root bone to the canonical frame (`+90°` about X — bone up, roll 0); geometry and every other bone keep their absolute rest positions so the model's facing is unchanged (the old root rotation is absorbed into the children's local transforms, where it cancels through their inverse-bind matrices). The root bone's own animation is rebound to the new rest so its world motion is preserved. No-op for rigs imported through this addon (already canonical)
6. Applies default PKX metadata to the armature (PKX-only)
7. Auto-derives animation timing from action durations for any animation slot that has an action assigned (PKX-only). Uses even splits: action types get 33%/66%/100% for wind-up/hit/duration, loops get full duration, hit reactions get 50%/100%
8. **Bakes custom shader-group materials down to a Principled BSDF** (scene-wide, before the texture steps). Some rips drive the Material Output from a custom shader node group (e.g. `PokemonShaderbyChicoEevee`) whose real surface colour is the albedo *modulated by a layer-mask* selecting flat base-colour layers — not the raw albedo. The exporter only reads a single texture feeding a Principled `Base Color`, so without this the material exports washed-out/untextured. The step bakes the group's `BaseColorBake` output (plus albedo alpha) to a per-material image and rebuilds the surface as a clean Principled BSDF, leaving the original group disconnected. No-op for materials already on a Principled BSDF. (Same logic as the standalone [`bake_chico_shader_to_principled.py`](#bake_chico_shader_to_principledpy), inlined here per the self-contained-scripts rule.)
9. Downscales any texture larger than `MAX_TEXTURE_DIM` (default 512) to fit, then auto-selects GX texture formats for textures still on `AUTO` — analyzes each texture's pixel content and picks the most efficient format (CMPR, I8, C8, etc.). Skips textures that already have a format. Runs after the bake so the baked albedos are downscaled and encoded like any other texture
10. Inserts shiny filter nodes into every material with a textured colour chain (PKX-only)
11. Authors two helper actions per armature for in-game smoke testing — `auto_animation_dummy` (two-frame identity pose; the game requires ≥ 2 keyframes per channel for an animation to play) and `auto_animation_spin` (60-frame full revolution around the rig's vertical axis on the root bone, with frame 0 == frame 60 mod 2π so the loop closes). Neither is assigned to a PKX slot — pick them by hand in the PKX Metadata panel only when smoke-testing; ignore them for normal authoring
12. Creates a 4-light preview rig — one POINT ambient (`dat_light_type = "AMBIENT"`, default `(76, 76, 76)`) plus three SUN directionals (Main/Fill/Back). All four are namespaced under `DATPlugin_Prep_*` so re-runs are idempotent and the names don't collide with imported or user-authored lights

**Tip:** After assigning actions to animation slots in the PKX Metadata panel, run the script again to auto-fill timing values based on the action durations. The script always re-derives timing for any slot with an action assigned.

See [Exporter Setup](exporter_setup.md) for a full reference of every property, what it does, and how to choose the right values.

---

## prepare_for_dat_export.py

**Purpose:** Prepare a Blender scene for **bare `.dat`** export (maps, scene archives, arbitrary models without a PKX header). Standalone — duplicates the shared helpers from `prepare_for_pkx_export.py` rather than importing them, so each script can be reasoned about in isolation.

> **Pick the right prep script for the output kind.** Use this one when the export target is `.dat`. For `.pkx` output use [`prepare_for_pkx_export.py`](#prepare_for_pkx_exportpy) instead — it adds the PKX-only steps (header metadata, animation slot timings, shiny filter, smoke-test actions, battle lights).

**Usage:**
1. Open the Scripting workspace
2. Open `scripts/prepare_for_dat_export.py`
3. Click **Run Script**

**What it does** (subset of the PKX prep — all the hardware-level steps, none of the PKX header authoring):
1. **Returns any armature left in Edit/Pose mode to Object mode** first (same reason as the PKX prep — otherwise the first operator fails its poll and the bake gets discarded), then **bakes loc/rot/scale** on every armature and its child meshes so each `matrix_world` is identity (the bone path SRT-decomposes and the vertex path matmuls; they must agree)
2. Stamps `dat_camera_aspect = 1.18` on any scene camera missing it
3. Limits vertex bone weights to `MAX_WEIGHTS_PER_VERTEX` per vertex (default 4) and quantises to 10 % steps
4. Culls unused material slots
5. Downscales any texture larger than 512×512
6. Auto-selects GX texture formats for textures still on `AUTO`

**What it skips** (vs the PKX prep): PKX header metadata, animation timing derivation, shiny filter shader nodes, the `auto_animation_*` smoke-test helpers, and the four-light battle preview. None of those apply to a bare `.dat` model.

---

## prepare_pbr_for_pkx_export.py

**Purpose:** One-shot prep for a freshly-imported **PBR** (Pokémon Battle Revolution) rig targeting `.pkx`. It runs the same pipeline as the generic [`prepare_for_pkx_export.py`](#prepare_for_pkx_exportpy) plus the PBR-rig-specific steps the deploy harness used to apply manually across two prep passes — scaling, body-map matching, and animation-slot matching — so a conforming rig preps correctly in a **single run** with no hand-tuning.

> **Use this only for PBR rips.** The body-map and animation-slot priority lists encode PBR's bone/action naming conventions (`origin`, `mouth`, `chest`, `head`, `left_hand`, `wait`, `kime`, `punch`, `damage`, `down`, …). For any other rig family use the generic [`prepare_for_pkx_export.py`](#prepare_for_pkx_exportpy) and assign the body map / anim slots by hand in the PKX Metadata panel, or copy this file as a template and edit the priority lists at the top.

> **Self-contained.** Like the other scripts here it inlines the shared prep steps rather than importing them — it does not depend on `prepare_for_pkx_export.py`. If the shared steps (bake, holder bones, metadata, timing, textures, shiny, lights) change, update both files.

**Usage:**
1. Import the PBR `.sdr` (or open a scene containing the imported rig)
2. Open the Scripting workspace and open `scripts/prepare_pbr_for_pkx_export.py`
3. Click **Run Script**

**What it does**, in order:
1. **Scales every armature to 10%** of import size (PBR rigs import ~10× too large for XD), before baking. One-time — guarded by a `dat_pbr_prep_scaled` marker so re-runs don't compound the scale
2. **Bakes transforms** and **inserts mesh-holder bones**, then per armature: limits/quantises weights, culls unused material slots, applies **default PKX metadata**
3. **Pattern-matches the body-map bone slots** (`dat_pkx_body_*`) from the rig's bone names via the priority lists, and sets `dat_pkx_head_bone` to the resolved `mouth` bone
4. **Pattern-matches the 17 animation slots** (`dat_pkx_anim_NN_sub_0_anim`) from the rig's action names by slot kind (Idle / Special / Physical / Damage / Faint)
5. **Derives animation timing** from the just-assigned slot actions, then finishes the per-armature prep: textures, formats, shiny filter, smoke-test actions
6. **Adds the four-light battle preview** and leaves the first armature selected

**Why one run is enough:** the generic prep's `apply_pkx_metadata` overwrites the anim slots with defaults and `derive_timing` runs off those defaults — so the deploy harness historically ran the generic prep twice (defaults, then again after assigning slots). This script does the body-map + anim-slot matching **inside the per-armature loop, between `apply_pkx_metadata` and `derive_timing`**, so timings are derived from the assigned actions on the first and only pass.

**Warnings it emits:** a body-map slot that the corpus actively reads (`mouth`, `chest`) falling back to `origin`; a non-idle anim slot that resolves only to `wait`/`wait_a` (the rig is missing the action kind that slot expects). These are advisory — the export still succeeds.

---

## bake_chico_shader_to_principled.py

**Purpose:** **Bake** `PokemonShaderbyChicoEevee` shader-group materials down to a **Principled BSDF** so the exporter can read their composited albedo. These rips drive the Material Output's Surface from a custom `ShaderNodeGroup`. The exporter only recognises a fixed set of colour sinks — chiefly a single `TEX_IMAGE` feeding a Principled BSDF's `Base Color` — so a material on a custom group exports **untextured** (renders missing/black in-game). The script is keyed to the chico convention: it acts on any group exposing a `BaseColorBake`-style output socket, which is a chico-shader feature; other custom shaders without that socket are reported and left unchanged.

The real surface colour of the chico shader is **not** the raw `Albedo` texture: that input is a near-neutral detail map, and the actual colour comes from a layer-mask texture (`Lym_color`/`Lym_alpha`) selecting between flat `BaseColorLayer1–4` colours per region, plus eye/emission compositing. Wiring the raw `Albedo` straight into a Principled (an earlier version of this script) dropped all of that recolouring and exported washed-out/wrong. The chico group is built for baking instead: it exposes a dedicated `BaseColorBake` output whose Principled BSDF carries the fully composited colour.

**Run when:** a model's materials use a custom shader node group with a `BaseColorBake`-style output and export without textures. Safe to run before *or* after `prepare_for_pkx_export.py`. Baking uses Cycles and writes packed images into the .blend, so the result is self-contained.

**What it does:** For every material whose Surface is a shader group (not already a Principled BSDF), it (1) creates a packed image sized to the source albedo; (2) bakes the group's `BaseColorBake` diffuse colour into it in one Cycles pass over **every** contributing mesh (so materials shared across objects keep all their islands); (3) bakes the albedo alpha into the image's alpha channel for cutout/eyes; (4) builds a fresh Principled BSDF fed by the baked image and connects it to the Material Output, leaving the original group in place but disconnected. Because these models stack UV islands across tiles (V > 1) and sample one tile with REPEAT, the bake temporarily collapses each face into the base tile by an integer offset, then restores the original UVs and marks the baked image REPEAT so the exporter re-tiles it. Idempotent — materials already on a Principled BSDF are skipped, and ones with no bake output are reported and left unchanged.

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

## add_debug_camera.py

**Purpose:** Drop a viewport-friendly preview camera into the scene, framed on the combined mesh AABB. The exporter writes whatever cameras are present in the scene, so anything added here will land in the output `.dat` / `.pkx` as a regular `scene_data.camera` entry — there is no special "debug" handling on the export side.

**Usage:**
1. Open the Scripting workspace
2. Open `scripts/add_debug_camera.py`
3. Click **Run Script**

By default the camera is named `Debug_Camera` (with a `Debug_Camera_target` empty as its TRACK_TO). Set `NAME` in the script's text editor (or via `bpy` globals) before running to use a different name.

**What it does:**
- Computes the scene's mesh AABB and places a perspective camera ~2.5× the model height back along `-Y`, looking at the model centre.
- Defaults: 37.5 mm lens (~27° vertical FOV), `dat_camera_aspect = 1.18`, near = 0.01, far = 3277.
- No-op if a camera with the chosen name already exists.

**Why a separate script:** the DAT exporter treats every scene camera the same way — there is no "is this a preview?" filter. Keeping camera creation out of the prep scripts means running prep on a model with no camera produces a model file with no camera, mirroring the source exactly.

---

## optimize.py

**Purpose:** Run every lossy optimisation pass in one go to shrink oversized models from newer games. Lossy — intended for rips/imports that are too heavy to fit the GameCube budget.

> **When to use:** the prep scripts (`prepare_for_pkx_export.py` and `prepare_for_dat_export.py`) already enforce the game's hard limits (≤ 512×512 textures, ≤ 4 weights per vertex, 10 % weight quantisation). Reach for these scripts when prep isn't enough — e.g. when the exported file is too large, when the source is a newer-gen rip with dense geometry / long animations, or when you want a smaller in-memory footprint than the hardware ceiling. Run `optimize.py` before whichever prep script matches your output kind; prep then picks up the already-optimised scene and adds the export-specific metadata.

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
