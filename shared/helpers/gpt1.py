"""GPT1 particle container parser — read and write GPT1 particle effect files.

GPT1 files contain particle generator definitions, textures, and bytecode
command sequences. They are embedded in PKX model containers.

Layout: [Header 32B][PTL section][TXG section][TEX data][REF section]

All internal offsets are relative to the GPT1 file start. The game relocates
them to absolute addresses on load; we store them as relative offsets.
"""
from dataclasses import dataclass, field
from .binary import read, read_many, pack, pack_many, write_into

GPT1_SIGNATURE = 0x47505431   # "GPT1" — V1 format
GPT1_V2_SIGNATURE = 0x01F056DA  # V2 format (different structure, not yet supported)
_HEADER_SIZE = 0x20
_GEN_HEADER_SIZE = 0x3C


@dataclass
class TextureContainer:
    """One texture group entry within the TXG section."""
    nb_textures: int = 0
    format: int = 0             # GX texture format ID
    data_offset: int = 0        # Offset into TEX region (from GPT1 base)
    width: int = 0
    height: int = 0
    nb_mipmaps: int = 0
    texture_offsets: list = field(default_factory=list)  # Offsets from TXG start


@dataclass
class TXGSection:
    """Texture group section — metadata for particle textures."""
    containers: list = field(default_factory=list)  # list[TextureContainer]


@dataclass
class GeneratorDef:
    """One particle generator definition (0x3C header + command bytecode)."""
    gen_type: int = 0           # var00: generator type/flags
    unknown_02: int = 0         # var02
    lifetime: int = 120         # var04: frame count
    max_particles: int = 0      # var06: max concurrent particles
    flags: int = 0              # var08: generator flags
    params: tuple = (0.0,) * 12  # 12 floats (var0C-var38)
    command_bytes: bytes = b''  # Variable-length particle bytecode


@dataclass
class PTLSection:
    """Particle Template List — generator definitions and pointer table."""
    version: int = 0x43
    unknown_02: int = 0
    skip_sections: int = 0
    generators: list = field(default_factory=list)  # list[GeneratorDef]


@dataclass
class GPT1File:
    """Parsed GPT1 particle container.

    Stores the complete particle data in structured form. Use from_bytes()
    to parse and to_bytes() to serialize.
    """
    signature: int = GPT1_SIGNATURE
    ptl: PTLSection = field(default_factory=PTLSection)
    txg: TXGSection = field(default_factory=TXGSection)
    tex_data: bytes = b''       # Raw texture pixel data
    ref_ids: list = field(default_factory=list)  # list[int] — generator ID lookup

    @classmethod
    def from_bytes(cls, data):
        """Parse a GPT1 file from raw bytes.

        Args:
            data: Complete GPT1 file bytes.

        Returns:
            GPT1File instance.

        Raises:
            ValueError: If signature is not recognized.
        """
        if len(data) < _HEADER_SIZE:
            raise ValueError("GPT1 data too small: %d bytes" % len(data))

        sig = read('uint', data, 0x00)
        if sig == GPT1_V2_SIGNATURE:
            raise ValueError("GPT1 V2 format (0x01F056DA) is not yet supported")
        if sig != GPT1_SIGNATURE:
            raise ValueError("Invalid GPT1 signature: 0x%08X" % sig)

        ptl_off = read('uint', data, 0x04)
        txg_off = read('uint', data, 0x08)
        tex_len = read('uint', data, 0x0C)
        ref_off = read('uint', data, 0x10)

        # Parse PTL
        ptl = _parse_ptl(data, ptl_off, txg_off)

        # Parse TXG
        txg = _parse_txg(data, txg_off)

        # Extract TEX data
        # TEX data starts right after TXG metadata and extends for tex_len bytes
        # The actual TEX start is determined by the TXG container data_offsets
        # For simplicity, we store the region from txg_off to ref_off as potential
        # texture data, but tex_len is the authoritative size
        tex_start = _find_tex_start(data, txg, txg_off)
        tex_data = bytes(data[tex_start:tex_start + tex_len]) if tex_len > 0 else b''

        # Parse REF
        ref_ids = []
        if ref_off > 0 and ref_off < len(data):
            nb_generators = len(ptl.generators)
            for i in range(nb_generators):
                off = ref_off + i * 4
                if off + 4 <= len(data):
                    ref_ids.append(read('uint', data, off))

        return cls(
            signature=sig,
            ptl=ptl,
            txg=txg,
            tex_data=tex_data,
            ref_ids=ref_ids,
        )

    def to_bytes(self):
        """Serialize the GPT1 file back to binary.

        Returns:
            bytes — complete GPT1 file.
        """
        # Build sections
        ptl_bytes = _serialize_ptl(self.ptl)
        txg_bytes = _serialize_txg(self.txg)
        ref_bytes = b''.join(pack('uint', rid) for rid in self.ref_ids)

        # Compute offsets
        ptl_off = _HEADER_SIZE
        txg_off = ptl_off + len(ptl_bytes)
        # TEX data sits between TXG metadata and REF
        tex_start = txg_off + len(txg_bytes)
        ref_off = tex_start + len(self.tex_data)

        # Build header
        header = bytearray(_HEADER_SIZE)
        write_into('uint', self.signature, header, 0x00)
        write_into('uint', ptl_off, header, 0x04)
        write_into('uint', txg_off, header, 0x08)
        write_into('uint', len(self.tex_data), header, 0x0C)
        write_into('uint', ref_off, header, 0x10)

        return bytes(header) + ptl_bytes + txg_bytes + self.tex_data + ref_bytes


