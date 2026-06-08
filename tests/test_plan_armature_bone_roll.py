"""Bone roll must survive export as a real GX rotation.

A Blender edit bone is fully defined by its head, its tail, and its *roll*.
head->tail fixes the bone's local +Y axis; roll is the remaining degree of
freedom — the spin of the local X/Z axes around that +Y axis. It is baked into
`edit_bone.matrix` (the X and Z columns), NOT carried as a separate scalar, so
the exporter respects roll exactly as long as it consumes the full edit matrix
(`exporter/phases/plan/helpers/armature.py` does: edit_world = base_xform @
br_bone.edit_matrix → decompose to SRT).

These tests pin that behaviour: two bones identical in head/tail but differing
in roll must decompose to different GX rotations, and an up-pointing bone with a
90° roll must produce the +90°-about-vertical (Y) rotation we observed in the
field. A future refactor that reconstructs bone orientation from head/tail
direction alone — dropping roll — would fail here.
"""
import math

from shared.BR.armature import BRArmature, BRBone
from exporter.phases.plan.helpers.armature import plan_armature


def _up_bone_matrix(roll_rad):
    """4x4 world matrix for a bone pointing straight up (+Z) with `roll_rad`.

    Columns are the bone's local axes. head->tail (+Y of the bone) is world +Z.
    Roll rotates the X/Z axes about that length axis: at roll 0, local X = world
    +X; the X/Z columns sweep through the world XY-plane as roll increases.
    (Verified against Blender: an up-bone at roll 90° has local X = world +Y.)
    """
    c, s = math.cos(roll_rad), math.sin(roll_rad)
    # col0 = X = (c, s, 0); col1 = Y = (0, 0, 1); col2 = Z = X×Y = (s, -c, 0)
    return [
        [c, 0.0, s, 0.0],
        [s, 0.0, -c, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _root(roll_rad):
    arm = BRArmature(
        name="rig",
        bones=[BRBone(
            name="root",
            parent_index=None,
            edit_matrix=_up_bone_matrix(roll_rad),
            tail_offset=(0.0, 0.0, 0.13),
            inherit_scale='FULL',
        )],
    )
    return plan_armature(arm)[0]


def test_roll_changes_the_exported_rotation():
    """Same head/tail, different roll → different GX rotation. If roll were
    dropped (orientation taken from head/tail only) these would be equal."""
    rot0 = _root(0.0)
    rot90 = _root(math.pi / 2)
    assert rot0.rotation != rot90.rotation


def test_zero_roll_up_bone_is_identity_rotation():
    """An up-pointing bone with roll 0 is the game-native convention: an
    axis-aligned, identity-rotation root."""
    rot = _root(0.0).rotation
    assert all(abs(a) < 1e-5 for a in rot), rot


def test_ninety_degree_roll_is_ninety_about_vertical():
    """Roll 90° on an up-pointing root yields a +90° rotation about GX's
    vertical (Y) axis — the exact value seen on the field model that rendered
    turned 90° in-game. Guards the convention, not just 'roll is non-zero'."""
    rx, ry, rz = _root(math.pi / 2).rotation
    assert abs(rx) < 1e-4, rx
    assert abs(abs(ry) - math.pi / 2) < 1e-4, ry
    assert abs(rz) < 1e-4, rz
