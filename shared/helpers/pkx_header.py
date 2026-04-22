"""PKX header dataclasses — structured representation of PKX metadata.

Supports both XD and Colosseum formats. All timing values are stored as float
seconds internally; Colosseum's integer frame counts (60fps) are converted
on read/write.

Layout reference (XD):
    [Preamble 0x00-0x83][AnimEntries × N at 0x84][pad to 0x20][GPT1][DAT][Trailer]

Layout reference (Colosseum):
    [Header 0x40][DAT padded][GPT1 padded][AnimEntries × N][Shiny 20 bytes]
"""
from dataclasses import dataclass, field
from .binary import read, read_many, pack, pack_many, write_into

_COLO_FPS = 60.0


def _align32(n):
    """Round up to next 32-byte boundary. Returns 0 for n <= 0."""
    if n <= 0:
        return 0
    remainder = n % 0x20
    return n if remainder == 0 else n + (0x20 - remainder)


# ---------------------------------------------------------------------------
# PartAnimData — 19 bytes each, 4 per PKX header (XD only)
# ---------------------------------------------------------------------------

@dataclass
class PartAnimData:
    """Part-specific animation config (blinking, breathing, etc).

    19 bytes: has_data(1) + sub_param(1) + bone_config(16) + anim_index_ref(1)
    """
    has_data: int = 0       # 0=none, 1=simple, 2=complex
    sub_param: int = 0
    bone_config: bytes = field(default_factory=lambda: b'\xff' * 16)
    anim_index_ref: int = 0

    @property
    def is_active(self):
        """True iff this entry references an animation (has_data > 0)."""
        return self.has_data > 0

    @property
    def is_targeted(self):
        """True iff has_data == 2 (targeted: bone_config carries real bone indices)."""
        return self.has_data == 2

    def active_bone_indices(self):
        """Return the bone-config indices, dropping the 0xFF "unused" sentinel.

        In: (none — derived from self.bone_config).
        Out: list[int] of bone indices in declaration order, no 0xFF entries.
        """
        return [b for b in self.bone_config if b != 0xFF]

    @classmethod
    def from_bytes(cls, data, offset):
        has_data = read('uchar', data, offset)
        sub_param = read('uchar', data, offset + 1)
        bone_config = bytes(data[offset + 2:offset + 18])
        anim_index_ref = read('uchar', data, offset + 18)
        return cls(has_data, sub_param, bone_config, anim_index_ref)

    def to_bytes(self):
        out = bytearray(19)
        out[0] = self.has_data & 0xFF
        out[1] = self.sub_param & 0xFF
        out[2:18] = self.bone_config[:16].ljust(16, b'\xff')
        out[18] = self.anim_index_ref & 0xFF
        return bytes(out)


# ---------------------------------------------------------------------------
# SubAnim — 8 bytes: motion_type(4) + anim_index(4)
# ---------------------------------------------------------------------------

@dataclass
class SubAnim:
    """Sub-animation entry within an AnimMetadataEntry."""
    motion_type: int = 0    # 0=none, 1=play_once, 2=loop
    anim_index: int = 0     # DAT animation index

    @property
    def is_active(self):
        """True iff this sub-anim references a real DAT animation (motion_type > 0)."""
        return self.motion_type > 0


# ---------------------------------------------------------------------------
# AnimMetadataEntry — 0xD0 (208) bytes
# ---------------------------------------------------------------------------

_ENTRY_SIZE = 0xD0
_MAX_SUB_ANIMS = 8   # space from 0x8C to 0xCC = 64 bytes = 8 × 8
_NUM_BODY_MAP_SLOTS = 16


