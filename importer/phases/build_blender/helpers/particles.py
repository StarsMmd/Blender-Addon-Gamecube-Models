"""Build Blender particle visualization from IRParticleSystem.

Stub — particle visualization is not yet implemented. The parsing,
bytecode disassembly, and IR representation are complete. The build
phase will be implemented once the physics fitting approach is validated.

The GPT1 data is fully preserved in IRParticleSystem.raw_gpt1 for
round-trip export.
"""

try:
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def build_particles(ir_particles, armature, context, logger=StubLogger()):
    """Stub — stores particle metadata on the armature but creates no Blender objects."""
    if ir_particles is None:
        return

    model_name = armature.name.replace('Armature_', '')
    armature["dat_particle_count"] = len(ir_particles.generators)
    armature["dat_particle_texture_count"] = len(ir_particles.textures)

    logger.info("  Particles: %d generators, %d textures (build stubbed)",
                len(ir_particles.generators), len(ir_particles.textures))
