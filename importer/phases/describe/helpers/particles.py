"""Phase 4b — Describe Particles: GPT1 binary → IRParticleSystem.

Parses GPT1 particle data and converts it to IR particle types.
Called from describe.py when GPT1 data is present on the metadata.
"""
try:
    from .....shared.helpers.gpt1 import GPT1File
    from .....shared.helpers.gpt1_commands import disassemble
    from .....shared.IR.particles import IRParticleSystem, IRParticleGenerator, IRParticleTexture
    from .....shared.helpers.logger import StubLogger
    from .....shared.gx_texture import decode_texture
except (ImportError, SystemError):
    from shared.helpers.gpt1 import GPT1File
    from shared.helpers.gpt1_commands import disassemble
    from shared.IR.particles import IRParticleSystem, IRParticleGenerator, IRParticleTexture
    from shared.helpers.logger import StubLogger
    from shared.gx_texture import decode_texture


def describe_particles(gpt1_data, logger=StubLogger()):
    """Convert raw GPT1 bytes into an IRParticleSystem.

    Args:
        gpt1_data: Raw GPT1 file bytes.
        logger: Logger instance.

    Returns:
        IRParticleSystem, or None if parsing fails.
    """
    if not gpt1_data:
        return None

    try:
        gpt1 = GPT1File.from_bytes(gpt1_data)
    except ValueError as e:
        logger.info("  Skipping GPT1: %s", e)
        return None

    logger.info("  GPT1: %d generators, %d texture containers, %d REF IDs",
                len(gpt1.ptl.generators), len(gpt1.txg.containers), len(gpt1.ref_ids))

    # Convert generators
    ir_generators = []
    for i, gen in enumerate(gpt1.ptl.generators):
        instructions = disassemble(gen.command_bytes)
        ir_gen = IRParticleGenerator(
            index=i,
            gen_type=gen.gen_type,
            lifetime=gen.lifetime,
            max_particles=gen.max_particles,
            flags=gen.flags,
            params=gen.params,
            instructions=instructions,
            command_bytes=gen.command_bytes,
        )
        ir_generators.append(ir_gen)
        logger.debug("    Generator %d: type=%d, lifetime=%d, max_particles=%d, %d instructions",
                     i, gen.gen_type, gen.lifetime, gen.max_particles, len(instructions))

    # Convert textures with pixel decoding
    ir_textures = []
    for container in gpt1.txg.containers:
        for t_idx in range(container.nb_textures):
            pixels = _decode_particle_texture(
                gpt1_data, container.format, container.width, container.height,
                container.data_offset, container.texture_offsets, t_idx, logger)
            ir_tex = IRParticleTexture(
                format=container.format,
                width=container.width,
                height=container.height,
                pixels=pixels,
            )
            ir_textures.append(ir_tex)

    logger.info("  Particles: %d generators, %d textures described",
                len(ir_generators), len(ir_textures))

    return IRParticleSystem(
        generators=ir_generators,
        textures=ir_textures,
        ref_ids=list(gpt1.ref_ids),
        raw_gpt1=bytes(gpt1_data),
    )


def _decode_particle_texture(gpt1_data, gx_format, width, height,
                              data_offset, texture_offsets, tex_idx, logger):
    """Decode a GX-format particle texture into RGBA pixels.

    Uses the shared gx_texture.decode_texture() codec.

    Args:
        gpt1_data: Complete GPT1 file bytes.
        gx_format: GX texture format ID (0=I4, 1=I8, ..., 0xE=CMPR).
        width: Texture width in pixels.
        height: Texture height in pixels.
        data_offset: Base offset of texture data from GPT1 start.
        texture_offsets: Per-texture offsets from TXG start.
        tex_idx: Index of the texture to decode.
        logger: Logger instance.

    Returns:
        bytes — RGBA pixel data (width * height * 4 bytes), or empty bytes on failure.
    """
    if width == 0 or height == 0:
        return b''

    try:
        from .....shared.gx_texture import FORMAT_INFO
    except (ImportError, SystemError):
        from shared.gx_texture import FORMAT_INFO
    if gx_format not in FORMAT_INFO:
        logger.debug("    Unsupported particle texture format: %d", gx_format)
        return b''

    bpp, tile_w, tile_h, _ = FORMAT_INFO[gx_format]
    blocks_x = (width + tile_w - 1) // tile_w
    blocks_y = (height + tile_h - 1) // tile_h
    tile_bytes = (tile_w * tile_h * bpp) >> 3
    total_bytes = blocks_x * blocks_y * tile_bytes

    tex_start = data_offset
    if tex_idx > 0 and tex_idx < len(texture_offsets):
        tex_start = data_offset + tex_idx * total_bytes

    if tex_start + total_bytes > len(gpt1_data):
        logger.debug("    Particle texture data out of bounds: start=%d, need=%d, have=%d",
                     tex_start, total_bytes, len(gpt1_data))
        return b''

    raw_data = gpt1_data[tex_start:tex_start + total_bytes]
    result = decode_texture(raw_data, width, height, gx_format)
    if result is None:
        return b''
    return bytes(result)
