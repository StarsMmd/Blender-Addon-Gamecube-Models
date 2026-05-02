"""Plan a BRArmature into a flat list of IRBone.

Pure — no bpy. Takes the Blender-frame edit matrices captured by the
describe phase, applies the Z-up → Y-up coordinate rotation, decomposes
each bone's local matrix to SRT, and accumulates world / inverse-bind
matrices in HSD's native (un-rotated) frame.

Flags here are minimal: HIDDEN only. Mesh-driven flags (LIGHTING, OPA,
TEXEDGE, ENVELOPE_MODEL, ROOT_OPA, SKELETON, etc.) are refined later
by `_refine_bone_flags` in the legacy describe_blender flow once mesh
attachment is known.
"""
import math

try:
    from .....shared.IR.skeleton import IRBone
    from .....shared.IR.enums import ScaleInheritance
    from .....shared.Constants.hsd import JOBJ_HIDDEN
    from .....shared.helpers.math_shim import compile_srt_matrix
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR.skeleton import IRBone
    from shared.IR.enums import ScaleInheritance
    from shared.Constants.hsd import JOBJ_HIDDEN
    from shared.helpers.math_shim import compile_srt_matrix
    from shared.helpers.logger import StubLogger


def plan_armature(br_armature, logger=StubLogger()):
    """Convert a BRArmature to a flat list of IRBone.

    In: br_armature (BRArmature) with edit_matrix per bone in Blender Z-up
        frame; logger.
    Out: list[IRBone] in depth-first order, with rest SRT, world / local
        matrices, IBM, and accumulated_scale all expressed in HSD's
        un-rotated SRT-accumulated frame.
    """
    bones = []
    gc_world = {}   # GameCube Y-up world matrices (post coord rotation)
    srt_world = {}  # SRT-accumulated world matrices (HSD-native, no coord rot)

    # Compose the armature object's matrix_basis with the Z-up → Y-up
    # coordinate rotation. For a baked scene `matrix_basis` is identity
    # so this collapses to just the coord rotation; for an unbaked
    # importer-built scene matrix_basis carries the Y-up→Z-up viewing
    # rotation and `_COORD_ROTATION_INV @ matrix_basis` cancels it back
    # out, leaving Y-up bone matrices either way.
    matrix_basis = (
        br_armature.matrix_basis if br_armature.matrix_basis is not None
        else _identity_4x4()
    )
    base_xform = _matmul_4x4(_COORD_ROTATION_INV, matrix_basis)

    for i, br_bone in enumerate(br_armature.bones):
        edit_world = _matmul_4x4(base_xform, br_bone.edit_matrix)
        gc_world[i] = edit_world

        if br_bone.parent_index is not None:
            local = _matmul_4x4(_inverse_4x4(gc_world[br_bone.parent_index]), edit_world)
        else:
            local = edit_world

        position, rotation, scale = _decompose_srt(local)

        srt_local = compile_srt_matrix(scale, rotation, position)
        srt_local = _to_list(srt_local)
        if br_bone.parent_index is not None:
            world = _matmul_4x4(srt_world[br_bone.parent_index], srt_local)
        else:
            world = srt_local
        srt_world[i] = world

        if br_bone.parent_index is not None:
            parent_accum = bones[br_bone.parent_index].accumulated_scale
            accumulated_scale = (
                scale[0] * parent_accum[0],
                scale[1] * parent_accum[1],
                scale[2] * parent_accum[2],
            )
        else:
            accumulated_scale = scale

        flags = JOBJ_HIDDEN if br_bone.is_hidden else 0

        identity_list = _identity_4x4()
        inverse_bind = _inverse_4x4(world)

        bones.append(IRBone(
            name=br_bone.name,
            parent_index=br_bone.parent_index,
            position=position,
            rotation=rotation,
            scale=scale,
            inverse_bind_matrix=inverse_bind,
            flags=flags,
            is_hidden=br_bone.is_hidden,
            inherit_scale=ScaleInheritance.ALIGNED,
            ik_shrink=False,
            world_matrix=_clone_4x4(world),
            local_matrix=_clone_4x4(srt_local),
            normalized_world_matrix=_clone_4x4(world),
            normalized_local_matrix=_clone_4x4(srt_local),
            scale_correction=identity_list,
            accumulated_scale=accumulated_scale,
        ))

    root_count = sum(1 for b in bones if b.parent_index is None)
    hidden_count = sum(1 for b in bones if b.is_hidden)
    logger.info("  Planned %d bones from armature '%s' (%d root(s), %d hidden)",
                len(bones), br_armature.name, root_count, hidden_count)
    return bones


