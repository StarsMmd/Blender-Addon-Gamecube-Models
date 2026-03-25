# Prevent pytest from trying to import Blender-specific entry points
collect_ignore = ['__init__.py', 'BlenderPlugin.py', '__main__.py', 'CommandLineInterface.py']
