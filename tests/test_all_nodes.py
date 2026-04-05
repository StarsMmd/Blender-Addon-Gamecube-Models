"""Comprehensive node parsing tests: every node type with binary round-trip verification."""
import io
import struct
import pytest

from helpers import *
from importer.phases.parse.helpers.dat_parser import DATParser
from shared.helpers.logger import Logger

# -- Node class imports (grouped by category) --

# Animation
from shared.Nodes.Classes.Animation.Animation import Animation
from shared.Nodes.Classes.Animation.AnimationJoint import AnimationJoint
from shared.Nodes.Classes.Animation.AnimationReference import AnimationReference
from shared.Nodes.Classes.Animation.Frame import Frame

# Camera
from shared.Nodes.Classes.Camera.Camera import Camera
from shared.Nodes.Classes.Camera.CameraAnimation import CameraAnimation
from shared.Nodes.Classes.Camera.CameraSet import CameraSet
from shared.Nodes.Classes.Camera.Viewport import Viewport

# Colors
from shared.Nodes.Classes.Colors.RGBAColor import (
    RGBAColor, RGB565Color, RGB5A3Color, RGB8Color, RGBX8Color,
    RGBA4Color, RGBA6Color, I8Color, IA4Color, IA8Color,
)

# Fog
from shared.Nodes.Classes.Fog.Fog import Fog
from shared.Nodes.Classes.Fog.FogAdj import FogAdj

# Joints
from shared.Nodes.Classes.Joints.Joint import Joint
from shared.Nodes.Classes.Joints.BoneReference import BoneReference
from shared.Nodes.Classes.Joints.Reference import Reference
from shared.Nodes.Classes.Joints.Envelope import EnvelopeList, Envelope

# Light
from shared.Nodes.Classes.Light.Light import Light
from shared.Nodes.Classes.Light.PointLight import PointLight
from shared.Nodes.Classes.Light.SpotLight import SpotLight
from shared.Nodes.Classes.Light.Attn import Attn
from shared.Nodes.Classes.Light.LightAnimation import LightAnimation
from shared.Nodes.Classes.Light.LightSet import LightSet

# Material
from shared.Nodes.Classes.Material.Material import Material
from shared.Nodes.Classes.Material.MaterialObject import MaterialObject
from shared.Nodes.Classes.Material.MaterialAnimation import MaterialAnimation
from shared.Nodes.Classes.Material.MaterialAnimationJoint import MaterialAnimationJoint

# Mesh
from shared.Nodes.Classes.Mesh.Mesh import Mesh
from shared.Nodes.Classes.Mesh.PObject import PObject
from shared.Nodes.Classes.Mesh.Vertex import Vertex
from shared.Nodes.Classes.Mesh.VertexList import VertexList

# Misc
from shared.Nodes.Classes.Misc.Spline import Spline
from shared.Nodes.Classes.Misc.SList import SList

# Rendering
from shared.Nodes.Classes.Rendering.Particle import Particle
from shared.Nodes.Classes.Rendering.PixelEngine import PixelEngine
from shared.Nodes.Classes.Rendering.Render import Render
from shared.Nodes.Classes.Rendering.RenderAnimation import RenderAnimation
from shared.Nodes.Classes.Rendering.WObject import WObject
from shared.Nodes.Classes.Rendering.WObjectAnimation import WObjectAnimation

# RootNodes
from shared.Nodes.Classes.RootNodes.SceneData import SceneData
from shared.Nodes.Classes.RootNodes.BoundBox import BoundBox

# Shape
from shared.Nodes.Classes.Shape.ShapeAnimation import ShapeAnimation
from shared.Nodes.Classes.Shape.ShapeAnimationJoint import ShapeAnimationJoint
from shared.Nodes.Classes.Shape.ShapeAnimationMesh import ShapeAnimationMesh
from shared.Nodes.Classes.Shape.ShapeIndexTri import ShapeIndexTri

# Texture
from shared.Nodes.Classes.Texture.Texture import Texture
from shared.Nodes.Classes.Texture.Image import Image
from shared.Nodes.Classes.Texture.Palette import Palette
from shared.Nodes.Classes.Texture.TextureLOD import TextureLOD
from shared.Nodes.Classes.Texture.TextureTEV import TextureTEV
from shared.Nodes.Classes.Texture.TextureAnimation import TextureAnimation

