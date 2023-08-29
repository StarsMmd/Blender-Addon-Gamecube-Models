from ...Node import Node

from ....Constants import *
from ....Errors import *
from ..Colors import *

# Vertex (aka vtxdesc)
class Vertex(Node):
    class_name = "Vertex"
    is_cachable = False
    fields = [
        ('attribute', 'uint'),
        ('attribute_type', 'uint'),
        ('component_count', 'uint'),
        ('component_type', 'uint'),
        ('component_frac', 'uchar'),
        ('stride', 'ushort'),
        ('base_pointer', 'uint'),
    ]

    def getElementType(self):
        if self.attribute_type == GX_NONE:
            return 'void'

        if self.attribute_type == GX_DIRECT:
            return self._getDirectElementType()
        else:
            if self.component_count == GX_NRM_NBT3:
                if self.attribute_type == GX_INDEX8:
                    return 'uchar[3]'
                else:
                    return 'ushort[3]'
            if self.attribute_type == GX_INDEX8:
                return 'uchar'
            else:
                return 'ushort'
        return 'void'

    def _getDirectElementType(self):
        if self.isMatrix():
            return 'uchar'
        type = ''
        if (self.attribute == GX_VA_CLR0 or
            self.attribute == GX_VA_CLR1):
            if self.component_type == GX_RGBA8:
                return 'RGBAColor'
            elif self.component_type == GX_RGBA6:
                return 'RGBA6Color'
            elif self.component_type == GX_RGBA4:
                return 'RGBA4Color'
            elif self.component_type == GX_RGBX8:
                return 'RGBX8Color'
            elif self.component_type == GX_RGB8:
                return 'RGB8Color'
            else:
                return 'RGB565Color'
        else:
            if self.component_type == GX_F32:
                type = 'float'
            elif self.component_type == GX_S16:
                type = 'short'
            elif self.component_type == GX_U16:
                type = 'ushort'
            elif self.component_type == GX_S8:
                type = 'char'
            else:
                type = 'uchar'
        if self.attribute == GX_VA_POS:
            if self.component_count == GX_POS_XY:
                return type + '[2]'
            else:
                return type + '[3]'
        elif self.attribute == GX_VA_NRM:
            # GX_NRM_XYZ:
            return type + '[3]'
        elif self.isTexture:
            if self.component_count == GX_TEX_S:
                return type
            else:
                return type + '[2]'
        elif self.attribute == GX_VA_NBT:
            if self.component_count == GX_NRM_NBT3:
                return type + '[3]'
            else:
                return type + '[9]'
        raise UnknownVertexAttributeError(self)
        return 'void'

    def isMatrix(self):
        return (self.attribute == GX_VA_PNMTXIDX or
                self.attribute == GX_VA_TEX0MTXIDX or
                self.attribute == GX_VA_TEX1MTXIDX or
                self.attribute == GX_VA_TEX2MTXIDX or
                self.attribute == GX_VA_TEX3MTXIDX or
                self.attribute == GX_VA_TEX4MTXIDX or
                self.attribute == GX_VA_TEX5MTXIDX or
                self.attribute == GX_VA_TEX6MTXIDX or
                self.attribute == GX_VA_TEX7MTXIDX)

    def isTexture(self):
        return (self.attribute == GX_VA_TEX0 or
            self.attribute == GX_VA_TEX1 or
            self.attribute == GX_VA_TEX2 or
            self.attribute == GX_VA_TEX3 or
            self.attribute == GX_VA_TEX4 or
            self.attribute == GX_VA_TEX5 or
            self.attribute == GX_VA_TEX6 or
            self.attribute == GX_VA_TEX7)
