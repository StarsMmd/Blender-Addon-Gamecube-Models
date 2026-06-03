"""Standalone Blender script: clamp oversize textures to a max dimension.

Run from Blender's Scripting panel (Text Editor > Run Script). Any image
whose width or height exceeds MAX_DIM is scaled down so its longer side
equals the largest power of two ≤ MAX_DIM. Aspect ratio is preserved; the
shorter side rounds down to a power of two as well.

GameCube textures cap at 512×512 in hardware; this script defaults to 256
to halve memory footprint without visible loss on most assets.

This script is fully standalone — no imports from the plugin codebase.
"""
import bpy


MAX_DIM = 256


def _largest_pow2_le(n):
    if n < 1:
        return 1
    p = 1
    while p * 2 <= n:
        p *= 2
    return p


def optimize_textures(max_dim=MAX_DIM):
    images = [img for img in bpy.data.images
              if img.size[0] > 0 and img.size[1] > 0 and img.source != 'MOVIE']

    rescaled = 0
    for img in images:
        w, h = img.size[0], img.size[1]
        if w <= max_dim and h <= max_dim:
            continue

        longer = max(w, h)
        target_long = _largest_pow2_le(min(longer, max_dim))
        scale = target_long / longer
        new_w = max(_largest_pow2_le(int(w * scale)), 1)
        new_h = max(_largest_pow2_le(int(h * scale)), 1)

        if new_w == w and new_h == h:
            continue

        img.scale(new_w, new_h)
        print("  %s: %dx%d → %dx%d" % (img.name, w, h, new_w, new_h))
        rescaled += 1

    print("[optimize_textures] done: %d / %d images rescaled (cap %d)"
          % (rescaled, len(images), max_dim))


if __name__ == '__main__':
    optimize_textures()