@dataclass
class AnimMetadataEntry:
    """One animation slot in the PKX header (0xD0 bytes).

    XD Pokémon slots: [0]Idle [1]SpecialA [2-5]PhysicalA-D [6]SpecialB
    [7]PhysicalE [8]Damage [9]DamageB [10]Faint [11-16]IdleB/SpecialC/etc.

    XD Trainer slots: [0]Idle [1]PokéballThrow [2]Victory [3]BattleIntro
    [4]Frustrated [5]Victory2 [6-9]Unused [10]Defeat [11-16]Unused
    """
    anim_type: int = 4          # 2=loop, 3=hit_reaction, 4=action, 5=compound
    sub_anim_count: int = 1     # 1-3
    damage_flags: int = 0
    timing: tuple = (0.0, 0.0, 0.0, 0.0)  # 4 floats (seconds)
    body_map_bones: list = field(default_factory=lambda: [-1] * _NUM_BODY_MAP_SLOTS)
    sub_anims: list = field(default_factory=lambda: [SubAnim()])
    terminator: int = 3         # 3 for XD, 1 for Colosseum

    @classmethod
    def default_unused(cls, is_xd=True):
        """Create an unused/empty animation slot."""
        return cls(
            anim_type=4,
            sub_anim_count=1,
            timing=(0.0, 0.0, 0.0, 0.0),
            body_map_bones=[-1] * _NUM_BODY_MAP_SLOTS,
            sub_anims=[SubAnim(0, 0)],
            terminator=3 if is_xd else 1,
        )

    @classmethod
    def default_idle(cls, is_xd=True):
        """Create a default idle (looping) animation slot."""
        return cls(
            anim_type=2,
            sub_anim_count=1,
            timing=(0.0, 0.0, 0.0, 0.0),
            body_map_bones=[0] + [-1] * (_NUM_BODY_MAP_SLOTS - 1),
            sub_anims=[SubAnim(2 if is_xd else 0, 0)],
            terminator=3 if is_xd else 1,
        )

    @classmethod
    def from_bytes(cls, data, offset, is_xd=True):
        anim_type = read('uint', data, offset + 0x00)
        sub_anim_count = read('uint', data, offset + 0x04)
        damage_flags = read('uint', data, offset + 0x08)

        if is_xd:
            t1 = read('float', data, offset + 0x10)
            t2 = read('float', data, offset + 0x14)
            t3 = read('float', data, offset + 0x18)
            t4 = read('float', data, offset + 0x1C)
        else:
            # Colosseum: integer frame counts at 60fps → seconds
            t1 = read('uint', data, offset + 0x10) / _COLO_FPS
            t2 = read('uint', data, offset + 0x14) / _COLO_FPS
            t3 = read('uint', data, offset + 0x18) / _COLO_FPS
            t4 = read('uint', data, offset + 0x1C) / _COLO_FPS

        bones = []
        for i in range(_NUM_BODY_MAP_SLOTS):
            bones.append(read('int', data, offset + 0x4C + i * 4))

        count = min(sub_anim_count, _MAX_SUB_ANIMS)
        subs = []
        for i in range(count):
            mt = read('uint', data, offset + 0x8C + i * 8)
            ai = read('uint', data, offset + 0x8C + i * 8 + 4)
            subs.append(SubAnim(mt, ai))

        terminator = read('uint', data, offset + 0xCC)

        return cls(
            anim_type=anim_type,
            sub_anim_count=sub_anim_count,
            damage_flags=damage_flags,
            timing=(t1, t2, t3, t4),
            body_map_bones=bones,
            sub_anims=subs,
            terminator=terminator,
        )

    def to_bytes(self, is_xd=True):
        out = bytearray(_ENTRY_SIZE)

        write_into('uint', self.anim_type, out, 0x00)
        write_into('uint', self.sub_anim_count, out, 0x04)
        write_into('uint', self.damage_flags, out, 0x08)
        # 0x0C reserved = 0

        if is_xd:
            write_into('float', self.timing[0], out, 0x10)
            write_into('float', self.timing[1], out, 0x14)
            write_into('float', self.timing[2], out, 0x18)
            write_into('float', self.timing[3], out, 0x1C)
        else:
            # Colosseum: seconds → integer frame counts at 60fps
            write_into('uint', round(self.timing[0] * _COLO_FPS), out, 0x10)
            write_into('uint', round(self.timing[1] * _COLO_FPS), out, 0x14)
            write_into('uint', round(self.timing[2] * _COLO_FPS), out, 0x18)
            write_into('uint', round(self.timing[3] * _COLO_FPS), out, 0x1C)

        # 0x20-0x4B reserved zeros (already zero)

        for i in range(min(len(self.body_map_bones), _NUM_BODY_MAP_SLOTS)):
            write_into('int', self.body_map_bones[i], out, 0x4C + i * 4)

        count = min(len(self.sub_anims), _MAX_SUB_ANIMS)
        for i in range(count):
            write_into('uint', self.sub_anims[i].motion_type, out, 0x8C + i * 8)
            write_into('uint', self.sub_anims[i].anim_index, out, 0x8C + i * 8 + 4)

        write_into('uint', self.terminator, out, 0xCC)

        return bytes(out)


