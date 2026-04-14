# Blender SysDolphin Addon

A Blender addon for importing and exporting GameCube `.dat` models. This addon is currently developed predominantly for `Pokemon Colosseum` and `Pokemon XD: Gale of Darkness` but may have some compatibility with other games that use the format (based on the SysDolphin library) such as `Super Smash Bros. Melee`, `Kirby Air Ride`, `Chibi-Robo! Plug Into Adventure!` and `Killer7`.

Original implementation provided by Made.

**Supported file extensions:** `.dat`, `.fdat`, `.rdat`, `.pkx`, `.fsys`, `.wzx`, `.cam`

**Target Blender version:** 4.5.7 LTS

## Installation

**This addon requires Blender 4.5.7 LTS. Using even a slightly different version of Blender may produce unexpected results.**

This addon uses Blender's extensions system. Compress the contents of this repository into a `.zip` file and install it via **Edit > Preferences > Extensions** (drag-and-drop the `.zip` into Blender also works). When the addon is enabled, navigate to **File > Import > Gamecube model (.dat)** and select your model file.

## Importing

- **File > Import > Gamecube model (.dat)** — select one or more `.dat` / `.pkx` / `.fsys` / `.wzx` files
- Imports skeleton, meshes, materials, textures, animations, lights, cameras, and constraints
- `.pkx` files automatically extract PKX metadata for animation naming and shiny variants
- `.fsys` archives are unpacked and each contained model is imported separately

### Importer Options

The file-browser sidebar exposes these toggles:

| Toggle | Default | Purpose |
|---|---|---|
| **IK Hack** | on | Shrink bones to 1e-3 so Blender's IK solver behaves correctly. |
| **Write Logs** | on | Write per-import logs to `$TMPDIR/blender_dat_import/<model>/`. Warnings and leniencies always print to the terminal regardless of this setting. |
| **Setup Workspace** | on | Split the viewport, open an Action Editor, set playback end to frame 60. |
| **Import Lights** | off | Import `LightSet` nodes as Blender lights (AMBIENT/SUN/POINT/SPOT). |
| **Import Cameras** | off | Import `CameraSet` nodes as Blender cameras (static + animated). |
| **Include Shiny Variant** | on | For `.pkx` files, extract shiny color parameters and build a toggleable shader filter. |
| **Use Legacy Importer** | off | Route through the pre-refactor pipeline instead of the IR pipeline. For comparison only. |
| **Strict Mirror Mode** | off | Refuse to silently heal malformed input. Use when diagnosing re-exported models — see below. |

#### Strict Mirror Mode

The importer normally heals edge-case data so it renders cleanly in Blender: it rescues near-zero-scale bones using animation keyframes, fabricates white vertex colors when `CLR0` is absent, falls back to rigid skinning when an envelope-typed mesh lacks `PNMTXIDX`, and drops cameras with unknown projection flags. These workarounds mask bugs in re-exported models — a file that crashes or renders garbage in-game often still loads fine here.

Strict Mirror Mode disables that healing for fault classes the game engine cannot tolerate. It raises on:

- Envelope weight chains longer than the game's 10-weight-per-vertex cap
- Missing `PNMTXIDX` on a mesh whose flags claim envelope skinning
- Cameras with unknown projection type or missing eye/target positions

and skips near-zero-scale bone rescue so broken skeletons collapse visibly instead of being silently repaired. Use it when a re-exported model looks fine in Blender but misbehaves in-game: the exception message points at the exact PObj address / camera index the game would also choke on.

Leniency warnings print to the terminal with strict mode **off** too — the toggle only controls whether the importer *fails* on them. Each import also writes a `dat_leniencies` list onto the armature as a custom property, so you can inspect healing history in the N-panel → Object Properties → Custom Properties.

## Particles (GPT1)

15 battle models ship with embedded GPT1 particle data — the flame-, gas- and mist-themed Pokémon (Moltres, Articuno, Charmander/Charmeleon/Charizard, Gastly, Magmar, Magcargo, Torkoal, Koffing, Weezing, Vaporeon, plus the three shiny variants `rare_fire`, `rare_freezer`, `rare_lizardon`).

**Particle import and export are both disabled in this release.** The GPT1 parser, disassembler, IR types, and compose-side assembler are all in place and unit-tested, but no Blender objects are created from the data. The blocker is the **generator → bone binding**: we have not been able to locate the table or code path that pairs each generator in a model's GPT1 with the body-map slot it renders from. Our investigation ruled out the HSD `JOBJ_PTCL` flag (unset on all 15 models), `_particleJObjCallback`, the PKX header body map (a bone lookup table, not a binding), WZX move files (carry move/attack effects only), the common.rel index table, and the DOL data section around `PKXPokemonModels`. See [CLAUDE.md](CLAUDE.md#particle-importgpt1) for pointers to what's left to check.

Visualising generators at the armature origin without a correct bone attachment looked misleading in practice (every flame floating in the wrong place), so the import stub logs generator/texture counts on the armature but creates nothing in the scene. Re-exported `.pkx` files drop the GPT1 region — keep the original file around if you need to preserve effects.

## Shiny Variants

When importing `.pkx` Pokemon models, the addon extracts shiny color parameters from the file header and builds a toggleable shader filter into the imported materials. Select the armature and find the **Shiny Variant** panel in **Properties > Object Properties** to toggle the shiny appearance and edit channel routing and brightness parameters.

Not every Pokemon has shiny parameters — some use a separate model for their shiny form instead. See [Shiny Variants](documentation/shiny_variants.md) for technical details.

## Exporting

The exporter writes a Blender scene to a `.dat` or `.pkx` binary. See the [Exporter Setup](documentation/exporter_setup.md) guide for the full workflow — from scene preparation through export.

For models not imported through this plugin, run `scripts/prepare_for_export.py` first to set up camera, lights, weight optimization, and PKX metadata.

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

### Code Structure

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
tests/                     # pytest suite (no game files required)
tests/round_trip/          # Round-trip tests with real model files (requires bpy)
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

- [**Blender API Usage**](documentation/blender_api_usage.md) — reference for Blender Python API patterns used in the addon
- [**Compatibility Table**](documentation/compatibility_table.md) — feature support across different games and file types
- [**Exporter Setup**](documentation/exporter_setup.md) — supported features and usage guide for the exporter (WIP)
- [**File Formats**](documentation/file_formats.md) — binary format specs for DAT, GX textures, WZX, PKX, and GPT1
- [**IR Specification**](documentation/ir_specification.md) — the Intermediate Representation dataclass hierarchy and design principles
- [**Round-Trip Test Progress**](documentation/round_trip_test_progress.md) — NBN/NIN/IBI/BNB test results per model
- [**Scripts**](documentation/scripts.md) — standalone Blender scripts and how to run them
- [**Shiny Variants**](documentation/shiny_variants.md) — how the game stores shiny color data and how the addon implements it

## Community

If you're interested in reverse engineering the Pokemon games on the Gamecube/Wii consoles you can find us on discord:
www.discord.gg/xCPjjnv
