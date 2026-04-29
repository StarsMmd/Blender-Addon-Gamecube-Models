"""_compose_bound_box must emit one AABB per animation frame (not a
single static AABB replicated). Each per-frame AABB is the true
linear-blend-skinned tight box: we skin every mesh vertex by its
bone weights at the given frame and take min/max.

Game-native PKXs ship one AABB per frame across every animation set:
achamo 561 distinct / 561 total, absol 560/566, rayquaza 716/722.
"""
import math
import struct

from exporter.phases.compose import compose as compose_mod
from shared.IR.enums import SkinType


def test_eval_channel_constant_outside_range():
    kf = [_KF(0, 1.0), _KF(10, 5.0)]
    assert compose_mod._eval_channel(kf, -5, 99) == 1.0
    assert compose_mod._eval_channel(kf, 100, 99) == 5.0


def test_eval_channel_linear_interior():
    kf = [_KF(0, 0.0), _KF(10, 10.0)]
    # Midpoint → linear interpolation = 5.0
    assert abs(compose_mod._eval_channel(kf, 5, 0.0) - 5.0) < 1e-6
    assert abs(compose_mod._eval_channel(kf, 2, 0.0) - 2.0) < 1e-6


def test_eval_channel_empty_uses_default():
    assert compose_mod._eval_channel([], 10, 7.5) == 7.5


def test_eval_channel_single_kf_returns_value():
    assert compose_mod._eval_channel([_KF(5, 3.14)], 0, 99) == 3.14
    assert compose_mod._eval_channel([_KF(5, 3.14)], 100, 99) == 3.14


def test_animated_bone_positions_static_rig_returns_rest_positions():
    """With no animation tracks, bones should all land at their rest
    world positions (derived from local SRT + parent chain)."""
    model = _FakeModel([
        _make_bone(name='root', parent=None, pos=(0, 0, 0), rot=(0, 0, 0), scl=(1, 1, 1)),
        _make_bone(name='mid',  parent=0,    pos=(1, 0, 0), rot=(0, 0, 0), scl=(1, 1, 1)),
        _make_bone(name='tip',  parent=1,    pos=(1, 0, 0), rot=(0, 0, 0), scl=(1, 1, 1)),
    ])
    anim = _FakeAnimSet(tracks=[])  # no tracks → rest pose
    positions = compose_mod._animated_bone_positions(model, anim, frame=0)
    assert len(positions) == 3
    # Parent chain propagates: mid at (1,0,0), tip at (2,0,0)
    assert abs(positions[0][0]) < 1e-6
    assert abs(positions[1][0] - 1.0) < 1e-6
    assert abs(positions[2][0] - 2.0) < 1e-6


def test_skinned_aabb_tracks_single_weighted_vertex():
    """A vertex at (2,0,0) fully weighted to a bone that rotates 90° about Z
    should skin to (0,2,0) — not the rest point."""
    bones = [
        _make_bone('root', parent=None, pos=(0, 0, 0), rot=(0, 0, 0), scl=(1, 1, 1)),
    ]
    mesh = _make_mesh(
        vertices=[(2.0, 0.0, 0.0)],
        bw=_IRBW(type=SkinType.WEIGHTED,
                 assignments=[(0, [('root', 1.0)])]),
        parent_bone_index=0,
    )
    model = _FakeModel(bones=bones, meshes=[mesh], anims=[])

    # Rest: AABB is a degenerate point at (2,0,0)
    samples = compose_mod._build_skin_samples(model, SkinType)
    rest = compose_mod._rest_bone_world_matrices(model)
    mn, mx = compose_mod._compute_skinned_aabb(samples, rest)
    assert abs(mn[0] - 2.0) < 1e-6 and abs(mx[0] - 2.0) < 1e-6

    # Animate: root rotates 90° about Z → vertex lands at (0,2,0)
    track = _Track(bone_index=0,
                   rotation=[[], [], [_KF(0, 0.0), _KF(10, math.pi / 2)]],
                   location=[[], [], []],
                   scale=[[], [], []],
                   end_frame=10)
    anim_set = _FakeAnimSet(tracks=[track])
    world = compose_mod._animated_bone_world_matrices(model, anim_set, frame=10)
    mn, mx = compose_mod._compute_skinned_aabb(samples, world)
    assert abs(mn[0]) < 1e-6 and abs(mx[0]) < 1e-6
    assert abs(mn[1] - 2.0) < 1e-6 and abs(mx[1] - 2.0) < 1e-6


def test_skinned_aabb_weight_blend_midpoint():
    """Vertex 50/50 weighted between two bones 2 units apart should
    skin to the midpoint — the AABB is a point at that midpoint."""
    bones = [
        _make_bone('a', parent=None, pos=(0, 0, 0), rot=(0, 0, 0), scl=(1, 1, 1)),
        _make_bone('b', parent=None, pos=(2, 0, 0), rot=(0, 0, 0), scl=(1, 1, 1)),
    ]
    mesh = _make_mesh(
        vertices=[(1.0, 0.0, 0.0)],
        bw=_IRBW(type=SkinType.WEIGHTED,
                 assignments=[(0, [('a', 0.5), ('b', 0.5)])]),
        parent_bone_index=0,
    )
    model = _FakeModel(bones=bones, meshes=[mesh], anims=[])
    samples = compose_mod._build_skin_samples(model, SkinType)
    rest = compose_mod._rest_bone_world_matrices(model)
    mn, mx = compose_mod._compute_skinned_aabb(samples, rest)
    # Rest: mid of (0,0,0)+offset and (2,0,0)+offset → (1,0,0)
    assert abs(mn[0] - 1.0) < 1e-6 and abs(mx[0] - 1.0) < 1e-6


