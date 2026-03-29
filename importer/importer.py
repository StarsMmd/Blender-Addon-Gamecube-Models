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

        for dat_bytes, metadata in dat_entries:
            logger.info("Processing: %s (%d bytes)", metadata.filename, len(dat_bytes))
            options["filepath"] = metadata.filename

            try:
                # Record which armatures exist before building so we can diff
                # after Phase 5 to find the newly created ones for Phase 6
                existing = set(obj.name for obj in bpy.data.objects if obj.type == 'ARMATURE')

                # Phase 2 — Section Routing: DAT bytes → section name→type map
                logger.info("=== Phase 2: Section Routing ===")
                section_map = route_sections(dat_bytes, logger=logger)

                # Phase 3 — Node Tree Parsing: DAT bytes + map → parsed node trees
                logger.info("=== Phase 3: Node Tree Parsing ===")
                sections = parse_sections(dat_bytes, section_map, options, logger=logger)
                logger.info("Parsed %d section(s)", len(sections))

                # Phase 4 — Scene Description: node trees → Intermediate Representation
                ir_scene = describe_scene(sections, options, logger=logger)

                # Phase 5 — Blender Build: Intermediate Representation → Blender scene
                if context is not None:
                    build_blender_scene(ir_scene, context, options, logger=logger)

                    # Phase 6 — Post-Processing: reset poses, select animations, apply shiny
                    # Diff armatures against the pre-build snapshot to find newly created ones
                    new_armatures = set(obj.name for obj in bpy.data.objects
                                        if obj.type == 'ARMATURE' and obj.name not in existing)
                    post_process(new_armatures, metadata.shiny_params, options, logger=logger)

            except Exception as error:
                traceback.print_exc()
                logger.error("Failed to import %s: %s", metadata.filename, error)
                logger.info("Log file: %s", logger.log_path)
                logger.close()
                raise ModelBuildError(metadata.filename, error) from error

        logger.info("Log file: %s", logger.log_path)
        logger.close()
        return {'FINISHED'}
