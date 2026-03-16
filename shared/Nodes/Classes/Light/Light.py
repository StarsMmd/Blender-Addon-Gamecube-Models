import math
import bpy
from mathutils import Matrix, Vector

from ...Node import Node
from ....Constants import *
from . import Attn, PointLight, SpotLight


# Light
class Light(Node):
    class_name = "Light"
    fields = [
        ('name', 'string'),
        ('link', 'Light'),
        ('flags', 'ushort'),
        ('attn_flags', 'ushort'),
        ('color', '@RGBAColor'),
        ('position', 'WObject'),
        ('interest', 'WObject'),
        ('property', 'uint'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        if self.attn_flags & LOBJ_LIGHT_ATTN:
            self.property = parser.read('Attn', self.property)
        else:
            if self.flags == LOBJ_INFINITE:
                self.property = parser.read('float', self.property)
            elif self.flags == LOBJ_POINT:
                self.property = parser.read('PointLight', self.property)
            elif self.flags == LOBJ_SPOT:
                self.property = parser.read('SpotLight', self.property)
            else: # LOBJ_AMBIENT
                self.property = None

    def writeBinary(self, builder):
        if isinstance(self.property, Attn):
            self.flags = 0
            self.attn_flags = LOBJ_LIGHT_ATTN
            self.property = self.property.address

        elif isinstance(self.property, float):
            self.flags = LOBJ_INFINITE
            self.attn_flags = 0
            # floats don't have an .address — write the value and use the returned address
            self.property = builder.write(self.property, 'float')

        elif isinstance(self.property, PointLight.PointLight):
            self.flags = LOBJ_POINT
            self.attn_flags = 0
            self.property = self.property.address

        elif isinstance(self.property, SpotLight.SpotLight):
            self.flags = LOBJ_SPOT
            self.attn_flags = 0
            self.property = self.property.address

        else:
            self.flags = 0
            self.attn_flags = 0
            self.property = 0

        super().writeBinary(builder)

    def build(self, builder):
        if self.name:
            name = 'Light_' + self.name
        else:
            name = 'Light_' + str(builder.light_count)

        light_type = self.flags & LOBJ_TYPE_MASK

        if light_type == LOBJ_INFINITE:
            light_data = bpy.data.lights.new(name=name, type='SUN')
        elif light_type == LOBJ_POINT:
            light_data = bpy.data.lights.new(name=name, type='POINT')
        elif light_type == LOBJ_SPOT:
            light_data = bpy.data.lights.new(name=name, type='SPOT')
        else:
            # LOBJ_AMBIENT — no direct Blender equivalent
            return

        if self.color:
            light_data.color = [self.color.red / 255,
                                self.color.green / 255,
                                self.color.blue / 255]

        lamp = bpy.data.objects.new(name=name, object_data=light_data)

        if self.position:
            lamp.matrix_basis = (Matrix.Translation(Vector(self.position.position))
                                 @ Matrix.Rotation(-math.pi / 2, 4, [1.0, 0.0, 0.0]))

        if self.interest and self.interest.position:
            target = bpy.data.objects.new(name + '_target', None)
            target.empty_display_type = 'PLAIN_AXES'
            target.matrix_basis = Matrix.Translation(Vector(self.interest.position))
            bpy.context.scene.collection.objects.link(target)

            constraint = lamp.constraints.new(type='TRACK_TO')
            constraint.target = target
            constraint.track_axis = 'TRACK_NEGATIVE_Z'
            constraint.up_axis = 'UP_Y'

        bpy.context.scene.collection.objects.link(lamp)

        # Correct coordinate system (GameCube Y-up to Blender Z-up)
        lamp.matrix_basis @= Matrix.Rotation(math.pi / 2, 4, [1.0, 0.0, 0.0])

        builder.light_count += 1

