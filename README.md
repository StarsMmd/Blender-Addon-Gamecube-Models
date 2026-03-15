# Blender SysDolphin Addon
A Blender addon for importing gamecube .dat models into Blender. This addon is currently developed predominantly for `Pokemon Colosseum` and `Pokemon XD: Gale of Darkness` but may have some compatibility with other games that use the format (based on the sysdolphin library) such as `Super Smash Bros. Melee`, `Kirby Air ride`, `Chibi-Robo! Plug Into Adventure!` and `Killer7`.
Original implementation provided by Made. 

# How to use
Compress the the contents of this repository into a .zip file and then add that .zip file as an addon in Blender. This addon is targeted at Blender versions 3.1 and above, older versions may not work as intended. When the addon is enabled, navigate to File > Import > Gamecube model (.dat) and select your .dat model.

# Milestone Tracker

### 1. Animation Import
- [x] Frame / keyframe data parsing
- [x] Bone animation import
- [ ] Material animation import
- [ ] Shape animation import
- [ ] Animation looping (CYCLES modifier)

### 2. Geometry Details
- [ ] Bone weights / envelope deformation
- [ ] Shape keys / morph targets
- [ ] Custom normals assignment
- [ ] sRGB to linear colour conversion
- [ ] IK constraints
- [ ] Bone instances (`JOBJ_INSTANCE`)

### 3. Advanced Materials
- [ ] TEV colour multiply / comparison ops
- [ ] Environment mapping
- [ ] Pixel engine blending

### 4. Lights / Cameras / Fog
- [ ] Light import
- [ ] Camera import
- [ ] Fog import

### 5. Exporter
- [ ] Blender scene to node tree
- [ ] Address pre-allocation
- [ ] Binary write + relocation table
- [ ] Round-trip validation (parse → write → identical binary)

# Running Tests

Tests use **pytest** and run outside of Blender (no Blender installation required).

```bash
# Install pytest (once)
pip install pytest

# Run all tests from the addon directory
cd Blender-Addon-Gamecube-Models
pytest

# Run a specific test file
pytest tests/test_primitives.py

# Run with verbose output
pytest -v
```

Tests live in the `tests/` directory. Test data is generated programmatically — no game files are needed or should ever be committed.

# Community

If you're interested in reverse engineering the Pokemon games on the Gamecube/Wii consoles you can find us on discord:
www.discord.gg/xCPjjnv
