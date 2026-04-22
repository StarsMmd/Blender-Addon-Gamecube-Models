"""Import pipeline entry point."""
import bpy
import traceback

try:
    from ..shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger

from .phases.extract.extract import extract_dat
from .phases.route.route import route_sections
from .phases.parse.parse import parse_sections
from .phases.describe.describe import describe_scene
from .phases.describe.helpers.particles import describe_particles
from .phases.plan.plan import plan_scene
from .phases.build_blender.build_blender import build_blender_scene
from .phases.build_blender.errors.build_errors import ModelBuildError
from .phases.post_process.post_process import post_process


class Importer:
    """Entry point for the Intermediate Representation import pipeline."""

    @staticmethod
    def run(context, raw_bytes, filename, options, logger=StubLogger()):
        """Run the full import pipeline.

        Args:
            context: Blender context (or None for headless).
            raw_bytes: Complete file contents as bytes.
            filename: Original filename (for container detection and logging).
            options: dict of importer options.
            logger: Logger instance.
        """
        # Phase 1 — Container Extraction: raw file bytes → DAT bytes
        logger.info("=== Phase 1: Container Extraction ===")
        dat_entries = extract_dat(raw_bytes, filename, options=options)
        logger.info("Extracted %d DAT entry(s) from %s", len(dat_entries), filename)

        any_succeeded = False
        errors = []

        for dat_bytes, metadata in dat_entries:
            logger.info("Processing: %s (%d bytes)", metadata.filename, len(dat_bytes))
            options["filepath"] = metadata.filename

            try:
                # GPT1-only entry (e.g. standalone particle from WZX) — skip DAT phases
                if not dat_bytes and metadata.gpt1_data:
                    logger.info("=== Phase 4b: Particle Description (standalone) ===")
                    particle_system = describe_particles(metadata.gpt1_data, logger=logger)
                    if particle_system:
                        logger.info("Described standalone particle system: %d generators",
                                    len(particle_system.generators) if particle_system.generators else 0)
                    any_succeeded = True
                    continue

                # Phase 2 — Section Routing: DAT bytes → section name→type map
                logger.info("=== Phase 2: Section Routing ===")
                section_map = route_sections(dat_bytes, logger=logger)

                # Phase 3 — Node Tree Parsing: DAT bytes + map → parsed node trees
                logger.info("=== Phase 3: Node Tree Parsing ===")
                sections = parse_sections(dat_bytes, section_map, options, logger=logger)
                logger.info("Parsed %d section(s)", len(sections))

                # Phase 4 — Scene Description: node trees → Intermediate Representation
                options["pkx_header"] = metadata.pkx_header
                ir_scene = describe_scene(sections, options, logger=logger)

                # Phase 4b — Particle Description: GPT1 binary → IRParticleSystem
                if metadata.gpt1_data:
                    logger.info("=== Phase 4b: Particle Description ===")
                    particle_system = describe_particles(metadata.gpt1_data, logger=logger)
                    if particle_system and ir_scene.models:
                        ir_scene.models[0].particles = particle_system
                        logger.info("Attached particle system to model '%s'",
                                    ir_scene.models[0].name)

                # Phase 5a — Plan: IR → BR (Blender Representation)
                logger.info("=== Phase 5a: Plan (IR → BR) ===")
                br_scene = plan_scene(ir_scene, options, logger=logger)

                # Phase 5b — Build: BR → Blender scene. No IR access from
                # here on; build is a pure bpy executor.
                if context is not None:
                    build_results = build_blender_scene(
                        br_scene, context, options, logger=logger,
                    )

                    # Phase 6 — Post-Processing: select animations, apply shiny, store PKX metadata
                    post_process(set(), metadata.shiny_params, options, logger=logger,
                                 build_results=build_results,
                                 pkx_header=metadata.pkx_header)

                any_succeeded = True

            except Exception as error:
                traceback.print_exc()
                logger.error("Failed to import %s: %s", metadata.filename, error)
                errors.append((metadata.filename, error))

        logger.info("Log file: %s", logger.log_path)
        logger.close()

        if not any_succeeded:
            if errors:
                first_file, first_error = errors[0]
                raise ModelBuildError(first_file, first_error) from first_error
            else:
                raise ModelBuildError(filename, ValueError("No importable content found in file"))

        return {'FINISHED'}
