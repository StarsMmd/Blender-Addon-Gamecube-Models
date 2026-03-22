import bpy
from mathutils import Vector

from ...Node import Node

# Spline
class Spline(Node):
    class_name = "Spline"
    fields = [
        ('flags', 'ushort'),
        ('n', 'ushort'),
        ('f0', 'float'),
        ('s1', 'uint'),
        ('f1', 'float'),
        ('s2', 'uint'),
        ('s3', 'uint'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        spline_type = self.flags >> 8
        parser.logger.debug("Spline 0x%X: type=%d, n=%d, s1=0x%X, s2=0x%X, s3=0x%X",
                            self.address, spline_type, self.n, self.s1 or 0, self.s2 or 0, self.s3 or 0)
        if (self.flags >> 8) == 0:
            if self.s1:
                s1_address = self.s1
                self.s1 = []
                for i in range(self.n):
                    v = []
                    for j in range(3):
                        offset = i * 12 + j * 4
                        value = parser.read('float', s1_address, offset)
                        v.append(value)
                    self.s1.append(v)

            else:
                self.s1 = None

            if not self.s3:
                self.s3 = None

        elif (self.flags >> 8) == 3:
            if self.s1:
                s1_address = self.s1
                self.s1 = []
                for i in range(self.n + 2):
                    v = []
                    for j in range(3):
                        offset = i * 12 + j * 4
                        value = parser.read('float', s1_address, offset)
                        v.append(value)
                    self.s1.append(v)

            else:
                self.s1 = None

            if self.s3:
                s3_address = self.s3
                self.s3 = []
                for i in range(self.n - 1):
                    v = []
                    for j in range(5):
                        offset = i * 20 + j * 4
                        value = parser.read('float', s3_address, offset)
                        v.append(value)
                    self.s3.append(v)

            else:
                self.s3 = None

        else:
            pass

        if self.s2:
            s2_address = self.s2
            self.s2 = []
            for i in range(self.n):
                offset = i * 4
                value = parser.read('float', s2_address, offset)
                self.s2.append(value)

        else:
            self.s2 = None

    def build(self, builder):
        if not self.s1:
            return None

        spline_type = self.flags >> 8
        curve_data = bpy.data.curves.new('Spline_' + str(self.address), type='CURVE')
        curve_data.dimensions = '3D'

        if spline_type == 0:
            # Polyline
            spline = curve_data.splines.new('POLY')
            spline.points.add(len(self.s1) - 1)
            for i, pt in enumerate(self.s1):
                spline.points[i].co = Vector((pt[0], pt[1], pt[2], 1.0))
        elif spline_type == 3:
            # NURBS
            spline = curve_data.splines.new('NURBS')
            spline.points.add(len(self.s1) - 1)
            for i, pt in enumerate(self.s1):
                w = self.s2[i] if self.s2 and i < len(self.s2) else 1.0
                spline.points[i].co = Vector((pt[0], pt[1], pt[2], w))
            spline.use_endpoint_u = True
            spline.order_u = min(4, len(self.s1))
        else:
            # Unsupported type — create polyline fallback
            spline = curve_data.splines.new('POLY')
            spline.points.add(len(self.s1) - 1)
            for i, pt in enumerate(self.s1):
                spline.points[i].co = Vector((pt[0], pt[1], pt[2], 1.0))

        curve_obj = bpy.data.objects.new('Spline_' + str(self.address), curve_data)
        bpy.context.scene.collection.objects.link(curve_obj)
        return curve_obj

