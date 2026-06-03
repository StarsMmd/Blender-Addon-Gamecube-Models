"""Tests for _determine_parent_bone — mesh→bone ownership round-trip.

Regression: meshes that the original DAT attached to a specific bone were
landing on a different bone on re-export because the exporter fell back to
"nearest common ancestor of weighted bones". The importer now records the
owning bone via Blender's native `parent_bone` field (with `parent_type`
left as 'OBJECT' to avoid double-deformation against the armature modifier),
and the exporter reads it back.
"""
from types import SimpleNamespace

from shared.IR.enums import SkinType
from shared.IR.geometry import IRBoneWeights
from exporter.phases.plan.helpers.meshes import determine_parent_bone as _determine_parent_bone


def _mesh(parent_bone="", parent_type="OBJECT"):
    return SimpleNamespace(parent_bone=parent_bone, parent_type=parent_type)


def _weights(bone_names):
    """WEIGHTED mesh with every vertex weighted to every listed bone equally."""
    assignments = [(0, [(name, 1.0 / len(bone_names)) for name in bone_names])]
    return IRBoneWeights(type=SkinType.WEIGHTED, assignments=assignments, bone_name=None)


def _bone(name, parent_index=None):
    return SimpleNamespace(name=name, parent_index=parent_index)


def test_uses_parent_bone_when_set_even_with_object_parent_type():
    """Importer records bone name via `parent_bone` with parent_type='OBJECT'.

    The exporter must honour that even though the parent isn't BONE-typed —
    otherwise round-tripped meshes fall back to the NCA heuristic.
    """
    bones = [_bone("root"), _bone("torso", 0), _bone("head", 1), _bone("hair", 2)]
    idx = {b.name: i for i, b in enumerate(bones)}
    mesh = _mesh(parent_bone="hair", parent_type="OBJECT")
    # Weights span torso + head → NCA would pick torso (1), but the
    # recorded parent_bone is "hair" (3).
    bw = _weights(["torso", "head"])
    assert _determine_parent_bone(mesh, bw, idx, bones) == 3


def test_falls_back_to_nca_when_parent_bone_empty():
    """Meshes authored outside our importer (no parent_bone set) still work."""
    bones = [_bone("root"), _bone("torso", 0), _bone("arm_l", 1), _bone("arm_r", 1)]
    idx = {b.name: i for i, b in enumerate(bones)}
    mesh = _mesh(parent_bone="", parent_type="OBJECT")
    bw = _weights(["arm_l", "arm_r"])
    # NCA of arm_l (2) and arm_r (3) is torso (1).
    assert _determine_parent_bone(mesh, bw, idx, bones) == 1


def test_unknown_parent_bone_falls_through_to_weights():
    """If `parent_bone` names a bone that doesn't exist, don't silently
    return 0 — fall through to the weight-based heuristic."""
    bones = [_bone("root"), _bone("torso", 0), _bone("head", 1)]
    idx = {b.name: i for i, b in enumerate(bones)}
    mesh = _mesh(parent_bone="deleted_bone", parent_type="OBJECT")
    bw = _weights(["head"])
    # Weighted to a single bone → returns that bone via SINGLE_BONE fallback?
    # Actually this is WEIGHTED with one entry, so NCA of just {head} = head (2).
    assert _determine_parent_bone(mesh, bw, idx, bones) == 2
