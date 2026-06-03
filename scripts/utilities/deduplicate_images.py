"""Standalone Blender script: Merge image datablocks that share the same filepath.

Run this from Blender's Scripting panel. It finds groups of bpy.data.images
that all resolve to the same absolute path on disk, picks one canonical
datablock per group (the one with the shortest name, which is the form
without a .001/.002/... suffix), remaps every user of the duplicates to
the canonical image, then deletes the now-orphaned duplicates.

The glTF importer creates a fresh Image datablock for every texture
reference in the file rather than per unique URI, so a single PNG that is
sampled from multiple material slots ends up as several datablocks sharing
one filepath. Blender's save warning "can't save multiple images to the
same path" refers to that collision.

Safe to run any time: pixels come from the same file on disk, so no image
content is lost. Packed images (source != 'FILE' or with no filepath) are
ignored, since their pixels may differ even if their names collide.
"""
import bpy
from collections import defaultdict


def main():
    groups = defaultdict(list)
    for img in bpy.data.images:
        if img.source != 'FILE' or not img.filepath:
            continue
        if img.packed_file is not None:
            continue
        key = bpy.path.abspath(img.filepath)
        groups[key].append(img)

    merged_groups = 0
    removed = 0

    for path, images in groups.items():
        if len(images) < 2:
            continue

        keeper = min(images, key=lambda i: (len(i.name), i.name))

        for dup in images:
            if dup is keeper:
                continue
            dup.user_remap(keeper)
            bpy.data.images.remove(dup)
            removed += 1

        merged_groups += 1
        print(f"  {path}: kept '{keeper.name}', removed {len(images) - 1} duplicate(s)")

    print()
    print(f"Deduplicated {merged_groups} filepath group(s), removed {removed} datablock(s).")


if __name__ == "__main__":
    main()
