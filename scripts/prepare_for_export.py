"""Standalone Blender script: Prepare a scene for Colosseum/XD export.

Run this from Blender's Scripting panel (Text Editor > Run Script) before
exporting. It ensures all objects in the scene have the custom properties
the exporter expects.

The script:
  1. Creates a Battle_Camera if none exists
  2. If an armature is selected and has no PKX metadata, applies defaults
  3. Auto-selects GX texture formats for textures on the selected armature
  4. Creates an ambient light if none exists

After running, the scene can be exported via File > Export > Gamecube model (.dat).

Requires the DAT plugin addon to be enabled (for registered shiny properties).

This script is fully standalone — no imports from the plugin codebase.
"""
import bpy
import math


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
# PKX metadata
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

    # --- Body map bones ---
    bones = list(armature.data.bones)
    root_name = bones[0].name if bones else ""
    armature["dat_pkx_body_root"] = root_name
    armature["dat_pkx_body_head"] = head_bone_name
    armature["dat_pkx_body_center"] = ""
    for key in ["body_3", "neck", "head_top", "limb_a", "limb_b",
                "secondary_8", "secondary_9", "secondary_10", "secondary_11",
                "attach_a", "attach_b", "attach_c", "attach_d"]:
        armature["dat_pkx_body_%s" % key] = ""

    # --- Animation entries (17 slots) ---
    anim_count = 17
    armature["dat_pkx_anim_count"] = anim_count

    # Slot types: 0=idle(loop), 8=damage(hit), 9=damageB(compound), 10=faint(hit), rest=action
    _SLOT_TYPES = {0: "loop", 8: "hit_reaction", 9: "compound", 10: "hit_reaction"}

    for i in range(anim_count):
        prefix = "dat_pkx_anim_%02d" % i
        anim_type = _SLOT_TYPES.get(i, "action")

        if i == 0:
            armature[prefix + "_sub_0_motion"] = 2 if is_xd else 0
        else:
            armature[prefix + "_sub_0_motion"] = 0

        armature[prefix + "_type"] = anim_type
        armature[prefix + "_sub_0_anim"] = ""
        armature[prefix + "_sub_count"] = 2 if anim_type == "compound" else 1
        armature[prefix + "_damage_flags"] = 0
        armature[prefix + "_terminator"] = 3 if is_xd else 1

        # Timing defaults (will be recalculated by derive_timing below)
        armature[prefix + "_timing_1"] = 0.0
        armature[prefix + "_timing_2"] = 0.0
        armature[prefix + "_timing_3"] = 0.0
        armature[prefix + "_timing_4"] = 0.0

    print("  PKX metadata applied to '%s':" % armature.name)
    print("    Format: %s, Species: %d, Head bone: '%s'" % (format, species_id, head_bone_name))
    print("    17 animation slots (slot 0 = idle loop)")


def _get_action_duration(action_name):
    """Get an action's duration in seconds (frame count / 60fps). Returns 0 if not found."""
    action = bpy.data.actions.get(action_name)
    if not action or not action.fcurves:
        return 0.0
    max_frame = max(kp.co[0] for fc in action.fcurves for kp in fc.keyframe_points)
    return max_frame / 60.0


def derive_timing(armature):
    """Auto-derive animation timing fields from action durations.

    Timing semantics per anim_type:
      loop:         T1 = duration
      action:       T1 = wind-up (50%), T2 = hit (50%), T3 = duration
      hit_reaction: T1 = reaction start (50%), T2 = duration
      compound:     T1 = sub1 mid, T2 = sub1 end, T3 = sub2 mid, T4 = sub2 end

    Returns the number of entries updated.
    """
    anim_count = armature.get("dat_pkx_anim_count", 0)
    updated = 0

    for i in range(anim_count):
        prefix = "dat_pkx_anim_%02d" % i
        anim_type = armature.get(prefix + "_type", "action")
        action_name = armature.get(prefix + "_sub_0_anim", "")
        dur = _get_action_duration(action_name) if action_name else 0.0

        if dur <= 0:
            continue

        if anim_type == "loop":
            armature[prefix + "_timing_1"] = dur
        elif anim_type == "action":
            armature[prefix + "_timing_1"] = dur * 0.5
            armature[prefix + "_timing_2"] = dur * 0.5
            armature[prefix + "_timing_3"] = dur
        elif anim_type == "hit_reaction":
            armature[prefix + "_timing_1"] = dur * 0.5
            armature[prefix + "_timing_2"] = dur
        elif anim_type == "compound":
            # Two sub-anims: get duration of second if available
            action2_name = armature.get(prefix + "_sub_1_anim", "")
            dur2 = _get_action_duration(action2_name) if action2_name else dur
            armature[prefix + "_timing_1"] = dur * 0.5
            armature[prefix + "_timing_2"] = dur
            armature[prefix + "_timing_3"] = dur2 * 0.5
            armature[prefix + "_timing_4"] = dur2

        updated += 1

    return updated