# ---------------------------------------------------------------------------
# PTL parsing
# ---------------------------------------------------------------------------

def _parse_ptl(data, ptl_off, txg_off):
    """Parse the PTL section."""
    version = read('ushort', data, ptl_off)
    unknown_02 = read('ushort', data, ptl_off + 2)
    skip_sections = read('uint', data, ptl_off + 4)
    nb_generators = read('uint', data, ptl_off + 8)

    # Read generator pointer array
    gen_offsets = []  # Offsets from PTL start
    for i in range(nb_generators):
        off = ptl_off + 12 + i * 4
        if off + 4 <= len(data):
            gen_offsets.append(read('uint', data, off))

    # Parse each generator
    generators = []
    for i, gen_rel_off in enumerate(gen_offsets):
        gen_abs = ptl_off + gen_rel_off
        if gen_abs + _GEN_HEADER_SIZE > len(data):
            continue

        # Determine command sequence end
        if i + 1 < len(gen_offsets):
            cmd_end = ptl_off + gen_offsets[i + 1]
        else:
            cmd_end = txg_off

        gen = _parse_generator(data, gen_abs, cmd_end)
        generators.append(gen)

    return PTLSection(
        version=version,
        unknown_02=unknown_02,
        skip_sections=skip_sections,
        generators=generators,
    )


def _parse_generator(data, offset, cmd_end):
    """Parse a single generator definition."""
    gen_type = read('ushort', data, offset)
    unknown_02 = read('ushort', data, offset + 2)
    lifetime = read('ushort', data, offset + 4)
    max_particles = read('ushort', data, offset + 6)
    flags = read('uint', data, offset + 8)

    params = read_many('float', 12, data, offset + 0x0C)

    cmd_start = offset + _GEN_HEADER_SIZE
    cmd_bytes = bytes(data[cmd_start:cmd_end]) if cmd_end > cmd_start else b''

    return GeneratorDef(
        gen_type=gen_type,
        unknown_02=unknown_02,
        lifetime=lifetime,
        max_particles=max_particles,
        flags=flags,
        params=params,
        command_bytes=cmd_bytes,
    )


def _serialize_ptl(ptl):
    """Serialize PTL section to bytes."""
    # Header: version(2) + unknown(2) + skip(4) + count(4) = 12 bytes
    # Pointer array: count × 4 bytes
    # Padding to 8-byte alignment (0xFF fill)
    # Generator data

    nb_gen = len(ptl.generators)
    ptr_array_size = nb_gen * 4
    header_and_ptrs = 12 + ptr_array_size

    # Pad to 8-byte alignment
    pad_to_8 = (8 - (header_and_ptrs % 8)) % 8

    # Compute generator offsets (from PTL start)
    gen_data_start = header_and_ptrs + pad_to_8
    gen_parts = []
    gen_offsets = []
    current_off = gen_data_start
    for gen in ptl.generators:
        gen_offsets.append(current_off)
        gen_bytes = _serialize_generator(gen)
        gen_parts.append(gen_bytes)
        current_off += len(gen_bytes)

    # Build
    out = bytearray(12)
    write_into('ushort', ptl.version, out, 0)
    write_into('ushort', ptl.unknown_02, out, 2)
    write_into('uint', ptl.skip_sections, out, 4)
    write_into('uint', nb_gen, out, 8)

    # Pointer array
    for off in gen_offsets:
        out.extend(pack('uint', off))

    # Padding
    out.extend(b'\xFF' * pad_to_8)

    # Generator data
    for part in gen_parts:
        out.extend(part)

    return bytes(out)


