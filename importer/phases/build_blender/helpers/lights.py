"""Build Blender light objects from IRLight dataclasses."""
import math
import bpy
from mathutils import Matrix, Vector

try:
    from .....shared.helpers.srgb import srgb_to_linear
except (ImportError, SystemError):
    from shared.helpers.srgb import srgb_to_linear


def build_lights(ir_lights, logger):
    """Create Blender lights from IRLight list."""
    for ir_light in ir_lights:
        _build_light(ir_light)
    if ir_lights:
        logger.info("  Built %d light(s)", len(ir_lights))


def _build_light(ir_light):
    """Create a single Blender light from IRLight."""
    if ir_light.type.value == 'AMBIENT':
        # Ambient lights have no Blender equivalent — create a no-op POINT
        # light with zero energy so it doesn't affect the scene visually.
        light_data = bpy.data.lights.new(name=ir_light.name, type='POINT')
        light_data.energy = 0
        c = ir_light.color
        light_data.color = (srgb_to_linear(c[0]), srgb_to_linear(c[1]), srgb_to_linear(c[2]))
        lamp = bpy.data.objects.new(name=ir_light.name, object_data=light_data)
        lamp["dat_light_type"] = "AMBIENT"
        bpy.context.scene.collection.objects.link(lamp)
        return

    type_map = {'SUN': 'SUN', 'POINT': 'POINT', 'SPOT': 'SPOT'}
    blender_type = type_map.get(ir_light.type.value, 'POINT')

    light_data = bpy.data.lights.new(name=ir_light.name, type=blender_type)
    # IR stores sRGB — linearize for Blender's light color
    c = ir_light.color
    light_data.color = (srgb_to_linear(c[0]), srgb_to_linear(c[1]), srgb_to_linear(c[2]))
    light_data.energy = ir_light.brightness

    lamp = bpy.data.objects.new(name=ir_light.name, object_data=light_data)

    # Convert IR position from Y-up to Blender Z-up: (x, y, z) → (x, -z, y)
    if ir_light.position:
        x, y, z = ir_light.position
        lamp.location = (x, -z, y)

    if ir_light.target_position:
        tx, ty, tz = ir_light.target_position
        target = bpy.data.objects.new(ir_light.name + '_target', None)
        target.empty_display_type = 'PLAIN_AXES'
        target.location = (tx, -tz, ty)
        bpy.context.scene.collection.objects.link(target)

        constraint = lamp.constraints.new(type='TRACK_TO')
        constraint.target = target
        constraint.track_axis = 'TRACK_NEGATIVE_Z'
        constraint.up_axis = 'UP_Y'

    bpy.context.scene.collection.objects.link(lamp)
