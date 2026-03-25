"""Re-export parse errors so shared/Nodes/ and shared/Constants/ can import them.

The canonical definitions live in importer/phases/parse/errors/parse_errors.py.
"""
try:
    from ...importer.phases.parse.errors.parse_errors import *
except (ImportError, SystemError):
    from importer.phases.parse.errors.parse_errors import *
