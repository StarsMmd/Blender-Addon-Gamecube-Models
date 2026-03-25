"""Import pipeline entry point."""
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
        dat_entries = extract_dat(raw_bytes, filename)
        logger.info("Extracted %d DAT entry(s) from %s", len(dat_entries), filename)

        for dat_bytes, metadata in dat_entries:
            logger.info("Processing: %s (%d bytes)", metadata.filename, len(dat_bytes))

            try:
                # Phase 2 — Section Routing: DAT bytes → section name→type map
                logger.info("=== Phase 2: Section Routing ===")
                section_map = route_sections(dat_bytes)
                logger.info("Routed %d section(s): %s", len(section_map), section_map)

                # Phase 3 — Node Tree Parsing: DAT bytes + map → parsed node trees
                logger.info("=== Phase 3: Node Tree Parsing ===")
                sections = parse_sections(dat_bytes, section_map, options, logger=logger)
                logger.info("Parsed %d section(s)", len(sections))

                # Phase 4 — Scene Description: node trees → Intermediate Representation
                ir_scene = describe_scene(sections, options, logger=logger)

                # Phase 5A — Blender Build: Intermediate Representation → Blender scene
                if context is not None:
                    build_blender_scene(ir_scene, context, options, logger=logger)

            except Exception as error:
                traceback.print_exc()
                logger.error("Failed to import %s: %s", metadata.filename, error)
                logger.info("Log file: %s", logger.log_path)
                logger.close()
                raise ModelBuildError(metadata.filename, error) from error

        logger.info("Log file: %s", logger.log_path)
        logger.close()
        return {'FINISHED'}
