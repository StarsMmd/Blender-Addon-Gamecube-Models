"""Phase 3 (Export): Serialize node trees to DAT bytes via DATBuilder.

Takes the root nodes and section names produced by the compose phase
and writes them to an in-memory DAT binary using DATBuilder.
"""
import io

try:
    from .helpers.dat_builder import DATBuilder
    from ....shared.helpers.logger import StubLogger
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
    logger.info("  Serializing %d section(s): %s", len(root_nodes), section_names)

    stream = io.BytesIO()
    builder = DATBuilder(stream, root_nodes, section_names)
    builder.build()

    dat_bytes = stream.getvalue()

    # Pad to 0x20 alignment
    remainder = len(dat_bytes) % 0x20
    if remainder != 0:
        dat_bytes += b'\x00' * (0x20 - remainder)

    logger.info("  Node count: %d", len(builder.node_list))
    logger.info("  Relocations: %d", len(builder.relocations))

    if logger.verbose:
        _log_size_breakdown(builder, section_names, dat_bytes, logger)

    logger.info("=== Export Phase 3 complete: %d bytes (0x20 aligned) ===", len(dat_bytes))
    return dat_bytes


def _log_size_breakdown(builder, section_names, dat_bytes, logger):
    """Emit a verbose per-section / per-node-type DAT size breakdown.

    Uses the section_ownership + node_sizes dicts populated by DATBuilder
    during build. Every byte in the data section is attributed to exactly
    one node, and every node to exactly one section, so the per-section
    totals always sum to the data-section length.
    """
    total = max(len(dat_bytes), 1)

    # --- Per-section totals ---
    section_totals = [0] * len(builder.root_nodes)
    for node in builder.node_list:
        idx = builder.section_ownership.get(id(node))
        if idx is None:
            continue
        section_totals[idx] += builder.node_sizes.get(id(node), 0)

    # --- Node-type rollup ---
    type_totals = {}
    type_counts = {}
    for node in builder.node_list:
        size = builder.node_sizes.get(id(node), 0)
        cls = type(node).__name__
        type_totals[cls] = type_totals.get(cls, 0) + size
        type_counts[cls] = type_counts.get(cls, 0) + 1

    # --- Overhead bytes (outside the node-by-node data section) ---
    relocation_bytes = len(builder.relocations) * 4
    section_info_bytes = len(builder.root_nodes) * 8  # (address uint, string_offset uint)
    string_table_bytes = 0
    for i, root_node in enumerate(builder.root_nodes):
        name = section_names[i] if i < len(section_names) and section_names[i] else root_node.class_name
        string_table_bytes += len(name) + 1
    header_bytes = builder.DAT_header_length

    logger.debug("=== DAT size breakdown ===")
    for i, name in enumerate(section_names):
        size = section_totals[i]
        logger.debug("  section '%s': %s (%.1f%%)",
                     name, _fmt_bytes(size), 100.0 * size / total)

    logger.debug("  by node type (top 10):")
    top = sorted(type_totals.items(), key=lambda kv: -kv[1])[:10]
    for cls, size in top:
        logger.debug("    %-20s %s (%.1f%%)  x %d",
                     cls, _fmt_bytes(size), 100.0 * size / total, type_counts[cls])

    logger.debug("  relocations: %s (%d entries)",
                 _fmt_bytes(relocation_bytes), len(builder.relocations))
    logger.debug("  section info: %s", _fmt_bytes(section_info_bytes))
    logger.debug("  string table: %s", _fmt_bytes(string_table_bytes))
    logger.debug("  header: %s", _fmt_bytes(header_bytes))
    logger.debug("  total DAT (aligned): %s", _fmt_bytes(len(dat_bytes)))


def _fmt_bytes(n):
    if n >= 1024 * 1024:
        return "%.2f MB" % (n / (1024 * 1024))
    if n >= 1024:
        return "%.1f KB" % (n / 1024)
    return "%d B" % n
