"""Phase 5 particle visualization — currently disabled.

GPT1 particles parse into `IRParticleSystem` (Phase 4) with full bytecode
decoded into `ParticleInstruction`s, but we never instantiate Blender
objects from that data. Reason: we could not locate the table that binds
a given generator to a body-map bone for the 15 particle-bearing models
(Moltres, Charizard, Gastly, …). Every attach path in the XD disassembly
takes a slot literal from a caller (WZX move data, status-effect
handlers, overworld scripts); no per-species idle-effect table has been
found in the PKX, the GPT1, the model's HSD tree, common.rel indexes, or
the DOL data section around `PKXPokemonModels`. Creating generator
meshes at the armature origin without a correct attachment would be
actively misleading, so we skip it.

The rest of the particle plumbing stays in place for when the binding
mechanism is discovered:
  * `shared/helpers/gpt1.py`            — GPT1 container parse/serialize
  * `shared/helpers/gpt1_commands.py`   — bytecode disassemble/assemble
  * `shared/IR/particles.py`            — `IRParticleSystem` dataclasses
  * `importer/phases/describe/helpers/particles.py` — GPT1 bytes → IR
  * `exporter/phases/compose/helpers/particles.py`  — IR → GPT1 bytes (not wired)
  * `importer/phases/build_blender/helpers/particle_opcodes.py` — opcode specs

When the binding is found, the rewrite lives here:
  1. Resolve each generator to a bone via the new binding table
  2. Create one mesh per generator, parented to that bone
  3. Build a GeometryNodeTree with NodeFrames per instruction (see
     `particle_opcodes.build_instruction_frame`)
"""
try:
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def build_particles(ir_particles, armature, context, logger=StubLogger()):
    """Stub — records generator/texture counts on the armature, nothing else."""
    if ir_particles is None:
        return

    gen_count = len(ir_particles.generators)
    tex_count = len(ir_particles.textures)
    armature["dat_particle_gen_count"] = gen_count
    armature["dat_particle_tex_count"] = tex_count

    if gen_count or tex_count:
        logger.info(
            "  Particles: %d generators / %d textures parsed; skipping build "
            "(generator-to-bone binding unresolved)",
            gen_count, tex_count,
        )
