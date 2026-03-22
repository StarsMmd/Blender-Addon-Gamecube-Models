import math
import struct

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
                parser.logger.debug("Reference 0x%X: -> Joint at 0x%X", self.address, self.property)
                self.property = parser.read('Joint', self.property)
            elif ref_type == REFTYPE_IKHINT:
                parser.logger.debug("Reference 0x%X: -> BoneReference at 0x%X (pole_flip=%s)",
                                    self.address, self.property, bool(self.flags & 0x4))
                boneReference = parser.read('BoneReference', self.property)
                if (self.flags & 0x4):
                    boneReference.pole_angle += math.pi
                self.property = boneReference
            elif ref_type == REFTYPE_LIMIT:
                # Property field is a float value (limit amount), reinterpret the uint as float
                self.property = struct.unpack('>f', struct.pack('>I', self.property))[0]
                parser.logger.debug("Reference 0x%X: LIMIT sub_type=%d value=%f",
                                    self.address, self.sub_type, self.property)
            else:
                parser.logger.warning("Reference 0x%X: unknown ref_type 0x%X, flags=0x%X",
                                      self.address, ref_type, self.flags)


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
