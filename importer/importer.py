"""Import pipeline entry point."""
import os

try:
    from ..shared.IO.Logger import Logger, NullLogger
except (ImportError, SystemError):
    from shared.IO.Logger import Logger, NullLogger

from .phases.extract.extract import extract_dat
from .phases.route.route import route_sections
from .phases.parse.parse import parse_sections
from .phases.describe.describe import describe_scene
from .phases.build_blender.build_blender import build_blender_scene


class Importer:
    """Entry point for the Intermediate Representation import pipeline."""

    @staticmethod
    def run(context, filepath, options, logger=NullLogger()):
        """Run the full import pipeline.

        Args:
            context: Blender context (or None for headless).
            filepath: Path to the model file (.dat, .pkx, .fsys).
            options: dict of importer options.
            logger: Logger instance.
        """
        # Phase 1 — Container Extraction: binary file → DAT bytes
        logger.info("=== Phase 1: Container Extraction ===")
        dat_entries = extract_dat(filepath)
        logger.info("Extracted %d DAT entry(s) from %s", len(dat_entries), os.path.basename(filepath))

        for dat_bytes, metadata in dat_entries:
            logger.info("Processing: %s (%d bytes)", metadata.filename, len(dat_bytes))

            # Phase 2 — Section Routing: DAT bytes → section name→type map
            logger.info("=== Phase 2: Section Routing ===")
            section_map = route_sections(dat_bytes)
            logger.info("Routed %d section(s): %s", len(section_map), section_map)

            # Phase 3 — Node Tree Parsing: DAT bytes + map → parsed node trees
            logger.info("=== Phase 3: Node Tree Parsing ===")
            sections = parse_sections(dat_bytes, section_map, options, logger=logger)
            logger.info("Parsed %d section(s)", len(sections))

            # Phase 4 — Scene Description: node trees → Intermediate Representation
            ir_scene, raw_animations = describe_scene(sections, options, logger=logger)

            # Phase 5A — Blender Build: Intermediate Representation → Blender scene
            if context is not None:
                try:
                    build_blender_scene(ir_scene, context, options, logger=logger,
                                        raw_animations=raw_animations)
                except Exception as error:
                    import traceback
                    traceback.print_exc()
                    logger.error("Failed to build model: %s", error)
                    logger.info("Log file: %s", logger.log_path)
                    logger.close()
                    raise

        logger.info("Log file: %s", logger.log_path)
        logger.close()
        return {'FINISHED'}
