from __future__ import annotations
from dataclasses import dataclass, field


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


@dataclass
class BRArmature:
    """One armature object + its Blender armature data block."""
    name: str
    bones: list[BRBone] = field(default_factory=list)
    display_type: str = 'OCTAHEDRAL'  # Blender enum: OCTAHEDRAL/STICK/BBONE/.../WIRE
    matrix_basis: list[list[float]] | None = None  # 4x4 armature object transform
    custom_props: dict[str, object] = field(default_factory=dict)