def _serialize_generator(gen):
    """Serialize a single generator to bytes."""
    header = bytearray(_GEN_HEADER_SIZE)
    write_into('ushort', gen.gen_type, header, 0)
    write_into('ushort', gen.unknown_02, header, 2)
    write_into('ushort', gen.lifetime, header, 4)
    write_into('ushort', gen.max_particles, header, 6)
    write_into('uint', gen.flags, header, 8)
    for i, val in enumerate(gen.params[:12]):
        write_into('float', val, header, 0x0C + i * 4)
    return bytes(header) + gen.command_bytes


# ---------------------------------------------------------------------------
# TXG parsing
# ---------------------------------------------------------------------------

def _parse_txg(data, txg_off):
    """Parse the TXG section."""
    if txg_off + 4 > len(data):
        return TXGSection()

    nb_containers = read('uint', data, txg_off)
    containers = []

    for i in range(nb_containers):
        ptr_off = txg_off + 4 + i * 4
        if ptr_off + 4 > len(data):
            break
        container_rel = read('uint', data, ptr_off)
        if container_rel == 0xFFFFFFFF:
            break
        container_abs = txg_off + container_rel
        if container_abs + 0x18 > len(data):
            break

        nb_tex = read('uint', data, container_abs)
        fmt = read('uint', data, container_abs + 4)
        data_off = read('uint', data, container_abs + 8)
        width = read('uint', data, container_abs + 0x0C)
        height = read('uint', data, container_abs + 0x10)
        mipmaps = read('uint', data, container_abs + 0x14)

        tex_offsets = []
        for t in range(nb_tex):
            t_off = container_abs + 0x18 + t * 4
            if t_off + 4 > len(data):
                break
            tex_rel = read('uint', data, t_off)
            if tex_rel != 0xFFFFFFFF:
                tex_offsets.append(tex_rel)

        containers.append(TextureContainer(
            nb_textures=nb_tex,
            format=fmt,
            data_offset=data_off,
            width=width,
            height=height,
            nb_mipmaps=mipmaps,
            texture_offsets=tex_offsets,
        ))

    return TXGSection(containers=containers)


def _serialize_txg(txg):
    """Serialize TXG section to bytes."""
    nb_cont = len(txg.containers)
    if nb_cont == 0:
        return pack('uint', 0)

    # Layout: count(4) + container_ptrs(nb_cont × 4) + pad_to_32 + container_data
    ptr_area = 4 + nb_cont * 4
    pad_to_32 = (32 - (ptr_area % 32)) % 32

    container_parts = []
    container_offsets = []
    current_off = ptr_area + pad_to_32
    for c in txg.containers:
        container_offsets.append(current_off)
        c_data = _serialize_texture_container(c)
        container_parts.append(c_data)
        current_off += len(c_data)

    out = bytearray()
    out.extend(pack('uint', nb_cont))
    for off in container_offsets:
        out.extend(pack('uint', off))
    out.extend(b'\xFF' * pad_to_32)
    for part in container_parts:
        out.extend(part)

    return bytes(out)


def _serialize_texture_container(c):
    """Serialize a TextureContainer."""
    out = bytearray(0x18 + len(c.texture_offsets) * 4)
    write_into('uint', c.nb_textures, out, 0)
    write_into('uint', c.format, out, 4)
    write_into('uint', c.data_offset, out, 8)
    write_into('uint', c.width, out, 0x0C)
    write_into('uint', c.height, out, 0x10)
    write_into('uint', c.nb_mipmaps, out, 0x14)
    for i, off in enumerate(c.texture_offsets):
        write_into('uint', off, out, 0x18 + i * 4)
    return bytes(out)


def _find_tex_start(data, txg, txg_off):
    """Find where TEX pixel data starts based on TXG container data_offsets."""
    if txg.containers:
        # The first container's data_offset points into the TEX region
        # This offset is from the GPT1 base
        return txg.containers[0].data_offset
    # Fallback: TEX data starts right after TXG metadata
    return txg_off
