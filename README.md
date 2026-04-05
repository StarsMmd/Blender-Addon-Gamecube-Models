# Blender SysDolphin Addon

A Blender addon for importing and exporting GameCube `.dat` models. This addon is currently developed predominantly for `Pokemon Colosseum` and `Pokemon XD: Gale of Darkness` but may have some compatibility with other games that use the format (based on the SysDolphin library) such as `Super Smash Bros. Melee`, `Kirby Air Ride`, `Chibi-Robo! Plug Into Adventure!` and `Killer7`.

Original implementation provided by Made.

**Supported file extensions:** `.dat`, `.fdat`, `.rdat`, `.pkx`, `.fsys`

**Target Blender version:** 4.5.7 LTS

## Installation

**This addon requires Blender 4.5.7 LTS. Using even a slightly different version of Blender may produce unexpected results.**

This addon uses Blender's extensions system. Compress the contents of this repository into a `.zip` file and install it via **Edit > Preferences > Extensions** (drag-and-drop the `.zip` into Blender also works). When the addon is enabled, navigate to **File > Import > Gamecube model (.dat)** and select your model file.

## What's Working

- Full skeleton import with bone hierarchy, IK, copy location/rotation, track-to, and limit constraints
- Static mesh import with UV mapping, vertex colors, custom normals, and envelope deformation
- Bone animation import with keyframe decoding, path/spline animation, and looping
- Material pipeline with TEV color combiners, pixel engine blending, and texture mapping
- Material animation import (color, alpha, texture UV) with NLA support
- Light import (SUN, POINT, SPOT) — toggle with "Import Lights" setting
- Bone instances (JOBJ_INSTANCE)
- [Shiny variant color filter](#shiny-variants) (PKX models)
- FSYS archive import (multi-model extraction + LZSS decompression)

## Shiny Variants

When importing `.pkx` Pokemon models with the **Include Shiny Variant** option enabled (on by default), the addon extracts shiny color parameters from the file header and builds a toggleable shader filter into the imported materials.

To use the shiny toggle:

1. Select the armature in the viewport
2. Open **Properties > Object Properties** (orange square icon)
3. Find the **Shiny Variant** panel
4. Check **Enable** to switch to the shiny appearance

The panel also exposes all 8 shiny parameters for live editing:

- **Channel Routing** — 4 dropdowns (Red/Green/Blue/Alpha) controlling which source channel maps to each output channel
- **Brightness** — 4 sliders (-1.0 to 1.0) for per-channel brightness adjustment

Not every Pokemon has shiny parameters in its PKX file — some (e.g. legendaries and starters) use a separate model for their shiny form instead. For these models, the Shiny Variant panel will not appear. See `documentation/shiny_variants.md` for technical details. Shiny variants are not available with the legacy importer setting enabled.

The shiny filter can also be added to any model manually using the standalone script documented in [Scripts](documentation/scripts.md).

## Exporting

The exporter writes a Blender scene to a `.dat` or `.pkx` binary. Skeleton and mesh geometry export is functional. Materials, animations, and constraints are not yet implemented. See the [Exporter Usage](documentation/exporter_usage.md) documentation for details.

## Remaining Work

- [ ] Shape animation import
- [ ] Camera import
- [ ] Fog import
- [x] Exporter: Blender scene → IR (skeleton + meshes + materials)
- [x] Exporter: IR → node trees (skeleton + meshes + materials)
- [x] Exporter: Materials + textures (CMPR, I8, RGBA8 + all GX formats)
- [x] Exporter: Bound box section
- [x] Exporter: Bone animations
- [x] Exporter: Lights
- [ ] Exporter: Constraints
- [ ] Code audit: identify opportunities to simplify and clean up code
- [ ] Code audit: identify opportunities to reduce algorithmic complexity

## Code Structure

```
importer/
  importer.py              # Pipeline entry point: Importer.run()
  phases/
    extract/               # Phase 1: container detection, PKX header stripping
    route/                 # Phase 2: section name -> node type mapping
    parse/                 # Phase 3: binary -> node trees (DATParser)
    describe/              # Phase 4: node trees -> IR dataclasses
    build_blender/         # Phase 5: IR -> Blender objects
    post_process/          # Phase 6: reset poses, select animations, apply shiny

shared/
  IR/                      # Intermediate Representation dataclasses
  Nodes/                   # Node class definitions (parsing + writing only, no bpy)
  Constants/               # HSD/GX format constants
  helpers/                 # Binary I/O, logging, math utilities, PKX container, sRGB

exporter/
  exporter.py              # Pipeline entry point: Exporter.run()
  phases/
    pre_process/           # Pre-process: validate output path + scene
    describe_blender/      # Phase 1: Blender -> IR dataclasses
    compose/               # Phase 2: IR -> node trees
    serialize/             # Phase 3: node trees -> DAT bytes (DATBuilder)
    package/               # Phase 4: DAT bytes -> final output (.dat or .pkx)

legacy/                    # Pre-refactor importer (available via "Use Legacy" toggle)
documentation/             # Pipeline docs, API reference, compatibility table, IR spec
tests/                     # pytest suite (443 tests, no game files required)
tests/round_trip/          # Round-trip tests with real model files (requires bpy)
```

## Developer Instructions

### Dependencies

Install the following Python packages for development and testing:

```bash
pip install pytest

# bpy 4.5 requires Python 3.11
python3.11 -m pip install bpy==4.5.7
```

| Package | Purpose |
|---|---|
| `pytest` | Required for running the unit test suite |
| `bpy` | Required for round-trip tests (IBI) and CLI pipeline phases 5-6. **Requires Python 3.11.** |

`bpy` bundles `mathutils` — no separate install needed.

To verify:

```bash
python3.11 -c "import bpy; print(bpy.app.version_string)"
# Should print: 4.5.7 LTS
```

### Running the CLI Pipeline

The pipeline can run outside of Blender for parsing and testing:

```bash
# From within the addon folder, run the pipeline on a model file
python3 CommandLineInterface.py model.dat

# Verbose mode (writes detailed log)
python3 CommandLineInterface.py model.dat -v
```

The CLI entry point is `CommandLineInterface.py` (invoked via `__main__.py`). Without `bpy` installed, the pipeline runs phases 1-4 (parse and describe) and outputs the IR without creating Blender objects.

### Running Tests

#### Unit Tests

Unit tests use **pytest** and run with mocked Blender APIs. All test data is generated programmatically — no game files are needed or should ever be committed.

```bash
python3 -m pytest tests/ -q
```

#### Round-Trip Tests

Round-trip tests validate the export pipeline against real model files using all four test types (NBN, NIN, IBI, BNB). These require `bpy` and `mathutils` to be installed.

```bash
# Single model
python3 tests/round_trip/run_round_trips.py path/to/model.pkx

# All models in a directory
python3 tests/round_trip/run_round_trips.py path/to/models/

# Verbose (shows mismatch details)
python3 tests/round_trip/run_round_trips.py path/to/model.pkx -v
```

See [Round-Trip Test Progress](documentation/round_trip_test_progress.md) for per-model scores and test type explanations.

## Documentation

Detailed documentation lives in the `documentation/` folder:

- [**Export Pipeline Plan**](documentation/export_pipeline_plan.md) — design for the export pipeline (DAT writing)
- [**Round-Trip Test Progress**](documentation/round_trip_test_progress.md) — NBN/NIN/IBI/BNB test results per model
- [**IR Specification**](documentation/ir_specification.md) — the Intermediate Representation dataclass hierarchy and design principles
- [**Compatibility Table**](documentation/compatibility_table.md) — feature support across different games and file types
- [**Blender API Usage**](documentation/blender_api_usage.md) — reference for Blender Python API patterns used in the addon
- [**Shiny Variants**](documentation/shiny_variants.md) — how the game stores shiny color data and how the addon implements it
- [**Exporter Usage**](documentation/exporter_usage.md) — supported features and usage guide for the exporter (WIP)
- [**Scripts**](documentation/scripts.md) — standalone Blender scripts and how to run them

## Community

If you're interested in reverse engineering the Pokemon games on the Gamecube/Wii consoles you can find us on discord:
www.discord.gg/xCPjjnv
