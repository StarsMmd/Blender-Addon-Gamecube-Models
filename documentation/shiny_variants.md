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
Phase 1 (Extract)    PKX header bytes → raw shiny params dict (routing ints + brightness floats)
                     Default parameter detection (unchanged routing + neutral brightness)
                     Returns None if defaults detected, skipping all downstream shiny logic

Phase 4 (Describe)   Raw dict → IRShinyFilter dataclass
                     Converts routing ints to ShinyChannel enum
                     Brightness already converted to [-1.0, 1.0] floats by Phase 1

Phase 5A (Build)     IRShinyFilter → Blender shader node group + armature properties + UI panel
```

### IR Representation

```python
class ShinyChannel(Enum):
    RED = 0
    GREEN = 1
    BLUE = 2
    ALPHA = 3

@dataclass
class IRShinyFilter:
    channel_routing: tuple[ShinyChannel, ShinyChannel, ShinyChannel, ShinyChannel]
    brightness: tuple[float, float, float, float]  # [-1.0, 1.0]
```

The filter lives as an optional field on `IRModel`:
```python
shiny_filter: IRShinyFilter | None = None
```

### Alpha Handling

Channel routing and brightness accept all four input channels (alpha is a valid source for routing), but only RGB outputs are applied in the shader. Alpha passes through unchanged.

### Shader Node Group

The addon creates a reusable node group (`ShinyFilter_{model_name}`) containing:

1. **Separate Color** — splits the input into R, G, B channels
2. **Channel routing** — reconnects source channels to output channels per the routing table
3. **Brightness multiply** — scales each RGB channel by `brightness + 1.0`
4. **Combine Color** — recombines into the output color (alpha from original)

This group is inserted into every material via a `MixRGB` node that blends between the original and shiny-filtered color. The mix factor is driven by the armature's `dat_shiny` property.

The node group is shared across all materials on the same model. When any shiny parameter property changes, the node group is cleared and rebuilt via `populate_shiny_node_group()`, and all material instances update automatically.

### Armature Properties

All shiny parameters are registered as `bpy.props` properties on `bpy.types.Object` in `BlenderPlugin.register()`:

| Property | Type | Description |
|---|---|---|
| `dat_shiny` | BoolProperty | Enable/disable the shiny filter |
| `dat_shiny_route_r` | EnumProperty (Red/Green/Blue/Alpha) | Source channel for red output |
| `dat_shiny_route_g` | EnumProperty | Source channel for green output |
| `dat_shiny_route_b` | EnumProperty | Source channel for blue output |
| `dat_shiny_route_a` | EnumProperty | Source channel for alpha output |
| `dat_shiny_brightness_r` | FloatProperty (-1.0 to 1.0) | Red brightness offset |
| `dat_shiny_brightness_g` | FloatProperty | Green brightness offset |
| `dat_shiny_brightness_b` | FloatProperty | Blue brightness offset |
| `dat_shiny_brightness_a` | FloatProperty | Alpha brightness offset |

On import, these are initialized from the extracted `IRShinyFilter` values. Users can then tweak any parameter and see the result in real time.

### UI Panel

A panel ("Shiny Variant") appears in **Object Properties** when the selected armature has `dat_has_shiny` set. It shows:

- **Enable** checkbox — toggles the shiny filter on/off via driver
- **Channel Routing** — 4 enum dropdowns
- **Brightness** — 4 float sliders

The routing/brightness controls are greyed out when Enable is unchecked.

### Viewport Refresh

The `dat_shiny` toggle uses a driver on the MixRGB factor input, with an update callback (`_on_shiny_toggle_update`) that tags the depsgraph for refresh. Routing and brightness changes use a separate callback (`_on_shiny_param_update`) that rebuilds the node group and tags materials for update.

### Key Files

| File | Role |
|---|---|
| `importer/phases/extract/extract.py` | `_extract_shiny_params()`, `_is_noop_shiny()` |
| `shared/IR/shiny.py` | `IRShinyFilter` dataclass |
| `shared/IR/enums.py` | `ShinyChannel` enum |
| `importer/phases/describe/describe.py` | `_build_shiny_filter()` — dict → IR conversion |
| `importer/phases/build_blender/helpers/shiny_filter.py` | Node group building, property setup, material insertion |
| `importer/phases/build_blender/build_blender.py` | Orchestrates shiny setup in Phase 5A |
| `BlenderPlugin.py` | Property registration, UI panel, update callbacks |

## Reference

The shiny parameter extraction logic is based on [ShinierTextures](https://github.com/mikeyX101/ShinierTextures) by mikeyX101, which processes shiny colors as a standalone texture tool. This addon applies the same transformation as a real-time shader in Blender.
