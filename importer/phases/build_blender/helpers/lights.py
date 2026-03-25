"""Build Blender light objects from IRLight dataclasses."""
import bpy
from mathutils import Matrix, Vector


def build_lights(ir_lights, logger):
    """Create Blender lights from IRLight list."""
    for ir_light in ir_lights:
        _build_light(ir_light)
    if ir_lights:
        logger.info("  Built %d light(s)", len(ir_lights))


def _build_light(ir_light):
    """Create a single Blender light from IRLight."""
    type_map = {'SUN': 'SUN', 'POINT': 'POINT', 'SPOT': 'SPOT'}
    blender_type = type_map.get(ir_light.type.value, 'POINT')

    light_data = bpy.data.lights.new(name=ir_light.name, type=blender_type)
    light_data.color = ir_light.color

    lamp = bpy.data.objects.new(name=ir_light.name, object_data=light_data)

    if ir_light.position:
        lamp.matrix_basis = Matrix.Translation(Vector(ir_light.position))

    if ir_light.target_position:
        target = bpy.data.objects.new(ir_light.name + '_target', None)
        target.empty_display_type = 'PLAIN_AXES'
        target.matrix_basis = Matrix.Translation(Vector(ir_light.target_position))
        bpy.context.scene.collection.objects.link(target)

        constraint = lamp.constraints.new(type='TRACK_TO')
        constraint.target = target
        constraint.track_axis = 'TRACK_NEGATIVE_Z'
        constraint.up_axis = 'UP_Y'

    bpy.context.scene.collection.objects.link(lamp)

    # Coordinate system rotation (GameCube Y-up → Blender Z-up)
    rx = ir_light.coordinate_rotation[0]
    if rx != 0:
        lamp.matrix_basis @= Matrix.Rotation(rx, 4, [1.0, 0.0, 0.0])
