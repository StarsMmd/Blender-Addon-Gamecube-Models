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

        light_type = self.flags & LOBJ_TYPE_MASK

        if self.attn_flags & LOBJ_LIGHT_ATTN:
            parser.logger.debug("Light 0x%X: property -> Attn at 0x%X", self.address, self.property)
            self.property = parser.read('Attn', self.property)
        else:
            if light_type == LOBJ_INFINITE:
                parser.logger.debug("Light 0x%X: INFINITE, property -> float at 0x%X", self.address, self.property)
                self.property = parser.read('float', self.property)
            elif light_type == LOBJ_POINT:
                parser.logger.debug("Light 0x%X: POINT, property -> PointLight at 0x%X", self.address, self.property)
                self.property = parser.read('PointLight', self.property)
            elif light_type == LOBJ_SPOT:
                parser.logger.debug("Light 0x%X: SPOT, property -> SpotLight at 0x%X", self.address, self.property)
                self.property = parser.read('SpotLight', self.property)
            else: # LOBJ_AMBIENT
                parser.logger.debug("Light 0x%X: AMBIENT, no property", self.address)
                self.property = None

    def writePrivateData(self, builder):
        super().writePrivateData(builder)
        # For INFINITE lights, property is a float that needs to be written as raw data
        if isinstance(self.property, float):
            builder.seek(0, 'end')
            self.property = builder.write(self.property, 'float')
            self._raw_pointer_fields.add('property')

    def writeBinary(self, builder):
        if isinstance(self.property, Attn):
            self.property = self.property.address
            if self.property != 0:
                self._raw_pointer_fields.add('property')

        elif isinstance(self.property, PointLight.PointLight):
            self.property = self.property.address
            if self.property != 0:
                self._raw_pointer_fields.add('property')

        elif isinstance(self.property, SpotLight.SpotLight):
            self.property = self.property.address
            if self.property != 0:
                self._raw_pointer_fields.add('property')

        elif self.property is None:
            self.property = 0

        # else: property is already an int address (from writePrimitivePointers for floats)

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

