"""Build Blender lights from a BR light list. Pure bpy executor.

Light animation clips build as real Blender fcurves (an Action on the light
object, mirroring the camera path): colour → `data.color`, visibility →
`data.energy`, cutoff → `data.spot_size`, eye position → the light object's
`location`, and interest → a paired Action on the TRACK_TO target empty.
Empty presence clips (map light animations carry no channels) have nothing
to anchor and are simply not built — they're inert.
"""
import bpy

from .cameras import _insert_keyframes


def build_lights(br_lights, logger):
    """Create Blender lights for every BRLight in the list.

    In: br_lights (list[BRLight]); logger (Logger).
    Out: None. Lights + target empties are linked into the scene.
    """
    for br_light in br_lights:
        _build_light(br_light, logger)
    if br_lights:
        logger.info("  Built %d light(s)", len(br_lights))


def _build_light(br_light, logger):
    """Build one Light data block + Object from a BRLight.

    In: br_light (BRLight); logger (Logger).
    Out: None. Ambient lights get dat_light_type='AMBIENT' custom prop;
         non-ambient with a target_location get a TRACK_TO-ed empty;
         animation clips build as fcurves.
    """
    light_data = bpy.data.lights.new(name=br_light.name, type=br_light.blender_type)
    light_data.color = br_light.color
    light_data.energy = br_light.energy

    lamp = bpy.data.objects.new(name=br_light.name, object_data=light_data)
    if br_light.is_ambient:
        lamp["dat_light_type"] = "AMBIENT"

    if br_light.location is not None:
        lamp.location = br_light.location

    target = None
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

    for anim in getattr(br_light, 'animations', None) or []:
        _build_light_animation(anim, lamp, target, light_data, logger)


def _build_light_animation(anim, lamp, target, light_data, logger):
    """Build fcurves for one light animation clip.

    All values in `anim` are pre-transformed into Blender space by Plan; this
    layer only inserts keyframes. Clips with no channel data build nothing.
    """
    lamp_channels = [
        ('data.color', 0, anim.color_r),
        ('data.color', 1, anim.color_g),
        ('data.color', 2, anim.color_b),
        ('data.energy', 0, anim.visibility),
        ('location', 0, anim.loc_x),
        ('location', 1, anim.loc_y),
        ('location', 2, anim.loc_z),
    ]
    if light_data.type == 'SPOT':
        lamp_channels.append(('data.spot_size', 0, anim.cutoff))

    if any(kfs for _, _, kfs in lamp_channels):
        action = bpy.data.actions.new(anim.name)
        action.use_fake_user = True
        for path, index, kfs in lamp_channels:
            _insert_keyframes(action, path, index, kfs)
        if not lamp.animation_data:
            lamp.animation_data_create()
        lamp.animation_data.action = action

    target_channels = [anim.target_loc_x, anim.target_loc_y, anim.target_loc_z]
    if target is not None and any(target_channels):
        target_action = bpy.data.actions.new(anim.name + '_target')
        target_action.use_fake_user = True
        for i, kfs in enumerate(target_channels):
            _insert_keyframes(target_action, 'location', i, kfs)
        if not target.animation_data:
            target.animation_data_create()
        target.animation_data.action = target_action

    logger.debug("  Light animation '%s': end_frame=%.1f, loop=%s",
                 anim.name, anim.end_frame, anim.loop)
