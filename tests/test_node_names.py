"""Authored node names: which node types carry one, and how the plugin
preserves them in both directions.

Every HSD object descriptor with a name (JObj, DObj, PObj, MObj, TObj,
CObj, LObj, WObj) opens with a class-name string pointer. The exporter
fills those slots from the Blender entity each node stands for — bone,
mesh object, material, image, camera, light, TRACK_TO target empty — and
the importer reads them back into the same Blender names when present.
PObjects have no Blender equivalent and stay unnamed. `strip_names`
clears every slot for byte comparisons against name-less game files.
"""
import io
from types import SimpleNamespace

from shared.IR.geometry import IRMesh
from shared.IR.material import IRMaterial, IRTextureLayer, IRImage
from shared.IR.camera import IRCamera
from shared.IR.lights import IRLight
from shared.IR.skeleton import IRBone
from shared.IR.enums import (
    ColorSource, LightingModel, CoordType, WrapMode, TextureInterpolation,
    LayerBlendMode, LightmapChannel, ScaleInheritance, CameraProjection,
    LightType,
)
from shared.BR.cameras import BRCamera
from shared.BR.lights import BRLight
from shared.Constants.gx import GX_VA_POS
from shared.Constants.hsd import LOBJ_SPOT, RENDER_DIFFUSE, RENDER_DIFFUSE_MAT
from shared.Nodes.Classes.Joints.Joint import Joint
from shared.Nodes.Classes.Material.MaterialObject import MaterialObject
from shared.helpers.logger import StubLogger

from exporter.phases.compose.compose import strip_node_names
from exporter.phases.compose.helpers.bones import compose_bones
from exporter.phases.compose.helpers.meshes import compose_meshes
from exporter.phases.compose.helpers.cameras import compose_camera
from exporter.phases.compose.helpers.lights import _compose_light
from exporter.phases.plan.helpers.cameras import plan_cameras
from exporter.phases.plan.helpers.lights import plan_lights

from importer.phases.parse.helpers.dat_parser import DATParser
from importer.phases.describe.helpers.bones import describe_bones
from importer.phases.describe.helpers.cameras import describe_camera
from importer.phases.describe.helpers.lights import describe_light
from importer.phases.describe.helpers.materials import describe_material
from importer.phases.describe.helpers.meshes import (
    _walk_mesh_chain, _pobj_name_hint,
)
from importer.phases.plan.helpers.meshes import _plan_mesh_name

from tests.helpers import (
    build_joint, build_dat_with_sections, build_material_object,
    build_material, JOINT_SIZE, MATERIALOBJECT_SIZE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _identity_4x4():
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def _make_bone(name, parent_index=None):
    return IRBone(
        name=name, parent_index=parent_index,
        position=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1),
        inverse_bind_matrix=None, flags=0, is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED, ik_shrink=False,
        world_matrix=_identity_4x4(), local_matrix=_identity_4x4(),
        normalized_world_matrix=_identity_4x4(),
        normalized_local_matrix=_identity_4x4(),
        scale_correction=_identity_4x4(), accumulated_scale=(1, 1, 1),
    )


def _make_image(name):
    return IRImage(name=name, width=2, height=2, pixels=bytes([255] * 16),
                   image_id=0, palette_id=0)


def _make_layer(image):
    return IRTextureLayer(
        image=image, coord_type=CoordType.UV, uv_index=0,
        rotation=(0, 0, 0), scale=(1, 1, 1), translation=(0, 0, 0),
        wrap_s=WrapMode.REPEAT, wrap_t=WrapMode.REPEAT, repeat_s=1, repeat_t=1,
        interpolation=TextureInterpolation.LINEAR,
        color_blend=LayerBlendMode.REPLACE, alpha_blend=LayerBlendMode.NONE,
        blend_factor=1.0, lightmap_channel=LightmapChannel.DIFFUSE, is_bump=False,
    )


