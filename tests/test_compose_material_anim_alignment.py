"""Regression: MaterialAnimation chain must align with the DObj chain.

compose_meshes groups IRMeshes by material under each bone, producing one
DObj per material group. compose_material_animations must emit a
MaterialAnimation chain with one entry per DObj position; the real track
goes at the animated mesh's DObj position, with empty placeholders in
front.

sirnight's idle hit this exactly: bone 71 owned 7 IRMeshes with 7 distinct
materials. The 2-texture material with the UV animation sat at DObj
position 5. Before the fix, the MA chain held one entry at position 0,
so the importer paired the 2-UV track with the 1-texture DObj at position
0 and raised `'TexMapping_1' not found`.
"""
from shared.IR.skeleton import IRBone
from shared.IR.geometry import IRMesh
from shared.IR.animation import (
    IRBoneAnimationSet, IRMaterialTrack, IRTextureUVTrack, IRKeyframe,
)
from shared.IR.enums import ScaleInheritance, Interpolation
from exporter.phases.compose.helpers.material_animations import (
    compose_material_animations,
)


def _identity():
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def _bone(name, parent_index=None, mesh_indices=()):
    return IRBone(
        name=name, parent_index=parent_index,
        position=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1),
        inverse_bind_matrix=None, flags=0, is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED, ik_shrink=False,
        world_matrix=_identity(), local_matrix=_identity(),
        normalized_world_matrix=_identity(),
        normalized_local_matrix=_identity(),
        scale_correction=_identity(),
        accumulated_scale=(1, 1, 1),
        mesh_indices=list(mesh_indices),
    )


class _FakeMat:
    """Stand-in for IRMaterial — compose only needs distinct id() per material.

    Carries an empty `texture_layers` list so the V-flip reversal can probe
    the TObj's static scale without AttributeError. Real IRMaterials always
    have this field.
    """
    def __init__(self, name):
        self.name = name
        self.texture_layers = []


def _mat(name):
    return _FakeMat(name)


def _mesh(name, material, parent_bone_index):
    return IRMesh(
        name=name, vertices=[(0, 0, 0)], faces=[],
        uv_layers=[], color_layers=[], normals=None,
        material=material, bone_weights=None, is_hidden=False,
        parent_bone_index=parent_bone_index, cull_back=False,
    )


def _uv_track(texture_index, frame_max=10):
    tt = IRTextureUVTrack(texture_index=texture_index)
    tt.translation_v = [
        IRKeyframe(frame=0.0, value=0.0, interpolation=Interpolation.CONSTANT),
        IRKeyframe(frame=float(frame_max), value=0.5, interpolation=Interpolation.LINEAR),
    ]
    return tt


def _chain_length(head):
    n = 0
    node = head
    while node is not None:
        n += 1
        node = node.next
    return n


def _chain_to_list(head):
    out = []
    node = head
    while node is not None:
        out.append(node)
        node = node.next
    return out


def test_ma_chain_pads_to_match_dobj_position():
    # bone 0 owns 3 meshes, each with its own material.
    # Animation targets mesh 2 (DObj position 2). Chain must have 3 entries:
    # empty, empty, real.
    mat_a, mat_b, mat_c = _mat('A'), _mat('B'), _mat('C')
    bones = [_bone('root', mesh_indices=[0, 1, 2])]
    meshes = [_mesh('m0', mat_a, 0), _mesh('m1', mat_b, 0), _mesh('m2', mat_c, 0)]

    track = IRMaterialTrack(material_mesh_name='mesh_2_root')
    track.texture_uv_tracks = [_uv_track(0)]
    anim_set = IRBoneAnimationSet(name='Idle', tracks=[], material_tracks=[track])

    root_maj = compose_material_animations(anim_set, bones, meshes)
    assert root_maj is not None

    # Bone 0's MAJ is the tree root. The MA chain is on root_maj.animation.
    chain = _chain_to_list(root_maj.animation)
    assert len(chain) == 3, f"expected 3 MAs aligned to 3 DObjs, got {len(chain)}"

    # Positions 0 and 1 must be empty placeholders; position 2 must carry the track.
    assert chain[0].animation is None and chain[0].texture_animation is None
    assert chain[1].animation is None and chain[1].texture_animation is None
    assert chain[2].texture_animation is not None


def test_ma_chain_preserves_trailing_empties():
    # bone 0 owns 4 meshes. Animation targets mesh 1 (position 1). Chain
    # must have 4 entries aligned to the 4 DObjs — trailing empties are
    # preserved to match the originals, which don't trim.
    mat_a, mat_b, mat_c, mat_d = _mat('A'), _mat('B'), _mat('C'), _mat('D')
    bones = [_bone('root', mesh_indices=[0, 1, 2, 3])]
    meshes = [
        _mesh('m0', mat_a, 0), _mesh('m1', mat_b, 0),
        _mesh('m2', mat_c, 0), _mesh('m3', mat_d, 0),
    ]

    track = IRMaterialTrack(material_mesh_name='mesh_1_root')
    track.texture_uv_tracks = [_uv_track(0)]
    anim_set = IRBoneAnimationSet(name='Idle', tracks=[], material_tracks=[track])

    chain = _chain_to_list(compose_material_animations(anim_set, bones, meshes).animation)
    assert len(chain) == 4
    assert chain[0].texture_animation is None    # empty placeholder for mesh 0
    assert chain[1].texture_animation is not None  # real track at position 1
    assert chain[2].texture_animation is None    # trailing empty for mesh 2
    assert chain[3].texture_animation is None    # trailing empty for mesh 3


