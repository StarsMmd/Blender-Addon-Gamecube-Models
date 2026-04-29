"""Export pipeline entry point."""
try:
    from ..shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger

from .phases.pre_process.pre_process import pre_process
from .phases.describe.describe import describe_scene
from .phases.plan.plan import plan_scene
from .phases.compose.compose import compose_scene
from .phases.serialize.serialize import serialize
from .phases.package.package import package_output


class Exporter:
    """Entry point for the export pipeline.

    Pipeline:
        Pre-process (pre_process)    Validate output path + scene
        Phase 1 (describe)           Blender context → BRScene
        Phase 2 (plan)               BRScene → IRScene
        Phase 3 (compose)            IRScene → node trees + section names
        Phase 4 (serialize)          node trees → DAT bytes (via DATBuilder)
        Phase 5 (package)            DAT bytes → final output bytes
    """

    @staticmethod
    def run(context, filepath, options=None, logger=StubLogger()):
        """Run the full export pipeline.

        Args:
            context: Blender context with the scene to export.
            filepath: Target output file path.
            options: dict of exporter options.
            logger: Logger instance.

        Returns:
            {'FINISHED'} on success.

        Raises:
            ValueError: If pre-process validation fails.
        """
        if options is None:
            options = {}

        # Pre-process — Validate output path and scene
        pre_process(context, filepath, options, logger)

        # Extension tells Phase 1 whether to drop the prep-script's
        # auto-generated preview lights/camera — we only strip those when
        # writing a bare .dat. A .pkx export keeps them for self-containment.
        output_ext = filepath.rsplit('.', 1)[-1].lower() if '.' in filepath else ''

        # Phase 1 — Describe Blender Scene: Blender context → BRScene
        br_scene, shiny_params, pkx_header = describe_scene(
            context, options, logger, output_ext=output_ext,
        )

        # Phase 2 — Plan: BRScene → IRScene
        ir_scene = plan_scene(br_scene, options, logger)

        # Phase 3 — Compose: IRScene → node trees
        root_nodes, section_names = compose_scene(ir_scene, options, logger)

        # Phase 4 — Serialize: node trees → DAT bytes
        dat_bytes = serialize(root_nodes, section_names, logger)

        # Phase 5 — Package: DAT bytes → final output
        final_bytes = package_output(dat_bytes, filepath, options, logger,
                                     shiny_params=shiny_params,
                                     pkx_header=pkx_header)

        # Write to disk
        with open(filepath, 'wb') as f:
            f.write(final_bytes)

        logger.info("Exported %d bytes to %s", len(final_bytes), filepath)
        logger.close()

        return {'FINISHED'}
