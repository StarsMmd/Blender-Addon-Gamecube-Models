"""Phase 2 (export) — serialize IRParticleSystem back to GPT1 file bytes.

Assembles the per-generator bytecode via `shared.helpers.gpt1_commands.assemble`,
repacks texture pixels into GX format via `shared.gx_texture.encode_texture`,
and emits the binary container via `shared.helpers.gpt1.GPT1File.to_bytes`.
"""
try:
    from .....shared.helpers.gpt1 import (
        GPT1File, PTLSection, TXGSection, GeneratorDef, TextureContainer,
    )
    from .....shared.helpers.gpt1_commands import assemble
    from .....shared.gx_texture import FORMAT_INFO
    from .....shared.texture_encoder import encode_texture
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.gpt1 import (
        GPT1File, PTLSection, TXGSection, GeneratorDef, TextureContainer,
    )
    from shared.helpers.gpt1_commands import assemble
    from shared.gx_texture import FORMAT_INFO
    from shared.texture_encoder import encode_texture
    from shared.helpers.logger import StubLogger


def compose_particles(ir_particles, logger=StubLogger()):
    """Convert an IRParticleSystem into GPT1 file bytes.

    Returns:
        bytes — the raw GPT1 file, or empty bytes if the system has no
        generators (no particles to emit).
    """
    if ir_particles is None or not ir_particles.generators:
        return b''

    # Build generators
    generators = []
    for gen in ir_particles.generators:
        params = tuple(gen.params) if gen.params else (0.0,) * 12
        while len(params) < 12:
            params = params + (0.0,)
        cmd_bytes = assemble(gen.instructions)
        generators.append(GeneratorDef(
            gen_type=int(gen.gen_type),
            unknown_02=0,
            lifetime=int(gen.lifetime),
            max_particles=int(gen.max_particles),
            flags=int(gen.flags),
            params=params[:12],
            command_bytes=cmd_bytes,
        ))

    ptl = PTLSection(
        version=0x43,
        unknown_02=0,
        skip_sections=0,
        generators=generators,
    )

    # Build texture containers — one per IRParticleTexture for simplicity.
    containers = []
    tex_data_parts = []
    tex_data_cursor = 0
    # The data_offset in each TextureContainer is relative to the GPT1 base,
    # not the TXG base — but we don't know the GPT1 base offset yet. The
    # header/PTL/TXG lengths determine where TEX data starts, so we compute
    # data_offset relative to the start of the TEX region and add the header
    # sizes later during GPT1 file assembly. For now store as "relative to
    # TEX start"; GPT1File.to_bytes() handles the rebase.
    for tex in ir_particles.textures:
        encoded, _ = _encode_ir_texture(tex, logger)
        containers.append(TextureContainer(
            nb_textures=1,
            format=int(tex.format),
            data_offset=tex_data_cursor,  # Relative offset into TEX region
            width=int(tex.width),
            height=int(tex.height),
            nb_mipmaps=0,
            texture_offsets=[0],
        ))
        tex_data_parts.append(encoded)
        tex_data_cursor += len(encoded)

    txg = TXGSection(containers=containers)
    tex_data = b''.join(tex_data_parts)

    ref_ids = list(ir_particles.ref_ids) if ir_particles.ref_ids else []
    # REF IDs default to one per generator when the model doesn't specify.
    if not ref_ids:
        ref_ids = list(range(len(generators)))

    gpt1 = GPT1File(
        ptl=ptl,
        txg=txg,
        tex_data=tex_data,
        ref_ids=ref_ids,
    )

    blob = gpt1.to_bytes()

    # Fix up TXG data_offsets to be absolute (from GPT1 start) — GPT1File.to_bytes()
    # doesn't know the final TEX region start until after PTL+TXG are sized.
    blob = _fix_data_offsets(blob, gpt1)

    logger.info("  Composed GPT1: %d generators, %d textures, %d bytes",
                len(generators), len(containers), len(blob))
    return blob


def _encode_ir_texture(tex, logger):
    """Encode IRParticleTexture pixels into GX-format bytes.

    IR pixels are stored bottom-to-top (matching `decode_texture`'s output
    and Blender's convention). `encode_texture` expects the same order, so
    no flip is needed.
    """
    if tex.format not in FORMAT_INFO:
        raise ValueError("Unsupported GX format %d for particle texture" % tex.format)
    if tex.width <= 0 or tex.height <= 0 or not tex.pixels:
        return b'', 0
    result = encode_texture(tex.pixels, tex.width, tex.height, tex.format)
    image_data = bytes(result['image_data'])
    return image_data, len(image_data)


def _fix_data_offsets(blob, gpt1):
    """Rewrite container data_offsets to be absolute (from GPT1 base).

    GPT1File serialization lays out as [header][PTL][TXG][TEX][REF]. The
    TEX region start in the final blob = len(header) + len(PTL_bytes) +
    len(TXG_bytes). Each container's data_offset currently holds a
    relative-to-TEX-start offset; shift by the absolute TEX start.
    """
    try:
        from .....shared.helpers.binary import read, write_into
        from .....shared.helpers.gpt1 import _HEADER_SIZE, _serialize_ptl, _serialize_txg
    except (ImportError, SystemError):
        from shared.helpers.binary import read, write_into
        from shared.helpers.gpt1 import _HEADER_SIZE, _serialize_ptl, _serialize_txg

    ptl_bytes = _serialize_ptl(gpt1.ptl)
    txg_bytes = _serialize_txg(gpt1.txg)
    ptl_off = _HEADER_SIZE
    txg_off = ptl_off + len(ptl_bytes)
    tex_start = txg_off + len(txg_bytes)

    out = bytearray(blob)
    # Walk the TXG section in the serialized blob and rewrite data_offset fields.
    nb_containers = read('uint', out, txg_off)
    for i in range(nb_containers):
        ptr_off = txg_off + 4 + i * 4
        container_rel = read('uint', out, ptr_off)
        if container_rel == 0xFFFFFFFF:
            continue
        container_abs = txg_off + container_rel
        current = read('uint', out, container_abs + 8)
        write_into('uint', current + tex_start, out, container_abs + 8)
    return bytes(out)
