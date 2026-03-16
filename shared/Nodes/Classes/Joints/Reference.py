import math

from ...Node import Node
from .Joint import Joint
from ....Constants import *

# Reference (aka RObject)
class Reference(Node):
    class_name = "Reference"
    fields = [
        ('next', 'Reference'),
        ('flags', 'uint'),
        ('property', 'uint'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        self.sub_type = 0
        if (self.flags & ROBJ_ACTIVE_BIT):
            self.sub_type = self.flags & ROBJ_CNST_MASK
            ref_type = self.flags & ROBJ_TYPE_MASK
            if ref_type == REFTYPE_JOBJ:
                self.property = parser.read('Joint', self.property)
            elif ref_type == REFTYPE_IKHINT:
                boneReference = parser.read('BoneReference', self.property)
                if (self.flags & 0x4):
                    boneReference.pole_angle += math.pi
                self.property = boneReference


    def writeBinary(self, builder):
        if not self.property:
            self.flags = 0

        elif isinstance(self.property, Joint):
            self.flags = ROBJ_ACTIVE_BIT | REFTYPE_JOBJ | self.sub_type

        elif isinstance(self.property, list):
            self.flags = ROBJ_ACTIVE_BIT | REFTYPE_IKHINT

        else:
            self.flags = 0

        super().writeBinary(builder)
