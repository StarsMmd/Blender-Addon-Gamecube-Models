from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class BRBakeBone:
    """Rest-pose + hierarchy data for one bone, consumed by the per-frame
    NONE-inheritance bake in ``build_blender/helpers/animations.py``.

    The bake reproduces the GX runtime pose exactly by (1) composing each
    bone's GX world per frame from its animated SRT and its ancestors'
    accumulated scale, then (2) inverting Blender's ``inherit_scale='NONE'``
    forward formula in pure math to recover a shear-free pose basis. Every
    field is plain data — no bpy or mathutils.
    """
    name: str
    parent_index: int | None
    rest_scale: tuple[float, float, float]      # GX joint local SRT
    rest_rotation: tuple[float, float, float]   # Euler XYZ radians
    rest_position: tuple[float, float, float]
    rest_world_matrix: list[list[float]]        # 4x4 GX rest world (scale baked in)
    normalized_rest_matrix: list[list[float]]   # 4x4 edit-bone matrix (rotation only)
    accumulated_scale: tuple[float, float, float]  # rest accumulated scale (rebound)
    classical_scaling: bool                     # JOBJ_CLASSICAL_SCALING


@dataclass
class BRBakeSkeleton:
    """Full-skeleton rest data + parent-first ordering for the pose bake.

    Shared across every action of a model. ``dfs_order`` lists bone indices
    parent-before-child so the per-frame chain composition and the NONE
    inversion (which needs each bone's parent pose already resolved) can run
    in a single forward pass.

    ``scale_baked_indices`` lists the bones that read back under ``NONE`` rather
    than native ``ALIGNED``: their own or an ancestor's accumulated rest scale
    is non-uniform, or their (or an ancestor's) scale is animated. Precomputed
    once so plan (inherit_scale) and build (posed set) agree.
    """
    bones: list[BRBakeBone] = field(default_factory=list)
    dfs_order: list[int] = field(default_factory=list)
    scale_baked_indices: list[int] = field(default_factory=list)


@dataclass
class BRBoneTrack:
    """One bone's animation keyframes.

    Carries only the decoded keyframes + rest constants; the pose-basis math is
    driven by the shared BRBakeSkeleton (see BRArmature.bake_skeleton).
    """
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