def _make_material(name=None, texture_layers=()):
    return IRMaterial(
        diffuse_color=(1, 1, 1, 1), ambient_color=(0.1, 0.1, 0.1, 1),
        specular_color=(1, 1, 1, 1), alpha=1.0, shininess=50.0,
        color_source=ColorSource.MATERIAL, alpha_source=ColorSource.MATERIAL,
        lighting=LightingModel.LIT, enable_specular=False, is_translucent=False,
        texture_layers=list(texture_layers), name=name,
    )


def _make_mesh(name, material, parent_bone_index=0):
    return IRMesh(
        name=name, vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], faces=[[0, 1, 2]],
        material=material, parent_bone_index=parent_bone_index,
    )


def _make_camera(name="MainCam", target_name="MainCam_aim"):
    return IRCamera(
        name=name, projection=CameraProjection.PERSPECTIVE,
        position=(1.0, 2.0, 3.0), target_position=(0.0, 0.0, 0.0),
        target_name=target_name,
    )


def _make_light(name="KeyLight", target_name="KeyLight_aim"):
    return IRLight(
        name=name, type=LightType.SPOT, color=(1.0, 1.0, 1.0),
        position=(1.0, 2.0, 3.0), target_position=(0.0, 0.0, 0.0),
        target_name=target_name,
    )


def _compose_model(mesh_name="Body", material_name="Skin", image_name="skin_tex"):
    bones = [_make_bone("Hips")]
    _, joints = compose_bones(bones)
    material = _make_material(material_name, [_make_layer(_make_image(image_name))])
    compose_meshes([_make_mesh(mesh_name, material)], joints, bones)
    return joints


# ---------------------------------------------------------------------------
# Export: compose writes the Blender-side name into each node's name slot
# ---------------------------------------------------------------------------

class TestComposeWritesNames:

    def test_joint_name_is_bone_name(self):
        joints = _compose_model()
        assert joints[0].name == "Hips"

    def test_mesh_node_name_is_mesh_name(self):
        joints = _compose_model(mesh_name="Body")
        assert joints[0].property.name == "Body"

    def test_pobject_stays_unnamed(self):
        joints = _compose_model()
        assert joints[0].property.pobject.name is None

    def test_material_class_type_is_material_name(self):
        joints = _compose_model(material_name="Skin")
        assert joints[0].property.mobject.class_type == "Skin"

    def test_texture_name_is_image_name(self):
        joints = _compose_model(image_name="skin_tex")
        assert joints[0].property.mobject.texture.name == "skin_tex"

    def test_unnamed_material_leaves_slot_null(self):
        bones = [_make_bone("Hips")]
        _, joints = compose_bones(bones)
        compose_meshes([_make_mesh("Body", _make_material(None))], joints, bones)
        assert joints[0].property.mobject.class_type is None

    def test_camera_and_interest_names(self):
        camera_set = compose_camera(_make_camera())
        assert camera_set.camera.name == "MainCam"
        assert camera_set.camera.interest.name == "MainCam_aim"
        # The eye WObject stands for the camera itself; the CObj carries it.
        assert camera_set.camera.position.name is None

    def test_light_and_interest_names(self):
        light = _compose_light(_make_light(), StubLogger())
        assert light.name == "KeyLight"
        assert light.interest.name == "KeyLight_aim"
        assert light.position.name is None


class TestStripNodeNames:

    def test_clears_every_name_slot(self):
        joints = _compose_model()
        camera_set = compose_camera(_make_camera())
        light = _compose_light(_make_light(), StubLogger())

        cleared = strip_node_names([joints[0], camera_set, light])

        assert cleared == 8  # joint, mesh, mobj, texture, camera, interest, light, interest
        assert joints[0].name is None
        assert joints[0].property.name is None
        assert joints[0].property.mobject.class_type is None
        assert joints[0].property.mobject.texture.name is None
        assert camera_set.camera.name is None
        assert camera_set.camera.interest.name is None
        assert light.name is None
        assert light.interest.name is None

    def test_visits_shared_nodes_once(self):
        joints = _compose_model()
        # The same subtree reachable twice must not double-count.
        assert strip_node_names([joints[0], joints[0]]) == 4