# ---------------------------------------------------------------------------
# Texture formats
# ---------------------------------------------------------------------------

def _analyze_texture(img):
    """Analyze an image's pixels and return a suitable GX format name.

    Checks for grayscale, alpha usage, and color count to pick the most
    efficient format. Returns a format string like 'CMPR', 'I8', etc.
    """
    w, h = img.size[0], img.size[1]
    if w == 0 or h == 0:
        return None

    pixels = img.pixels[:]
    num_pixels = w * h

    is_gray = True
    has_alpha = False
    unique_colors = set()
    max_unique = 260  # stop counting after we know it's > 256

    for i in range(num_pixels):
        base = i * 4
        r, g, b, a = pixels[base], pixels[base+1], pixels[base+2], pixels[base+3]

        if a < 0.998:
            has_alpha = True

        if is_gray and (abs(r - g) > 0.004 or abs(r - b) > 0.004):
            is_gray = False

        if len(unique_colors) < max_unique:
            ri = min(255, int(r * 255 + 0.5))
            gi = min(255, int(g * 255 + 0.5))
            bi = min(255, int(b * 255 + 0.5))
            ai = min(255, int(a * 255 + 0.5))
            unique_colors.add((ri, gi, bi, ai))

    n_colors = len(unique_colors)

    # Format selection logic (matches shared/texture_encoder.py)
    if is_gray:
        if has_alpha:
            return 'IA8'
        else:
            return 'I8'
    elif n_colors <= 16:
        return 'C4'
    elif n_colors <= 256:
        return 'C8'
    elif has_alpha:
        return 'RGB5A3'
    else:
        return 'CMPR'


def prepare_texture_formats(armature):
    """Auto-select GX texture formats for textures that don't have one set.

    Returns the number of textures that were assigned a format.
    """
    images_seen = set()
    count = 0

    for child in armature.children:
        if child.type != 'MESH':
            continue
        for slot in child.material_slots:
            if not slot.material or not slot.material.use_nodes:
                continue
            for node in slot.material.node_tree.nodes:
                if node.bl_idname == 'ShaderNodeTexImage' and node.image:
                    img = node.image
                    if img.name in images_seen:
                        continue
                    images_seen.add(img.name)

                    # Skip textures that already have a format set
                    if hasattr(img, 'dat_gx_format') and img.dat_gx_format != 'AUTO':
                        continue

                    fmt = _analyze_texture(img)
                    if fmt:
                        img.dat_gx_format = fmt
                        count += 1
                        print("    %s (%dx%d): %s" % (img.name, img.size[0], img.size[1], fmt))

    return count


# ---------------------------------------------------------------------------
# Ambient light
# ---------------------------------------------------------------------------

def _srgb_to_linear(c):
    """Convert a single sRGB channel value (0-1) to linear."""
    if c <= 0.0404482362771082:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


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

    # Default: (76, 76, 76) / 255 ≈ 0.298 sRGB — the most common
    # ambient color across all tested Pokémon models.
    srgb_val = 76 / 255.0
    linear_val = _srgb_to_linear(srgb_val)

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

    # 3. Derive animation timing from action durations
    if obj and obj.type == 'ARMATURE':
        timing_count = derive_timing(obj)
        if timing_count:
            print("  Derived timing for %d animation slot(s)" % timing_count)

    # 5. Texture formats (on the selected armature's textures)
    if obj and obj.type == 'ARMATURE':
        fmt_count = prepare_texture_formats(obj)
        if fmt_count:
            print("  Set GX format on %d texture(s)" % fmt_count)
        else:
            print("  All textures already have formats set (skipped)")
    else:
        print("  No armature selected (texture format step skipped)")

    # 6. Ambient light
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
