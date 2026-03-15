"""pytest configuration: mock Blender APIs and add the addon to sys.path."""
import sys
import os
import pytest
from unittest.mock import MagicMock

# Add the addon directory so `shared` is importable as a top-level package
addon_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

# Add the tests directory so `helpers` is importable
tests_dir = os.path.abspath(os.path.dirname(__file__))
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)

# Mock Blender-only modules before any addon imports
for mod in ('bpy', 'bpy.types', 'bpy.props', 'bpy_extras', 'bpy_extras.io_utils', 'mathutils'):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()


# ---------------------------------------------------------------------------
# --dat-file CLI option and "realfile" marker for opt-in real-file tests
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--dat-file", action="store", default=None,
        help="Path to a real .dat/.pkx file for round-trip validation tests",
    )


@pytest.fixture
def dat_file(request):
    """Fixture that provides the --dat-file path or skips the test."""
    path = request.config.getoption("--dat-file")
    if path is None:
        pytest.skip("No --dat-file provided")
    return path
