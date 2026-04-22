"""Phase 3 — Node Tree Parsing: DAT bytes + section map → parsed node trees.

Thin wrapper around DATParser. Creates a parser from in-memory bytes,
resolves sections using the provided section map, and returns the
parsed section list.
"""
import io

from .helpers.dat_parser import DATParser

try:
    from ....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def parse_sections(dat_bytes, section_map, options, logger=StubLogger()):
    """Parse DAT bytes into node trees, typing each section via the section map.

    In: dat_bytes (bytes, raw DAT, no container header); section_map (dict[str,str], section_name→node_type from Phase 2); options (dict, importer options); logger (Logger, defaults to StubLogger).
    Out: list[SectionInfo], one per recognized section with `.root_node` populated.
    """
    stream = io.BytesIO(dat_bytes)

    parse_options = dict(options)
    parse_options['section_map'] = section_map

    parser = DATParser(stream, parse_options, logger=logger)
    parser.parseSections()
    parser.close()

    return parser.sections
