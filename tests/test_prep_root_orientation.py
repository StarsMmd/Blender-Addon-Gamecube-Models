"""Pre-process guard: reject scenes whose root bone won't export to an identity
root JOBJ rotation.

A non-identity root JOBJ rotation turns the whole model 90 deg in-game (the
game applies the root joint's own rotation as the model's base orientation and
doesn't cancel it the way a full skinning solve does), while every game-native
model has an identity root. The prep scripts no longer auto-normalize the root
bone — fixing the orientation is the author's job — but the exporter still
refuses to export a scene whose root would round-trip to a rotated root joint,
so the failure surfaces at validation time with an actionable message instead
of silently shipping a sideways model.

The canonical frame is coupled to the exporter's Z-up -> Y-up coordinate
rotation: the root bone's world rest matrix must equal the forward coord
rotation (+90 deg about X) so the exporter's inverse coord rotation cancels it.
The first test pins the prep's documented canonical against `plan_armature`'s
output; the rest pin the pre_process guard's accept/reject behaviour for the
common cases (canonical, importer-built, rolled, skewed, empty).
"""
from shared.BR.armature import BRArmature, BRBone


# Root bone's world rest in canonical form: +90 deg about X. The exporter's
# inverse Z-up→Y-up rotation cancels this to an identity root JOBJ.
CANONICAL = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 0.0, -1.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]
IDENTITY4 = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]

# Root pointing up with roll 90 deg — exports a 90-deg-about-Y root joint.
ROLLED_ROOT = [
    [0.0, 0.0, 1.0, 0.0],
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]

# Root pointing along world +Y (lying forward) — exports an X-axis rotation.
FORWARD_ROOT = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
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


def test_guard_rejects_forward_pointing_root():
    """Root pointing along world +Y (no Z-up→Y-up rotation applied) bakes a
    pure-X rotation into the root joint."""
    import pytest
    from exporter.phases.pre_process.pre_process import _check_root_bone_orientation
    with pytest.raises(ValueError) as exc:
        _check_root_bone_orientation([("forward_rig", IDENTITY4, FORWARD_ROOT)])
    assert "forward_rig" in str(exc.value)


def test_guard_collects_all_offenders():
    """Multiple rigs with bad roots: every offender named in the error."""
    import pytest
    from exporter.phases.pre_process.pre_process import _check_root_bone_orientation
    with pytest.raises(ValueError) as exc:
        _check_root_bone_orientation([
            ("rolled", IDENTITY4, ROLLED_ROOT),
            ("forward", IDENTITY4, FORWARD_ROOT),
            ("good", IDENTITY4, CANONICAL),
        ])
    msg = str(exc.value)
    assert "rolled" in msg and "forward" in msg
    assert "good" not in msg


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
