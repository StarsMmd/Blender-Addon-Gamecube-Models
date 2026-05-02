from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class BRBakeContext:
    """Everything a pose-basis computation needs at each animation frame.

    Produced by Plan once per bone track; consumed by the per-frame basis
    formula (pure, see importer/phases/plan/helpers/animations.py::
    compute_pose_basis). All fields are plain data — no bpy or mathutils.

    ``strategy`` selects between two mathematically distinct paths:
      - ``'aligned'``: legacy edit_scale_correction sandwich. Correct for
        uniform parent scales (no shear); carries scale information for
        ALIGNED inheritance propagation.
      - ``'direct'``: per-channel SRT delta against the rest pose. Used
        when the accumulated parent scale is non-uniform, because the
        sandwich formula would produce a sheared matrix that TRS
        decomposition can't represent.
    """
    strategy: str  # 'aligned' | 'direct'
    rest_base: list[list[float]]          # 4x4 rest_local (with path rotation baked in)
    rest_base_inv: list[list[float]]      # 4x4 — fallback for aligned when local_edit is singular
    has_path: bool

    # Direct-path pre-decomposition (also used as constants in aligned's fallback):
    rest_translation: tuple[float, float, float]
    rest_rotation_quat: tuple[float, float, float, float]  # (w, x, y, z)
    rest_scale: tuple[float, float, float]

    # Aligned-path only:
    local_edit: list[list[float]] | None = None
    edit_scale_correction: list[list[float]] | None = None
    parent_edit_scale_correction: list[list[float]] | None = None


@dataclass
class BRBoneTrack:
    """One bone's animation keyframes + pre-computed bake context."""
    bone_name: str
    bone_index: int
    # IR-decoded keyframes per channel (3 components each).
    rotation: list[list[object]]  # list[IRKeyframe] per axis
    location: list[list[object]]
    scale: list[list[object]]
    # Rest-pose constants used to fill channels with no keyframes.
    rest_rotation: tuple[float, float, float]
    rest_position: tuple[float, float, float]
    rest_scale: tuple[float, float, float]
    end_frame: float
    # Importer-only: pre-computed pose-basis bake context, consumed by
    # `build_blender/helpers/animations.py`. The exporter direction
    # leaves this `None` — its plan converts BRBoneTrack back to
    # IRBoneTrack without ever touching the basis math.
    bake_context: BRBakeContext | None = None
    # Pass-through until later stages migrate these:
    spline_path: object = None  # IRSplinePath


@dataclass
class BRMaterialTrack:
    """Pass-through wrapper for an IR material-animation track.

    Carried through Plan unchanged until the materials stage migrates the
    material-animation pipeline.
    """
    material_mesh_name: str
    diffuse_r: list | None = None
    diffuse_g: list | None = None
    diffuse_b: list | None = None
    alpha: list | None = None
    texture_uv_tracks: list = field(default_factory=list)
    loop: bool = False


@dataclass
class BRAction:
    """One Blender Action: armature bone tracks + paired material tracks."""
    name: str
    bone_tracks: list[BRBoneTrack] = field(default_factory=list)
    material_tracks: list[BRMaterialTrack] = field(default_factory=list)
    loop: bool = False
    is_static: bool = False
