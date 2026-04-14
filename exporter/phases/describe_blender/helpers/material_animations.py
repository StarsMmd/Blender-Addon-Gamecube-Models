"""Describe material animations from Blender actions back into IRMaterialTracks.

Inverts importer/phases/build_blender/helpers/material_animations.py.
The importer writes diffuse RGB / alpha / texture UV fcurves onto Blender
materials, one MATERIAL-type slot per animated material per action. This
module reads those back and produces `list[IRMaterialTrack]` to attach
to the corresponding `IRBoneAnimationSet.material_tracks`.

Data path conventions (must match the importer):
    diffuse_{r,g,b}: node_tree.nodes["DiffuseColor"].outputs[0].default_value[0..2]
    alpha:          node_tree.nodes["AlphaValue"].outputs[0].default_value[0]
    UV tracks:      node_tree.nodes["TexMapping_<idx>"].inputs[1..3].default_value[axis]
                    (input 1 = translation, 2 = rotation, 3 = scale)

The `material_mesh_name` identifier format is `"mesh_{padded_idx}_{bone_name}"`
— the *first* IRMesh (in describe_meshes iteration order) that uses each
material, matching how the importer keyed its `material_lookup` dict.
"""
import re

try:
    from .....shared.IR.animation import (
        IRMaterialTrack, IRTextureUVTrack, IRKeyframe,
    )
    from .....shared.IR.enums import Interpolation
    from .....shared.helpers.srgb import linear_to_srgb
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR.animation import (
        IRMaterialTrack, IRTextureUVTrack, IRKeyframe,
    )
    from shared.IR.enums import Interpolation
    from shared.helpers.srgb import linear_to_srgb
    from shared.helpers.logger import StubLogger


_COLOR_PATH_RE = re.compile(
    r'^node_tree\.nodes\["(DiffuseColor|AlphaValue)"\]\.outputs\[0\]\.default_value$'
)
_UV_PATH_RE = re.compile(
    r'^node_tree\.nodes\["TexMapping_(\d+)"\]\.inputs\[(\d+)\]\.default_value$'
)

_INTERP_FROM_BLENDER = {
    'CONSTANT': Interpolation.CONSTANT,
    'LINEAR':   Interpolation.LINEAR,
    'BEZIER':   Interpolation.BEZIER,
}


def describe_material_animations_for_action(
        action, material_lookup, logger=StubLogger()):
    """Read material fcurves off `action` and return a list[IRMaterialTrack].

    Args:
        action: bpy.types.Action. Its slots of type 'MATERIAL' are scanned.
        material_lookup: dict mapping id(bpy.types.Material) → the
            `material_mesh_name` string (mesh_{idx}_{bone_name}) that the
            importer used when it built the material. Built once by
            `build_material_lookup_from_meshes`.
        logger: Logger.

    Returns:
        list[IRMaterialTrack], empty when no material fcurves are present.
    """
    tracks = []

    # Slotted actions: each slot has its own channelbag on the layer's strip.
    # Fall back to the legacy flat action.fcurves when the action has no slots
    # (older fixtures, test doubles, etc).
    slots = getattr(action, 'slots', None) or []
    mat_slots = [s for s in slots if getattr(s, 'target_id_type', None) == 'MATERIAL']

    if mat_slots:
        for slot in mat_slots:
            blender_mat = _resolve_slot_material(slot)
            if blender_mat is None:
                continue
            mesh_name = material_lookup.get(id(blender_mat))
            if mesh_name is None:
                logger.debug(
                    "    skipping material slot '%s' — no IRMesh uses it",
                    getattr(slot, 'name_display', '?'))
                continue
            fcurves = _fcurves_for_slot(action, slot)
            track = _build_material_track(mesh_name, fcurves, action, logger)
            if track is not None:
                tracks.append(track)
    else:
        # Flat action (no slots) — find material fcurves by data path pattern.
        # This path is primarily for test fixtures; real slotted imports take
        # the branch above.
        flat_by_mesh = _group_flat_fcurves_by_material(
            action, material_lookup, logger)
        for mesh_name, fcurves in flat_by_mesh.items():
            track = _build_material_track(mesh_name, fcurves, action, logger)
            if track is not None:
                tracks.append(track)

    return tracks


def build_material_lookup_from_meshes(meshes, blender_materials, bones):
    """Build {id(blender_mat): "mesh_{idx}_{bone_name}"} from describe_meshes output.

    Matches the importer's convention: the *first* IRMesh that references
    a given Blender material becomes its material_mesh_name. Subsequent
    meshes with the same material are ignored — the importer collapses
    them into the same fcurve-bearing slot.
    """
    lookup = {}
    if not meshes or not blender_materials:
        return lookup
    mesh_digits = len(str(max(len(meshes) - 1, 0))) if meshes else 1
    for i, (ir_mesh, mat) in enumerate(zip(meshes, blender_materials)):
        if mat is None:
            continue
        mat_id = id(mat)
        if mat_id in lookup:
            continue   # first-wins, matching importer's build_meshes order
        bone_idx = ir_mesh.parent_bone_index
        bone_name = bones[bone_idx].name if 0 <= bone_idx < len(bones) else 'unknown'
        lookup[mat_id] = "mesh_%s_%s" % (str(i).zfill(mesh_digits), bone_name)
    return lookup


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_slot_material(slot):
    """Return the bpy.types.Material that this MATERIAL slot targets, if any."""
    # Blender 4.x: slot.target_id is the ID. Older paths fall back to
    # iterating bpy.data.materials and matching by name — slot.name_display
    # is the material's name.
    target = getattr(slot, 'target_id', None)
    if target is not None:
        return target
    try:
        import bpy
    except ImportError:
        return None
    name = getattr(slot, 'name_display', None) or getattr(slot, 'identifier', None)
    if name and name in bpy.data.materials:
        return bpy.data.materials[name]
    return None


