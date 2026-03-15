import bpy
from mathutils import Vector

from ...Node import Node

# Spline type constants (flags >> 8)
SPLINE_LINEAR = 0
SPLINE_CUBIC_BEZIER = 1
SPLINE_BSPLINE = 2
SPLINE_CARDINAL = 3

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

    @property
    def spline_type(self):
        return self.flags >> 8

    @property
    def numcvs(self):
        return self.n

    @property
    def tension(self):
        return self.f0

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
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

    def build(self):
        """Build a Blender curve object from spline data. Returns the curve object."""
        if not self.s1:
            return None

        spline_type = self.spline_type
        n = self.numcvs

        curve_data = bpy.data.curves.new(name='Spline_' + str(self.address), type='CURVE')
        curve_data.dimensions = '3D'
        curve_data.resolution_u = 12

        if spline_type == SPLINE_LINEAR:
            # Linear → POLY spline
            spline = curve_data.splines.new('POLY')
            spline.points.add(n - 1)
            for i, cv in enumerate(self.s1):
                spline.points[i].co = Vector((cv[0], cv[1], cv[2], 1.0))

        elif spline_type == SPLINE_CUBIC_BEZIER:
            # Cubic Bezier → BEZIER spline
            spline = curve_data.splines.new('BEZIER')
            spline.bezier_points.add(n - 1)
            for i, cv in enumerate(self.s1[:n]):
                bp = spline.bezier_points[i]
                bp.co = Vector(cv)
                bp.handle_type_left = 'AUTO'
                bp.handle_type_right = 'AUTO'

        elif spline_type == SPLINE_BSPLINE:
            # B-spline → NURBS spline
            spline = curve_data.splines.new('NURBS')
            spline.points.add(n - 1)
            for i, cv in enumerate(self.s1[:n]):
                spline.points[i].co = Vector((cv[0], cv[1], cv[2], 1.0))
            spline.use_endpoint_u = True
            spline.order_u = 4

        elif spline_type == SPLINE_CARDINAL:
            # Cardinal spline → BEZIER approximation
            # Cardinal splines use n+2 control points (extra start/end tangent points)
            spline = curve_data.splines.new('BEZIER')
            spline.bezier_points.add(n - 1)
            for i in range(n):
                bp = spline.bezier_points[i]
                # s1 has n+2 points; actual curve points are indices 1..n
                bp.co = Vector(self.s1[i + 1])
                bp.handle_type_left = 'AUTO'
                bp.handle_type_right = 'AUTO'
        else:
            return None

        curve_obj = bpy.data.objects.new(name='Spline_' + str(self.address), object_data=curve_data)
        bpy.context.scene.collection.objects.link(curve_obj)

        return curve_obj