# ---------------------------------------------------------------------------
# Export plan: BR target names ride through to the IR
# ---------------------------------------------------------------------------

class TestExportPlanTargetNames:

    def test_camera_target_name(self):
        br = BRCamera(name="Cam", projection="PERSP", lens=50.0, sensor_height=18.0,
                      clip_start=0.1, clip_end=100.0, aspect=1.333,
                      location=(0, 0, 0), target_location=(0, 1, 0),
                      target_name="Cam_aim")
        assert plan_cameras([br])[0].target_name == "Cam_aim"

    def test_light_target_name(self):
        br = BRLight(name="Spot", blender_type="SPOT", color=(1, 1, 1), energy=1.0,
                     location=(0, 0, 1), target_location=(0, 0, 0),
                     target_name="Spot_aim")
        assert plan_lights([br])[0].target_name == "Spot_aim"


# ---------------------------------------------------------------------------
# Import: describe reads authored names back
# ---------------------------------------------------------------------------

def _parse_joint_tree(data, relocations):
    dat_bytes = build_dat_with_sections(
        data, relocations, sections=[(0, True)], section_names=["test_joint"])
    parser = DATParser(io.BytesIO(dat_bytes), {"section_names": []})
    joint = Joint(0, None)
    joint.loadFromBinary(parser)
    parser.close()
    return joint


class TestDescribeBoneNames:

    def test_authored_joint_name_wins(self):
        string_offset = JOINT_SIZE
        data = build_joint(name_ptr=string_offset, scale=(1, 1, 1)) + b"Hips\0"
        bones, _ = describe_bones(_parse_joint_tree(data, relocations=[0]))
        assert bones[0].name == "Hips"

    def test_unnamed_joint_gets_generated_name(self):
        data = build_joint(scale=(1, 1, 1))
        bones, _ = describe_bones(_parse_joint_tree(data, relocations=[]))
        assert bones[0].name == "Bone_0"

    def test_duplicate_authored_name_falls_back_to_generated(self):
        # root (0) → child (64); both point at the same "Hips" string (128).
        string_offset = 2 * JOINT_SIZE
        data = (build_joint(name_ptr=string_offset, child_ptr=JOINT_SIZE, scale=(1, 1, 1))
                + build_joint(name_ptr=string_offset, scale=(1, 1, 1))
                + b"Hips\0")
        joint = _parse_joint_tree(data, relocations=[0, 8, JOINT_SIZE])
        bones, _ = describe_bones(joint)
        assert [b.name for b in bones] == ["Hips", "Bone_1"]


class TestDescribeMaterialName:

    def _parse_mobj(self, class_type):
        mat_offset = MATERIALOBJECT_SIZE
        string_offset = mat_offset + 20  # MATERIAL_SIZE
        data = (build_material_object(
                    class_type_ptr=string_offset if class_type else 0,
                    render_mode=RENDER_DIFFUSE | RENDER_DIFFUSE_MAT,
                    material_ptr=mat_offset)
                + build_material(diffuse=(255, 255, 255, 255), alpha=1.0))
        relocs = [12]
        if class_type:
            data += class_type.encode() + b"\0"
            relocs.insert(0, 0)
        dat_bytes = build_dat_with_sections(
            data, relocs, sections=[(0, True)], section_names=["mobj"])
        parser = DATParser(io.BytesIO(dat_bytes), {})
        mobj = MaterialObject(0, None)
        mobj.loadFromBinary(parser)
        return mobj

    def test_class_type_becomes_material_name(self):
        assert describe_material(self._parse_mobj("Skin")).name == "Skin"

    def test_missing_class_type_is_none(self):
        assert describe_material(self._parse_mobj(None)).name is None


