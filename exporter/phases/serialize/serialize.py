"""Phase 3 (Export): Serialize node trees to DAT bytes via DATBuilder.

Takes the root nodes and section names produced by the compose phase
and writes them to an in-memory DAT binary using DATBuilder.
"""
import io

try:
    from .helpers.dat_builder import DATBuilder
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from exporter.phases.serialize.helpers.dat_builder import DATBuilder
    from shared.helpers.logger import StubLogger


def serialize(root_nodes, section_names, logger=StubLogger()):
    """Serialize node trees to DAT bytes.

    Args:
        root_nodes: list of root Node objects (e.g. SceneData).
        section_names: list of section name strings (same order as root_nodes).
        logger: Logger instance.

    Returns:
        bytes — the complete DAT binary.
    """
    logger.info("=== Export Phase 3: Serialize ===")
    logger.info("Serializing %d section(s): %s", len(root_nodes), section_names)

    stream = io.BytesIO()
    builder = DATBuilder(stream, root_nodes, section_names)
    builder.build()

    dat_bytes = stream.getvalue()

    logger.info("=== Export Phase 3 complete: %d bytes ===", len(dat_bytes))
    return dat_bytes
