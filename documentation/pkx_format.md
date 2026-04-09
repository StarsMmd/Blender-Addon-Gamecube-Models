# PKX Format — Behavioral Reference

How the game uses PKX metadata at runtime. Complements the binary layout in `file_formats.md` with behavioral semantics discovered from the XD disassembly.

---

## Animation System

### Battle Animation Slots (17 entries)

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

### Animation Index Sharing

Multiple slots can reference the SAME DAT animation index. For example, absol:
- Physical 1-5 all reference animation index 2 (one animation for all physical attacks)
- Damage and Damage 2 both reference index 4

Inactive slots (motion_type=0) fall back to a default index but are not actively used.

### Animation Types

| Value | Name | Behavior |
|-------|------|----------|
| 2 | loop | Plays continuously (idle, breathing) |
| 3 | hit_reaction | Plays once when hit, returns to idle |
| 4 | action | Plays once (attacks, poses) |
| 5 | compound | Chains two animations (e.g., damage then faint) |

### Timing Breakpoints

Each entry has 4 float timing values (seconds). These define transition points within the animation playback — wind-up, impact, recovery phases. Colosseum stores these as integer frame counts at 60fps.

---

## Sub-Animation System (PartAnimData)

### Overview

Four PartAnimData blocks (19 bytes each in XD) define **overlay animations** that play on top of the current battle animation. The game overlays them using `GSmodelSetPartAnimIndex`, which targets specific bones with a dedicated animation.

### Triggers

| Block | Trigger | Example |
|-------|---------|---------|
| 0 | Sleep On | Eyelids close when put to sleep |
| 1 | Sleep Off | Eyelids open when waking up |
| 2 | Extra | Blinking, breathing, wing flapping |
| 3 | (Unused) | Typically inactive |

### Sub-Animation Types

| Value | Name | Behavior |
|-------|------|---------|
| 0 | none | Block is inactive |
| 1 | simple | Animation plays on ALL bones (whole-body pose) |
| 2 | targeted | Animation plays on specific bones only |

### Targeted Bone Indices

For type=2 (targeted), the `bone_config` bytes (bytes 2-9 of the block) specify which bone indices participate. Up to 8 bones, with 0xFF marking unused slots.

Examples:
- **Moltres** block 2: bone 116 plays animation 10 (wing fire animation)
- **Mage** block 2: bones 39, 40, 30, 29 play animation 1 (cape/cloth movement)
- **Umbreon** block 2: bone 78 plays animation 6 (ring glow)

### Sub-Animations Are Target Poses

Sub-animation DAT indices reference **extra animations beyond the 17 battle slots**. These animations are real bone animation sets with keyframe data, but they're typically 2-frame static poses — they define WHERE the bones should be, not a transition.

The game engine smoothly blends from the current battle animation to the sub-animation's target pose. Our importer imports them as separate actions but they can't be properly previewed in Blender without NLA track layering.

### Identifying Sub-Animations

Sub-animation `anim_ref` values are typically higher than the max battle animation index:
- Absol: battle anims 0-4, sub-anims 5, 6, 7
- Moltres: battle anims 0-9, sub-anims 10, 11, 12

---

## Shiny Color System

### How It Works

The shiny filter is a hardware-level color transformation applied globally to ALL materials on the model:

1. **Channel Routing** (`GSmodelEnableColorSwap`): Remaps which texture color channels are read. Uses GX's `GXSetTevSwapModeTable` to swap R/G/B/A at the TEV stage level. Iterates all materials and calls `GSmaterialSetColorChannels` on each.

2. **Brightness Modulation** (`GSmodelEnableModulation`): Scales RGB channels by a per-channel factor. Also iterates all materials.

### Alpha Brightness Forced to Max

The game forces the alpha brightness byte to 0xFF before applying modulation (line 223 in `__ct__13ModelSequenceFUsUlb`). This means shiny brightness ONLY affects RGB — alpha is untouched.

### No Per-Material Selectivity

Both routing and brightness apply to ALL materials uniformly. There is no per-material or per-mesh control in the PKX metadata.

### Brightness Encoding

| Byte Value | Float | Multiply Factor | Effect |
|-----------|-------|-----------------|--------|
| 0 | -1.0 | 0.0 | Black |
| 64 | -0.50 | 0.5 | Half brightness |
| 127 | 0.0 | 1.0 | Unchanged |
| 191 | 0.50 | 1.5 | 1.5× bright |
| 255 | 1.0 | 2.0 | 2× bright |

### Color Space

The GameCube renders in gamma space (no linear pipeline). The shiny brightness multiplication happens in gamma/sRGB space. Blender operates in linear space. Our shader nodes convert linear→sRGB before multiplying, then sRGB→linear after, to match the game's visual output.

---

## Body Map (Null Joint Bones)

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

---

## Flags

| Bit | Mask | Name | Description |
|-----|------|------|-------------|
| 0 | 0x01 | Flying | Enables Take Flight animation and hovering mode |
| 2 | 0x04 | Skip Fractional Frames | Integer frame stepping instead of interpolated |
| 6 | 0x40 | No Root Animation | Locks the root bone's position in place |
| 7 | 0x80 | Unknown | Only observed on Espeon (eifie.pkx) |

---

## Particle Orientation

Signed integer (-2 to +2) controlling rotation angle for sleep and ice particle effects attached to the model. Used by `SetFlags` to orient particle generators via a switch-case lookup table mapping each value to a specific rotation angle.

---

## Colosseum Differences

- Animation timing stored as integer frame counts at 60fps (XD uses float seconds)
- Sub-animation entries have motion_type always 0
- Animation terminator value is 1 (XD uses 3)
- PKX header is 0x40 bytes (XD is variable, typically 0xE60)
- Animation metadata comes AFTER DAT+GPT1 data (XD stores in header)
- Shiny data is last 20 bytes of file (XD stores at 0x70-0x83 in header)
- Shiny brightness stored as ARGB (XD stores as RGBA bytes)
- Animation section count can be 16 (XD is always 17)

---

## Disassembly Reference

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
