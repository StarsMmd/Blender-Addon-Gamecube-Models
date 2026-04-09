# File Format Specifications

Binary format references for GameCube SysDolphin files used by Pokémon Colosseum and XD: Gale of Darkness. All multi-byte values are **big-endian** (GameCube native byte order).

---

## GX Texture Formats

The GameCube GPU (GX) stores textures in tiled/blocked layouts. Each format divides the image into rectangular blocks, each stored contiguously in memory.

### Format Table

| ID | Name | BPP | Block (W×H) | Block Bytes | Palette | Description |
|----|------|-----|-------------|-------------|---------|-------------|
| 0x0 | I4 | 4 | 8×8 | 32 | No | 4-bit grayscale intensity |
| 0x1 | I8 | 8 | 8×4 | 32 | No | 8-bit grayscale intensity |
| 0x2 | IA4 | 8 | 8×4 | 32 | No | 4-bit intensity + 4-bit alpha |
| 0x3 | IA8 | 16 | 4×4 | 32 | No | 8-bit intensity + 8-bit alpha |
| 0x4 | RGB565 | 16 | 4×4 | 32 | No | 5-bit R, 6-bit G, 5-bit B |
| 0x5 | RGB5A3 | 16 | 4×4 | 32 | No | Mode bit: 1=RGB555, 0=ARGB3444 |
| 0x6 | RGBA8 | 32 | 4×4 | 64 | No | 8-bit per channel, stored as AR+GB interleaved blocks |
| 0x8 | C4 | 4 | 8×8 | 32 | Yes (16 entries) | 4-bit palette index |
| 0x9 | C8 | 8 | 8×4 | 32 | Yes (256 entries) | 8-bit palette index |
| 0xA | C14X2 | 16 | 4×4 | 32 | Yes (16384 entries) | 14-bit palette index + 2 unused bits |
| 0xE | CMPR | 4 | 8×8 | 32 | No | S3TC/DXT1 compression (4 sub-blocks of 4×4) |

### Block Layout

Images are divided into blocks of the specified W×H dimensions. Blocks are stored left-to-right, top-to-bottom. The image width and height are rounded up to block boundaries. Total blocks = `ceil(width/block_W) × ceil(height/block_H)`.

### RGBA8 Special Layout

RGBA8 blocks store alpha+red bytes first, then green+blue bytes:
```
[Block N: AR[0..15], GB[0..15]] — 64 bytes per 4×4 block
```

### RGB5A3 Mode Bit

```
Bit 15 = 1: RGB555   — bits [14:10]=R, [9:5]=G, [4:0]=B, A=255
Bit 15 = 0: ARGB3444 — bits [14:12]=A, [11:8]=R, [7:4]=G, [3:0]=B
```

### CMPR (S3TC/DXT1)

Each 8×8 block contains four 4×4 DXT1 sub-blocks (8 bytes each = 32 bytes total). Each sub-block has two RGB565 color endpoints and a 32-bit index table (2 bits per pixel). The 4-color palette is: c0, c1, (2c0+c1)/3, (c0+2c1)/3 when c0 > c1; or c0, c1, (c0+c1)/2, transparent when c0 ≤ c1.

### Palette Formats

Palettes for C4/C8/C14X2 use one of: IA8 (0x0), RGB565 (0x1), or RGB5A3 (0x2).

---

## PKX Model Container

PKX files wrap a DAT model binary with metadata for the game's battle system. Two variants exist: XD and Colosseum.

### Format Detection

Compare the uint32 values at offsets 0x00 and 0x40:
- **Different** → XD format
- **Same** → Colosseum format

### XD Format

**File layout:**
```
[Preamble: 0x00-0x83 (132 bytes)]
[Animation Metadata: 17 × 0xD0 bytes at offset 0x84]
[Padding: to 0x20 boundary]
[GPT1 particle data: if gpt1_length > 0, padded to 0x20]
[DAT model binary]
[Trailer: remaining bytes]
```

**Header size is dynamic:**
```
header_size = align32(0x84 + anim_count × 0xD0) + align32(gpt1_length)
```
For standard files (17 entries, no GPT1): `align32(0xE54) = 0xE60`