def test_meshes_sharing_material_collapse_into_one_dobj():
    # mesh_0 and mesh_1 share material A; mesh_2 has material B.
    # That yields 2 DObjs under bone 0: DObj[0] = mat_A (holds both meshes),
    # DObj[1] = mat_B. Animation on mesh 2 → real MA at position 1.
    mat_a, mat_b = _mat('A'), _mat('B')
    bones = [_bone('root', mesh_indices=[0, 1, 2])]
    meshes = [_mesh('m0', mat_a, 0), _mesh('m1', mat_a, 0), _mesh('m2', mat_b, 0)]

    track = IRMaterialTrack(material_mesh_name='mesh_2_root')
    track.texture_uv_tracks = [_uv_track(0)]
    anim_set = IRBoneAnimationSet(name='Idle', tracks=[], material_tracks=[track])

    chain = _chain_to_list(compose_material_animations(anim_set, bones, meshes).animation)
    assert len(chain) == 2, "mesh_0/mesh_1 share material A, so bone 0 has only 2 DObjs"
    assert chain[0].texture_animation is None
    assert chain[1].texture_animation is not None


def test_shared_material_animation_applies_to_the_shared_dobj():
    # When an animation track targets mesh 0, but mesh 0 and mesh 1 share
    # the same material, the track applies to the shared DObj — i.e. the
    # MA goes on the DObj position for material A, regardless of which
    # IRMesh name the track was originally keyed by.
    mat_a, mat_b = _mat('A'), _mat('B')
    bones = [_bone('root', mesh_indices=[0, 1, 2])]
    meshes = [_mesh('m0', mat_a, 0), _mesh('m1', mat_a, 0), _mesh('m2', mat_b, 0)]

    track = IRMaterialTrack(material_mesh_name='mesh_0_root')
    track.texture_uv_tracks = [_uv_track(0)]
    anim_set = IRBoneAnimationSet(name='Idle', tracks=[], material_tracks=[track])

    chain = _chain_to_list(compose_material_animations(anim_set, bones, meshes).animation)
    # Real track goes at DObj position 0 (material A). Trailing empty for
    # material B is preserved to align with the DObj chain.
    assert len(chain) == 2
    assert chain[0].texture_animation is not None
    assert chain[1].texture_animation is None


def test_no_tracks_returns_none():
    anim_set = IRBoneAnimationSet(name='Idle', tracks=[], material_tracks=[])
    assert compose_material_animations(anim_set, [_bone('root')], []) is None


def test_mesh_bone_without_animated_material_gets_empty_chain():
    # bone 0 has 2 DObjs, but the animation track targets a different bone's
    # mesh. Bone 0 must still emit a length-2 all-empty MA chain so the
    # MAJ-to-DObj lockstep walk at read-time stays aligned.
    mat_a, mat_b, mat_c = _mat('A'), _mat('B'), _mat('C')
    bones = [
        _bone('root', mesh_indices=[0, 1]),
        _bone('arm', parent_index=0, mesh_indices=[2]),
    ]
    meshes = [_mesh('m0', mat_a, 0), _mesh('m1', mat_b, 0), _mesh('m2', mat_c, 1)]

    track = IRMaterialTrack(material_mesh_name='mesh_2_arm')
    track.texture_uv_tracks = [_uv_track(0)]
    anim_set = IRBoneAnimationSet(name='Idle', tracks=[], material_tracks=[track])

    root_maj = compose_material_animations(anim_set, bones, meshes)
    assert root_maj is not None

    # root_maj corresponds to bone 0 ('root'). Its MA chain should have 2
    # empty entries (one per DObj), not None.
    root_chain = _chain_to_list(root_maj.animation)
    assert len(root_chain) == 2
    assert all(ma.animation is None and ma.texture_animation is None for ma in root_chain)

    # The child MAJ (bone 1, 'arm') holds the real track.
    arm_chain = _chain_to_list(root_maj.child.animation)
    assert len(arm_chain) == 1
    assert arm_chain[0].texture_animation is not None


def test_bone_without_dobjs_still_returns_none_animation():
    # bones with no meshes at all (pure skeleton bones) have no DObj chain,
    # so their MAJ.animation stays None — no empty chain to emit.
    mat_a = _mat('A')
    bones = [
        _bone('root', mesh_indices=[]),
        _bone('mesh_bone', parent_index=0, mesh_indices=[0]),
    ]
    meshes = [_mesh('m0', mat_a, 1)]

    track = IRMaterialTrack(material_mesh_name='mesh_0_mesh_bone')
    track.texture_uv_tracks = [_uv_track(0)]
    anim_set = IRBoneAnimationSet(name='Idle', tracks=[], material_tracks=[track])

    root_maj = compose_material_animations(anim_set, bones, meshes)
    assert root_maj is not None
    assert root_maj.animation is None       # no DObjs on root → None
    assert root_maj.child.animation is not None  # mesh_bone has the real track
