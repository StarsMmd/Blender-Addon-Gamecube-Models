from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class BRBoneSpline:
    """A JOBJ_SPLINE joint's curve, as a Blender-native Curve spec.

    build_blender creates a real Curve object parented to the bone (so the
    user can see/edit it); describe reads it back. This is a *lossy* native
    mapping: control points survive, but the GX spline type collapses onto a
    Blender curve type and the precomputed segment coefficients (`s3` / knots)
    are dropped — accepted per the round-trip leniency note. Control points
    are in the game's native GC units. BR must not import IR.
    """
    curve_type: str = 'POLY'  # Blender enum: POLY / BEZIER / NURBS
    control_points: list[list[float]] = field(default_factory=list)


@dataclass
class BRBone:
    """One edit-bone + pose-bone spec, ready for bpy to instantiate.

    Every field is a decided, Blender-native value — no IR-side semantics.
    """
    name: str
    parent_index: int | None
    edit_matrix: list[list[float]]  # 4x4 world-space matrix for the edit bone
    tail_offset: tuple[float, float, float]  # relative head → tail offset
    inherit_scale: str  # Blender enum: FULL/FIX_SHEAR/ALIGNED/AVERAGE/NONE/NONE_LEGACY
    rotation_mode: str = 'XYZ'  # Blender enum: XYZ/XZY/YXZ/.../QUATERNION
    use_connect: bool = False
    is_hidden: bool = False
    spline: BRBoneSpline | None = None  # JOBJ_SPLINE curve (maps only)


@dataclass
class BRArmature:
    """One armature object + its Blender armature data block."""
    name: str
    bones: list[BRBone] = field(default_factory=list)
    display_type: str = 'OCTAHEDRAL'  # Blender enum: OCTAHEDRAL/STICK/BBONE/.../WIRE
    matrix_basis: list[list[float]] | None = None  # 4x4 armature object transform
    custom_props: dict[str, object] = field(default_factory=dict)
