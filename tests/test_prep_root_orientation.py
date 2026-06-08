"""The prep scripts' canonical root orientation must export to an identity
root joint.

A non-identity root JOBJ rotation turns the whole model 90 deg in-game (the
game applies the root joint's own rotation as the model's base orientation and
doesn't cancel it the way a full skinning solve does), while every game-native
model has an identity root. `normalize_root_orientation` in the prep scripts
reorients the root bone to a canonical rest frame so the exporter emits an
identity root joint.

The canonical frame is coupled to the exporter's Z-up -> Y-up coordinate
rotation: the root bone's world rest matrix must equal the forward coord
rotation (+90 deg about X) so the exporter's inverse coord rotation cancels it.
These tests lock the prep's target matrix to the exporter so neither can drift
without the other.
"""
import os

from shared.BR.armature import BRArmature, BRBone


PREP_PKX = os.path.join(os.path.dirname(__file__), "..", "scripts",
                        "prepare_for_pkx_export.py")
PREP_PBR = os.path.join(os.path.dirname(__file__), "..", "scripts",
                        "prepare_pbr_for_pkx_export.py")
PREP_DAT = os.path.join(os.path.dirname(__file__), "..", "scripts",
                        "prepare_for_dat_export.py")
ALL_PREP = (PREP_PKX, PREP_PBR, PREP_DAT)

# The canonical root rest the prep emits (+90 deg about X), as a 4x4 edit matrix.
CANONICAL = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 0.0, -1.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]
IDENTITY4 = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
# A root bone pointing up with roll 90 deg (the field-bug rig) — exports a
# 90-deg-about-Y root joint.
ROLLED_ROOT = [
    [0.0, 0.0, 1.0, 0.0],
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


def test_canonical_root_matrix_exports_identity_root_joint():
    from exporter.phases.plan.helpers.armature import plan_armature
    arm = BRArmature(
        name="rig",
        bones=[BRBone(
            name="root",
            parent_index=None,
            edit_matrix=CANONICAL,
            tail_offset=(0.0, 0.0, 0.13),
            inherit_scale='FULL',
        )],
    )
    root = plan_armature(arm)[0]
    assert all(abs(a) < 1e-5 for a in root.rotation), root.rotation


def _src(path):
    with open(path) as f:
        return f.read()


def test_prep_scripts_define_and_call_normalizer():
    for path in ALL_PREP:
        src = _src(path)
        assert "def normalize_root_orientation" in src, path
        assert "normalize_root_orientation(arm)" in src, path


# ---------------------------------------------------------------------------
# Pre-process guard
# ---------------------------------------------------------------------------

def test_guard_accepts_canonical_root():
    """A baked rig (identity matrix_basis) with a canonical root passes."""
    from exporter.phases.pre_process.pre_process import _check_root_bone_orientation
    _check_root_bone_orientation([("rig", IDENTITY4, CANONICAL)])  # no raise


def test_guard_rejects_rolled_root():
    import pytest
    from exporter.phases.pre_process.pre_process import _check_root_bone_orientation
    with pytest.raises(ValueError) as exc:
        _check_root_bone_orientation([("badrig", IDENTITY4, ROLLED_ROOT)])
    assert "badrig" in str(exc.value)
    assert "root JOBJ" in str(exc.value)


def test_guard_accepts_importer_built_root():
    """An importer-built rig stores Y-up bones with a +90-deg-about-X
    matrix_basis; the root bone is axis-aligned in that frame, so basis @
    root cancels to canonical and the guard passes. Modelled by basis =
    CANONICAL and an identity-rotation root bone."""
    from exporter.phases.pre_process.pre_process import _check_root_bone_orientation
    _check_root_bone_orientation([("imported", CANONICAL, IDENTITY4)])  # no raise


def test_guard_empty_scene_is_fine():
    from exporter.phases.pre_process.pre_process import _check_root_bone_orientation
    _check_root_bone_orientation([])  # no raise


def test_prep_target_matrix_matches_exporter_canonical():
    """The (0,0,-1)/(0,1,0) rows of the prep's target must match CANONICAL so
    the prep emits exactly what the exporter cancels to identity."""
    for path in (PREP_PKX, PREP_PBR):
        src = _src(path)
        assert "(0.0, 0.0, -1.0)" in src and "(0.0, 1.0, 0.0)" in src, path
