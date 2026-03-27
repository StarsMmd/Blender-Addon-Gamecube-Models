"""Tests for Intermediate Representation dataclass instantiation and enum values."""
import math
from shared.IR import (
    # Scene
    IRScene,
    # Skeleton
    IRModel, IRBone,
    # Geometry
    IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights, IRShapeKey,
    # Material
    IRMaterial, IRTextureLayer, IRImage,
    CombinerInput, CombinerStage, ColorCombiner, FragmentBlending,
    # Animation
    IRKeyframe, IRSplinePath, IRBoneAnimationSet, IRBoneTrack,
    IRMaterialTrack, IRTextureUVTrack,
    IRShapeAnimationSet, IRShapeTrack,
    # Constraints
    IRIKConstraint, IRBoneReposition, IRCopyLocationConstraint,
    IRTrackToConstraint, IRCopyRotationConstraint, IRLimitConstraint,
    # Lights / Camera / Fog
    IRLight, IRCamera, IRFog,
    # Enums
    CoordType, WrapMode, Interpolation, TextureInterpolation,
    LightType, SkinType, ScaleInheritance,
    ColorSource, LightingModel, LayerBlendMode, LightmapChannel,
    CombinerInputSource, CombinerOp, CombinerBias, CombinerScale,
    OutputBlendEffect, BlendFactor,
)

IDENTITY_4X4 = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


# --- Enum tests ---

def test_coord_type_values():
    assert CoordType.UV.value == "UV"
    assert CoordType.REFLECTION.value == "REFLECTION"
    assert len(CoordType) == 6


def test_skin_type_values():
    assert SkinType.WEIGHTED.value == "WEIGHTED"
    assert SkinType.SINGLE_BONE.value == "SINGLE_BONE"
    assert SkinType.RIGID.value == "RIGID"


def test_interpolation_values():
    assert Interpolation.CONSTANT.value == "CONSTANT"
    assert Interpolation.LINEAR.value == "LINEAR"
    assert Interpolation.BEZIER.value == "BEZIER"


def test_light_type_values():
    assert LightType.SUN.value == "SUN"
    assert LightType.POINT.value == "POINT"
    assert LightType.SPOT.value == "SPOT"


def test_layer_blend_mode_values():
    assert LayerBlendMode.NONE.value == "NONE"
    assert LayerBlendMode.MULTIPLY.value == "MULTIPLY"
    assert len(LayerBlendMode) == 9


def test_output_blend_effect_values():
    assert OutputBlendEffect.OPAQUE.value == "OPAQUE"
    assert OutputBlendEffect.CUSTOM.value == "CUSTOM"
    assert len(OutputBlendEffect) == 14


def test_combiner_op_values():
    assert CombinerOp.ADD.value == "ADD"
    assert CombinerOp.SUBTRACT.value == "SUBTRACT"
    assert len(CombinerOp) == 10


# --- Dataclass instantiation tests ---

def test_ir_scene_empty():
    scene = IRScene()
    assert scene.models == []
    assert scene.lights == []
    assert scene.cameras == []
    assert scene.fogs == []


def test_ir_bone():
    bone = IRBone(
        name="root",
        parent_index=None,
        position=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        inverse_bind_matrix=None,
        flags=0,
        is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED,
        ik_shrink=False,
        world_matrix=IDENTITY_4X4,
        local_matrix=IDENTITY_4X4,
        normalized_world_matrix=IDENTITY_4X4,
        normalized_local_matrix=IDENTITY_4X4,
        scale_correction=IDENTITY_4X4,
        accumulated_scale=(1.0, 1.0, 1.0),
    )
    assert bone.name == "root"
    assert bone.parent_index is None
    assert bone.mesh_indices == []
    assert bone.instance_child_bone_index is None


def test_ir_model():
    model = IRModel(name="test_model")
    assert model.name == "test_model"
    assert model.bones == []
    assert model.meshes == []
    assert model.bone_animations == []
    assert model.limit_location_constraints == []


