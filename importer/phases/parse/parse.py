"""Phase 3 — Node Tree Parsing: DAT bytes + section map → parsed node trees.

Thin wrapper around the existing DATParser. Creates a parser from
in-memory bytes, resolves sections using the provided section map,
and returns the parsed section list.
"""
import io

try:
    from ....shared.IO.DAT_io import DATParser
    from ....shared.IO.Logger import StubLogger
except (ImportError, SystemError):
    from shared.IO.DAT_io import DATParser
    from shared.IO.Logger import StubLogger


def parse_sections(dat_bytes, section_map, options, logger=StubLogger()):
    """Parse DAT bytes into node trees using the section map.

    Args:
        dat_bytes: Raw DAT binary (no container header).
        section_map: dict of {section_name: node_type_name} from Phase 2.
        options: Importer options dict.
        logger: Logger instance.

    Returns:
        list of SectionInfo with parsed root nodes.
    """

    stream = io.BytesIO(dat_bytes)

    parse_options = dict(options)
    parse_options['section_map'] = section_map

    parser = DATParser(stream, parse_options, logger=logger)
    parser.parseSections()
    parser.close()

    return parser.sections
