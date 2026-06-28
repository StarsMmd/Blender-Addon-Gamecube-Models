"""Unit tests for node-declared serialization orderings.

These exercise the pure ``serializationOrder`` hooks (no bpy, no binary) that
reproduce Sysdolphin's struct-emission order:

* ``MaterialAnimationJoint`` — texture animations emit in *reverse* material-
  animation order while each MA's own ``texture_animation`` chain stays forward.
* ``SceneData`` — the scene tail emits leaves (light WObject+Light, then camera
  WObjects+Camera) before containers (ModelSets, CameraSet, LightSets), with the
  light leaves and LightSets in reverse LightSet-index order, SceneData last.
"""
import io

from shared.Nodes.Classes.Material.MaterialAnimationJoint import MaterialAnimationJoint
from shared.Nodes.Classes.Material.MaterialAnimation import MaterialAnimation
from shared.Nodes.Classes.Material.MaterialObject import MaterialObject
from shared.Nodes.Classes.Texture.Texture import Texture
from shared.Nodes.Classes.Texture.TextureAnimation import TextureAnimation
from shared.Nodes.Classes.Animation.Animation import Animation
from shared.Nodes.Classes.Animation.Frame import Frame
from shared.Nodes.Classes.RootNodes.SceneData import SceneData
from shared.Nodes.Classes.Light.LightSet import LightSet
from shared.Nodes.Classes.Light.Light import Light
from shared.Nodes.Classes.Camera.CameraSet import CameraSet
from shared.Nodes.Classes.Camera.Camera import Camera
from shared.Nodes.Classes.Rendering.WObject import WObject
from shared.Nodes.Classes.Joints.ModelSet import ModelSet


def _anim(tag):
    """An Animation with a single Frame, both tagged for identification."""
    frame = Frame(None, None)
    frame.tag = tag + ':frame'
    anim = Animation(None, None)
    anim.tag = tag + ':anim'
    anim.frame = frame
    return anim


def _texanim(tag):
    ta = TextureAnimation(None, None)
    ta.tag = tag
    ta.animation = _anim(tag)
    return ta


def _matanim(texanims):
    ma = MaterialAnimation(None, None)
    head = None
    for ta in reversed(texanims):
        ta.next = head
        head = ta
    ma.texture_animation = head
    return ma


def _chain_mas(mas):
    """Link a list of MaterialAnimations via .next and return the head."""
    for a, b in zip(mas, mas[1:]):
        a.next = b
    return mas[0] if mas else None


def _tags(nodes, kind):
    return [n.tag for n in nodes if isinstance(n, kind) and getattr(n, 'tag', None)]


# --- MaterialAnimationJoint -------------------------------------------------

def test_texture_animations_emit_in_reverse_ma_order():
    """Two MAs on one joint, each with one texture animation: the later MA's
    texture animation precedes the earlier MA's (reverse MA order)."""
    ma0 = _matanim([_texanim('ma0_ta')])
    ma1 = _matanim([_texanim('ma1_ta')])
    joint = MaterialAnimationJoint(None, None)
    joint.animation = _chain_mas([ma0, ma1])

    order = joint.serializationOrder()
    assert _tags(order, TextureAnimation) == ['ma1_ta', 'ma0_ta']


def test_texture_chain_within_one_ma_stays_forward():
    """A single MA whose texture_animation is a 2-element chain keeps the chain
    in forward order."""
    ma = _matanim([_texanim('taA'), _texanim('taB')])
    joint = MaterialAnimationJoint(None, None)
    joint.animation = ma

    order = joint.serializationOrder()
    assert _tags(order, TextureAnimation) == ['taA', 'taB']


def test_texture_reverse_ma_keeps_chains_internally_forward():
    """Reverse MA order across MAs, forward within each MA's chain."""
    ma0 = _matanim([_texanim('ma0_a'), _texanim('ma0_b')])
    ma1 = _matanim([_texanim('ma1_a'), _texanim('ma1_b')])
    joint = MaterialAnimationJoint(None, None)
    joint.animation = _chain_mas([ma0, ma1])

    order = joint.serializationOrder()
    assert _tags(order, TextureAnimation) == ['ma1_a', 'ma1_b', 'ma0_a', 'ma0_b']


