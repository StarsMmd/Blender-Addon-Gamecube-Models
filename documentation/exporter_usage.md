# Exporter Usage

> **Status:** Work in progress — skeleton and mesh export functional, materials and animations not yet implemented.

The exporter writes a Blender scene to a `.dat` or `.pkx` binary that can be used in Pokemon Colosseum or Pokemon XD: Gale of Darkness. The output is not directly compatible with other games that use `.dat` models (e.g. Super Smash Bros. Melee).

---

## Supported Features

| Feature | Status |
|---|---|
| Skeleton / Bones | ✅ Working |
| Meshes (geometry, faces) | ✅ Working |
| UV Mapping | ✅ Working |
| Vertex Colors | ✅ Working |
| Normals | ✅ Working |
| Bone Weights / Skinning | ✅ Working (single-bone) |
| Materials (colors, properties) | Not yet implemented |
| Textures | Not yet implemented |
| Bone Animations | Not yet implemented |
| Material Animations (color/alpha) | Not yet implemented |
| Material Animations (texture UV) | Not yet implemented |
| Lights | Not yet implemented |
| Bone Constraints | Not yet implemented |
| Shape Animations | Not yet implemented |
| Bound Box | Not yet implemented |

---

## How to Prepare a Model for Export

> This section is a work in progress.

### Armature Selection

The exporter exports **the currently selected armature(s)** in the scene. Each selected armature becomes one model in the output file.

- Select the armature(s) you want to export before running the exporter
- Meshes parented to a selected armature are automatically included
- Meshes not parented to any selected armature are ignored

### Bone Visibility

Hidden bones in Blender are exported as hidden bones in the DAT file. Toggle bone visibility in the armature to control this.

### Mesh-to-Bone Binding

Each mesh must be parented to the armature. Bone assignments are determined from vertex groups:

- **Weighted skinning**: Meshes with vertex groups assigned to multiple bones
- **Single-bone binding**: Meshes where all vertices belong to one bone's vertex group
- **No vertex groups**: Meshes with no vertex groups are bound to the root bone

### Base Model

_WIP_

### Bound Boxes

_WIP_

### Shiny Filter

_WIP_

---

## How to Export

> This section is a work in progress. The exporter is not yet functional.

Once implemented, exporting will be available via **File > Export > Gamecube model (.dat)** in Blender.

### Output Formats

- **`.dat`** — Standalone DAT model file. Can be exported from scratch.
- **`.pkx`** — PKX container wrapping a DAT model. Exporting to `.pkx` requires an existing `.pkx` file at the output path — the exporter injects the new model into the existing container, preserving the PKX header. Creating a new `.pkx` from scratch is not yet supported.

---

## How to Use the New Model in Game

> This section is a work in progress.

For guidance on replacing model files in a game ISO, visit the community Discord: www.discord.gg/xCPjjnv
