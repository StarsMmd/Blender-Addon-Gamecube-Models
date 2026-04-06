"""Standalone Blender script: Set GX texture format on all textures of the selected armature.

Run this from Blender's Scripting panel (Text Editor > Run Script) with an
armature selected. It analyzes each texture's pixel content and sets the
dat_gx_format property to the recommended format.

The exporter reads this property to determine which GX format to encode
each texture in. If not set, the exporter auto-selects (defaulting to CMPR).

Requires the DAT plugin addon to be enabled (for the dat_gx_format property).
"""
import bpy
import sys
import os

# Add the addon directory to path
addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

from shared.texture_encoder import analyze_pixels, select_format


# Mapping from GX format ID to property enum string
_FORMAT_ID_TO_NAME = {
    0: 'I4', 1: 'I8', 2: 'IA4', 3: 'IA8',
    4: 'RGB565', 5: 'RGB5A3', 6: 'RGBA8',
    8: 'C4', 9: 'C8', 14: 'CMPR',
}


def main():
    armature = bpy.context.active_object

    if armature is None or armature.type != 'ARMATURE':
        raise ValueError("Select an armature object before running this script.")

    if not hasattr(bpy.types.Image, 'dat_gx_format'):
        raise ValueError("The DAT plugin addon must be enabled for the dat_gx_format property. "
                         "Enable it in Edit > Preferences > Extensions.")

    # Collect all unique images from the armature's materials
    images_seen = set()
    results = []

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

                    # Read pixels and analyze
                    w, h = img.size[0], img.size[1]
                    if w == 0 or h == 0:
                        continue

                    flat = list(img.pixels)
                    pixel_bytes = bytearray(w * h * 4)
                    for i in range(w * h * 4):
                        pixel_bytes[i] = min(255, max(0, int(flat[i] * 255 + 0.5)))

                    analysis = analyze_pixels(bytes(pixel_bytes), w, h)
                    fmt_id = select_format(analysis)
                    fmt_name = _FORMAT_ID_TO_NAME.get(fmt_id, 'CMPR')

                    old_fmt = img.dat_gx_format
                    img.dat_gx_format = fmt_name

                    results.append((img.name, w, h, old_fmt, fmt_name, analysis))

    if not results:
        print("No textures found on armature '%s'." % armature.name)
        return

    print("Set GX texture formats for %d texture(s) on '%s':" % (len(results), armature.name))
    for name, w, h, old, new, analysis in results:
        gray = 'gray' if analysis['is_grayscale'] else 'color'
        alpha = '+alpha' if analysis['has_alpha'] else ''
        colors = analysis['unique_color_count']
        print("  %s (%dx%d, %s%s, %d colors): %s -> %s" % (
            name, w, h, gray, alpha, colors, old, new))


main()
