"""Standalone Blender script: Prepare a scene for Colosseum/XD export.

Run this from Blender's Scripting panel (Text Editor > Run Script) before
exporting. It ensures all objects in the scene have the custom properties
the exporter expects.

The script:
  1. Sets dat_camera_aspect on any cameras that don't have it yet (default 1.18,
     the standard Colosseum/XD battle camera aspect ratio)
  2. If an armature is selected and has no PKX metadata, applies default PKX
     metadata (format, animations, shiny, null joints) — same as the old
     apply_pkx_metadata.py script

After running, the scene can be exported via File > Export > Gamecube model (.dat).

Requires the DAT plugin addon to be enabled (for registered shiny properties).
"""
import bpy
import sys
import os

# Add the addon directory to path so we can import from the plugin
addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)


# ---------------------------------------------------------------------------
# Battle camera
# ---------------------------------------------------------------------------

BATTLE_CAMERA_NAME = "Battle_Camera"
BATTLE_CAMERA_TARGET = "Battle_Camera_target"


def prepare_camera():
    """Create a default battle camera if none exists, and set aspect on all cameras.

    Returns the number of cameras created (0 or 1).
    """
    created = 0

    # Create Battle_Camera if it doesn't exist
    if bpy.data.objects.get(BATTLE_CAMERA_NAME) is None:
        cam_data = bpy.data.cameras.new(BATTLE_CAMERA_NAME)
        cam_data.type = 'PERSP'
        cam_data.lens = 37.5       # ~27° vertical FOV (most common across all PKX models)
        cam_data.clip_start = 0.1
        cam_data.clip_end = 32768.0

        cam_obj = bpy.data.objects.new(BATTLE_CAMERA_NAME, cam_data)
        cam_obj.location = (0.0, 8.0, 50.0)
        cam_obj["dat_camera_aspect"] = 1.18
        bpy.context.scene.collection.objects.link(cam_obj)

        # Create target empty
        target = bpy.data.objects.new(BATTLE_CAMERA_TARGET, None)
        target.empty_display_type = 'PLAIN_AXES'
        target.empty_display_size = 1.0
        target.location = (0.0, 5.0, 0.0)
        bpy.context.scene.collection.objects.link(target)

        # Add TRACK_TO constraint
        track = cam_obj.constraints.new('TRACK_TO')
        track.target = target
        track.track_axis = 'TRACK_NEGATIVE_Z'
        track.up_axis = 'UP_Y'

        created = 1
        print("  Created '%s' with target at (0, 5, 0)" % BATTLE_CAMERA_NAME)
        print("    Lens: 37.5mm (~27° FOV), aspect: 1.18, far: 32768")
        print("    Adjust position/FOV to frame your model. Smaller models need wider FOV.")

    # Set dat_camera_aspect on any cameras that don't have it
    for obj in bpy.data.objects:
        if obj.type == 'CAMERA' and "dat_camera_aspect" not in obj:
            obj["dat_camera_aspect"] = 1.18
            print("  Camera '%s': set dat_camera_aspect = 1.18" % obj.name)

    return created


# ---------------------------------------------------------------------------
# PKX metadata (from former apply_pkx_metadata.py)
# ---------------------------------------------------------------------------

def _find_head_bone(armature):
    """Auto-detect the head bone by name heuristic."""
    for bone in armature.data.bones:
        if 'head' in bone.name.lower():
            return bone.name
    root_bones = [b for b in armature.data.bones if b.parent is None]
    if root_bones:
        root = root_bones[0]
        if root.children:
            return root.children[0].name
        return root.name
    return ""


