"""Build Blender lights from a BR light list. Pure bpy executor."""
import bpy


def build_lights(br_lights, logger):
    """Create Blender lights for every BRLight in the list.

    In: br_lights (list[BRLight]); logger (Logger).
    Out: None. Lights + target empties are linked into the scene.
    """
    for br_light in br_lights:
        _build_light(br_light)
    if br_lights:
        logger.info("  Built %d light(s)", len(br_lights))


def _build_light(br_light):
    """Build one Light data block + Object from a BRLight.

    In: br_light (BRLight).
    Out: None. Ambient lights get dat_light_type='AMBIENT' custom prop;
         non-ambient with a target_location get a TRACK_TO-ed empty.
    """
    light_data = bpy.data.lights.new(name=br_light.name, type=br_light.blender_type)
    light_data.color = br_light.color
    light_data.energy = br_light.energy

    lamp = bpy.data.objects.new(name=br_light.name, object_data=light_data)
    if br_light.is_ambient:
        lamp["dat_light_type"] = "AMBIENT"

    if br_light.location is not None:
        lamp.location = br_light.location

    if br_light.target_location is not None:
        target = bpy.data.objects.new(br_light.name + '_target', None)
        target.empty_display_type = 'PLAIN_AXES'
        target.location = br_light.target_location
        bpy.context.scene.collection.objects.link(target)

        constraint = lamp.constraints.new(type='TRACK_TO')
        constraint.target = target
        constraint.track_axis = 'TRACK_NEGATIVE_Z'
        constraint.up_axis = 'UP_Y'

    bpy.context.scene.collection.objects.link(lamp)