# HSD constants
from shared.Constants.hsd import *


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(node_cls, address, data_section: bytes):
    dat_bytes = build_minimal_dat(data_section)
    parser = DATParser(io.BytesIO(dat_bytes), {})
    node = node_cls(address, None)
    node.loadFromBinary(parser)
    parser.close()
    return node


# ===========================================================================
# Animation/
# ===========================================================================

class TestAnimationNode:

    def test_animation_solo(self):
        data = build_animation()
        node = _parse(Animation, 0, data)
        assert node.flags == 0
        assert node.end_frame == 0.0
        assert node.frame is None
        assert node.joint is None

    def test_animation_with_values(self):
        data = build_animation(flags=0x40, end_frame=120.0)
        node = _parse(Animation, 0, data)
        assert node.flags == 0x40
        assert abs(node.end_frame - 120.0) < 1e-5

    def test_animation_with_frame_child(self):
        frame_offset = ANIMATION_SIZE
        data = build_animation(frame_ptr=frame_offset) + build_frame()
        node = _parse(Animation, 0, data)
        assert isinstance(node.frame, Frame)


class TestFrameNode:

    def test_frame_solo_no_data(self):
        data = build_frame()
        node = _parse(Frame, 0, data)
        assert node.data_length == 0
        assert node.raw_ad == b''

    def test_frame_with_ad_data(self):
        """Frame with ad pointer to a small animation data buffer."""
        ad_offset = FRAME_SIZE
        ad_bytes = bytes([0x20, 0x01, 0x00, 0x3F, 0x80, 0x00, 0x00, 0x00])
        data = build_frame(
            data_length=len(ad_bytes),
            start_frame=0.0,
            ftype=5,
            frac_value=0x20,
            frac_slope=0x20,
            ad_ptr=ad_offset,
        ) + ad_bytes
        node = _parse(Frame, 0, data)
        assert node.data_length == len(ad_bytes)
        assert node.type == 5
        assert len(node.raw_ad) == len(ad_bytes)
        assert node.raw_ad == ad_bytes

    def test_frame_with_next(self):
        data = build_frame(next_ptr=FRAME_SIZE) + build_frame()
        node = _parse(Frame, 0, data)
        assert isinstance(node.next, Frame)


class TestAnimationReferenceNode:

    def test_animation_reference_solo(self):
        """AnimationReference has no fields — should parse without error."""
        data = b'\x00' * 4  # pad to avoid truncated file
        node = _parse(AnimationReference, 0, data)
        assert node is not None


# ===========================================================================
# Camera/
# ===========================================================================

class TestCameraNode:

    def test_camera_solo(self):
        data = build_camera()
        node = _parse(Camera, 0, data)
        assert node.name is None
        assert node.flags == 0
        assert node.roll == 0.0
        assert node.position is None

    def test_camera_with_values(self):
        data = build_camera(
            flags=1, perspective_flags=2,
            viewport=(10, 640, 20, 480),
            scissor=(0, 640, 0, 480),
            roll=0.5, near=1.0, far=1000.0,
            field_of_view=60.0, aspect=1.333,
        )
        node = _parse(Camera, 0, data)
        assert node.flags == 1
        assert node.perspective_flags == 2
        assert abs(node.roll - 0.5) < 1e-5
        assert abs(node.near - 1.0) < 1e-5
        assert abs(node.far - 1000.0) < 1e-5
        assert abs(node.field_of_view - 60.0) < 1e-5


class TestViewportNode:

    def test_viewport_solo(self):
        data = build_viewport(ix=10, iw=640, iy=20, ih=480)
        node = _parse(Viewport, 0, data)
        assert node.ix == 10
        assert node.iw == 640
        assert node.iy == 20
        assert node.ih == 480


class TestCameraSetNode:

    def test_camera_set_solo(self):
        data = build_camera_set()
        node = _parse(CameraSet, 0, data)
        assert node.camera is None
        assert node.animations is None


class TestCameraAnimationNode:

    def test_camera_animation_solo(self):
        data = build_camera_animation()
        node = _parse(CameraAnimation, 0, data)
        assert node.animation is None
        assert node.eye_position_animation is None
        assert node.interest_animation is None


# ===========================================================================
# Colors/ (inline, is_cachable=False)
# ===========================================================================