def test_data_band_precedes_structs():
    """All keyframe data (Frames + Animations) precede the TextureAnimation and
    MaterialAnimation structs in the emitted order."""
    ma = _matanim([_texanim('ta')])
    joint = MaterialAnimationJoint(None, None)
    joint.animation = ma

    order = joint.serializationOrder()
    last_data = max(i for i, n in enumerate(order) if isinstance(n, (Frame, Animation)))
    first_struct = min(i for i, n in enumerate(order)
                       if isinstance(n, (TextureAnimation, MaterialAnimation)))
    assert last_data < first_struct


# --- MaterialObject texture chain (DFS reversal) ----------------------------

def _texture(name):
    tex = Texture(None, None)
    tex.name = name
    return tex


def test_material_texture_chain_emits_reversed():
    """A MaterialObject's texture.next chain lands in node_list deepest-first
    (head last); each texture still precedes nothing of its own beyond itself."""
    from exporter.phases.serialize.helpers.dat_builder import DATBuilder

    t0 = _texture('t0'); t1 = _texture('t1'); t2 = _texture('t2')
    t0.next = t1; t1.next = t2
    mobj = MaterialObject(None, None)
    mobj.texture = t0

    node_list = DATBuilder(io.BytesIO(), [mobj], ['m']).node_list
    tex_names = [n.name for n in node_list if isinstance(n, Texture)]
    assert tex_names == ['t2', 't1', 't0']
    # MaterialObject itself is written after all of its textures
    assert node_list.index(mobj) > max(node_list.index(t) for t in (t0, t1, t2))


def test_material_single_texture_unchanged():
    """A single-texture material is unaffected by the reversal."""
    from exporter.phases.serialize.helpers.dat_builder import DATBuilder

    t0 = _texture('only')
    mobj = MaterialObject(None, None)
    mobj.texture = t0

    node_list = DATBuilder(io.BytesIO(), [mobj], ['m']).node_list
    assert [n.name for n in node_list if isinstance(n, Texture)] == ['only']
    assert node_list.index(t0) < node_list.index(mobj)


# --- SceneData --------------------------------------------------------------

def _light_set(tag):
    light = Light(None, None)
    light.tag = tag + ':light'
    pos = WObject(None, None)
    pos.tag = tag + ':pos'
    light.position = pos
    ls = LightSet(None, None)
    ls.tag = tag + ':set'
    ls.light = light
    return ls


def test_scene_tail_order():
    ls0 = _light_set('L0')
    ls1 = _light_set('L1')

    cam = Camera(None, None)
    cam.tag = 'cam'
    cam.position = WObject(None, None); cam.position.tag = 'cam_pos'
    cam.interest = WObject(None, None); cam.interest.tag = 'cam_int'
    cam_set = CameraSet(None, None); cam_set.tag = 'camset'
    cam_set.camera = cam

    model_set = ModelSet(None, None); model_set.tag = 'model0'

    scene = SceneData(None, None)
    scene.models = [model_set]
    scene.camera = cam_set
    scene.lights = [ls0, ls1]
    scene.fog = 0

    order = scene.serializationOrder()
    tags = [getattr(n, 'tag', type(n).__name__) for n in order]
    assert tags == [
        # 1. light leaves, reverse LightSet-index order (WObject then Light)
        'L1:pos', 'L1:light', 'L0:pos', 'L0:light',
        # 2. camera leaves
        'cam_pos', 'cam_int', 'cam',
        # 3. containers: ModelSets, CameraSet, LightSets (reverse index)
        'model0', 'camset', 'L1:set', 'L0:set',
        # 4. SceneData itself (no tag -> falls back to type name)
        'SceneData',
    ]
    assert order[-1] is scene


def test_scene_handles_missing_camera_and_lights():
    """SceneData with no camera or lights still emits ModelSet then itself."""
    model_set = ModelSet(None, None); model_set.tag = 'm'
    scene = SceneData(None, None)
    scene.models = [model_set]
    scene.camera = 0
    scene.lights = 0
    scene.fog = 0

    order = scene.serializationOrder()
    assert order[0] is model_set
    assert order[-1] is scene
