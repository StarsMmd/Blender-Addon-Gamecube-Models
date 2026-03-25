"""Errors specific to Phase 3 — Node Tree Parsing.

Errors raised by shared/Nodes/ and shared/Constants/ code during parsing
remain in shared/Errors/. This module defines errors specific to the
Phase 3 pipeline wrapper.
"""


class SectionParseError(Exception):
    """Failed to parse a section's node tree."""
    def __init__(self, section_name, cause):
        self.section_name = section_name
        self.cause = cause

    def __str__(self):
        return "Failed to parse section '%s': %s" % (self.section_name, self.cause)