def apply_pkx_metadata(armature, format='XD', model_type='POKEMON', species_id=0):
    """Apply default PKX metadata to an armature."""
    is_xd = (format == 'XD')

    # --- General ---
    armature["dat_pkx_format"] = format
    armature["dat_pkx_species_id"] = species_id
    armature["dat_pkx_model_type"] = model_type
    armature["dat_pkx_particle_orientation"] = 0
    armature["dat_pkx_distortion_param"] = 0
    armature["dat_pkx_distortion_type"] = 0

    # Head bone
    head_bone_name = _find_head_bone(armature)
    armature["dat_pkx_head_bone"] = head_bone_name

    # --- Flags (all off) ---
    armature["dat_pkx_flag_flying"] = False
    armature["dat_pkx_flag_skip_frac_frames"] = False
    armature["dat_pkx_flag_no_root_anim"] = False
    armature["dat_pkx_flag_bit7"] = False

    # --- Shiny (identity routing, neutral brightness) ---
    armature.dat_pkx_shiny = False
    armature.dat_pkx_shiny_route_r = '0'
    armature.dat_pkx_shiny_route_g = '1'
    armature.dat_pkx_shiny_route_b = '2'
    armature.dat_pkx_shiny_route_a = '3'
    armature.dat_pkx_shiny_brightness_r = 0.0
    armature.dat_pkx_shiny_brightness_g = 0.0
    armature.dat_pkx_shiny_brightness_b = 0.0

    # --- Sub-animations (all inactive) ---
    sub_triggers = ["sleep_on", "sleep_off", "extra", "unused"]
    for i in range(4):
        prefix = "dat_pkx_sub_anim_%d" % i
        armature[prefix + "_type"] = "none"
        armature[prefix + "_trigger"] = sub_triggers[i]
        armature[prefix + "_anim_ref"] = ""

    # --- Null joint bones ---
    bones = list(armature.data.bones)
    root_name = bones[0].name if bones else ""
    armature["dat_pkx_joint_root"] = root_name
    armature["dat_pkx_joint_head"] = head_bone_name
    armature["dat_pkx_joint_center"] = ""
    for key in ["body_3", "neck", "head_top", "limb_a", "limb_b",
                "secondary_8", "secondary_9", "secondary_10", "secondary_11",
                "attach_a", "attach_b", "attach_c", "attach_d"]:
        armature["dat_pkx_joint_%s" % key] = ""

    # --- Animation entries (17 slots) ---
    anim_count = 17
    armature["dat_pkx_anim_count"] = anim_count

    for i in range(anim_count):
        prefix = "dat_pkx_anim_%02d" % i
        if i == 0:
            armature[prefix + "_type"] = "loop"
            armature[prefix + "_sub_0_motion"] = 2 if is_xd else 0
            armature[prefix + "_sub_0_anim"] = ""
        else:
            armature[prefix + "_type"] = "action"
            armature[prefix + "_sub_0_motion"] = 0
            armature[prefix + "_sub_0_anim"] = ""
        armature[prefix + "_sub_count"] = 1
        armature[prefix + "_damage_flags"] = 0
        armature[prefix + "_timing_1"] = 0.0
        armature[prefix + "_timing_2"] = 0.0
        armature[prefix + "_timing_3"] = 0.0
        armature[prefix + "_timing_4"] = 0.0
        armature[prefix + "_terminator"] = 3 if is_xd else 1

    print("  PKX metadata applied to '%s':" % armature.name)
    print("    Format: %s, Species: %d, Head bone: '%s'" % (format, species_id, head_bone_name))
    print("    17 animation slots (slot 0 = idle loop)")


# ---------------------------------------------------------------------------
# Ambient light
# ---------------------------------------------------------------------------

def prepare_ambient_light():
    """Add an ambient light if none exists in the scene.

    Creates a no-op POINT light with energy=0 (invisible in Blender) and
    a dat_light_type="AMBIENT" custom property. The color controls
    scene-level fill lighting in-game — applied uniformly to all materials.

    Returns the number of ambient lights created (0 or 1).
    """
    # Check for existing ambient light
    for obj in bpy.data.objects:
        if obj.type == 'LIGHT' and obj.get('dat_light_type') == 'AMBIENT':
            return 0

    from shared.helpers.srgb import srgb_to_linear

    # Default: (76, 76, 76) / 255 ≈ 0.298 sRGB — the most common
    # ambient color across all tested Pokémon models.
    srgb_val = 76 / 255.0
    linear_val = srgb_to_linear(srgb_val)

    light_data = bpy.data.lights.new(name='Ambient_Light', type='POINT')
    light_data.energy = 0
    light_data.color = (linear_val, linear_val, linear_val)

    lamp = bpy.data.objects.new(name='Ambient_Light', object_data=light_data)
    lamp["dat_light_type"] = "AMBIENT"
    bpy.context.scene.collection.objects.link(lamp)

    return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__" or True:
    print("=== Prepare for Colosseum/XD Export ===")

    # 1. Camera
    cam_created = prepare_camera()
    if not cam_created:
        print("  Battle camera already exists")

    # 2. PKX metadata on selected armature (if it doesn't already have it)
    obj = bpy.context.active_object
    if obj and obj.type == 'ARMATURE':
        if obj.get("dat_pkx_format"):
            print("  Armature '%s' already has PKX metadata (skipped)" % obj.name)
        else:
            apply_pkx_metadata(obj, format='XD', model_type='POKEMON', species_id=0)
    else:
        print("  No armature selected (PKX metadata step skipped)")

    # 3. Ambient light
    amb_count = prepare_ambient_light()
    if amb_count:
        print("  Added ambient light (no visible change in Blender)")
        print("    Color controls scene fill lighting in-game:")
        print("    - Lower (darker) = more contrast, deeper shadows")
        print("    - Higher (lighter) = flatter, softer look")
        print("    Edit the light's color in the Object Data panel to adjust.")
    else:
        print("  Ambient light already exists (skipped)")

    print("=== Done ===")
