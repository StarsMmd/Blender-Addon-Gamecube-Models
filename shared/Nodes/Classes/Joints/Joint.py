from ...Node import Node
from ....Constants import *
from ..Rendering.Particle import Particle
from ..Misc.Spline import Spline

# Joint (aka Bone)
class Joint(Node):
    class_name = "Joint"
    isHidden = False
    fields = [
        ('name', 'string'),
        ('flags', 'uint'),
        ('child', 'Joint'),
        ('next', 'Joint'),
        ('property', 'uint'),
        ('rotation', 'vec3'),
        ('scale', 'vec3'),
        ('position', 'vec3'),
        ('inverse_bind', 'matrix'),
        ('reference', 'Reference')
    ]

    # Parse struct from binary file.
    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        self.id = self.address
        self.isHidden = self.flags & JOBJ_HIDDEN

        property_type = 'Mesh'
        if self.flags & JOBJ_PTCL:
            property_type = 'Particle'
        elif self.flags & JOBJ_SPLINE:
            property_type = 'Spline'

        if self.property > 0:
            parser.logger.debug("Joint 0x%X: property -> %s at 0x%X, flags=0x%X",
                                self.address, property_type, self.property, self.flags)
            self.property = parser.read(property_type, self.property)
        else:
            self.property = None

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder):
        # Convert property Node to its address — don't modify flags
        if self.property is not None and hasattr(self.property, 'address'):
            self.property = self.property.address if self.property.address is not None else 0
            if self.property != 0:
                if not hasattr(self, '_raw_pointer_fields'):
                    self._raw_pointer_fields = set()
                self._raw_pointer_fields.add('property')
        elif self.property is None:
            self.property = 0
        # else: property is already an int (e.g. 0)

        super().writeBinary(builder)

    def getReferenceObject(self, type, sub_type):
        """Find a Reference by property type and sub_type.
        When sub_type is 0, matches any sub_type (wildcard), matching legacy behavior."""
        reference = self.reference
        while reference:
            if isinstance(reference.property, type):
                if not sub_type or reference.sub_type == sub_type:
                    return reference
            reference = reference.next

        return None

