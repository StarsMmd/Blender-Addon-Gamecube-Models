"""IR armature → BR armature conversion.

Pure — no bpy, no side effects. Takes an IRModel and returns a BRArmature
with every Blender-side decision pre-baked: edit-bone matrices, inherit_scale
mode per bone, tail offsets for IK hacks, rotation mode, display type.
"""
import math
import os

try:
    from .....shared.BR.armature import BRArmature, BRBone
except (ImportError, SystemError):
    from shared.BR.armature import BRArmature, BRBone


_NEAR_ZERO = 0.001
_UNIFORM_RATIO = 1.1

# GameCube Y-up → Blender Z-up: π/2 around X.
_Y_UP_TO_Z_UP = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, math.cos(math.pi / 2), -math.sin(math.pi / 2), 0.0],
    [0.0, math.sin(math.pi / 2), math.cos(math.pi / 2), 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


def choose_inherit_scale(accumulated_scale):
    """Pick Blender's inherit_scale enum value for a bone's accumulated scale.

    ALIGNED: accumulated chain is uniform (correct under HSD's aligned scale
    inheritance, no shear under TRS decomposition).
    NONE: non-uniform accumulation (avoids cascading shear that TRS can't
    represent; caller accepts that the child won't inherit parent's scale).

    The thresholds mirror the pre-Plan build_skeleton heuristic so this
    refactor produces byte-identical output.
    """
    mn = min(abs(x) for x in accumulated_scale)
    mx = max(abs(x) for x in accumulated_scale)
    is_uniform = (mn < _NEAR_ZERO) or (mx / max(mn, 1e-9) < _UNIFORM_RATIO)
    return 'ALIGNED' if is_uniform else 'NONE'


def choose_tail_offset(ir_bone, ik_hack):
    """Compute the relative tail offset for an edit bone.

    IK-hack bones (effectors, splines under options['ik_hack']) get a
    shrunk tail; regular bones get a 0.01-unit Y offset so edit bones
    aren't degenerate.
    """
    if ik_hack and ir_bone.ik_shrink:
        y = ir_bone.scale[1] if ir_bone.scale[1] != 0 else 1.0
        return (0.0, 1e-4 / y, 0.0)
    return (0.0, 0.01, 0.0)


def derive_armature_name(ir_model, options, model_index):
    """Replicate build_skeleton's naming scheme."""
    filepath = options.get("filepath", "") if options else ""
    base_name = os.path.basename(filepath).split('.')[0] if filepath else "model"
    model_name = ir_model.name or ""
    if model_name and model_name != base_name:
        return f"{base_name}_{model_name}_skeleton_{model_index}"
    return f"{base_name}_skeleton_{model_index}"


def plan_armature(ir_model, options=None, model_index=0):
    """Convert IRModel to BRArmature.

    Args:
        ir_model: source IR model.
        options: importer options dict (reads 'filepath', 'ik_hack').
        model_index: scene index for unique naming.
    """
    options = options or {}
    ik_hack = bool(options.get("ik_hack"))

    br_bones = [
        BRBone(
            name=ir_bone.name,
            parent_index=ir_bone.parent_index,
            edit_matrix=ir_bone.normalized_world_matrix,
            tail_offset=choose_tail_offset(ir_bone, ik_hack),
            inherit_scale=choose_inherit_scale(ir_bone.accumulated_scale),
            rotation_mode='XYZ',
            is_hidden=ir_bone.is_hidden,
        )
        for ir_bone in ir_model.bones
    ]

    return BRArmature(
        name=derive_armature_name(ir_model, options, model_index),
        bones=br_bones,
        display_type='STICK' if ik_hack else 'OCTAHEDRAL',
        matrix_basis=_Y_UP_TO_Z_UP,
    )