def test_compose_bound_box_emits_one_aabb_per_frame():
    """A 5-frame animation should yield 5 AABBs (24 bytes each)."""
    bones = [
        _make_bone('root', parent=None, pos=(0, 0, 0), rot=(0, 0, 0), scl=(1, 1, 1)),
    ]
    mesh = _make_mesh(
        vertices=[(1.0, 0.0, 0.0)],
        bw=_IRBW(type=SkinType.WEIGHTED,
                 assignments=[(0, [('root', 1.0)])]),
        parent_bone_index=0,
    )
    track = _Track(bone_index=0,
                   rotation=[[_KF(0, 0.0), _KF(4, math.pi)], [], []],
                   location=[[], [], []],
                   scale=[[], [], []],
                   end_frame=4)
    model = _FakeModel(bones=bones, meshes=[mesh], anims=[_FakeAnimSet(tracks=[track])])

    bb = compose_mod._compose_bound_box(model, _NullLogger())
    assert bb is not None
    # 5 frames × 24 bytes = 120
    assert len(bb.raw_aabb_data) == 5 * 24
    assert bb.first_anim_frame_count == 5
    assert bb.anim_set_count == 1


def test_compose_bound_box_rigid_uses_parent_bone():
    """Mesh with no bone_weights falls back to parent_bone_index for
    skinning — so animating that bone moves the AABB with it."""
    bones = [
        _make_bone('root', parent=None, pos=(0, 0, 0), rot=(0, 0, 0), scl=(1, 1, 1)),
        _make_bone('hand', parent=0,    pos=(5, 0, 0), rot=(0, 0, 0), scl=(1, 1, 1)),
    ]
    # Mesh vertex in world-rest space at (5,0,0) — right at hand bone origin.
    mesh = _make_mesh(
        vertices=[(5.0, 0.0, 0.0)],
        bw=None,
        parent_bone_index=1,
    )
    model = _FakeModel(bones=bones, meshes=[mesh], anims=[])
    samples = compose_mod._build_skin_samples(model, SkinType)
    rest = compose_mod._rest_bone_world_matrices(model)
    mn, mx = compose_mod._compute_skinned_aabb(samples, rest)
    # local_rest = inv_bind[hand] @ (5,0,0,1) = (0,0,0) — the offset is baked in
    assert abs(mn[0] - 5.0) < 1e-6


# ----- test fixtures ------------------------------------------------


class _KF:
    def __init__(self, frame, value):
        self.frame = frame
        self.value = value


class _FakeBone:
    def __init__(self, name, parent, pos, rot, scl,
                 world_matrix=None, inverse_bind_matrix=None):
        self.name = name
        self.parent_index = parent
        self.position = pos
        self.rotation = rot
        self.scale = scl
        self.world_matrix = world_matrix
        self.inverse_bind_matrix = inverse_bind_matrix


def _make_bone(name, parent, pos, rot, scl):
    """Build a fake bone, computing rest world_matrix from SRT chain."""
    # Only supports translations-only hierarchies here (rot=0, scl=1).
    # Callers that need real rotations can pass world_matrix explicitly.
    wx = pos[0]
    wy = pos[1]
    wz = pos[2]
    # Parent offset resolution is left to the model-level helper below.
    world_matrix = [
        [1.0, 0.0, 0.0, wx],
        [0.0, 1.0, 0.0, wy],
        [0.0, 0.0, 1.0, wz],
        [0.0, 0.0, 0.0, 1.0],
    ]
    return _FakeBone(name, parent, pos, rot, scl, world_matrix=world_matrix)


class _IRBW:
    def __init__(self, type, assignments=None, bone_name=None):
        self.type = type
        self.assignments = assignments
        self.bone_name = bone_name


class _FakeMesh:
    def __init__(self, vertices, bone_weights, parent_bone_index):
        self.vertices = vertices
        self.bone_weights = bone_weights
        self.parent_bone_index = parent_bone_index
        self.local_matrix = None


def _make_mesh(vertices, bw, parent_bone_index):
    return _FakeMesh(vertices=vertices, bone_weights=bw, parent_bone_index=parent_bone_index)


class _Track:
    def __init__(self, bone_index, rotation, location, scale, end_frame):
        self.bone_index = bone_index
        self.rotation = rotation
        self.location = location
        self.scale = scale
        self.end_frame = end_frame


class _FakeModel:
    def __init__(self, bones, meshes=None, anims=None):
        self.bones = bones
        self.meshes = meshes or []
        self.bone_animations = anims or []

        # Resolve world_matrix using parent chain (translation-only).
        for i, b in enumerate(bones):
            if b.parent_index is not None and 0 <= b.parent_index < i:
                parent_wm = bones[b.parent_index].world_matrix
                tx = parent_wm[0][3] + b.position[0]
                ty = parent_wm[1][3] + b.position[1]
                tz = parent_wm[2][3] + b.position[2]
                b.world_matrix = [
                    [1.0, 0.0, 0.0, tx],
                    [0.0, 1.0, 0.0, ty],
                    [0.0, 0.0, 1.0, tz],
                    [0.0, 0.0, 0.0, 1.0],
                ]


class _FakeAnimSet:
    def __init__(self, tracks):
        self.tracks = tracks


class _NullLogger:
    def info(self, *a, **kw): pass
    def debug(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
