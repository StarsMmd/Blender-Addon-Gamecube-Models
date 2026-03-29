class BlenderVersion:
    """Version comparison utility for Blender version checks.

    Usage:
        from shared.BlenderVersion import BlenderVersion
        if bpy.app.version >= BlenderVersion(4, 5, 0):
            ...
    """

    def __init__(self, major, minor, patch):
        self.version = (major, minor, patch)

    def __eq__(self, other):
        if isinstance(other, tuple):
            return self.version == other
        if isinstance(other, BlenderVersion):
            return self.version == other.version
        return NotImplemented

    def __lt__(self, other):
        if isinstance(other, tuple):
            return self.version < other
        if isinstance(other, BlenderVersion):
            return self.version < other.version
        return NotImplemented

    def __le__(self, other):
        if isinstance(other, tuple):
            return self.version <= other
        if isinstance(other, BlenderVersion):
            return self.version <= other.version
        return NotImplemented

    def __gt__(self, other):
        if isinstance(other, tuple):
            return self.version > other
        if isinstance(other, BlenderVersion):
            return self.version > other.version
        return NotImplemented

    def __ge__(self, other):
        if isinstance(other, tuple):
            return self.version >= other
        if isinstance(other, BlenderVersion):
            return self.version >= other.version
        return NotImplemented

    def __repr__(self):
        return f"BlenderVersion{self.version}"