class TestRGBAColorNode:

    def test_rgba_color(self):
        data = build_rgba_color(red=128, green=64, blue=32, alpha=255)
        node = _parse(RGBAColor, 0, data)
        assert node.red == 128
        assert node.green == 64
        assert node.blue == 32
        assert node.alpha == 255


class TestRGB565ColorNode:

    def test_rgb565_decode(self):
        # Red=31, Green=63, Blue=31 → max values
        raw = (0x1F << 11) | (0x3F << 5) | 0x1F  # 0xFFFF
        data = build_rgb565_color(raw_value=raw)
        node = _parse(RGB565Color, 0, data)
        assert node.red == 0x1F << 3   # 248
        assert node.green == 0x3F << 2  # 252
        assert node.blue == 0x1F << 3   # 248
        assert node.alpha == 0xFF

    def test_rgb565_zero(self):
        data = build_rgb565_color(raw_value=0)
        node = _parse(RGB565Color, 0, data)
        assert node.red == 0
        assert node.green == 0
        assert node.blue == 0
        assert node.alpha == 0xFF


class TestRGB5A3ColorNode:

    def test_rgb5a3_opaque(self):
        # Top bit set → opaque mode (RGB555)
        raw = 0x8000 | (0x1F << 10) | (0x1F << 5) | 0x1F  # white opaque
        data = build_rgb5a3_color(raw_value=raw)
        node = _parse(RGB5A3Color, 0, data)
        assert node.red == 0x1F * 8   # 248
        assert node.green == 0x1F * 8
        assert node.blue == 0x1F * 8
        assert node.alpha == 0xFF

    def test_rgb5a3_transparent(self):
        # Top bit clear → transparent mode (ARGB3444)
        # Alpha=7, R=15, G=15, B=15
        raw = (7 << 12) | (0xF << 8) | (0xF << 4) | 0xF
        data = build_rgb5a3_color(raw_value=raw)
        node = _parse(RGB5A3Color, 0, data)
        assert node.red == 0xF * 0x11    # 255
        assert node.green == 0xF * 0x11
        assert node.blue == 0xF * 0x11
        assert node.alpha == 7 * 0x20     # 224


class TestRGBA4ColorNode:

    def test_rgba4_decode(self):
        # R=15, G=8, B=4, A=2
        raw = (0xF << 12) | (0x8 << 8) | (0x4 << 4) | 0x2
        data = build_rgba4_color(raw_value=raw)
        node = _parse(RGBA4Color, 0, data)
        assert node.red == 0xF << 4    # 240
        assert node.green == 0x8 << 4  # 128
        assert node.blue == 0x4 << 4   # 64
        assert node.alpha == 0x2 << 4  # 32


class TestRGBA6ColorNode:

    def test_rgba6_decode(self):
        # Pack: R=63, G=32, B=16, A=8 → 24-bit value
        raw_value = (63 << 18) | (32 << 12) | (16 << 6) | 8
        b0 = (raw_value >> 16) & 0xFF
        b1 = (raw_value >> 8) & 0xFF
        b2 = raw_value & 0xFF
        data = build_rgba6_color(raw_bytes=(b0, b1, b2))
        node = _parse(RGBA6Color, 0, data)
        assert node.red == 63 << 2    # 252
        assert node.green == 32 << 2  # 128
        assert node.blue == 16 << 2   # 64
        assert node.alpha == 8 << 2   # 32


class TestRGB8ColorNode:

    def test_rgb8_decode(self):
        data = build_rgb8_color(red=100, green=150, blue=200)
        node = _parse(RGB8Color, 0, data)
        assert node.red == 100
        assert node.green == 150
        assert node.blue == 200
        assert node.alpha == 0xFF


class TestRGBX8ColorNode:

    def test_rgbx8_decode(self):
        data = build_rgbx8_color(red=50, green=100, blue=200)
        node = _parse(RGBX8Color, 0, data)
        assert node.red == 50
        assert node.green == 100
        assert node.blue == 200
        assert node.alpha == 0xFF


class TestI8ColorNode:

    def test_i8_decode(self):
        data = build_i8_color(intensity=128)
        node = _parse(I8Color, 0, data)
        assert node.red == 128
        assert node.green == 128
        assert node.blue == 128
        assert node.alpha == 0xFF


