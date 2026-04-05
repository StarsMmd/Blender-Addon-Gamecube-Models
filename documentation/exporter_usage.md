# Exporter Usage

> **Status:** Work in progress — skeleton, mesh (including envelope skinning), material, and texture export functional. Animations, constraints, and lights not yet implemented.

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
| Bone Weights / Skinning | ✅ Working (single-bone + envelope/weighted) |
| Materials (colors, properties) | ✅ Working |
| Textures (all GX formats) | ✅ Working (preserves original format on re-export) |
| Bone Animations | ⚠️ Placeholder stubs (rest-pose only) |
| Material Animations (color/alpha) | Not yet implemented |
| Material Animations (texture UV) | Not yet implemented |
| Lights | Not yet implemented |
| Bone Constraints | Not yet implemented |
| Shape Animations | Not yet implemented |
| Bound Box | ✅ Working (static AABB per animation slot) |

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

### Ambient Lighting

The game uses per-material ambient colors to control how materials respond to ambient light. In Blender, this is approximated with an Emission node.

To set up ambient lighting for export:
1. Add an Emission node named `dat_ambient_emission` to the material
2. Set its Color to the desired ambient color
3. Add an Add Shader node named `dat_ambient_add` to mix it with the main shader
4. Connect: `main_shader → Add Shader input 0`, `Emission → Add Shader input 1`, `Add Shader → Material Output`

The exporter reads the ambient color from the `dat_ambient_emission` node. If no such node exists, a default of (0.5, 0.5, 0.5) is used.

Use the standalone script `scripts/add_ambient_lighting.py` to add ambient nodes to all materials at once.

### Specular Color

The exporter computes the specular color from Blender's Principled BSDF Specular Tint and diffuse color. No manual setup is needed — the exporter reads the Specular Tint value and reverse-maps it to the game's absolute specular color.

### Base Model

_WIP_

### Bound Boxes

Bound boxes are generated automatically from the model's mesh vertices. Each animation slot gets an axis-aligned bounding box (AABB) encompassing the full model extent.

### Shiny Filter

_WIP_

---

## How to Export

Export via **File > Export > Gamecube model (.dat)** in Blender.

### Output Formats

- **`.dat`** — Standalone DAT model file. Can be exported from scratch.
- **`.pkx`** — PKX container wrapping a DAT model. Exporting to `.pkx` requires an existing `.pkx` file at the output path — the exporter injects the new model into the existing container, preserving the PKX header. Creating a new `.pkx` from scratch is not yet supported.

---

## How to Use the New Model in Game

> This section is a work in progress.

For guidance on replacing model files in a game ISO, visit the community Discord: www.discord.gg/xCPjjnv