class TestDescribeCameraAndLightNames:

    def test_camera_name_and_target_name(self):
        node = SimpleNamespace(
            name="MainCam", flags=0, perspective_flags=1,
            position=SimpleNamespace(position=(0, 0, 10), name=None),
            interest=SimpleNamespace(position=(0, 0, 0), name="MainCam_aim"),
            roll=0.0, near=0.1, far=100.0, field_of_view=27.0, aspect=1.33,
        )
        ir = describe_camera(node, camera_index=3)
        assert ir.name == "MainCam"
        assert ir.target_name == "MainCam_aim"

    def test_unnamed_camera_uses_index(self):
        node = SimpleNamespace(
            name=None, flags=0, perspective_flags=1, position=None, interest=None,
            roll=0.0, near=0.1, far=100.0, field_of_view=27.0, aspect=1.33,
        )
        ir = describe_camera(node, camera_index=3)
        assert ir.name == "Camera_3"
        assert ir.target_name is None

    def test_light_name_and_target_name(self):
        node = SimpleNamespace(
            flags=LOBJ_SPOT, name="KeyLight", color=None,
            position=SimpleNamespace(position=(0, 0, 10)),
            interest=SimpleNamespace(position=(0, 0, 0), name="KeyLight_aim"),
        )
        ir = describe_light(node, light_index=2)
        assert ir.name == "KeyLight"
        assert ir.target_name == "KeyLight_aim"

    def test_unnamed_light_uses_index(self):
        node = SimpleNamespace(flags=LOBJ_SPOT, name=None, color=None,
                               position=None, interest=None)
        ir = describe_light(node, light_index=2)
        assert ir.name == "Light_2"
        assert ir.target_name is None


def _make_pobj(address, name=None):
    ns = SimpleNamespace(
        address=address, name=name,
        vertex_list=SimpleNamespace(vertices=[
            SimpleNamespace(attribute=GX_VA_POS, isTexture=lambda: False),
        ]),
        flags=0, sources=[[(0, 0, 0), (1, 0, 0), (0, 1, 0)]],
        face_lists=[[[0, 1, 2]]], property=None, next=None,
    )
    ns.find_attribute_index = lambda attr: next(
        (i for i, v in enumerate(ns.vertex_list.vertices) if v.attribute == attr), None)
    ns.pobj_type_flag = lambda: 0
    return ns


def _walk(mesh_node):
    bone = SimpleNamespace(
        name="bone", flags=0, world_matrix=_identity_4x4(), inverse_bind_matrix=None,
        parent_index=None, mesh_indices=[], instance_child_bone_index=None,
    )
    meshes = []
    _walk_mesh_chain(
        mesh_node, SimpleNamespace(address=0, flags=0), bone_index=0,
        bones=[bone], joint_to_bone_index={0: 0}, options={}, image_cache={},
        logger=StubLogger(), meshes=meshes, material_cache={},
    )
    return [m.name for m in meshes]


class TestDescribeMeshNames:

    def test_dobject_name_names_its_pobjects(self):
        first = _make_pobj(200)
        first.next = _make_pobj(300)
        node = SimpleNamespace(address=50, name="Body", mobject=None,
                               pobject=first, next=None)
        assert _walk(node) == ["Body", "Body_1"]

    def test_pobject_name_takes_precedence(self):
        node = SimpleNamespace(address=50, name="Body", mobject=None,
                               pobject=_make_pobj(200, name="prim"), next=None)
        assert _walk(node) == ["prim"]

    def test_unnamed_falls_back_to_ordinal(self):
        node = SimpleNamespace(address=50, name=None, mobject=None,
                               pobject=_make_pobj(200), next=None)
        assert _walk(node) == ["0"]

    def test_name_hint_helper(self):
        assert _pobj_name_hint(None, 0) is None
        assert _pobj_name_hint("Body", 0) == "Body"
        assert _pobj_name_hint("Body", 2) == "Body_2"


class TestImportPlanMeshName:

    def test_authored_name_is_used_verbatim(self):
        assert _plan_mesh_name("juptile", "Body") == "Body"

    def test_ordinal_is_prefixed_with_model(self):
        assert _plan_mesh_name("juptile", "03") == "juptile_mesh_03"