class TestIA4ColorNode:

    def test_ia4_decode(self):
        # raw_value: high nibble = alpha, low nibble = intensity
        raw = 0xA5  # alpha=0xA0, intensity=0x5<<4=0x50
        data = build_ia4_color(raw_value=raw)
        node = _parse(IA4Color, 0, data)
        assert node.red == 0x5 << 4  # 80
        assert node.green == 0x5 << 4
        assert node.blue == 0x5 << 4
        assert node.alpha == 0xA0


class TestIA8ColorNode:

    def test_ia8_decode(self):
        data = build_ia8_color(alpha=200, intensity=100)
        node = _parse(IA8Color, 0, data)
        assert node.red == 100
        assert node.green == 100
        assert node.blue == 100
        assert node.alpha == 200


# ===========================================================================
# Fog/
# ===========================================================================

class TestFogNode:

    def test_fog_solo(self):
        data = build_fog(fog_type=2, start_z=10.0, end_z=500.0,
                         color_red=128, color_green=128, color_blue=128, color_alpha=255)
        node = _parse(Fog, 0, data)
        assert node.type == 2
        assert node.adj is None
        assert abs(node.start_z - 10.0) < 1e-5
        assert abs(node.end_z - 500.0) < 1e-5
        assert node.color.red == 128
        assert node.color.alpha == 255


# ===========================================================================
# Joints/
# ===========================================================================

class TestBoneReferenceNode:

    def test_bone_reference_solo(self):
        data = build_bone_reference(length=5.0, pole_angle=1.57)
        node = _parse(BoneReference, 0, data)
        assert abs(node.length - 5.0) < 1e-5
        assert abs(node.pole_angle - 1.57) < 1e-3


class TestReferenceNode:

    def test_reference_inactive(self):
        """Inactive reference (ROBJ_ACTIVE_BIT not set) — property stays as raw uint."""
        data = build_reference(flags=0, property_raw=0x1234)
        node = _parse(Reference, 0, data)
        assert node.sub_type == 0
        assert node.property == 0x1234  # stays raw

    def test_reference_jobj(self):
        """Active reference with REFTYPE_JOBJ dispatches property to Joint."""
        joint_offset = REFERENCE_SIZE
        flags = ROBJ_ACTIVE_BIT | REFTYPE_JOBJ | 1  # sub_type = 1
        data = build_reference(flags=flags, property_raw=joint_offset) + build_joint()
        node = _parse(Reference, 0, data)
        assert node.sub_type == 1
        assert isinstance(node.property, Joint)

    def test_reference_ikhint(self):
        """Active reference with REFTYPE_IKHINT dispatches to BoneReference."""
        boneref_offset = REFERENCE_SIZE
        flags = ROBJ_ACTIVE_BIT | REFTYPE_IKHINT
        data = build_reference(flags=flags, property_raw=boneref_offset) + build_bone_reference(length=3.0, pole_angle=0.5)
        node = _parse(Reference, 0, data)
        assert isinstance(node.property, BoneReference)
        assert abs(node.property.length - 3.0) < 1e-5
        assert abs(node.property.pole_angle - 0.5) < 1e-3

    def test_reference_ikhint_pole_flip(self):
        """REFTYPE_IKHINT with flag 0x4 sets pole_flip on BoneReference.
        The actual pi addition happens later in ModelSet.build()."""
        boneref_offset = REFERENCE_SIZE
        flags = ROBJ_ACTIVE_BIT | REFTYPE_IKHINT | 0x4
        data = build_reference(flags=flags, property_raw=boneref_offset) + build_bone_reference(length=1.0, pole_angle=0.0)
        node = _parse(Reference, 0, data)
        assert isinstance(node.property, BoneReference)
        assert node.property.pole_flip is True
        assert node.property.pole_angle == 0.0


class TestEnvelopeNode:

    def test_envelope_solo(self):
        """Single Envelope with null joint → joint is None."""
        data = build_envelope(joint_ptr=0, weight=0.5)
        node = _parse(Envelope, 0, data)
        assert node.joint is None
        assert abs(node.weight - 0.5) < 1e-5


