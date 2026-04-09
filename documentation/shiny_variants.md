# Shiny Variants

## Background

Every Pokemon has a "shiny" variant with an alternate color palette. In Pokemon Colosseum and XD: Gale of Darkness, a few prominent Pokemon (e.g. legendaries and starters) have entirely separate models for their shiny forms. However, the majority use a color filter stored in the PKX file header that transforms the base model's textures into the shiny appearance at runtime.

## How the Game Stores Shiny Data

Each PKX file contains two hidden RGBA color values in its header that define the shiny color filter:

### Color1 — Channel Routing

Four bytes stored at 3-byte intervals from a base offset. Each byte (0-3) specifies which source RGBA channel maps to the corresponding output channel:

- 0 = Red
- 1 = Green
- 2 = Blue
- 3 = Alpha

For example, `(2, 1, 0, 3)` swaps the red and blue channels while keeping green and alpha unchanged.

### Color2 — Brightness Scaling

Four contiguous bytes representing a per-channel brightness multiplier. Raw byte values map from `[0, 255]` to `[-1.0, 1.0]`, where 0 means no change. The shader applies this as `color * (brightness + 1.0)`, giving an effective multiplier range of `[0.0, 2.0]` (0x = black through 2x = double bright).

### Game-Specific Details

| Detail | Colosseum | XD |
|---|---|---|
| Game detection | `byte[0x00] == byte[0x40]` | `byte[0x00] != byte[0x40]` |
| Color data offset | `file_length - 0x11` | Fixed at `0x73` |
| Color2 byte order | ABGR (reversed) | RGBA |

### Default Parameter Detection

Models without a meaningful shiny variant (e.g. legendaries and starters, which use separate shiny models) store default routing `(0, 1, 2, 3)` (each channel maps to itself) and neutral brightness bytes near `128`. The addon detects this pattern on raw byte values (before conversion to floats) and skips the shiny filter entirely for these models.

## Implementation in the Addon

### Pipeline Flow

```
Phase 1 (Extract)        PKX header bytes → raw shiny params dict (routing ints + brightness floats)
                         Default parameter detection (unchanged routing + neutral brightness)
                         Returns None if defaults detected, skipping all downstream shiny logic

Phase 6 (Post-Process)   Raw params dict → Blender shader node group + armature properties + UI panel
                         Converts routing ints to node group connections
                         Sets up armature properties from brightness/routing values
                         Inserts shiny filter nodes into each material
```

Raw shiny params bypass the IR entirely — they go from Phase 1 (Extract) directly to Phase 6 (Post-Process), since the shiny filter is a Blender-only display feature that does not belong in the platform-agnostic intermediate representation.

**Note:** The legacy import path disables shiny entirely (`include_shiny=False`).

### Alpha Handling

Channel routing and brightness accept all four input channels (alpha is a valid source for routing), but only RGB outputs are applied in the shader. Alpha passes through unchanged.

### Shader Node Groups

The addon creates two reusable node groups, inserted at different points in the material graph to ensure channel routing doesn't affect vertex colors:

**`ShinyRoute_{model_name}`** — Channel routing (swizzle):
1. **Separate Color** — splits the input into R, G, B channels
2. **Channel routing** — reconnects source channels to output channels per the routing table
3. **Combine Color** — recombines into the output color
4. **Gamma** — linearizes sRGB → linear for Blender's scene-linear pipeline

**`ShinyBright_{model_name}`** — Brightness scaling:
1. **Separate Color** — splits the input into R, G, B channels
2. **Brightness multiply** — scales each RGB channel by `brightness + 1.0`
3. **Combine Color** — recombines into the output color

Each group is inserted into every material via a `MixRGB` node that blends between the original and filtered color. The mix factor is driven by the armature's `dat_pkx_shiny` property.

### Vertex Color Separation

The routing stage is placed **before** any vertex color multiply node in the material graph, while the brightness stage is placed **after** it. This ensures the channel swizzle only transforms texture/material colors — vertex colors pass through unaffected.

The vertex color multiply node is detected by graph analysis: walking backward from the shader input and looking for a `MixRGB` node with `MULTIPLY` blend type that has a `ShaderNodeAttribute` (vertex color) as one of its inputs. This works on any material, not just those created by the importer.

```
With vertex colors:    [textures] → [ShinyRoute] → [vtx_color MULTIPLY] → [ShinyBright] → [Principled BSDF]
Without vertex colors: [textures] → [ShinyRoute] → [ShinyBright] → [Principled BSDF]
```

If no vertex color multiply is found, both stages are inserted in sequence at the shader input.

Both node groups are shared across all materials on the same model. When any shiny parameter property changes, the relevant group is cleared and rebuilt, and all material instances update automatically.

### Armature Properties

All shiny parameters are registered as `bpy.props` properties on `bpy.types.Object` in `BlenderPlugin.register()`:

| Property | Type | Description |
|---|---|---|
| `dat_pkx_shiny` | BoolProperty | Enable/disable the shiny filter |
| `dat_pkx_shiny_route_r` | EnumProperty (Red/Green/Blue/Alpha) | Source channel for red output |
| `dat_pkx_shiny_route_g` | EnumProperty | Source channel for green output |
| `dat_pkx_shiny_route_b` | EnumProperty | Source channel for blue output |
| `dat_pkx_shiny_route_a` | EnumProperty | Source channel for alpha output |
| `dat_pkx_shiny_brightness_r` | FloatProperty (-1.0 to 1.0) | Red brightness offset |
| `dat_pkx_shiny_brightness_g` | FloatProperty | Green brightness offset |
| `dat_pkx_shiny_brightness_b` | FloatProperty | Blue brightness offset |
| `dat_pkx_shiny_brightness_a` | FloatProperty | Alpha brightness offset |

On import, these are initialized from the extracted raw shiny param values. Users can then tweak any parameter and see the result in real time.

### UI Panel

A panel ("Shiny Variant") appears in **Object Properties** when the selected armature has `dat_pkx_has_shiny` set. It shows:

- **Enable** checkbox — toggles the shiny filter on/off via driver
- **Channel Routing** — 4 enum dropdowns
- **Brightness** — 4 float sliders

The routing/brightness controls are greyed out when Enable is unchecked.

### Viewport Refresh

The `dat_pkx_shiny` toggle uses a driver on the MixRGB factor input, with an update callback (`_on_shiny_toggle_update`) that tags the depsgraph for refresh. Routing and brightness changes use a separate callback (`_on_shiny_param_update`) that rebuilds the node group and tags materials for update.

### Key Files

| File | Role |
|---|---|
| `importer/phases/extract/extract.py` | `_extract_shiny_params()`, `_is_noop_shiny()` |
| `importer/phases/post_process/post_process.py` | `_apply_shiny()` — orchestrates shiny setup in Phase 6 |
| `importer/phases/post_process/shiny_filter.py` | Node group building, property setup, material insertion |
| `BlenderPlugin.py` | Property registration, UI panel, update callbacks |
| `scripts/add_shiny_filter.py` | Standalone script for manual shiny filter application (imports from `shiny_filter.py`) |

## Reference

The shiny parameter extraction logic is based on [ShinierTextures](https://github.com/mikeyX101/ShinierTextures) by mikeyX101, which processes shiny colors as a standalone texture tool. This addon applies the same transformation as a real-time shader in Blender.
