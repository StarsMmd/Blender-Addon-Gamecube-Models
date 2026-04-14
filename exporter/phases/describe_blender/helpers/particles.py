"""Phase 1 (export) — read GPT1 particle data from a Blender armature.

Inverts importer/phases/build_blender/helpers/particles.py: walks the
`Particles_{model}` empty under the armature, reads each generator mesh's
header-field custom properties, extracts the instruction list from the
GeometryNodeTree's NodeFrames, and recovers texture data from the atlas image.
"""
import bpy

try:
    from .....shared.IR.particles import (
        IRParticleSystem, IRParticleGenerator, IRParticleTexture,
    )
    from .....shared.helpers.logger import StubLogger
    from .....importer.phases.build_blender.helpers.particle_opcodes import (
        read_instruction_frames, SUPPORTED_MNEMONICS,
    )
    from .....importer.phases.build_blender.helpers.particles import (
        PARTICLES_EMPTY_PREFIX, GENERATOR_MESH_PREFIX,
    )
except (ImportError, SystemError):
    from shared.IR.particles import (
        IRParticleSystem, IRParticleGenerator, IRParticleTexture,
    )
    from shared.helpers.logger import StubLogger
    from importer.phases.build_blender.helpers.particle_opcodes import (
        read_instruction_frames, SUPPORTED_MNEMONICS,
    )
    from importer.phases.build_blender.helpers.particles import (
        PARTICLES_EMPTY_PREFIX, GENERATOR_MESH_PREFIX,
    )


def describe_particles(armature, logger=StubLogger()):
    """Read particle data from the Blender scene for a single armature.

    Returns:
        IRParticleSystem or None if no `Particles_{model}` empty exists.
    """
    model_name = armature.name.replace('Armature_', '')
    empty_name = PARTICLES_EMPTY_PREFIX + model_name
    empty = bpy.data.objects.get(empty_name)
    if empty is None:
        return None

    generator_meshes = sorted(
        (c for c in empty.children if c.type == 'MESH'),
        key=lambda o: o.name,
    )
    if not generator_meshes:
        return None

    ir_generators = []
    ir_textures = []
    textures_seen = {}  # atlas_image_name → starting index in ir_textures

    for gen_idx, mesh_obj in enumerate(generator_meshes):
        instructions = _extract_instructions_from_mesh(mesh_obj, gen_idx)
        _validate_instructions(gen_idx, instructions)

        params = tuple(float(v) for v in mesh_obj.get('params', (0.0,) * 12))
        while len(params) < 12:
            params = params + (0.0,)

        ir_gen = IRParticleGenerator(
            index=gen_idx,
            gen_type=int(mesh_obj.get('gen_type', 0)),
            lifetime=int(mesh_obj.get('lifetime', 120)),
            max_particles=int(mesh_obj.get('max_particles', 0)),
            flags=int(mesh_obj.get('flags', 0)),
            params=params[:12],
            instructions=instructions,
        )
        ir_generators.append(ir_gen)

        # Collect textures from the atlas (once per unique atlas image).
        atlas = _find_atlas_image_for_mesh(mesh_obj)
        if atlas is not None and atlas.name not in textures_seen:
            textures_seen[atlas.name] = len(ir_textures)
            ir_textures.extend(_unpack_atlas(atlas))

    ref_ids = list(empty.get('gpt1_ref_ids', []))

    logger.info("  Particles (export): %d generators, %d textures",
                len(ir_generators), len(ir_textures))
    return IRParticleSystem(
        generators=ir_generators,
        textures=ir_textures,
        ref_ids=ref_ids,
    )


def _extract_instructions_from_mesh(mesh_obj, gen_idx):
    for mod in mesh_obj.modifiers:
        if mod.type == 'NODES' and mod.node_group is not None:
            return read_instruction_frames(mod.node_group)
    raise ValueError(
        "Particle generator mesh '%s' (generator %d) has no GeometryNodes modifier "
        "with a node group — cannot export." % (mesh_obj.name, gen_idx)
    )


def _validate_instructions(gen_idx, instructions):
    for ins_idx, ins in enumerate(instructions):
        if ins.mnemonic not in SUPPORTED_MNEMONICS:
            raise ValueError(
                "Particle generator %d instruction %d uses unsupported opcode '%s'. "
                "Phase 1 supports: %s" %
                (gen_idx, ins_idx, ins.mnemonic, ', '.join(sorted(SUPPORTED_MNEMONICS)))
            )


def _find_atlas_image_for_mesh(mesh_obj):
    """Find the atlas image referenced by the generator mesh's material."""
    for slot in mesh_obj.material_slots:
        mat = slot.material
        if mat is None or not mat.use_nodes:
            continue
        for node in mat.node_tree.nodes:
            if node.bl_idname == 'ShaderNodeTexImage' and node.image is not None:
                if 'gpt1_tex_widths' in node.image:
                    return node.image
    return None


def _unpack_atlas(atlas):
    """Split an atlas image back into its original IRParticleTexture list."""
    widths = list(atlas.get('gpt1_tex_widths', []))
    heights = list(atlas.get('gpt1_tex_heights', []))
    formats = list(atlas.get('gpt1_tex_formats', []))
    if not widths:
        return []

    pixels_flat = list(atlas.pixels)
    atlas_w = atlas.size[0]
    atlas_h = atlas.size[1]

    textures = []
    x_cursor = 0
    for i, w in enumerate(widths):
        h = heights[i] if i < len(heights) else 0
        fmt = formats[i] if i < len(formats) else 0
        if w <= 0 or h <= 0:
            textures.append(IRParticleTexture(format=fmt, width=w, height=h, pixels=b''))
            continue
        buf = bytearray(w * h * 4)
        # Atlas and IR both use bottom-to-top row order (no flip).
        for y in range(h):
            for x in range(w):
                src = (y * atlas_w + (x_cursor + x)) * 4
                dst = (y * w + x) * 4
                buf[dst + 0] = int(max(0, min(255, round(pixels_flat[src + 0] * 255))))
                buf[dst + 1] = int(max(0, min(255, round(pixels_flat[src + 1] * 255))))
                buf[dst + 2] = int(max(0, min(255, round(pixels_flat[src + 2] * 255))))
                buf[dst + 3] = int(max(0, min(255, round(pixels_flat[src + 3] * 255))))
        textures.append(IRParticleTexture(format=fmt, width=w, height=h, pixels=bytes(buf)))
        x_cursor += w
    return textures