class TestEnvelopeListNode:

    def test_envelope_list_empty(self):
        """EnvelopeList with immediate null terminator → 0 envelopes."""
        data = build_envelope_list_terminator()
        # Pad to ensure file isn't truncated (terminator is only 4 bytes but
        # parser tries to read a full Envelope of 8 bytes before checking joint)
        data += b'\x00' * 4
        node = _parse(EnvelopeList, 0, data)
        assert len(node.envelopes) == 0

    def test_envelope_list_with_entries(self):
        """EnvelopeList with two envelopes followed by terminator."""
        # We need two Joint nodes for the envelope entries to point to
        joint1_offset = 64  # after envelopes + terminator
        joint2_offset = joint1_offset + JOINT_SIZE

        env1 = build_envelope(joint_ptr=joint1_offset, weight=0.6)
        env2 = build_envelope(joint_ptr=joint2_offset, weight=0.4)
        terminator = build_envelope_list_terminator() + b'\x00' * 4  # padded

        envelopes_data = env1 + env2 + terminator
        # Pad to reach joint1_offset
        padding = b'\x00' * (joint1_offset - len(envelopes_data))
        data = envelopes_data + padding + build_joint() + build_joint()

        node = _parse(EnvelopeList, 0, data)
        assert len(node.envelopes) == 2
        assert abs(node.envelopes[0].weight - 0.6) < 1e-5
        assert abs(node.envelopes[1].weight - 0.4) < 1e-5


# ===========================================================================
# Light/
# ===========================================================================

class TestLightNode:

    def test_light_ambient(self):
        """LOBJ_AMBIENT (flags=0, no LOBJ_LIGHT_ATTN) → property is None."""
        data = build_light(flags=0, attn_flags=0,
                           color_red=255, color_green=200, color_blue=100, color_alpha=255)
        node = _parse(Light, 0, data)
        assert node.property is None
        assert node.color.red == 255
        assert node.color.green == 200

    def test_light_point(self):
        """LOBJ_POINT → property dispatches to PointLight."""
        pl_offset = LIGHT_SIZE
        data = build_light(flags=LOBJ_POINT, property_raw=pl_offset) + build_point_light(reference_br=1.0, reference_distance=100.0)
        node = _parse(Light, 0, data)
        assert isinstance(node.property, PointLight)
        assert abs(node.property.reference_br - 1.0) < 1e-5
        assert abs(node.property.reference_distance - 100.0) < 1e-5

    def test_light_spot(self):
        """LOBJ_SPOT → property dispatches to SpotLight."""
        sl_offset = LIGHT_SIZE
        data = build_light(flags=LOBJ_SPOT, property_raw=sl_offset) + build_spot_light(cutoff=45.0)
        node = _parse(Light, 0, data)
        assert isinstance(node.property, SpotLight)
        assert abs(node.property.cutoff - 45.0) < 1e-5

    def test_light_attn(self):
        """LOBJ_LIGHT_ATTN flag → property dispatches to Attn."""
        attn_offset = LIGHT_SIZE
        data = build_light(attn_flags=LOBJ_LIGHT_ATTN, property_raw=attn_offset) + build_attn(angle=(1.0, 0.5, 0.0))
        node = _parse(Light, 0, data)
        assert isinstance(node.property, Attn)
        assert abs(node.property.angle[0] - 1.0) < 1e-5


class TestPointLightNode:

    def test_point_light_solo(self):
        data = build_point_light(reference_br=2.5, reference_distance=50.0)
        node = _parse(PointLight, 0, data)
        assert abs(node.reference_br - 2.5) < 1e-5
        assert abs(node.reference_distance - 50.0) < 1e-5


class TestSpotLightNode:

    def test_spot_light_solo(self):
        data = build_spot_light(cutoff=30.0, spot_flags=1, reference_br=1.5,
                                reference_distance=200.0, distance_attn_flags=2)
        node = _parse(SpotLight, 0, data)
        assert abs(node.cutoff - 30.0) < 1e-5
        assert node.spot_flags == 1
        assert abs(node.reference_br - 1.5) < 1e-5
        assert abs(node.reference_distance - 200.0) < 1e-5
        assert node.distance_attn_flags == 2


class TestAttnNode:

    def test_attn_solo(self):
        data = build_attn(angle=(1.0, 2.0, 3.0), distance=(4.0, 5.0, 6.0))
        node = _parse(Attn, 0, data)
        assert abs(node.angle[0] - 1.0) < 1e-5
        assert abs(node.distance[2] - 6.0) < 1e-5