# ---------------------------------------------------------------------------
# PKXHeader — full parsed header for XD or Colosseum
# ---------------------------------------------------------------------------

_XD_ANIM_COUNT = 17
_XD_PREAMBLE_SIZE = 0x84  # bytes before anim entries
_COLO_HEADER_SIZE = 0x40
_COLO_SHINY_SIZE = 20  # 4×uint32 routing + 1×uint32 ARGB


@dataclass
class PKXHeader:
    """Unified PKX header representation for both XD and Colosseum.

    All timing values stored as float seconds. Colosseum frame counts
    converted automatically on from_bytes/to_bytes.
    """
    is_xd: bool = True
    dat_file_size: int = 0
    gpt1_length: int = 0
    anim_section_count: int = _XD_ANIM_COUNT

    # Preamble fields
    particle_orientation: int = 0   # signed, -2 to 2
    species_id: int = 0             # Pokédex #, 0 = trainer/generic
    type_id: int = 0x000C           # PKX marker

    # Part animation data (XD: 4 × 19-byte blocks; Colo: 3 int refs)
    part_anim_data: list = field(default_factory=lambda: [PartAnimData() for _ in range(4)])
    # Colosseum part anim refs (stored separately since format differs)
    colo_part_anim_refs: list = field(default_factory=lambda: [-1, -1, -1])

    # Flags and misc
    flags: int = 0
    unknown_69: int = 0
    distortion_param: int = 0
    distortion_type: int = 0
    head_bone_index: int = 0

    # Colosseum-only preamble fields
    colo_unknown_10: int = 5
    colo_unknown_14: int = -1

    # Shiny data
    shiny_route: tuple = (0, 1, 2, 3)  # RGBA channel routing, values 0-3
    shiny_brightness: tuple = (0x7F, 0x7F, 0x7F, 0x7F)  # raw bytes, 0x7F = neutral

    # Animation entries
    anim_entries: list = field(default_factory=list)

    @property
    def has_shiny(self):
        """True if shiny params differ from identity/neutral."""
        identity = (self.shiny_route == (0, 1, 2, 3))
        neutral = all(abs(b - 0x7F) <= 1 for b in self.shiny_brightness)
        return not (identity and neutral)

    @property
    def is_trainer(self):
        """True iff this PKX represents a trainer (species_id == 0 and particle_orientation == 0)."""
        return self.species_id == 0 and self.particle_orientation == 0

    @property
    def model_type_label(self):
        """Human-readable model classification."""
        return "TRAINER" if self.is_trainer else "POKEMON"

    @property
    def format_label(self):
        """Container format label ('XD' or 'COLOSSEUM')."""
        return "XD" if self.is_xd else "COLOSSEUM"

    @property
    def flag_flying(self):
        """True iff the flying behaviour bit (0x01) is set."""
        return bool(self.flags & 0x01)

    @property
    def flag_skip_frac_frames(self):
        """True iff the integer-frame-stepping bit (0x04) is set."""
        return bool(self.flags & 0x04)

    @property
    def flag_no_root_anim(self):
        """True iff the root-joint-animation-suppression bit (0x40) is set."""
        return bool(self.flags & 0x40)

    @property
    def flag_bit7(self):
        """True iff the unknown bit-7 flag (0x80) is set."""
        return bool(self.flags & 0x80)

    @property
    def header_byte_size(self):
        """Compute the header size in bytes (XD only; Colo header is fixed 0x40)."""
        if not self.is_xd:
            return _COLO_HEADER_SIZE
        base = _XD_PREAMBLE_SIZE + self.anim_section_count * _ENTRY_SIZE
        return _align32(base)

    # -------------------------------------------------------------------
    # XD parsing
    # -------------------------------------------------------------------

    @classmethod
    def _from_bytes_xd(cls, data):
        h = cls(is_xd=True)
        h.dat_file_size = read('uint', data, 0x00)
        h.gpt1_length = read('uint', data, 0x08)
        h.anim_section_count = read('uint', data, 0x10)
        h.particle_orientation = read('int', data, 0x14)
        h.species_id = read('ushort', data, 0x18)
        h.type_id = read('ushort', data, 0x1A)

        h.part_anim_data = [
            PartAnimData.from_bytes(data, 0x1C),
            PartAnimData.from_bytes(data, 0x2F),
            PartAnimData.from_bytes(data, 0x42),
            PartAnimData.from_bytes(data, 0x55),
        ]

        h.flags = read('uchar', data, 0x68)
        h.unknown_69 = read('uchar', data, 0x69)
        h.distortion_param = read('ushort', data, 0x6A)
        h.distortion_type = read('uchar', data, 0x6C)
        h.head_bone_index = read('ushort', data, 0x6E)

        # Shiny routing: 4 × uint32 at 0x70-0x7F
        h.shiny_route = read_many('uint', 4, data, 0x70)

        # Shiny brightness: 4 bytes at 0x80-0x83
        h.shiny_brightness = read_many('uchar', 4, data, 0x80)

        # Animation entries
        count = min(h.anim_section_count, 64)  # safety cap
        h.anim_entries = []
        for i in range(count):
            offset = _XD_PREAMBLE_SIZE + i * _ENTRY_SIZE
            if offset + _ENTRY_SIZE <= len(data):
                h.anim_entries.append(AnimMetadataEntry.from_bytes(data, offset, is_xd=True))

        return h

    def _to_bytes_xd(self):
        """Serialize XD header (preamble + anim entries + padding)."""
        total = self.header_byte_size
        out = bytearray(total)

        write_into('uint', self.dat_file_size, out, 0x00)
        # 0x04 reserved
        write_into('uint', self.gpt1_length, out, 0x08)
        # 0x0C reserved
        write_into('uint', self.anim_section_count, out, 0x10)
        write_into('int', self.particle_orientation, out, 0x14)
        write_into('ushort', self.species_id, out, 0x18)
        write_into('ushort', self.type_id, out, 0x1A)

        # Part anim data blocks
        offsets = [0x1C, 0x2F, 0x42, 0x55]
        for i, off in enumerate(offsets):
            if i < len(self.part_anim_data):
                out[off:off + 19] = self.part_anim_data[i].to_bytes()

        write_into('uchar', self.flags, out, 0x68)
        write_into('uchar', self.unknown_69, out, 0x69)
        write_into('ushort', self.distortion_param, out, 0x6A)
        write_into('uchar', self.distortion_type, out, 0x6C)
        # 0x6D reserved
        write_into('ushort', self.head_bone_index, out, 0x6E)

        # Shiny routing
        for i in range(4):
            write_into('uint', self.shiny_route[i], out, 0x70 + i * 4)

        # Shiny brightness
        for i in range(4):
            write_into('uchar', self.shiny_brightness[i], out, 0x80 + i)

        # Animation entries
        for i, entry in enumerate(self.anim_entries):
            offset = _XD_PREAMBLE_SIZE + i * _ENTRY_SIZE
            out[offset:offset + _ENTRY_SIZE] = entry.to_bytes(is_xd=True)

        return bytes(out)

    # -------------------------------------------------------------------
    # Colosseum parsing
    # -------------------------------------------------------------------

    @classmethod
    def _from_bytes_colo(cls, data, meta_start, file_size):
        """Parse Colosseum PKX header + animation metadata.

        Args:
            data: Full PKX file bytes.
            meta_start: Byte offset where animation metadata begins
                        (after aligned DAT + aligned GPT1).
            file_size: Total file size.
        """
        h = cls(is_xd=False)
        h.dat_file_size = read('uint', data, 0x00)
        h.gpt1_length = read('uint', data, 0x04)
        h.anim_section_count = read('uint', data, 0x08)
        h.particle_orientation = read('int', data, 0x0C)
        h.colo_unknown_10 = read('uint', data, 0x10)
        h.colo_unknown_14 = read('int', data, 0x14)
        h.colo_part_anim_refs = [
            read('int', data, 0x18),
            read('int', data, 0x1C),
            read('int', data, 0x20),
        ]

        # Animation entries
        count = min(h.anim_section_count, 64)
        h.anim_entries = []
        for i in range(count):
            offset = meta_start + i * _ENTRY_SIZE
            if offset + _ENTRY_SIZE <= file_size:
                h.anim_entries.append(AnimMetadataEntry.from_bytes(data, offset, is_xd=False))

        # Head bone from first active entry's body_map[1]
        if h.anim_entries and h.anim_entries[0].body_map_bones[1] >= 0:
            h.head_bone_index = h.anim_entries[0].body_map_bones[1]

        # Shiny: last 20 bytes of file (4×uint32 routing + 1×uint32 ARGB)
        shiny_base = file_size - _COLO_SHINY_SIZE
        if shiny_base > meta_start:
            h.shiny_route = read_many('uint', 4, data, shiny_base)
            argb = read('uint', data, shiny_base + 16)
            # ARGB → RGBA byte order
            a = (argb >> 24) & 0xFF
            r = (argb >> 16) & 0xFF
            g = (argb >> 8) & 0xFF
            b = argb & 0xFF
            h.shiny_brightness = (r, g, b, a)

        return h

    def _to_bytes_colo_header(self):
        """Serialize the 0x40-byte Colosseum header."""
        out = bytearray(_COLO_HEADER_SIZE)
        write_into('uint', self.dat_file_size, out, 0x00)
        write_into('uint', self.gpt1_length, out, 0x04)
        write_into('uint', self.anim_section_count, out, 0x08)
        write_into('int', self.particle_orientation, out, 0x0C)
        write_into('uint', self.colo_unknown_10, out, 0x10)
        write_into('int', self.colo_unknown_14, out, 0x14)
        for i in range(3):
            write_into('int', self.colo_part_anim_refs[i], out, 0x18 + i * 4)
        return bytes(out)

    def _to_bytes_colo_metadata(self):
        """Serialize Colosseum animation entries + shiny trailer."""
        parts = []
        for entry in self.anim_entries:
            parts.append(entry.to_bytes(is_xd=False))

        # Shiny: 4×uint32 routing + 1×uint32 ARGB
        shiny = bytearray(_COLO_SHINY_SIZE)
        for i in range(4):
            write_into('uint', self.shiny_route[i], shiny, i * 4)
        # RGBA → ARGB
        r, g, b, a = self.shiny_brightness
        argb = (a << 24) | (r << 16) | (g << 8) | b
        write_into('uint', argb, shiny, 16)
        parts.append(bytes(shiny))

        return b''.join(parts)

    # -------------------------------------------------------------------
    # Unified interface
    # -------------------------------------------------------------------

    @classmethod
    def from_bytes(cls, data, is_xd, meta_start=None):
        """Parse a PKXHeader from raw PKX file bytes.

        Args:
            data: Full PKX file bytes.
            is_xd: True for XD format, False for Colosseum.
            meta_start: For Colosseum, the byte offset where animation
                        metadata begins. Ignored for XD.
        """
        if is_xd:
            return cls._from_bytes_xd(data)
        else:
            if meta_start is None:
                raise ValueError("meta_start required for Colosseum PKX parsing")
            return cls._from_bytes_colo(data, meta_start, len(data))

    def to_bytes(self):
        """Serialize the header. Returns bytes for XD; for Colosseum,
        returns (header_bytes, metadata_bytes) tuple since they're
        stored in different parts of the file."""
        if self.is_xd:
            return self._to_bytes_xd()
        else:
            return (self._to_bytes_colo_header(), self._to_bytes_colo_metadata())

    @classmethod
    def default_xd(cls, dat_file_size=0, species_id=0):
        """Create a default XD PKXHeader with sensible defaults."""
        h = cls(is_xd=True)
        h.dat_file_size = dat_file_size
        h.anim_section_count = _XD_ANIM_COUNT
        h.species_id = species_id
        h.type_id = 0x000C
        h.anim_entries = [AnimMetadataEntry.default_idle(is_xd=True)]
        h.anim_entries += [AnimMetadataEntry.default_unused(is_xd=True) for _ in range(16)]
        return h

    @classmethod
    def default_colosseum(cls, dat_file_size=0):
        """Create a default Colosseum PKXHeader with sensible defaults."""
        h = cls(is_xd=False)
        h.dat_file_size = dat_file_size
        h.anim_section_count = _XD_ANIM_COUNT
        h.anim_entries = [AnimMetadataEntry.default_idle(is_xd=False)]
        h.anim_entries += [AnimMetadataEntry.default_unused(is_xd=False) for _ in range(16)]
        return h


