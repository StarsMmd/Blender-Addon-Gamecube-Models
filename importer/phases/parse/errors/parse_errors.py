"""Errors raised during Phase 3 — Node Tree Parsing.

All parsing errors are defined here. shared/Errors/ re-exports them
so that shared/Nodes/ and shared/Constants/ code can raise them via
their existing relative imports.
"""


class SectionParseError(Exception):
    """Failed to parse a section's node tree."""
    def __init__(self, section_name, cause):
        self.section_name = section_name
        self.cause = cause

    def __str__(self):
        return "Failed to parse section '%s': %s" % (self.section_name, self.cause)


class InvalidReadAddressError(Exception):
    """Read attempted beyond the end of the binary data."""
    def __init__(self, read_address=0, value_type='', file_size=0):
        self.read_address = read_address
        self.value_type = value_type
        self.file_size = file_size

    def __str__(self):
        return ("Failed to read %s at address: 0x%X (file size: 0x%X)"
                % (self.value_type, self.read_address, self.file_size))


class ArrayBoundsUnknownVariableError(Exception):
    """Bounded array references a field name that doesn't exist on the node."""
    def __init__(self, variable_name=''):
        self.variable_name = variable_name

    def __str__(self):
        return "Array field with unknown variable name: %s" % self.variable_name


class InvalidEnvelopeError(Exception):
    """PObject with POBJ_ENVELOPE flag has no PNMTXIDX vertex attribute."""
    def __str__(self):
        return "Vertex list does not contain vertex with attribute GX_VA_PNMTXIDX"


class MeshWithoutPositionError(Exception):
    """PObject has no vertex attribute with GX_VA_POS."""
    def __str__(self):
        return "Vertex list does not contain vertex with attribute GX_VA_POS"


class PixelEngineUnknownBlendModeError(Exception):
    """Pixel engine data with unrecognized blend mode type."""
    def __init__(self, blend_mode=0):
        self.blend_mode = blend_mode

    def __str__(self):
        return "Pixel Engine data with unknown blend mode: %s" % str(self.blend_mode)


class ShapeSetDimensionMismatchError(Exception):
    """ShapeSet vertex and normal arrays have different lengths."""
    def __init__(self, vertex_count=0, normal_count=0):
        self.vertex_count = vertex_count
        self.normal_count = normal_count

    def __str__(self):
        return ("Shape set vertex/normal count mismatch: %d vertices, %d normals"
                % (self.vertex_count, self.normal_count))


class InvalidPrimitiveTypeError(Exception):
    """Unrecognized primitive type name."""
    def __init__(self, type_name=''):
        self.type_name = type_name

    def __str__(self):
        return "Couldn't recognise primitive type with name: %s" % self.type_name


class InvalidTypeError(Exception):
    """Unrecognized type name."""
    def __init__(self, type_name=''):
        self.type_name = type_name

    def __str__(self):
        return "Couldn't recognise type with name: %s" % self.type_name


class StringTypeLengthError(Exception):
    """Attempted to get a fixed length for a variable-length string type."""
    def __str__(self):
        return "Strings have varying lengths. Never stride by string type length."


class VoidTypeStructFormatError(Exception):
    """Attempted to unpack void data from a struct."""
    def __str__(self):
        return "Void data can't be unpacked from structs"


class StringTypeStructFormatError(Exception):
    """Attempted to unpack a string directly from a struct."""
    def __str__(self):
        return "Strings can't be unpacked from structs"


class MatrixTypeStructFormatError(Exception):
    """Attempted to unpack a matrix directly from a struct."""
    def __str__(self):
        return "Matrices can't be unpacked directly from structs"


class UnknownVertexAttributeError(Exception):
    """Vertex has an unrecognized attribute type."""
    def __init__(self, vertex=None):
        self.vertex = vertex

    def __str__(self):
        return "Vertex with unknown attribute type: %s" % str(getattr(self.vertex, 'attribute', '?'))


class VertexListTerminatorError(Exception):
    """Vertex list is missing the 0xFF terminator."""
    def __str__(self):
        return "Vertex List is missing terminator vertex with attribute 0xFF"