class TestLightSetNode:

    def test_light_set_solo(self):
        data = build_light_set()
        node = _parse(LightSet, 0, data)
        assert node.light is None
        assert node.animations is None


class TestLightAnimationNode:

    def test_light_animation_solo(self):
        data = build_light_animation()
        node = _parse(LightAnimation, 0, data)
        assert node.next is None
        assert node.animation is None


# ===========================================================================
# Material/
# ===========================================================================

class TestMaterialNode:

    def test_material_solo(self):
        """Material with specific colors; loadFromBinary calls transform() (normalize only) on each."""
        data = build_material(
            ambient=(50, 50, 50, 255),
            diffuse=(200, 100, 50, 255),
            specular=(255, 255, 255, 255),
            alpha=1.0,
            shininess=50.0,
        )
        node = _parse(Material, 0, data)
        # After transform(), RGB values are normalized to [0-1] sRGB.
        # Linearization happens in the build phase, not here.
        assert abs(node.diffuse.red - 200 / 255) < 1e-5
        assert abs(node.diffuse.green - 100 / 255) < 1e-5
        assert abs(node.diffuse.blue - 50 / 255) < 1e-5
        assert abs(node.alpha - 1.0) < 1e-5
        assert abs(node.shininess - 50.0) < 1e-5


class TestMaterialObjectNode:

    def test_material_object_solo(self):
        data = build_material_object(render_mode=0x17)
        node = _parse(MaterialObject, 0, data)
        assert node.render_mode == 0x17
        assert node.texture is None
        assert node.material is None
        assert node.id == 0

    def test_material_object_with_material(self):
        """MaterialObject pointing to a Material child."""
        mat_offset = MATERIALOBJECT_SIZE
        data = (
            build_material_object(render_mode=0x04, material_ptr=mat_offset)
            + build_material(diffuse=(128, 128, 128, 255), alpha=0.8, shininess=25.0)
        )
        node = _parse(MaterialObject, 0, data)
        assert node.render_mode == 0x04
        assert isinstance(node.material, Material)
        assert abs(node.material.alpha - 0.8) < 1e-5


class TestMaterialAnimationNode:

    def test_material_animation_solo(self):
        data = build_material_animation()
        node = _parse(MaterialAnimation, 0, data)
        assert node.next is None
        assert node.animation is None
        assert node.texture_animation is None
        assert node.render_animation is None


class TestMaterialAnimationJointNode:

    def test_material_animation_joint_solo(self):
        data = build_material_animation_joint()
        node = _parse(MaterialAnimationJoint, 0, data)
        assert node.child is None
        assert node.next is None
        assert node.animation is None

    def test_material_animation_joint_with_child(self):
        data = (
            build_material_animation_joint(child_ptr=MATERIALANIMATIONJOINT_SIZE)
            + build_material_animation_joint()
        )
        node = _parse(MaterialAnimationJoint, 0, data)
        assert isinstance(node.child, MaterialAnimationJoint)


# ===========================================================================
# Misc/
# ===========================================================================

class TestSListNode:

    def test_slist_solo(self):
        data = build_slist(data=0xDEADBEEF)
        node = _parse(SList, 0, data)
        assert node.data == 0xDEADBEEF
        assert node.next is None

    def test_slist_linked(self):
        data = build_slist(next_ptr=SLIST_SIZE, data=1) + build_slist(data=2)
        node = _parse(SList, 0, data)
        assert node.data == 1
        assert isinstance(node.next, SList)
        assert node.next.data == 2


