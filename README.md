# Blender HAL DAT Model Addon

A Blender addon for importing and exporting GameCube `.dat` models. This addon is currently developed predominantly for `Pokemon Colosseum` and `Pokemon XD: Gale of Darkness` but may have some compatibility with other games that use the format (based on HAL Laboratory's DAT model format) such as `Super Smash Bros. Melee`, `Kirby Air Ride`, `Chibi-Robo! Plug Into Adventure!` and `Killer7`.

Original implementation provided by Made.

**Supported file extensions:** `.dat`, `.fdat`, `.rdat`, `.pkx`, `.fsys`, `.wzx`, `.cam`

**Target Blender version:** 4.5.7 LTS

## Installation

**This addon requires Blender 4.5.7 LTS. Using even a slightly different version of Blender may produce unexpected results.**

This addon uses Blender's extensions system. Compress the contents of this repository into a `.zip` file and install it via **Edit > Preferences > Extensions** (drag-and-drop the `.zip` into Blender also works). When the addon is enabled, navigate to **File > Import > Gamecube model (.dat)** and select your model file.

## Importing

Open a model via **File > Import > Gamecube model (.dat)**. The importer reads `.dat`, `.fdat`, `.rdat`, `.pkx`, `.fsys`, `.wzx`, and `.cam` files, and brings in the skeleton, meshes, materials, textures, animations, lights, cameras, and (for `.pkx` Pokémon) the shiny variant toggle.

See the [Importer guide](docs/importer.html) for the full walkthrough — from extracting model files out of a ROM through to playing animations and toggling shiny variants in Blender.

## Particles (GPT1)

15 battle models ship with embedded GPT1 particle data — the flame-, gas- and mist-themed Pokémon (Moltres, Articuno, Charmander/Charmeleon/Charizard, Gastly, Magmar, Magcargo, Torkoal, Koffing, Weezing, Vaporeon, plus the three shiny variants `rare_fire`, `rare_freezer`, `rare_lizardon`).

Particle import and export are not currently supported but are planned for the future. See [Implementation Notes — Particles (GPT1)](technical-docs/implementation_notes.md#particles-gpt1) for the technical details and outstanding investigation.

## Shiny Variants

When importing `.pkx` Pokemon models, the addon extracts shiny color parameters from the file header and builds a toggleable shader filter into the imported materials. Select the armature and find the **Shiny Variant** panel in **Properties > Object Properties** to toggle the shiny appearance and edit channel routing and brightness parameters.

Not every Pokemon has shiny parameters — some use a separate model for their shiny form instead. See [Shiny Variants](technical-docs/shiny_variants.md) for technical details.

## Exporting

The exporter writes a Blender scene back to a `.dat` or `.pkx` binary the game can load. Works for models that came in through this plugin and for custom or third-party models prepared via `scripts/prepare_for_export.py`.

See the [Exporter guide](docs/exporter.html) for the full workflow — scene preparation, export options, and getting your model back into the game. For implementation details and the supported-feature matrix, see [Exporter Setup](technical-docs/exporter_setup.md).

## Developer Instructions

### Local Development Setup

**Goal:** install the addon into Blender, find the on-disk install location, and edit files there so changes pick up after a restart.

1. **Clone the repository.** The same `git` commands work on macOS, Linux, and Windows (Git Bash, PowerShell, or Command Prompt — all accept this syntax once Git for Windows is installed).
   ```bash
   git clone https://github.com/StarsMmd/Blender-Addon-Gamecube-Models.git
   cd Blender-Addon-Gamecube-Models
   ```

2. **Build a Blender extension `.zip`.** Compress the **contents** of the repo (not the parent folder), so the resulting zip's top level is the addon files (`__init__.py`, `blender_manifest.toml`, `BlenderPlugin.py`, etc.).
   ```bash
   # macOS / Linux
   cd /path/to/colo_xd
   zip -r ../colo_xd.zip . -x ".git/*" "__pycache__/*"

   # Windows (PowerShell)
   Compress-Archive -Path * -DestinationPath ..\colo_xd.zip
   ```

3. **Install in Blender.** Open Blender 4.5.7 LTS, then:
   - **Edit > Preferences > Get Extensions > drop-down (top right) > Install from Disk…** and select the `.zip`.
   - Or simply drag the `.zip` into a Blender window.

4. **Find the on-disk install location.** Blender unpacks extensions into a per-OS user-default folder:
   | OS | Default extensions folder |
   |---|---|
   | macOS | `~/Library/Application Support/Blender/4.5/extensions/user_default/` |
   | Windows | `%APPDATA%\Blender Foundation\Blender\4.5\extensions\user_default\` |
   | Linux | `~/.config/blender/4.5/extensions/user_default/` |

   Inside that folder, the addon lives in a sub-directory named after the manifest's `id` (here: `gamecube_dat_model`) — or after whatever folder name the `.zip` extracted to. Edit files **at this location** for changes to affect the running addon.

5. **Restart Blender after every code change.** Blender loads extension modules once at startup; reloading without a restart will not pick up edits to the addon's Python files. If a change doesn't take effect, fully quit and relaunch Blender (closing the window is sometimes not enough — use *Blender > Quit* on macOS, or kill the process if the launcher menu won't accept input).

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
    describe/              # Phase 4: node trees -> IR (platform-agnostic)
    plan/                  # Phase 5a: IR -> BR (Blender-specialised, pure)
    build_blender/         # Phase 5b: BR -> Blender objects (bpy executor only)
    post_process/          # Phase 6: reset poses, select animations, apply shiny

shared/
  IR/                      # Intermediate Representation dataclasses
  BR/                      # Blender Representation dataclasses (shader graphs, etc.)
  Nodes/                   # Node class definitions (parsing + writing only, no bpy)
  Constants/               # HSD/GX format constants
  helpers/                 # Binary I/O, logging, math utilities, PKX container, sRGB

exporter/
  exporter.py              # Pipeline entry point: Exporter.run()
  phases/
    pre_process/           # Validate output path + scene (baked transforms,
                           #   weight/texture caps, anim timings)
    describe/              # Phase 1: Blender -> BR (only phase that touches bpy)
    plan/                  # Phase 2: BR -> IR (pure)
    compose/               # Phase 3: IR -> node trees
    serialize/             # Phase 4: node trees -> DAT bytes (DATBuilder)
    package/               # Phase 5: DAT bytes -> final output (.dat or .pkx)
    describe_blender/      # Empty deprecation stubs (pending file deletion)

legacy/                    # Pre-refactor importer (available via "Use Legacy" toggle)
technical-docs/            # Pipeline docs, API reference, compatibility table, IR spec
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

The CLI entry point is `CommandLineInterface.py` (invoked via `__main__.py`). Without `bpy` installed, the pipeline runs phases 1-5a (parse, describe, and plan) and outputs the BR without creating Blender objects.

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

See [Round-Trip Test Progress](technical-docs/round_trip_test_progress.md) for per-model scores and test type explanations.

## Documentation

Detailed documentation lives in the `technical-docs/` folder:

- [**Blender API Usage**](technical-docs/blender_api_usage.md) — reference for Blender Python API patterns used in the addon
- [**Compatibility Table**](technical-docs/compatibility_table.md) — feature support across different games and file types
- [**Exporter Setup**](technical-docs/exporter_setup.md) — supported features and usage guide for the exporter (WIP)
- [**File Formats**](technical-docs/file_formats.md) — binary format specs for DAT, GX textures, WZX, PKX, and GPT1
- [**IR Specification**](technical-docs/ir_specification.md) — the Intermediate Representation dataclass hierarchy (output of Phase 4)
- [**BR Specification**](technical-docs/br_specification.md) — the Blender Representation dataclass hierarchy (output of Phase 5a, Plan)
- [**Implementation Notes**](technical-docs/implementation_notes.md) — architectural decisions, runtime invariants, and policies
- [**Round-Trip Test Progress**](technical-docs/round_trip_test_progress.md) — NBN/NIN/IBI/BNB test results per model
- [**Scripts**](technical-docs/scripts.md) — standalone Blender scripts and how to run them
- [**Shiny Variants**](technical-docs/shiny_variants.md) — how the game stores shiny color data and how the addon implements it

## Community

If you're interested in reverse engineering the Pokemon games on the Gamecube/Wii consoles you can find us on discord:
www.discord.gg/xCPjjnv
