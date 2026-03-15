"""pytest configuration: mock Blender APIs and add the addon to sys.path."""
import sys
import os
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