class TestSplineNode:

    def test_spline_polyline_no_points(self):
        """Polyline (type=0) with n=0 and no data pointers."""
        data = build_spline(flags=0, n=0)
        node = _parse(Spline, 0, data)
        assert node.s1 is None
        assert node.s2 is None
        assert node.s3 is None

    def test_spline_polyline_with_points(self):
        """Polyline (type=0) with 2 control points."""
        s1_offset = SPLINE_SIZE
        s1_data = struct.pack('>fff', 1.0, 2.0, 3.0) + struct.pack('>fff', 4.0, 5.0, 6.0)
        data = build_spline(flags=0, n=2, s1=s1_offset) + s1_data
        node = _parse(Spline, 0, data)
        assert len(node.s1) == 2
        assert abs(node.s1[0][0] - 1.0) < 1e-5
        assert abs(node.s1[1][2] - 6.0) < 1e-5
        assert node.s2 is None

    def test_spline_nurbs_with_points(self):
        """NURBS (type=3) with n=2 control points (reads n+2=4 for s1)."""
        n = 2
        s1_offset = SPLINE_SIZE
        # NURBS reads n+2 points for s1
        s1_data = b''
        for i in range(n + 2):
            s1_data += struct.pack('>fff', float(i), float(i + 1), float(i + 2))
        data = build_spline(flags=(3 << 8), n=n, s1=s1_offset) + s1_data
        node = _parse(Spline, 0, data)
        assert len(node.s1) == n + 2
        assert abs(node.s1[0][0] - 0.0) < 1e-5
        assert abs(node.s1[3][0] - 3.0) < 1e-5

    def test_spline_with_s2_weights(self):
        """Polyline with s2 (weight) data."""
        s1_offset = SPLINE_SIZE
        s1_data = struct.pack('>fff', 1.0, 0.0, 0.0) + struct.pack('>fff', 0.0, 1.0, 0.0)
        s2_offset = s1_offset + len(s1_data)
        s2_data = struct.pack('>ff', 1.0, 0.5)
        data = build_spline(flags=0, n=2, s1=s1_offset, s2=s2_offset) + s1_data + s2_data
        node = _parse(Spline, 0, data)
        assert len(node.s2) == 2
        assert abs(node.s2[0] - 1.0) < 1e-5
        assert abs(node.s2[1] - 0.5) < 1e-5


# ===========================================================================
# Rendering/
# ===========================================================================

class TestPixelEngineNode:

    def test_pixel_engine_solo(self):
        data = build_pixel_engine(pe_type=1, source_factor=4, destination_factor=5, logic_op=3)
        node = _parse(PixelEngine, 0, data)
        assert node.type == 1
        assert node.source_factor == 4
        assert node.destination_factor == 5
        assert node.logic_op == 3


class TestRenderNode:

    def test_render_solo(self):
        data = build_render(terminator=0xFFFFFFFF)
        node = _parse(Render, 0, data)
        assert node.toon_texture is None
        assert node.grad_texture is None
        assert node.terminator == 0xFFFFFFFF


class TestWObjectNode:

    def test_wobject_solo(self):
        data = build_wobject(position=(10.0, 20.0, 30.0))
        node = _parse(WObject, 0, data)
        assert abs(node.position[0] - 10.0) < 1e-5
        assert abs(node.position[1] - 20.0) < 1e-5
        assert abs(node.position[2] - 30.0) < 1e-5
        assert node.render is None


class TestWObjectAnimationNode:

    def test_wobject_animation_solo(self):
        data = build_wobject_animation()
        node = _parse(WObjectAnimation, 0, data)
        assert node.animation is None
        assert node.render_animation is None


# ===========================================================================
# RootNodes/
# ===========================================================================

class TestSceneDataNode:

    def test_scene_data_solo(self):
        data = build_scene_data()
        node = _parse(SceneData, 0, data)
        assert node.models is None
        assert node.camera is None
        assert node.lights is None
        assert node.fog is None


class TestBoundBoxNode:

    def test_bound_box_solo(self):
        data = build_bound_box(unknown_1=42, unknown_2=0xABCD)
        node = _parse(BoundBox, 0, data)
        assert node.anim_set_count == 42
        assert node.first_anim_frame_count == 0xABCD


# ===========================================================================
# Shape/
# ===========================================================================

class TestShapeAnimationNode:

    def test_shape_animation_solo(self):
        data = build_shape_animation()
        node = _parse(ShapeAnimation, 0, data)
        assert node.next is None
        assert node.animation is None


class TestShapeAnimationJointNode:

    def test_shape_animation_joint_solo(self):
        data = build_shape_animation_joint()
        node = _parse(ShapeAnimationJoint, 0, data)
        assert node.child is None
        assert node.next is None
        assert node.animation is None

    def test_shape_animation_joint_with_child(self):
        data = (
            build_shape_animation_joint(child_ptr=SHAPEANIMATIONJOINT_SIZE)
            + build_shape_animation_joint()
        )
        node = _parse(ShapeAnimationJoint, 0, data)
        assert isinstance(node.child, ShapeAnimationJoint)


