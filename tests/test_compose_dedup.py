"""Tests for material/image dedup in the export pipeline.

When a Blender model has one material reused across multiple mesh objects
(e.g. after splitting a single mesh by loose parts), the exporter must
collapse the MObject/TObject/Image subtree so it is serialized only once.
Otherwise file size grows linearly with the number of parts.

Dedup happens in two places:
  - describe_blender: cache keyed on id(blender_mat) / id(bpy_image)
  - compose: cache keyed on id(ir_material), reused across DObjects

These tests exercise the compose-side behavior directly with hand-built
IRMesh inputs — the describe-side cache is covered by integration round-trips.
"""
from shared.IR.geometry import IRMesh
from shared.IR.material import IRMaterial, IRTextureLayer, IRImage
from shared.IR.enums import (
    ColorSource, LightingModel, CoordType, WrapMode,
    TextureInterpolation, LayerBlendMode, LightmapChannel,
)
from shared.IR.skeleton import IRBone
from shared.IR.enums import ScaleInheritance
from exporter.phases.compose.helpers.bones import compose_bones
from exporter.phases.compose.helpers.meshes import compose_meshes


def _identity_4x4():
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def _make_bone(name, parent_index=None):
    return IRBone(
        name=name,
        parent_index=parent_index,
        position=(0, 0, 0),
        rotation=(0, 0, 0),
        scale=(1, 1, 1),
        inverse_bind_matrix=None,
        flags=0,
        is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED,
        ik_shrink=False,
        world_matrix=_identity_4x4(),
        local_matrix=_identity_4x4(),
        normalized_world_matrix=_identity_4x4(),
        normalized_local_matrix=_identity_4x4(),
        scale_correction=_identity_4x4(),
        accumulated_scale=(1, 1, 1),
    )


def _make_material(texture_layers=()):
    return IRMaterial(
        diffuse_color=(1, 1, 1, 1),
        ambient_color=(0.1, 0.1, 0.1, 1),
        specular_color=(1, 1, 1, 1),
        alpha=1.0,
        shininess=50.0,
        color_source=ColorSource.MATERIAL,
        alpha_source=ColorSource.MATERIAL,
        lighting=LightingModel.LIT,
        enable_specular=False,
        is_translucent=False,
        texture_layers=list(texture_layers),
    )


def _make_texture_layer(ir_image):
    return IRTextureLayer(
        image=ir_image,
        coord_type=CoordType.UV,
        uv_index=0,
        rotation=(0, 0, 0),
        scale=(1, 1, 1),
        translation=(0, 0, 0),
        wrap_s=WrapMode.REPEAT,
        wrap_t=WrapMode.REPEAT,
        repeat_s=1,
        repeat_t=1,
        interpolation=TextureInterpolation.LINEAR,
        color_blend=LayerBlendMode.REPLACE,
        alpha_blend=LayerBlendMode.NONE,
        blend_factor=1.0,
        lightmap_channel=LightmapChannel.DIFFUSE,
        is_bump=False,
    )


def _make_mesh(name, material, parent_bone_index):
    return IRMesh(
        name=name,
        vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
        faces=[[0, 1, 2]],
        uv_layers=[],
        color_layers=[],
        normals=None,
        material=material,
        bone_weights=None,
        is_hidden=False,
        parent_bone_index=parent_bone_index,
        cull_back=False,
    )


class TestComposeMaterialDedup:
    def test_same_material_on_different_bones_shares_mobject(self):
        # Two meshes on different bones, sharing one IRMaterial instance —
        # without dedup each would get its own MObject tree.
        bones = [_make_bone("root"), _make_bone("child", parent_index=0)]
        _, joints = compose_bones(bones)

        mat = _make_material()
        meshes = [
            _make_mesh("m0", mat, parent_bone_index=0),
            _make_mesh("m1", mat, parent_bone_index=1),
        ]

        compose_meshes(meshes, joints, bones)

        mobj_a = joints[0].property.mobject
        mobj_b = joints[1].property.mobject
        assert mobj_a is not None
        assert mobj_a is mobj_b, "same IRMaterial should yield one shared MObject"

    def test_different_materials_produce_distinct_mobjects(self):
        bones = [_make_bone("root"), _make_bone("child", parent_index=0)]
        _, joints = compose_bones(bones)

        meshes = [
            _make_mesh("m0", _make_material(), parent_bone_index=0),
            _make_mesh("m1", _make_material(), parent_bone_index=1),
        ]

        compose_meshes(meshes, joints, bones)

        assert joints[0].property.mobject is not joints[1].property.mobject

    def test_shared_material_shares_texture_and_image_subtree(self):
        # IRMaterial with a texture → MObject.texture.image is the serialized
        # Image node. Sharing the MObject must also share Image and its pixels.
        bones = [_make_bone("root"), _make_bone("child", parent_index=0)]
        _, joints = compose_bones(bones)

        img = IRImage(name="tex", width=2, height=2,
                      pixels=bytes([255] * 16),
                      image_id=0, palette_id=0)
        mat = _make_material(texture_layers=[_make_texture_layer(img)])
        meshes = [
            _make_mesh("m0", mat, parent_bone_index=0),
            _make_mesh("m1", mat, parent_bone_index=1),
        ]

        compose_meshes(meshes, joints, bones)

        tex_a = joints[0].property.mobject.texture
        tex_b = joints[1].property.mobject.texture
        assert tex_a is tex_b
        assert tex_a.image is tex_b.image