# ---------------------------------------------------------------------------
# Animation slot name lookups
# ---------------------------------------------------------------------------

XD_POKEMON_ANIM_NAMES = [
    "Idle", "Special A", "Physical A", "Physical B", "Physical C",
    "Physical D", "Special B", "Physical E", "Damage", "Damage B",
    "Faint", "Extra 1", "Special C", "Extra 2", "Extra 3", "Extra 4",
    "Take Flight",
]

XD_TRAINER_ANIM_NAMES = [
    "Idle", "Pokéball Throw", "Victory", "Battle Intro", "Frustrated",
    "Victory 2", "Unused 1", "Unused 2", "Unused 3", "Unused 4",
    "Defeat", "Unused 5", "Unused 6", "Unused 7", "Unused 8",
    "Unused 9", "Unused 10",
]

COLO_TRAINER_ANIM_NAMES = [
    "Idle", "Pokéball Throw", "Victory", "Unknown 1", "Unknown 2",
    "Victory 2", "Battle Intro", "Unused 1", "Unused 2",
    "Hit by Shadow 1", "Hit by Shadow 2", "Defeat", "Unused 3",
    "Unused 4", "Unused 5", "Unused 6", "Unused 7",
]

BODY_MAP_NAMES = [
    "Root",             # 0 — always bone 0
    "Head",             # 1 — head tracking
    "Center",           # 2 — center null fallback
    "Body Part 3",      # 3
    "Neck",             # 4 — typically head-1
    "Head Top",         # 5 — typically head+1
    "Limb Left",        # 6 — from the Pokémon's perspective
    "Limb Right",       # 7 — from the Pokémon's perspective
    "Secondary 8",      # 8
    "Secondary 9",      # 9
    "Secondary 10",     # 10
    "Secondary 11",     # 11
    "Attachment A",     # 12
    "Attachment B",     # 13
    "Attachment C",     # 14
    "Attachment D",     # 15
]