# Z-up Blender frame → Y-up GC frame: inverse of pi/2 X rotation.
_COS = math.cos(math.pi / 2)
_SIN = math.sin(math.pi / 2)
# Inverse rotates by -pi/2 around X.
_COORD_ROTATION_INV = [
    [1.0, 0.0,  0.0, 0.0],
    [0.0, _COS,  _SIN, 0.0],
    [0.0, -_SIN, _COS, 0.0],
    [0.0, 0.0,  0.0, 1.0],
]


def _matmul_4x4(a, b):
    out = [[0.0]*4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            out[i][j] = sum(a[i][k] * b[k][j] for k in range(4))
    return out


def _identity_4x4():
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def _clone_4x4(m):
    return [list(row) for row in m]


def _to_list(m):
    return [list(row) for row in m]


def _inverse_4x4(m):
    """Inverse of a 4x4 matrix via Gauss-Jordan."""
    n = 4
    a = [list(row) + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot_row][col]) < 1e-12:
            raise ValueError("Singular matrix in plan_armature inverse")
        a[col], a[pivot_row] = a[pivot_row], a[col]
        pv = a[col][col]
        for j in range(2 * n):
            a[col][j] /= pv
        for r in range(n):
            if r == col:
                continue
            f = a[r][col]
            if f == 0.0:
                continue
            for j in range(2 * n):
                a[r][j] -= f * a[col][j]
    return [row[n:] for row in a]


def _decompose_srt(m):
    """Decompose a 4x4 affine matrix into (position, euler_xyz, scale).

    Mirrors mathutils.Matrix.decompose() + Quaternion.to_euler('XYZ').
    """
    position = (m[0][3], m[1][3], m[2][3])

    sx = math.sqrt(m[0][0]**2 + m[1][0]**2 + m[2][0]**2)
    sy = math.sqrt(m[0][1]**2 + m[1][1]**2 + m[2][1]**2)
    sz = math.sqrt(m[0][2]**2 + m[1][2]**2 + m[2][2]**2)

    det = (
        m[0][0] * (m[1][1]*m[2][2] - m[1][2]*m[2][1]) -
        m[0][1] * (m[1][0]*m[2][2] - m[1][2]*m[2][0]) +
        m[0][2] * (m[1][0]*m[2][1] - m[1][1]*m[2][0])
    )
    if det < 0:
        sx = -sx

    if sx == 0 or sy == 0 or sz == 0:
        return position, (0.0, 0.0, 0.0), (sx, sy, sz)

    r = [
        [m[0][0]/sx, m[0][1]/sy, m[0][2]/sz],
        [m[1][0]/sx, m[1][1]/sy, m[1][2]/sz],
        [m[2][0]/sx, m[2][1]/sy, m[2][2]/sz],
    ]

    # Euler XYZ extraction (matches mathutils' to_euler('XYZ')).
    sy_axis = -r[2][0]
    if sy_axis > 1.0: sy_axis = 1.0
    if sy_axis < -1.0: sy_axis = -1.0
    if abs(sy_axis) < 0.999999:
        ex = math.atan2(r[2][1], r[2][2])
        ey = math.asin(sy_axis)
        ez = math.atan2(r[1][0], r[0][0])
    else:
        ex = math.atan2(-r[1][2], r[1][1])
        ey = math.asin(sy_axis)
        ez = 0.0

    return position, (ex, ey, ez), (sx, sy, sz)
