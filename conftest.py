# Prevent pytest from trying to import the Blender addon entry point,
# which uses relative imports that are only valid inside Blender.
collect_ignore = ['__init__.py']