def test_ir_mesh():
    mesh = IRMesh(
        name="mesh_0",
        vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
        faces=[[0, 1, 2]],
    )
    assert len(mesh.vertices) == 3
    assert len(mesh.faces) == 1
    assert mesh.uv_layers == []
    assert mesh.normals is None
    assert mesh.bone_weights is None
    assert mesh.is_hidden is False


def test_ir_uv_layer():
    uv = IRUVLayer(name="uvtex_0", uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
    assert uv.name == "uvtex_0"
    assert len(uv.uvs) == 3


def test_ir_color_layer():
    cl = IRColorLayer(name="color_0", colors=[(1, 0, 0, 1), (0, 1, 0, 1)])
    assert len(cl.colors) == 2


def test_ir_bone_weights_weighted():
    bw = IRBoneWeights(
        type=SkinType.WEIGHTED,
        assignments=[(0, [("bone_a", 0.5), ("bone_b", 0.5)])],
    )
    assert bw.type == SkinType.WEIGHTED
    assert len(bw.assignments) == 1


def test_ir_bone_weights_rigid():
    bw = IRBoneWeights(type=SkinType.RIGID, bone_name="root")
    assert bw.type == SkinType.RIGID
    assert bw.bone_name == "root"
    assert bw.assignments is None


def test_ir_shape_key():
    sk = IRShapeKey(name="Key_1", vertex_positions=[(0, 0, 0), (1, 1, 1)])
    assert len(sk.vertex_positions) == 2


def test_ir_material():
    mat = IRMaterial(
        diffuse_color=(0.8, 0.2, 0.1, 1.0),
        ambient_color=(0.1, 0.1, 0.1, 1.0),
        specular_color=(1.0, 1.0, 1.0, 1.0),
        alpha=1.0,
        shininess=30.0,
        color_source=ColorSource.MATERIAL,
        alpha_source=ColorSource.MATERIAL,
        lighting=LightingModel.LIT,
        enable_specular=True,
        is_translucent=False,
    )
    assert mat.alpha == 1.0
    assert mat.texture_layers == []
    assert mat.fragment_blending is None


def test_ir_image():
    img = IRImage(
        name="tex_0",
        width=2, height=2,
        pixels=bytes([255] * 16),
        image_id=0, palette_id=0,
    )
    assert img.width == 2
    assert len(img.pixels) == 16


def test_ir_texture_layer():
    img = IRImage(name="t", width=1, height=1, pixels=bytes([255, 255, 255, 255]), image_id=0, palette_id=0)
    layer = IRTextureLayer(
        image=img,
        coord_type=CoordType.UV,
        uv_index=0,
        rotation=(0, 0, 0),
        scale=(1, 1, 1),
        translation=(0, 0, 0),
        wrap_s=WrapMode.REPEAT,
        wrap_t=WrapMode.REPEAT,
        repeat_s=1, repeat_t=1,
        interpolation=TextureInterpolation.LINEAR,
        color_blend=LayerBlendMode.REPLACE,
        alpha_blend=LayerBlendMode.REPLACE,
        blend_factor=1.0,
        lightmap_channel=LightmapChannel.NONE,
        is_bump=False,
    )
    assert layer.coord_type == CoordType.UV
    assert layer.combiner is None


def test_combiner_stage():
    inp = CombinerInput(source=CombinerInputSource.ZERO)
    stage = CombinerStage(
        input_a=inp, input_b=inp, input_c=inp, input_d=inp,
        operation=CombinerOp.ADD,
        bias=CombinerBias.ZERO,
        scale=CombinerScale.SCALE_1,
        clamp=True,
    )
    assert stage.clamp is True


def test_fragment_blending():
    fb = FragmentBlending(
        effect=OutputBlendEffect.ALPHA_BLEND,
        source_factor=BlendFactor.SRC_ALPHA,
        dest_factor=BlendFactor.INV_SRC_ALPHA,
        alpha_test_threshold_0=0,
        alpha_test_threshold_1=255,
        alpha_test_op=0,
        depth_compare=0,
    )
    assert fb.effect == OutputBlendEffect.ALPHA_BLEND


def test_ir_keyframe():
    kf = IRKeyframe(frame=0.0, value=1.5, interpolation=Interpolation.LINEAR)
    assert kf.frame == 0.0
    assert kf.handle_left is None


def test_ir_spline_path():
    path = IRSplinePath(
        control_points=[[0, 0, 0], [1, 0, 0], [2, 0, 0]],
        parameter_keyframes=[IRKeyframe(frame=0, value=0, interpolation=Interpolation.LINEAR)],
        curve_type=2,
        num_control_points=3,
    )
    assert len(path.control_points) == 3
    assert path.curve_type == 2
    assert path.tension == 0.0
    assert path.world_matrix is None


def test_ir_bone_track():
    track = IRBoneTrack(
        bone_name="bone_0",
        bone_index=0,
        rotation=[[], [], []],
        location=[[], [], []],
        scale=[[], [], []],
    )
    assert track.bone_name == "bone_0"
    assert len(track.rotation) == 3
    assert track.spline_path is None


def test_ir_bone_animation_set():
    anim = IRBoneAnimationSet(name="walk")
    assert anim.tracks == []
    assert anim.material_tracks == []
    assert anim.loop is False
    assert anim.is_static is False


def test_ir_bone_animation_set_with_material_tracks():
    mat_track = IRMaterialTrack(material_mesh_name="mesh_0_Bone")
    anim = IRBoneAnimationSet(name="Test_Anim_00", material_tracks=[mat_track])
    assert len(anim.material_tracks) == 1
    assert anim.material_tracks[0].material_mesh_name == "mesh_0_Bone"


def test_ir_material_track():
    track = IRMaterialTrack(material_mesh_name="mesh_0_mat")
    assert track.diffuse_r is None
    assert track.texture_uv_tracks == []


def test_ir_texture_uv_track():
    track = IRTextureUVTrack(texture_index=0)
    assert track.translation_u is None


def test_ir_shape_track():
    track = IRShapeTrack(bone_name="bone_0")
    assert track.keyframes == []


def test_ir_shape_animation_set():
    anim = IRShapeAnimationSet(name="morph_0")
    assert anim.tracks == []


def test_ir_ik_constraint():
    c = IRIKConstraint(bone_name="hand", chain_length=3)
    assert c.target_bone is None
    assert c.bone_repositions == []


def test_ir_bone_reposition():
    r = IRBoneReposition(bone_name="arm", bone_length=5.0)
    assert r.bone_length == 5.0


def test_ir_copy_location_constraint():
    c = IRCopyLocationConstraint(bone_name="a", target_bone="b")
    assert c.influence == 1.0


def test_ir_track_to_constraint():
    c = IRTrackToConstraint(bone_name="eye", target_bone="target")
    assert c.track_axis == "TRACK_X"


def test_ir_copy_rotation_constraint():
    c = IRCopyRotationConstraint(bone_name="a", target_bone="b")
    assert c.owner_space == "WORLD"


def test_ir_limit_constraint():
    c = IRLimitConstraint(bone_name="arm", min_x=-1.0, max_x=1.0)
    assert c.min_y is None


def test_ir_light():
    light = IRLight(name="sun_0", type=LightType.SUN, color=(1.0, 1.0, 1.0))
    assert light.position is None
    assert light.target_position is None


def test_ir_camera_stub():
    cam = IRCamera(name="cam_0")
    assert cam.name == "cam_0"


def test_ir_fog_stub():
    fog = IRFog(name="fog_0")
    assert fog.name == "fog_0"


def test_ir_scene_with_data():
    model = IRModel(name="model_0")
    light = IRLight(name="sun", type=LightType.SUN, color=(1, 1, 1))
    scene = IRScene(models=[model], lights=[light])
    assert len(scene.models) == 1
    assert len(scene.lights) == 1
