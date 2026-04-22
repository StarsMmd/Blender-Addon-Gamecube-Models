"""Particle visualization — stub.

Full instantiation awaits the generator→bone binding mechanism (see
original file header in git history for the investigation notes). For
now we stamp counts onto the armature so users can see the data parsed.
"""
try:
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def build_particles(br_particles, armature, context, logger=StubLogger()):
    if br_particles is None:
        return

    armature["dat_particle_gen_count"] = br_particles.generator_count
    armature["dat_particle_tex_count"] = br_particles.texture_count

    if br_particles.generator_count or br_particles.texture_count:
        logger.info(
            "  Particles: %d generators / %d textures parsed; skipping build "
            "(generator-to-bone binding unresolved)",
            br_particles.generator_count, br_particles.texture_count,
        )