def _fcurves_for_slot(action, slot):
    """Return the fcurves bound to `slot` in `action`."""
    # Slotted actions keep fcurves on a channelbag inside the layer's strip.
    for layer in getattr(action, 'layers', []) or []:
        for strip in getattr(layer, 'strips', []) or []:
            cb = None
            # `strip.channelbag(slot)` exists on Blender 4.x but returns None
            # when there's no bag for that slot — guard against both.
            if hasattr(strip, 'channelbag'):
                try:
                    cb = strip.channelbag(slot)
                except TypeError:
                    cb = None
            if cb is None:
                continue
            return list(cb.fcurves)
    return []


def _group_flat_fcurves_by_material(action, material_lookup, logger):
    """Fallback: scan `action.fcurves` and group by material name prefix.

    Only used when an action has no slots — primarily for simplified test
    fixtures. Returns {material_mesh_name: [fcurve, ...]}.
    """
    # We can't recover material identity from a flat fcurve list in general
    # (the data_path doesn't carry the material), so this fallback matches
    # every material fcurve against every entry in material_lookup. Real
    # exports go through the slotted branch above.
    grouped = {}
    for fc in action.fcurves:
        if (_COLOR_PATH_RE.match(fc.data_path) or
                _UV_PATH_RE.match(fc.data_path)):
            # Apply the fcurve to every material in the lookup — fine for
            # single-material test fixtures; real models use slots.
            for mesh_name in material_lookup.values():
                grouped.setdefault(mesh_name, []).append(fc)
    return grouped


def _build_material_track(mesh_name, fcurves, action, logger):
    """Consolidate color + UV fcurves into one IRMaterialTrack."""
    diffuse_r = diffuse_g = diffuse_b = alpha = None
    uv_tracks_by_index = {}   # {texture_idx: IRTextureUVTrack}

    for fc in fcurves:
        color_m = _COLOR_PATH_RE.match(fc.data_path)
        if color_m:
            node_name = color_m.group(1)
            kfs = _fcurve_to_keyframes(fc, linearize_from_blender=(node_name == 'DiffuseColor'))
            if node_name == 'DiffuseColor':
                if fc.array_index == 0: diffuse_r = kfs
                elif fc.array_index == 1: diffuse_g = kfs
                elif fc.array_index == 2: diffuse_b = kfs
            elif node_name == 'AlphaValue' and fc.array_index == 0:
                alpha = kfs
            continue

        uv_m = _UV_PATH_RE.match(fc.data_path)
        if uv_m:
            tex_idx = int(uv_m.group(1))
            input_idx = int(uv_m.group(2))
            axis = fc.array_index
            uv_track = uv_tracks_by_index.setdefault(
                tex_idx, IRTextureUVTrack(texture_index=tex_idx))
            field = _UV_FIELD_LOOKUP.get((input_idx, axis))
            if field is not None:
                setattr(uv_track, field, _fcurve_to_keyframes(fc))

    has_any = (diffuse_r or diffuse_g or diffuse_b or alpha or uv_tracks_by_index)
    if not has_any:
        return None

    loop = '_Loop' in action.name or '_loop' in action.name
    return IRMaterialTrack(
        material_mesh_name=mesh_name,
        diffuse_r=diffuse_r, diffuse_g=diffuse_g, diffuse_b=diffuse_b,
        alpha=alpha,
        texture_uv_tracks=[uv_tracks_by_index[k] for k in sorted(uv_tracks_by_index)],
        loop=loop,
    )


_UV_FIELD_LOOKUP = {
    # (mapping-node input index, array axis) → IRTextureUVTrack field name
    (1, 0): 'translation_u',
    (1, 1): 'translation_v',
    (2, 0): 'rotation_x',
    (2, 1): 'rotation_y',
    (2, 2): 'rotation_z',
    (3, 0): 'scale_u',
    (3, 1): 'scale_v',
}


def _fcurve_to_keyframes(fcurve, linearize_from_blender=False):
    """Convert a Blender fcurve into a list[IRKeyframe].

    The importer stores sRGB [0-1] in the IR and linearizes to scene-linear
    when writing RGB fcurves into Blender's DiffuseColor node. Reverse that
    with linear_to_srgb for RGB channels; leave alpha and UV values raw.
    """
    kfs = []
    for kp in fcurve.keyframe_points:
        value = kp.co[1]
        if linearize_from_blender:
            value = linear_to_srgb(max(0.0, min(1.0, value)))
        interp = _INTERP_FROM_BLENDER.get(kp.interpolation, Interpolation.LINEAR)
        kfs.append(IRKeyframe(
            frame=float(kp.co[0]), value=float(value),
            interpolation=interp,
            handle_left=(float(kp.handle_left[0]), float(kp.handle_left[1])),
            handle_right=(float(kp.handle_right[0]), float(kp.handle_right[1])),
        ))
    return kfs