class TestShapeAnimationMeshNode:

    def test_shape_animation_mesh_solo(self):
        data = build_shape_animation_mesh()
        node = _parse(ShapeAnimationMesh, 0, data)
        assert node.next is None
        assert node.animation is None


class TestShapeIndexTriNode:

    def test_shape_index_tri_solo(self):
        data = build_shape_index_tri(id0=1, id1=2, id2=3)
        node = _parse(ShapeIndexTri, 0, data)
        assert node.id0 == 1
        assert node.id1 == 2
        assert node.id2 == 3


# ===========================================================================
# Texture/
# ===========================================================================

class TestImageNode:

    def test_image_solo(self):
        data = build_image(data_address=0x1000, width=64, height=64, fmt=0)
        node = _parse(Image, 0, data)
        assert node.width == 64
        assert node.height == 64
        assert node.format == 0
        assert node.id == 0x1000  # id set from data_address


class TestTextureLODNode:

    def test_texture_lod_solo(self):
        data = build_texture_lod(min_filter=1, lod_bias=0.5, bias_clamp=1,
                                 enable_edge_lod=0, max_anisotropy=4)
        node = _parse(TextureLOD, 0, data)
        assert node.min_filter == 1
        assert abs(node.LOD_bias - 0.5) < 1e-5
        assert node.bias_clamp == 1
        assert node.max_anisotropy == 4


class TestTextureTEVNode:

    def test_texture_tev_solo(self):
        """TextureTEV parses 16 uchar fields + 3 inline RGBX8Colors + active uint.
        loadFromBinary normalizes the 3 color fields."""
        data = build_texture_tev(
            color_op=0, alpha_op=1,
            color_a=8, color_b=9, color_c=10, color_d=11,
            konst=(128, 64, 32), tev0=(255, 0, 0), tev1=(0, 255, 0),
            active=0x03,
        )
        node = _parse(TextureTEV, 0, data)
        assert node.color_op == 0
        assert node.alpha_op == 1
        assert node.color_a == 8
        assert node.active == 0x03
        # After normalize(), konst colors are in [0,1]
        assert abs(node.konst.red - 128 / 255) < 1e-3
        assert abs(node.tev0.red - 1.0) < 1e-3
        assert abs(node.tev1.green - 1.0) < 1e-3


class TestTextureAnimationNode:

    def test_texture_animation_solo(self):
        data = build_texture_animation(tex_id=5, image_table_count=2, palette_table_count=1)
        node = _parse(TextureAnimation, 0, data)
        assert node.id == 5
        assert node.image_table_count == 2
        assert node.palette_table_count == 1
        assert node.next is None
        assert node.animation is None


class TestTextureNode:

    def test_texture_solo_no_image(self):
        """Texture with no image → decoded_pixels is None."""
        data = build_texture(
            texture_id=42, source=4,
            rotation=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            translation=(0.0, 0.0, 0.0),
            wrap_s=1, wrap_t=1,
            repeat_s=1, repeat_t=1,
            flags=0x10,
        )
        node = _parse(Texture, 0, data)
        assert node.texture_id == 42
        assert node.source == 4
        assert abs(node.scale[0] - 1.0) < 1e-5
        assert node.repeat_s == 1
        assert node.repeat_t == 1
        assert node.flags == 0x10
        assert node.image is None
        assert node.decoded_pixels is None
        assert node.id == 0  # id set from address


class TestPaletteNode:

    def test_palette_solo(self):
        """Palette reads raw_data from the data address."""
        # Place palette color data after the Palette struct
        palette_data_offset = PALETTE_SIZE + 2  # +2 pad to align to 4
        # IA8 format (format=0), 2 entries × 2 bytes each = 4 bytes
        palette_colors = struct.pack('>BBBB', 0xFF, 0x80, 0x00, 0x40)

        data = build_palette(
            data_address=palette_data_offset,
            fmt=0,  # IA8
            entry_count=2,
        )
        # Pad to reach palette_data_offset
        data += b'\x00' * (palette_data_offset - len(data))
        data += palette_colors

        node = _parse(Palette, 0, data)
        assert node.format == 0
        assert node.entry_count == 2
        assert node.id == palette_data_offset
        assert len(node.raw_data) == 4
