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
- Sets up the `dat_shiny` properties on the armature so the Shiny Variant panel appears
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