#### XD Preamble (0x00-0x83)

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0x00 | 4 | u32 | dat_file_size |
| 0x04 | 4 | u32 | *(reserved, always 0)* |
| 0x08 | 4 | u32 | gpt1_length |
| 0x0C | 4 | u32 | *(reserved, always 0)* |
| 0x10 | 4 | u32 | anim_section_count (always 17) |
| 0x14 | 4 | s32 | particle_orientation (-2 to +2) |
| 0x18 | 2 | u16 | species_id (Pokédex #, 0=trainer) |
| 0x1A | 2 | u16 | type_id (always 0x000C) |
| 0x1C | 19 | bytes | part_anim_data[0] — sleep-on |
| 0x2F | 19 | bytes | part_anim_data[1] — sleep-off |
| 0x42 | 19 | bytes | part_anim_data[2] — extra |
| 0x55 | 19 | bytes | part_anim_data[3] — usually inactive |
| 0x68 | 1 | u8 | flags |
| 0x69 | 1 | u8 | unknown |
| 0x6A | 2 | u16 | distortion_param |
| 0x6C | 1 | u8 | distortion_type |
| 0x6D | 1 | u8 | *(reserved)* |
| 0x6E | 2 | u16 | head_bone_index |
| 0x70 | 16 | 4×u32 | shiny_route RGBA (values 0-3) |
| 0x80 | 4 | 4×u8 | shiny_brightness RGBA (0x7F=neutral) |

**Flags byte (0x68):** bit 0=flying, bit 2=skip fractional frames, bit 6=remove root joint anim

**PartAnimData (19 bytes):** byte 0=has_data (0/1/2), byte 1=sub_param, bytes 2-17=bone_config (0xFF when unused), byte 18=anim_index_ref

#### Animation Metadata Entry (0xD0 bytes)

17 entries for both Pokémon and trainer models. Pokémon slots: [0]Idle, [1]Status1, [2-5]Physical1-4, [6]Status2, [7]Physical5, [8]Damage, [9]Damage2, [10]Faint, [11-16]Idle2/Special/Idle3-5/TakeFlight.

| Offset | Size | Type | Field | XD | Colosseum |
|--------|------|------|-------|----|----|
| 0x00 | 4 | u32 | anim_type | 2=loop, 3=hit, 4=action, 5=compound | Same |
| 0x04 | 4 | u32 | sub_anim_count (1-3) | Same | Same |
| 0x08 | 4 | u32 | damage_flags | Same | Same |
| 0x0C | 4 | u32 | *(reserved, 0)* | | |
| 0x10 | 4 | f32/u32 | timing_1 | float seconds | int frame count (60fps) |
| 0x14 | 4 | f32/u32 | timing_2 | float seconds | int frame count |
| 0x18 | 4 | f32/u32 | timing_3 | float seconds | int frame count |
| 0x1C | 4 | f32/u32 | timing_4 | float (compound only) | int frame count |
| 0x20-0x4B | 44 | | *(reserved, zeros)* | | |
| 0x4C | 64 | s32[16] | body_map_bones | Bone indices, -1=unused | Same |
| 0x8C | 8×N | pairs | sub_anims | [motion_type, anim_idx] | [0, anim_idx] |
| 0xCC | 4 | u32 | terminator | 3 | 1 |

**body_map_bones[N]:** 0=root, 1=head, 2=center/jaw, 3-15=body parts. Used for particle attachment, camera targeting, head tracking.

**Timing conversion:** Colosseum frames = round(XD seconds × 60)

### Colosseum Format

**File layout:**
```
[Header: 0x40 bytes]
[DAT: padded to 0x20 boundary]
[GPT1: padded to 0x20 boundary, if present]
[Animation Metadata: N × 0xD0 bytes]
[Shiny: 20 bytes at end of file]
```

#### Colosseum Header (0x40 bytes)

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0x00 | 4 | u32 | dat_file_size |
| 0x04 | 4 | u32 | gpt1_length |
| 0x08 | 4 | u32 | anim_section_count (16 or 17) |
| 0x0C | 4 | s32 | particle_orientation |
| 0x10 | 4 | u32 | unknown (always 5) |
| 0x14 | 4 | s32 | unknown |
| 0x18 | 4 | s32 | part_anim_ref_1 (-1=none) |
| 0x1C | 4 | s32 | part_anim_ref_2 (-1=none) |
| 0x20 | 4 | s32 | part_anim_ref_3 (-1=none) |
| 0x24-0x3F | | | *(zeros)* |

#### Colosseum Shiny Data (last 20 bytes of file)

```
[4 × u32: channel routing R,G,B,A (values 0-3)]
[1 × u32: ARGB brightness color]
```

---

## GPT1 Particle Container

GPT1 files contain particle effect definitions, textures, and bytecode command sequences that drive the particle system at runtime.

### Overall Layout

```
[Header: 32 bytes]
[PTL Section: generator definitions + command bytecode]
[TXG Section: texture group metadata]
[TEX Data: raw GX texture pixels]
[REF Section: generator ID lookup table]
```

All internal offsets are relative to the GPT1 file start.

### Header (32 bytes)

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0x00 | 4 | u32 | signature — `0x47505431` ("GPT1") for V1, `0x01F056DA` for V2 |
| 0x04 | 4 | u32 | ptl_offset — offset to PTL section (typically 0x20) |
| 0x08 | 4 | u32 | txg_offset — offset to TXG section |
| 0x0C | 4 | u32 | tex_length — total size of texture pixel data |
| 0x10 | 4 | u32 | ref_offset — offset to REF section |
| 0x14 | 12 | pad | *(zeros)* |

On load, the game relocates ptl_offset, txg_offset, and ref_offset by adding the GPT1 base address.

### PTL Section (Particle Template List)

```
[Header: version(2) + unknown(2) + skip_sections(4) + nb_generators(4)]
[Generator pointers: nb_generators × u32 (offsets from PTL start)]
[Padding to 8-byte alignment, filled with 0xFFFFFFFF]
[Generator definitions]
```

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0x00 | 2 | u16 | version (0x43 for V1 standard) |
| 0x02 | 2 | u16 | unknown |
| 0x04 | 4 | u32 | skip_sections (0 for most XD, 150-400 for some models) |
| 0x08 | 4 | u32 | nb_generators (3-28 in observed models) |
| 0x0C+ | 4×N | u32[] | generator offsets (relative to PTL start) |

**Version behavior:**
- Version 0: Old format — generator pointers at +0x08, `var04` = nb_generators
- Version 0x40-0x43: New format — extra `var08` field, pointers at +0x0C, NULL pointers allowed

### Generator Definition (0x3C header + variable-length bytecode)

| Offset | Size | Type | Field | Description |
|--------|------|------|-------|-------------|
| 0x00 | 2 | u16 | type | Generator type/flags (0 or 5 observed) |
| 0x02 | 2 | u16 | unknown_02 | Usually 0 |
| 0x04 | 2 | u16 | lifetime | Frame count (120 in all observed) |
| 0x06 | 2 | u16 | max_particles | Maximum concurrent particles (36-81) |
| 0x08 | 4 | u32 | flags | Generator flags (e.g. 0x01400001) |
| 0x0C | 4 | f32 | param_00 | Float parameter |
| 0x10 | 4 | f32 | param_01 | Float parameter |
| 0x14 | 4 | f32 | param_02 | Float parameter |
| 0x18 | 4 | f32 | param_03 | Float parameter |
| 0x1C | 4 | f32 | param_04 | Float parameter |
| 0x20 | 4 | f32 | param_05 | Float parameter |
| 0x24 | 4 | f32 | param_06 | Float parameter |
| 0x28 | 4 | f32 | param_07 | Float parameter |
| 0x2C | 4 | f32 | param_08 | Float parameter |
| 0x30 | 4 | f32 | param_09 | Float parameter |
| 0x34 | 4 | f32 | param_10 | Float parameter |
| 0x38 | 4 | f32 | param_11 | Float parameter |
| 0x3C+ | var | u8[] | command_sequence | Particle command bytecode |

The command sequence extends until the next generator's start offset or the TXG section boundary.

### TXG Section (Texture Group)

```
[u32: nb_containers]
[u32 × nb_containers: container offsets from TXG start]
[Padding to 32-byte alignment, 0xFFFFFFFF fill]
[TextureContainer × nb_containers]
```

#### TextureContainer

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0x00 | 4 | u32 | nb_textures |
| 0x04 | 4 | u32 | format (GX texture format ID) |
| 0x08 | 4 | u32 | data_offset (into TEX region, from GPT1 base) |
| 0x0C | 4 | u32 | width |
| 0x10 | 4 | u32 | height |
| 0x14 | 4 | u32 | nb_mipmaps |
| 0x18+ | 4×N | u32[] | texture offsets from TXG start |

### TEX Data

Raw GX-format texture pixels, referenced by TextureContainer.data_offset. Uses the same tiled block formats described in the GX Texture Formats section above.

### REF Section (Reference ID Table)

Array of `nb_generators` × u32 values. Each entry is a generator/particle ID used by spawn-from-ref commands (opcodes 0xAA, 0xF0, 0xF1, 0xF2).

### Particle Command Bytecode

Single-byte opcodes followed by variable-length arguments. Executed by `psInterpretParticle0` at runtime.

**Helper functions:**
- `getFloat()` — read big-endian f32 (4 bytes) from command stream
- `getTime()` — variable-length time value: reads 1 byte; if bit 7 is set, reads a second byte and combines into a 15-bit value: `(byte0 & 0x7F) << 8 | byte1`. Range: 0-127 (1 byte) or 0-32767 (2 bytes). Same extension scheme as the LIFETIME opcode.
- `HSD_Randf()` — random float in [0, 1)

#### Opcode Table

##### 0x00-0x7F: Lifetime + Texture Select

```
Bits: 0TExxxx
  Bits 0-4: Frame countdown value
  Bit 5 (E): Extended — countdown = (low5 << 8) | next_byte (same scheme as getTime)
  Bit 6 (T): Load texture — poseNum = next_byte; enable DispTexture if valid

The frame countdown pauses bytecode execution for N frames before continuing.
This is NOT the particle's total lifetime — it's a yield/delay within the
command sequence. The particle lives until EXIT (0xFE/0xFF) is reached.
```

##### 0x80-0x87: Set Position (bits 0-2 = X,Y,Z axis flags)
Each flagged axis reads a `getFloat()`. Result transformed by local rotation.

##### 0x88-0x8F: Move (add to position, same axis flags)

##### 0x90-0x97: Set Velocity (same axis flags)

##### 0x98-0x9F: Accelerate (add to velocity, same axis flags)

##### 0xA0-0xBF: Miscellaneous

| Opcode | Mnemonic | Arguments | Description |
|--------|----------|-----------|-------------|
| 0xA0 | SCALE | getTime, getFloat | Interpolate size over time |
| 0xA1 | TEX_OFF | — | Disable texture display |
| 0xA2 | GRAVITY | getFloat | Set gravity (0 disables) |
| 0xA3 | FRICTION | getFloat | Set friction (1.0 disables) |
| 0xA4 | SPAWN_PARTICLE | u16 id | Create particle at current position |
| 0xA5 | SPAWN_GENERATOR | u16 id | Create generator at current position |
| 0xA6 | RAND_KILL_TIMER | u16 base, u16 range | Kill timer = base + range × rand() |
| 0xA7 | RAND_KILL_CHANCE | u8 chance | Kill if chance < 100 × rand() |
| 0xA8 | RAND_OFFSET | 3× getFloat | Random position offset per axis |
| 0xA9 | MODIFY_DIR | getFloat | Modify direction |
| 0xAA | SPAWN_RAND_REF | u16 base, u16 count | Spawn from refs[base + count × rand()] |
| 0xAB | SCALE_VEL | getFloat | Multiply all velocity components |
| 0xAC | SCALE_RAND | getTime, getFloat | Size target += float × rand() |
| 0xAD | PRIMENV_ON | — | Enable PrimEnv color mode |
| 0xAE | MIRROR_OFF | — | Disable mirror S and T |
| 0xAF | MIRROR_S | — | Enable mirror S only |
| 0xB0 | MIRROR_T | — | Enable mirror T only |
| 0xB1 | MIRROR_ST | — | Enable mirror both S and T |
| 0xB2 | APPLY_APPSRT | — | Apply AppSRT transform to position |
| 0xB3 | ALPHA_CMP | getTime, u8 mode, u8 p1, u8 p2 | Alpha compare interpolation |
| 0xB4 | TEXINTERP_NEAR | — | Nearest-neighbor texture filtering |
| 0xB5 | TEXINTERP_LINEAR | — | Linear texture filtering |
| 0xB6 | ROTATE_RAND | getTime, getFloat | Rotation target += float |
| 0xB7 | VEL_TO_JOINT | u8 joint | Set velocity toward joint |
| 0xB8 | FORCES_JOINT | getFloat, getFloat, u8 | Gravity+friction from joint, kill on collision |
| 0xB9 | SPAWN_PARTICLE_VEL | u16 id | Create particle with current velocity |
| 0xBA | RAND_PRIMCOL | 4× u8 | Random primary color adjustment |
| 0xBB | RAND_ENVCOL | 4× u8 | Random environment color adjustment |
| 0xBC | SET_TEXTURE_IDX | u8 base, u8 range | poseNum = base + range × rand() |
| 0xBD | SET_SPEED | getFloat base, getFloat range | Normalize velocity to speed |
| 0xBE | SCALE_VEL_AXIS | 3× getFloat | Per-axis velocity scale |
| 0xBF | SET_JOINT | u8 id | Attach to bone joint |

##### 0xC0-0xCF: Set Primary Color Target (bits 0-3 = R,G,B,A flags)

Resolves current color interpolation, then: `time = getTime()`, for each flagged channel: `target = next_byte`. Starts interpolation if time > 0, else snaps.

##### 0xD0-0xDF: Set Environment Color Target (same pattern)

##### 0xE0-0xFF: Extended Commands

| Opcode | Mnemonic | Arguments | Description |
|--------|----------|-----------|-------------|
| 0xE0 | RAND_COLORS | 4× u8 | Set both primCol + envCol randomly |
| 0xE1 | SET_CALLBACK | u8 | Set particle update callback |
| 0xE2 | TEXEDGE_ON | — | Enable texture edge |
| 0xE3 | SET_PALETTE | u8 | Set palette number |
| 0xE4 | FLIP_S | u8 (0=off,1=on,2=toggle,3=random) | Control S-axis flip |
| 0xE5 | FLIP_T | u8 | Control T-axis flip |
| 0xE6 | DIRVEC_ON | — | Enable direction vector mode |
| 0xE7 | DIRVEC_OFF | — | Disable direction vector mode |
| 0xE8 | SET_TRAIL | getFloat | Set trail length (negative disables) |
| 0xE9 | RAND_PRIMENV | u8 flags, u8 count, var args | Complex random color adjustment |
| 0xEA | MAT_COLOR | getTime, u8 flags, var u8 | Material color interpolation |
| 0xEB | AMB_COLOR | getTime, u8 flags, var u8 | Ambient color interpolation |
| 0xEC | CUSTOM_FLOAT | u8 idx, getFloat | Write to custom parameter array |
| 0xED | RAND_ROTATE | getFloat, getFloat, u8 | Random rotation with range |
| 0xEF | SPAWN_GEN_FLAGS | u16 id, u8 flags | Create generator with extra flags |
| 0xF0 | SPAWN_GEN_REF_FLAGS | u16 ref, u8 flags | Create generator from REF with flags |
| 0xF1 | SPAWN_PARTICLE_REF | u16 ref | Create particle from REF at position |
| 0xF2 | SPAWN_PARTICLE_REF_VEL | u16 ref | Create particle from REF with velocity |
| 0xF3 | ROTATE_ACCEL | u8 dir, getFloat rate, getFloat accel, getTime | Rotation with acceleration |
| 0xF4 | GEN_DIR_BASE | 4× getFloat | Set generator direction base |
| 0xF5 | GEN_FLAG_2000 | — | Set generator joint tracking flag |
| 0xF6 | GEN_FLAG_1000 | — | Set generator joint tracking flag |
| 0xF7 | NO_ZCOMP | — | Disable Z comparison |
| 0xFA | LOOP_START | u8 count | Begin loop, save position |
| 0xFB | LOOP_END | — | Decrement counter, jump if nonzero |
| 0xFC | SAVE_JUMP | — | Save current position |
| 0xFD | JUMP | — | Jump to saved position |
| 0xFE | EXIT | — | Kill particle |
| 0xFF | EXIT | — | Kill particle |

### Particle Flags Bitfield (runtime `kind` / `var04`)

| Bit(s) | Mask | Name | Description |
|--------|------|------|-------------|
| 0 | 0x00000001 | APPLYGRAVITY | Apply gravity each frame |
| 1 | 0x00000002 | APPLYFRICTION | Apply friction each frame |
| 2 | 0x00000004 | Tornado | Tornado motion mode |
| 3 | 0x00000008 | TexEdge | Texture edge rendering |
| 4 | 0x00000010 | ComTLUT | Common TLUT palette |
| 5 | 0x00000020 | MirrorS | Mirror texture S axis |
| 6 | 0x00000040 | MirrorT | Mirror texture T axis |
| 7 | 0x00000080 | PrimEnv | Use primary + environment color registers |
| 9 | 0x00000200 | TexInterpNear | Nearest-neighbor texture filtering |
| 10 | 0x00000400 | DispTexture | Display texture on particle |
| 11 | 0x00000800 | SkipInterp | Skip interpretation |
| 12-14 | 0x7000 | JointID | Bone attachment ID (3 bits) |
| 15 | 0x00008000 | UpdateJoint | Update joint position each frame |
| 18 | 0x00040000 | TexFlipS | Flip texture S axis |
| 19 | 0x00080000 | TexFlipT | Flip texture T axis |
| 20 | 0x00100000 | Trail | Enable trail rendering |
| 21 | 0x00200000 | DirVec | Direction vector mode |
| 22-23 | 0x00C00000 | BlendMode | Blend mode (2 bits) |
| 24 | 0x01000000 | DispFog | Display fog |
| 28 | 0x10000000 | NoZComp | Disable Z comparison |
| 30 | 0x40000000 | DisPoint | Disable point rendering |
| 31 | 0x80000000 | DispLighting | Enable lighting calculations |

### V2 Format (0x01F056DA)

A different container format used by some XD files. Uses 16 subsections of 0x3C bytes each, loaded via `peBankLoadFile`. Not yet fully documented.

---

## DAT Model Binary

The DAT format is the core SysDolphin model container used across GameCube games. Documented separately in the codebase's node system and IR specification. Key structural elements:

### DAT Header (32 bytes)

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0x00 | 4 | u32 | file_size (total, including header) |
| 0x04 | 4 | u32 | data_block_size |
| 0x08 | 4 | u32 | relocation_count |
| 0x0C | 4 | u32 | root_count |
| 0x10 | 4 | u32 | reference_count |
| 0x14 | 12 | pad | *(zeros)* |

After the header: data block, relocation table (root_count × u32 offsets), root entries (root_count × {node_offset, string_offset}), reference entries (ref_count × {node_offset, string_offset}), string table.

See `documentation/ir_specification.md` for the full node hierarchy.

---

## CAM Camera File

CAM files are standard DAT binaries (same 32-byte header, relocation table, root/reference entries) containing camera and light scene data. They use `scene_data` as their root section name, with `CameraSet` and `LightSet` nodes inside the `SceneData`.

- **FSYS file type ID:** `0x18`
- **File extension:** `.cam`
- **Content:** Camera position/target/FOV/roll/clip planes + optional animations + optional light sets
- **Corpus:** 78 files in XD (sizes 475–9,915 bytes), all 12 with cameras have animation data

No special container handling is needed — `.cam` files pass through the normal DAT import pipeline. The `describe_scene` phase extracts cameras from `SceneData.camera` and lights from `SceneData.lights`.

### CameraSet Structure

```
CameraSet
├── camera (Camera)
│   ├── position (WObject → static eye position vec3)
│   ├── interest (WObject → static target position vec3)
│   ├── field_of_view, roll, near, far, aspect
│   └── viewport, scissor (640×480)
└── animations (CameraAnimation[])
    ├── animation (Animation/AOBJ → FOV/roll/near/far keyframes)
    ├── eye_position_animation (WObjectAnimation → eye position XYZ keyframes)
    └── interest_animation (WObjectAnimation → target position XYZ keyframes)
```

**WObjectAnimation** (8 bytes, NOT WObjDesc) is a separate struct from WObject:
- `+0x00`: Animation pointer (AOBJ with position X/Y/Z keyframes via `HSD_A_W_TRAX/Y/Z`)
- `+0x04`: RObjAnimation pointer (render object animations, optional)

### Camera Animation Track Types

Decoded from the CObj AOBJ Frame chain (`CObjUpdateFunc` dispatch table):

| Type | HSD Constant | Property |
|------|-------------|----------|
| 1 | `HSD_A_C_EYEX` | Eye position X |
| 2 | `HSD_A_C_EYEY` | Eye position Y |
| 3 | `HSD_A_C_EYEZ` | Eye position Z |
| 5 | `HSD_A_C_ATX` | Target position X |
| 6 | `HSD_A_C_ATY` | Target position Y |
| 7 | `HSD_A_C_ATZ` | Target position Z |
| 9 | `HSD_A_C_ROLL` | Camera roll angle |
| 10 | `HSD_A_C_FOVY` | Vertical field of view |
| 11 | `HSD_A_C_NEAR` | Near clip plane |
| 12 | `HSD_A_C_FAR` | Far clip plane |

Eye/target position can also be animated via WObjectAnimation AOBJs using `HSD_A_W_TRAX` (5), `HSD_A_W_TRAY` (6), `HSD_A_W_TRAZ` (7). All keyframes use the same FObjDesc encoding as bone and material animations.

---

## WZX Effect Container

WZX files are **WazaSequence** containers — move and overworld effect animations used by the battle system and field engine. They are stored inside FSYS archives with file type ID `0x20`, extracted to `/Assets/Models/effects/` by the GoD Tool. Each WZX file defines a complete effect sequence composed of sub-entries (particles, models, sounds, camera moves, etc.).

**Known corpus:** 1,098 Colosseum files + 1,401 XD files.

### Overall Layout

```
[Main SequenceEntry: 0x70 bytes at file offset 0x00]
[Section Header: 0x20 bytes at file offset 0x70, padded to 0xA0]
[Optional HSD Archive (DAT): align32(size) bytes at 0xA0]
[Sub-entries × (entry_count − 1)]
[Next section repeats: SequenceEntry → Header → content → sub-entries ...]
```

Multi-phase effects (e.g. attack + damage + special) chain multiple sections end-to-end. Empty effects (7 observed) are exactly 0xA0 bytes — one main entry + one header with zero sub-entries.

### Format Detection

Bytes 0x10–0x1B are always `FF FF FF FF FF FF FF FF FF FF FF FF` (12 bytes of 0xFF). This sentinel distinguishes WZX from DAT (which has a file_size u32 at 0x00) and PKX (which has different header patterns). The version field at offset 0x80 is always 5 (Colosseum) or 6 (XD).

### SequenceEntry (0x70 bytes)

Every entry — both the main entry at file offset 0x00 and each sub-entry — shares this structure. Derived from the `SequenceEntry` constructor in the XD disassembly (`wazaSequenceEntry/__ct__13SequenceEntryF25enumSequenceEntryDataTypeP12WazaSequencePPUc.s`).

| Offset | Size | Type | Field | Notes |
|--------|------|------|-------|-------|
| 0x00 | 4 | u32→u8 | identifier | Stored as low byte |
| 0x04 | 4 | u32 | entry_type | Dispatch key (0–7), see sub-entry types |
| 0x08 | 4 | u32→u8 | param_a | |
| 0x0C | 4 | u32→u8 | param_b | |
| 0x10 | 4 | s32→u8 | timing_start | Negative → 0xFF |
| 0x14 | 4 | s32→u8 | timing_hit | Negative → 0 |
| 0x18 | 4 | s32→u8 | timing_end | Negative → 0 |
| 0x1C | 4 | u32→u8 | bone_attachment | |
| 0x20 | 64 | raw | extra_data | Type-specific; pointer stored at runtime |
| 0x60 | 4 | u32→u16 | param_c | |
| 0x64 | 4 | u32→u16 | param_d | |
| 0x68 | 4 | — | *(not read)* | Often matches version (2 or 3) |
| 0x6C | 4 | u32→u8 | link_ref | Reference to another entry by ID |

**Main entry (file offset 0x00):** In all observed files, `timing_start/hit/end` are −1 (0xFFFFFFFF), `bone_attachment` is 2–4, and `entry_type` is 0. The 64-byte `extra_data` block (0x20–0x5F) is typically all zeros.

### Section Header (0x20 bytes at file offset 0x70)

Read by `WazaSequence::Load` / `WazaSequence::LoadData` after consuming the main entry. All offsets are relative to the header start; file offsets shown for reference.

| Header Offset | File Offset | Size | Type | Field |
|--------------|-------------|------|------|-------|
| 0x00 | 0x70 | 2 | u16 | speed_value |
| 0x02 | 0x72 | 2 | u16 | variation_slot |
| 0x04 | 0x74 | 4 | u32 | entry_count (sub_entries = value − 1) |
| 0x08 | 0x78 | 4 | u32 | flags |
| 0x0C | 0x7C | 4 | u32 | param (low byte used) |
| 0x10 | 0x80 | 4 | u32 | version (5 = Colosseum, 6 = XD) |
| 0x14 | 0x84 | 4 | u32 | hsd_archive_size (0 = none) |
| 0x18 | 0x88 | 4 | u32 | unknown |
| 0x1C | 0x8C | 4 | u32 | camera_resource (non-zero = load camera) |

**Version behavior:**
- version ≤ 3: `flags |= 0x78`
- version ≤ 5: `flags &= ~0x3F80` (clear bits 7–13)
- version ≥ 6 (XD): `speed_value` converted from u16 to float via `(float)speed_value / constant`

**HSD Archive:** When `hsd_archive_size` > 0, a standard DAT binary begins at file offset 0xA0 (after align32 padding of the section header). Parsed by `HSD_ArchiveParse`. The data pointer advances by `align32(hsd_archive_size)`.

**Camera:** When `camera_resource` is non-zero, a camera DAT of `hsd_archive_size` bytes is loaded via `loadCamera`. The data pointer advances by `align32(hsd_archive_size)`.

### Sub-Entry Types

After the section header (and optional HSD archive), sub-entries follow sequentially. Each starts with a 0x70-byte SequenceEntry header. The `entry_type` field at offset +0x04 determines which loader handles the type-specific extra data that follows.

| Type | Name | Extra Data | Description |
|------|------|-----------|-------------|
| 0 | Camera | 0x0C bytes; if [0x00]=3: + [0x04]×8 bytes | Camera animation keyframes |
| 1 | Model | align32(0x28) + optional DAT | 3D model with HSD scene data |
| 2 | Particle | align32(0x14) + align32(particle_size) | Particle effect (GPT1/GPT1v2) |
| 3 | Effect | 0x0C header + variable (10 sub-types) | Composite effect (see below) |
| 4 | Sound | 0x14 bytes | Sound effect reference |
| 5 | Event | 0x08 bytes | Script event trigger |
| 6 | LensFlare | align32(0x14) + align32([0x00]) | Lens flare effect data |

#### Model Extra Data (0x28 bytes)

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0x00 | 4 | u32 | anim_type |
| 0x04 | 4 | u32 | anim_mode |
| 0x08 | 4 | u32 | render_flags |
| 0x0C | 4 | u32 | render_mode |
| 0x10 | 4 | u32 | scale_sign (negative = flag set) |
| 0x14 | 4 | u32 | param |
| 0x18 | 4 | u32 | param2 |
| 0x1C | 4 | u32 | dat_size (0 = no embedded DAT) |
| 0x20 | 4 | u32 | model_resource_id (loaded via `loadModel`) |
| 0x24 | 4 | u32 | unknown |

When `dat_size` > 0, a DAT binary follows immediately after the align32(0x28) extra header, parsed by `HSD_ArchiveParse`.

#### Particle Extra Data (0x14 bytes)

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0x00 | 4 | u32 | unknown |
| 0x04 | 4 | u32 | unknown |
| 0x08 | 4 | u32 | particle_data_size |
| 0x0C | 4 | u32 | particle_bank (set at runtime, 0 in file) |
| 0x10 | 4 | u32 | unknown |

Particle data (GPT1 or GPT1v2) of `particle_data_size` bytes follows after align32 padding. Loaded by `GSparticleLoad`.

#### Effect Sub-Types (0–9)

The Effect entry has a 0x0C-byte header where offset 0x00 is the sub-type ID (0–9). Each sub-type has different variable-length data. The full sub-type dispatch table (at `lbl_80412E38` in the DOL) has not been fully mapped. Known sub-type behaviors:

- **Animation keyframes:** 0x10-byte header with block count at +0x04, followed by count × 0x10-byte keyframe blocks. A XOR byte-swap is applied in-place (swaps bytes 0↔3, 1↔2, 4↔7, 5↔6 within each block).
- **Embedded HSD archive:** 0x40-byte or 0x20-byte header with DAT size, followed by DAT data parsed by `HSD_ArchiveParse`.
- **Embedded particle:** 0x18-byte header with particle size at +0x0C, followed by particle data loaded by `GSparticleLoad`.

### Colosseum vs XD Differences

| Aspect | Colosseum | XD |
|--------|-----------|-----|
| Version field (0x80) | 5 | 6 |
| Particle format | GPT1 V1 (`0x47505431`) | GPT1 V2 (`0x01F056DA`) |
| Speed value | Not used (default float) | u16 → float conversion |
| Flag adjustments | `flags \|= 0x78`, clear bits 7–13 | None |

### DOL Reference Tables (XD US)

The game's executable contains two tables that map moves to WZX effect animations.

#### WZXMoveAnimation (DOL 0x4095C8, RAM 0x8040C5C8)

373 entries × 6 bytes — one per move. Each entry indexes into the WZXAnimation table:

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0x00 | 2 | u16 | attack_animation_index |
| 0x02 | 2 | u16 | damage_animation_index |
| 0x04 | 2 | u16 | special_animation_index |

#### WZXAnimation (DOL 0x40D0F0, RAM 0x804100F0)

1,399 entries × 8 bytes — maps animation indices to FSYS archive resources:

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0x00 | 4 | u32 | fsys_group_id |
| 0x04 | 4 | u32 | wzx_file_id |

#### Loading Flow

```
Move ID → WZXMoveAnimation[move_id].attack_index
       → WZXAnimation[attack_index].fsys_group_id
       → Load FSYS archive → Extract WZX file
       → floorReadWZXPreFunc (allocate + lock)
       → floorReadWZXPostFunc (GSresGetResource → WazaSequence::Load)
```

### Disassembly Sources

Reverse-engineered from the XD US DOL disassembly at `GoD-Tool/scripts/Disassembly XD/text1/`:
- `wazaSequence/Load__12WazaSequenceFPUcUlUl.s` — static loader
- `wazaSequence/LoadData__12WazaSequenceFPUc.s` — instance loader with version checks
- `wazaSequenceEntry/__ct__13SequenceEntryF...s` — 0x70-byte entry format
- `wazaSequenceEntry/Load__13ParticleEntryFPPUc.s` — particle data layout
- `wazaSequenceEntry/Load__10ModelEntryFPPUc.s` — model + embedded DAT layout
- `wazaSequenceEntry/Load__11EffectEntryFPPUc.s` — effect sub-type dispatch
- `floorRead/floorReadWZXPostFunc.s` — WZX load entry point

The XD symbol map (`GXXE.map`) provides function addresses and sizes for cross-referencing.

---

## PKX Format — Behavioral Reference

How the game uses PKX metadata at runtime. Complements the binary layout above with behavioral semantics discovered from the XD disassembly.

### Animation System

#### Battle Animation Slots (17 entries)

Each PKX has 17 animation metadata entries. For Pokémon models:

| Slot | Name | Typical Type | Description |
|------|------|-------------|-------------|
| 0 | Idle | loop | Default standing animation |
| 1 | Status 1 | action | Status move animation (sleep, poison, etc.) |
| 2-5 | Physical 1-4 | action | Physical attack animations |
| 6 | Status 2 | action | Second status animation |
| 7 | Physical 5 | action | Fifth physical attack |
| 8 | Damage | hit_reaction | Taking damage |
| 9 | Damage 2 | compound | Taking heavy damage (chains two animations) |
| 10 | Faint | hit_reaction | Fainting animation |
| 11-16 | Idle 2-5, Special, Take Flight | varies | Situational / unused |

#### Animation Index Sharing

Multiple slots can reference the SAME DAT animation index. For example, absol:
- Physical 1-5 all reference animation index 2 (one animation for all physical attacks)
- Damage and Damage 2 both reference index 4

Inactive slots (motion_type=0) fall back to a default index but are not actively used.

#### Animation Types

| Value | Name | Behavior |
|-------|------|----------|
| 2 | loop | Plays continuously (idle, breathing) |
| 3 | hit_reaction | Plays once when hit, returns to idle |
| 4 | action | Plays once (attacks, poses) |
| 5 | compound | Chains two animations (e.g., damage then faint) |

#### Timing Breakpoints

Each entry has 4 float timing values (seconds). These define transition points within the animation playback — wind-up, impact, recovery phases. Colosseum stores these as integer frame counts at 60fps.

### Sub-Animation System (PartAnimData)

#### Overview

Four PartAnimData blocks (19 bytes each in XD) define **overlay animations** that play on top of the current battle animation. The game overlays them using `GSmodelSetPartAnimIndex`, which targets specific bones with a dedicated animation.

#### Triggers

| Block | Trigger | Example |
|-------|---------|---------|
| 0 | Sleep On | Eyelids close when put to sleep |
| 1 | Sleep Off | Eyelids open when waking up |
| 2 | Extra | Blinking, breathing, wing flapping |
| 3 | (Unused) | Typically inactive |

#### Sub-Animation Types

| Value | Name | Behavior |
|-------|------|---------|
| 0 | none | Block is inactive |
| 1 | simple | Animation plays on ALL bones (whole-body pose) |
| 2 | targeted | Animation plays on specific bones only |

#### Targeted Bone Indices

For type=2 (targeted), the `bone_config` bytes (bytes 2-9 of the block) specify which bone indices participate. Up to 8 bones, with 0xFF marking unused slots.

Examples:
- **Moltres** block 2: bone 116 plays animation 10 (wing fire animation)
- **Mage** block 2: bones 39, 40, 30, 29 play animation 1 (cape/cloth movement)
- **Umbreon** block 2: bone 78 plays animation 6 (ring glow)

#### Sub-Animations Are Target Poses

Sub-animation DAT indices reference **extra animations beyond the 17 battle slots**. These animations are real bone animation sets with keyframe data, but they're typically 2-frame static poses — they define WHERE the bones should be, not a transition.

The game engine smoothly blends from the current battle animation to the sub-animation's target pose. Our importer imports them as separate actions but they can't be properly previewed in Blender without NLA track layering.

#### Identifying Sub-Animations

Sub-animation `anim_ref` values are typically higher than the max battle animation index:
- Absol: battle anims 0-4, sub-anims 5, 6, 7
- Moltres: battle anims 0-9, sub-anims 10, 11, 12

### Shiny Color System

#### How It Works

The shiny filter is a hardware-level color transformation applied globally to ALL materials on the model:

1. **Channel Routing** (`GSmodelEnableColorSwap`): Remaps which texture color channels are read. Uses GX's `GXSetTevSwapModeTable` to swap R/G/B/A at the TEV stage level. Iterates all materials and calls `GSmaterialSetColorChannels` on each.

2. **Brightness Modulation** (`GSmodelEnableModulation`): Scales RGB channels by a per-channel factor. Also iterates all materials.

#### Alpha Brightness Forced to Max

The game forces the alpha brightness byte to 0xFF before applying modulation (line 223 in `__ct__13ModelSequenceFUsUlb`). This means shiny brightness ONLY affects RGB — alpha is untouched.

#### No Per-Material Selectivity

Both routing and brightness apply to ALL materials uniformly. There is no per-material or per-mesh control in the PKX metadata.

#### Brightness Encoding

| Byte Value | Float | Multiply Factor | Effect |
|-----------|-------|-----------------|--------|
| 0 | -1.0 | 0.0 | Black |
| 64 | -0.50 | 0.5 | Half brightness |
| 127 | 0.0 | 1.0 | Unchanged |
| 191 | 0.50 | 1.5 | 1.5× bright |
| 255 | 1.0 | 2.0 | 2× bright |

#### Color Space

The GameCube renders in gamma space (no linear pipeline). The shiny brightness multiplication happens in gamma/sRGB space. Blender operates in linear space. Our shader nodes convert linear→sRGB before multiplying, then sRGB→linear after, to match the game's visual output.

### Body Map (Null Joint Bones)

16 bone indices stored per animation entry, accessed by `GetPart__13ModelSequenceF17enumNullJointName` in the game code. Used for particle attachment, camera targeting, and head tracking.

| Index | Name | Purpose |
|-------|------|---------|
| 0 | Root | Always bone 0 |
| 1 | Head | Head tracking rotation target |
| 2 | Center | Center null / jaw bone (fallback for `GSmodelCenterNull`) |
| 3 | Body 3 | Generic body attachment |
| 4 | Neck | Typically head bone - 1 |
| 5 | Head Top | Typically head bone + 1 |
| 6 | Limb Left | Left limb (from the Pokémon's perspective, not the viewer's) |
| 7 | Limb Right | Right limb (from the Pokémon's perspective, not the viewer's) |
| 8-11 | Secondary | Less commonly used attachments |
| 12-15 | Attach A-D | Particle/effect attachment points |

Values are mostly consistent across all 17 entries within a model. Per-entry overrides exist for entries where different animations need different attachment points.

### Flags

| Bit | Mask | Name | Description |
|-----|------|------|-------------|
| 0 | 0x01 | Flying | Enables Take Flight animation and hovering mode |
| 2 | 0x04 | Skip Fractional Frames | Integer frame stepping instead of interpolated |
| 6 | 0x40 | No Root Animation | Locks the root bone's position in place |
| 7 | 0x80 | Unknown | Only observed on Espeon (eifie.pkx) |

### Particle Orientation

Signed integer (-2 to +2) controlling rotation angle for sleep and ice particle effects attached to the model. Used by `SetFlags` to orient particle generators via a switch-case lookup table mapping each value to a specific rotation angle.

### Colosseum Differences

- Animation timing stored as integer frame counts at 60fps (XD uses float seconds)
- Sub-animation entries have motion_type always 0
- Animation terminator value is 1 (XD uses 3)
- PKX header is 0x40 bytes (XD is variable, typically 0xE60)
- Animation metadata comes AFTER DAT+GPT1 data (XD stores in header)
- Shiny data is last 20 bytes of file (XD stores at 0x70-0x83 in header)
- Shiny brightness stored as ARGB (XD stores as RGBA bytes)
- Animation section count can be 16 (XD is always 17)

### Disassembly Reference

| Function | File | Purpose |
|----------|------|---------|
| `LoadData__13ModelSequenceFPUc` | modelSequence/ | Parses PKX header, sets up shiny, loads DAT |
| `GSmodelEnableColorSwap` | GSmodelExt/ | Applies channel routing to all materials |
| `GSmodelEnableModulation` | GSmodelExt/ | Applies brightness to all materials |
| `HSD_InitColorSwapTable` | tev/ | Sets GX TEV swap mode table entries |
| `GetPart__13ModelSequenceF17enumNullJointName` | modelSequence/ | Looks up null joint bones by enum |
| `DoAnimation__13ModelSequenceFi21enumSectionMotionTypeb` | modelSequence/ | Plays battle animation by slot |
| `SetFlags__13ModelSequenceFUc` | modelSequence/ | Triggers sub-animations (sleep particles) |
| `wazaSequenceSysPartAnimationStart` | wazaSequenceSys/ | Starts targeted sub-animation on bones |
| `psInterpretParticle0` | psinterpret/ | Particle bytecode interpreter (3358 lines) |
| `generateParticle` | generator/ | Particle emission from generator params (1454 lines) |
