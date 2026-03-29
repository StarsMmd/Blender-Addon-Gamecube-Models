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

**Purpose:** Add a shiny color filter to any armature, including models that weren't imported from PKX files or that had no-op shiny parameters.

**Usage:**
1. Select an armature in the viewport
2. Open the Scripting workspace (or any Text Editor area)
3. Open `scripts/add_shiny_filter.py`
4. Click **Run Script**

**What it does:**
- Creates a `ShinyFilter_{armature_name}` node group with identity (no-op) parameters
- Inserts the filter into every material on the armature's child meshes
- Sets up the `dat_shiny` properties on the armature so the Shiny Variant panel appears
- Skips materials that already have a `shiny_filter_shader` node to avoid duplicates

**Initial parameters:**
- Channel routing: R→Red, G→Green, B→Blue, A→Alpha (identity)
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
