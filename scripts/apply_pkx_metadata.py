"""Standalone Blender script: Apply default PKX metadata to the selected armature.

Run this from Blender's Scripting panel (Text Editor > Run Script) with an
armature selected. It populates all dat_pkx_* custom properties needed to
export the model as a .pkx file.

The script:
  1. Sets the PKX format (XD by default), species ID, and flags
  2. Auto-detects the head bone by name heuristic
  3. Creates 17 animation metadata entries (entry 0 = idle loop, rest = unused)
  4. Sets default null joint bone assignments
  5. Sets identity shiny routing (no shiny filter)

After running, the model can be exported as .pkx from the DAT exporter.
Edit the dat_pkx_* custom properties in the Object Properties panel to customize.

Requires the DAT plugin addon to be enabled.
"""
import bpy
import sys
import os

# Add the addon directory to path so we can import from the plugin
addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

from shared.helpers.pkx_header import (
    PKXHeader, AnimMetadataEntry, SubAnim, PartAnimData,
    XD_POKEMON_ANIM_NAMES, XD_TRAINER_ANIM_NAMES, NULL_JOINT_NAMES,
)


def _find_head_bone(armature):
    """Auto-detect the head bone by name heuristic.

    Checks for bones containing 'head' (case-insensitive), then falls back
    to the first child of the root bone.
    """
    bones = armature.data.bones
    # Check for name containing 'head'
    for bone in bones:
        if 'head' in bone.name.lower():
            return bone.name

    # Fallback: first child of root bone
    root_bones = [b for b in bones if b.parent is None]
    if root_bones:
        root = root_bones[0]
        if root.children:
            return root.children[0].name
        return root.name

    return ""


def _find_bone_index(armature, bone_name):
    """Get the index of a bone by name, or -1 if not found."""
    bones = list(armature.data.bones)
    for i, bone in enumerate(bones):
        if bone.name == bone_name:
            return i
    return -1


def apply_pkx_metadata(armature, format='XD', model_type='POKEMON', species_id=0):
    """Apply default PKX metadata to an armature.

    Args:
        armature: Blender armature object.
        format: 'XD' or 'COLOSSEUM'.
        model_type: 'POKEMON' or 'TRAINER'.
        species_id: Pokédex number (0 for trainer/generic).
    """
    is_xd = (format == 'XD')

    # Preamble
    armature["dat_pkx_format"] = format
    armature["dat_pkx_species_id"] = species_id
    armature["dat_pkx_particle_orientation"] = 0
    armature["dat_pkx_flags"] = 0
    armature["dat_pkx_distortion_param"] = 0
    armature["dat_pkx_distortion_type"] = 0
    armature["dat_pkx_model_type"] = model_type

    # Head bone
    head_bone_name = _find_head_bone(armature)
    armature["dat_pkx_head_bone"] = head_bone_name
    head_index = _find_bone_index(armature, head_bone_name)

    # Shiny (identity = no filter)
    armature["dat_pkx_shiny_route"] = [0, 1, 2, 3]
    armature["dat_pkx_shiny_brightness"] = [0x7F, 0x7F, 0x7F, 0x7F]

    # Part animation data (inactive defaults)
    if is_xd:
        for i in range(4):
            prefix = "dat_pkx_part_%d" % i
            armature[prefix + "_has_data"] = 0
            armature[prefix + "_sub_param"] = 0
            armature[prefix + "_bone_config"] = "ff" * 16
            armature[prefix + "_anim_ref"] = 0
    else:
        for i in range(3):
            armature["dat_pkx_colo_part_ref_%d" % i] = -1

    # Null joint bones
    bones = list(armature.data.bones)
    root_name = bones[0].name if bones else ""
    armature["dat_pkx_null_bone_0"] = root_name       # Root
    armature["dat_pkx_null_bone_1"] = head_bone_name   # Head
    armature["dat_pkx_null_bone_2"] = ""               # Center/jaw
    for j in range(3, 16):
        armature["dat_pkx_null_bone_%d" % j] = ""

    # Build default null_joint_bones array for entries
    null_bones = [0, head_index if head_index >= 0 else 0] + [-1] * 14

    # Animation entries (17 slots)
    anim_count = 17
    armature["dat_pkx_anim_count"] = anim_count

    for i in range(anim_count):
        prefix = "dat_pkx_anim_%02d" % i
        if i == 0:
            # Idle — loop
            armature[prefix + "_type"] = 2
            armature[prefix + "_sub_count"] = 1
            armature[prefix + "_damage_flags"] = 0
            armature[prefix + "_timing_1"] = 0.0
            armature[prefix + "_timing_2"] = 0.0
            armature[prefix + "_timing_3"] = 0.0
            armature[prefix + "_timing_4"] = 0.0
            armature[prefix + "_terminator"] = 3 if is_xd else 1
            armature[prefix + "_sub_0_motion"] = 2 if is_xd else 0
            armature[prefix + "_sub_0_anim"] = 0
        else:
            # Unused slot
            armature[prefix + "_type"] = 4
            armature[prefix + "_sub_count"] = 1
            armature[prefix + "_damage_flags"] = 0
            armature[prefix + "_timing_1"] = 0.0
            armature[prefix + "_timing_2"] = 0.0
            armature[prefix + "_timing_3"] = 0.0
            armature[prefix + "_timing_4"] = 0.0
            armature[prefix + "_terminator"] = 3 if is_xd else 1
            armature[prefix + "_sub_0_motion"] = 0
            armature[prefix + "_sub_0_anim"] = 0

    print("PKX metadata applied to '%s':" % armature.name)
    print("  Format: %s, Model type: %s, Species: %d" % (format, model_type, species_id))
    print("  Head bone: '%s' (index %d)" % (head_bone_name, head_index))
    print("  Animation entries: %d (slot 0 = idle loop, rest = unused)" % anim_count)
    print("  Edit dat_pkx_* properties in Object Properties > Custom Properties to customize.")


# ---------------------------------------------------------------------------
# Main: run on selected armature
# ---------------------------------------------------------------------------

if __name__ == "__main__" or True:
    obj = bpy.context.active_object
    if obj is None or obj.type != 'ARMATURE':
        print("Error: Select an armature first.")
    else:
        apply_pkx_metadata(obj, format='XD', model_type='POKEMON', species_id=0)
