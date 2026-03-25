"""Node parsing tests: single node and single node with one level of children."""
import io
import struct
import pytest

from helpers import (
    build_minimal_dat, build_joint, build_mesh, build_pobject,
    build_animjoint, build_spline, build_particle, build_render_animation,
    build_animation,
    build_vertex_list_terminator,
    JOINT_SIZE, MESH_SIZE, POBJECT_SIZE, ANIMJOINT_SIZE, SPLINE_SIZE, VERTEX_SIZE,
)
from importer.phases.parse.helpers.dat_parser import DATParser
from shared.Nodes.Classes.Joints.Joint import Joint
from shared.Nodes.Classes.Mesh.Mesh import Mesh
from shared.Nodes.Classes.Mesh.PObject import PObject
from shared.Nodes.Classes.Animation.AnimationJoint import AnimationJoint
from shared.Nodes.Classes.Animation.Animation import Animation
from shared.Nodes.Classes.Rendering.RenderAnimation import RenderAnimation
from shared.Nodes.Classes.Misc.Spline import Spline
from shared.Nodes.Classes.Rendering.Particle import Particle
from shared.Constants.hsd import JOBJ_HIDDEN, JOBJ_PTCL, JOBJ_SPLINE
from shared.Constants.hsd import POBJ_SKIN, POBJ_SHAPEANIM, POBJ_ENVELOPE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(node_cls, address, data_section: bytes):
    """Parse a single node from the given data section bytes."""
    dat_bytes = build_minimal_dat(data_section)
    parser = DATParser(io.BytesIO(dat_bytes), {})
    node = node_cls(address, None)
    node.loadFromBinary(parser)
    parser.close()
    return node


def _parse_keep_parser(node_cls, address, data_section: bytes):
    """Parse a node and return (node, parser) — caller must close parser."""
    dat_bytes = build_minimal_dat(data_section)
    parser = DATParser(io.BytesIO(dat_bytes), {})
    node = node_cls(address, None)
    node.loadFromBinary(parser)
    return node, parser


# ---------------------------------------------------------------------------
# Mesh (DObject) — 16 bytes: name(4) next(4) mobject(4) pobject(4)
# ---------------------------------------------------------------------------

class TestMeshNode:

    def test_mesh_solo(self):
        """A Mesh with all-zero pointers should parse cleanly with all fields None."""
        data = build_mesh()
        mesh = _parse(Mesh, 0, data)

        assert mesh.name is None
        assert mesh.next is None
        assert mesh.mobject is None
        assert mesh.pobject is None
        assert mesh.id == 0

    def test_mesh_solo_at_nonzero_address(self):
        """Parsing a Mesh at a non-zero data-section offset sets id correctly."""
        # Pad so the Mesh starts at offset 16 inside the data section
        offset = 16
        data = b'\x00' * offset + build_mesh()
        mesh = _parse(Mesh, offset, data)

        assert mesh.id == offset
        assert mesh.name is None
        assert mesh.next is None

    def test_mesh_with_next_sibling(self):
        """A Mesh whose next pointer points to a second Mesh at offset MESH_SIZE."""
        data = build_mesh(next_ptr=MESH_SIZE) + build_mesh()
        mesh = _parse(Mesh, 0, data)

        assert isinstance(mesh.next, Mesh)
        assert mesh.next.id == MESH_SIZE
        assert mesh.next.next is None


# ---------------------------------------------------------------------------
# Joint (JObj) — 64 bytes
# ---------------------------------------------------------------------------

class TestJointNode:

    def test_joint_solo(self):
        """A Joint with all zeros should parse cleanly."""
        data = build_joint()
        joint = _parse(Joint, 0, data)

        assert joint.name is None
        assert joint.flags == 0
        assert joint.child is None
        assert joint.next is None
        assert joint.property is None
        assert tuple(joint.rotation) == (0.0, 0.0, 0.0)
        assert tuple(joint.scale) == (0.0, 0.0, 0.0)
        assert tuple(joint.position) == (0.0, 0.0, 0.0)
        assert not joint.isHidden

    def test_joint_solo_representative(self):
        """A Joint with representative primitive-field values round-trips correctly."""
        # flags=0x02 is an arbitrary non-special bit (not HIDDEN/PTCL/SPLINE/INSTANCE)
        data = build_joint(
            flags=0x02,
            rotation=(0.5, 1.0, 1.5),
            scale=(2.0, 3.0, 4.0),
            position=(10.0, 20.0, 30.0),
        )
        joint = _parse(Joint, 0, data)

        assert joint.flags == 0x02
        assert not joint.isHidden
        assert abs(joint.rotation[0] - 0.5) < 1e-5
        assert abs(joint.rotation[1] - 1.0) < 1e-5
        assert abs(joint.rotation[2] - 1.5) < 1e-5
        assert abs(joint.scale[0] - 2.0) < 1e-5
        assert abs(joint.scale[1] - 3.0) < 1e-5
        assert abs(joint.scale[2] - 4.0) < 1e-5
        assert abs(joint.position[0] - 10.0) < 1e-5
        assert abs(joint.position[1] - 20.0) < 1e-5
        assert abs(joint.position[2] - 30.0) < 1e-5
        assert joint.child is None
        assert joint.next is None
        assert joint.property is None

    def test_joint_with_next_sibling(self):
        """A Joint whose next pointer points to a second Joint; both have distinct flags."""
        data = build_joint(flags=0xAB, next_ptr=JOINT_SIZE) + build_joint(flags=0xCD)
        joint = _parse(Joint, 0, data)

        assert joint.flags == 0xAB
        assert isinstance(joint.next, Joint)
        assert joint.next.flags == 0xCD
        assert joint.next.next is None

    def test_joint_vec3_fields(self):
        """rotation, scale, and position fields are decoded correctly from the binary."""
        data = build_joint(
            rotation=(0.1, 0.2, 0.3),
            scale=(1.0, 2.0, 3.0),
            position=(4.0, 5.0, 6.0),
        )
        joint = _parse(Joint, 0, data)

        assert abs(joint.rotation[0] - 0.1) < 1e-5
        assert abs(joint.rotation[1] - 0.2) < 1e-5
        assert abs(joint.rotation[2] - 0.3) < 1e-5
        assert abs(joint.scale[0] - 1.0) < 1e-5
        assert abs(joint.scale[1] - 2.0) < 1e-5
        assert abs(joint.scale[2] - 3.0) < 1e-5
        assert abs(joint.position[0] - 4.0) < 1e-5
        assert abs(joint.position[1] - 5.0) < 1e-5
        assert abs(joint.position[2] - 6.0) < 1e-5

    def test_joint_is_hidden_flag(self):
        """JOBJ_HIDDEN flag causes joint.isHidden to be truthy."""
        data = build_joint(flags=JOBJ_HIDDEN)
        joint = _parse(Joint, 0, data)

        assert joint.isHidden

    def test_joint_property_null(self):
        """property_ptr == 0 → joint.property is None regardless of flags."""
        for flags in (0, JOBJ_PTCL, JOBJ_SPLINE):
            data = build_joint(flags=flags, property_ptr=0)
            joint = _parse(Joint, 0, data)
            assert joint.property is None, f"Expected None for flags={flags:#x}"

    def test_joint_property_dispatches_to_mesh(self):
        """Default flags (no PTCL/SPLINE) → property resolved as Mesh."""
        # Mesh placed at offset JOINT_SIZE; we only need the Mesh header (16 bytes of zeros)
        data = build_joint(flags=0, property_ptr=JOINT_SIZE) + build_mesh()
        joint = _parse(Joint, 0, data)

        assert isinstance(joint.property, Mesh)

    def test_joint_property_dispatches_to_spline(self):
        """JOBJ_SPLINE flag → property resolved as Spline (with n=0 so no array reads)."""
        # Spline at offset JOINT_SIZE; flags=0 (no sub-flag bits) and n=0 avoids array reads
        data = build_joint(flags=JOBJ_SPLINE, property_ptr=JOINT_SIZE) + build_spline(flags=0, n=0)
        joint = _parse(Joint, 0, data)

        assert isinstance(joint.property, Spline)
        assert joint.property.n == 0

    def test_joint_property_dispatches_to_particle(self):
        """JOBJ_PTCL flag → property resolved as Particle (zero-field node)."""
        # Particle has no fields, so it reads nothing; any non-zero address is fine
        data = build_joint(flags=JOBJ_PTCL, property_ptr=JOINT_SIZE) + build_particle()
        # Particle takes no bytes but we need enough data so the file isn't truncated
        data += b'\x00' * 4   # pad to keep file valid
        joint = _parse(Joint, 0, data)

        assert isinstance(joint.property, Particle)


# ---------------------------------------------------------------------------
# PObject (PObj) — 24 bytes; requires a VertexList terminator at vertex_list_ptr
# ---------------------------------------------------------------------------

class TestPObjectNode:

    def test_pobject_solo(self):
        """A PObject with null property but valid VertexList (terminator only) parses cleanly."""
        # read_geometry() unconditionally accesses self.vertex_list.vertices, so we must always
        # supply a valid VertexList.  A single terminator Vertex (attribute=0xFF) produces an
        # empty vertices list and stops all geometry loops immediately.
        vertex_offset = POBJECT_SIZE
        data = (
            build_pobject(vertex_list_ptr=vertex_offset, property_ptr=0)
            + build_vertex_list_terminator()
        )
        pobj = _parse(PObject, 0, data)

        assert pobj.name is None
        assert pobj.next is None
        assert pobj.property is None
        assert pobj.sources == []
        assert pobj.face_lists == []

    def test_pobject_solo_representative(self):
        """A PObject with representative primitive fields (flags, display_list_chunk_count) parses correctly."""
        # flags=0x0001: a non-zero raw bit that doesn't fall in POBJ_TYPE_MASK (SKIN/SHAPEANIM/ENVELOPE)
        # display_list_chunk_count=5: non-zero; display_list_size = 5*32 = 160, but the vertex list
        # is empty so the geometry loop body never executes — the value is simply stored on the node.
        vertex_offset = POBJECT_SIZE
        data = (
            build_pobject(
                flags=0x0001,
                vertex_list_ptr=vertex_offset,
                display_list_chunk_count=5,
                display_list_address=0,
                property_ptr=0,
            )
            + build_vertex_list_terminator()
        )
        pobj = _parse(PObject, 0, data)

        assert pobj.flags == 0x0001
        assert pobj.display_list_chunk_count == 5
        assert pobj.property is None
        assert pobj.sources == []
        assert pobj.face_lists == []

    @pytest.mark.parametrize("flags", [POBJ_SKIN, POBJ_SHAPEANIM, POBJ_ENVELOPE])
    def test_pobject_property_null_all_flag_variants(self, flags):
        """property_ptr == 0 → pobj.property is None for every POBJ_* flag variant."""
        vertex_offset = POBJECT_SIZE
        data = (
            build_pobject(flags=flags, vertex_list_ptr=vertex_offset, property_ptr=0)
            + build_vertex_list_terminator()
        )
        pobj = _parse(PObject, 0, data)

        assert pobj.property is None

    def test_pobject_property_dispatches_to_joint_when_pobj_skin(self):
        """POBJ_SKIN flag + non-null property_ptr → pobj.property is Joint."""
        # Layout (data section):
        #   offset 0              : PObject  (24 bytes)
        #   offset POBJECT_SIZE   : VertexList terminator (24 bytes) — vertex_list_ptr
        #   offset POBJECT_SIZE + VERTEX_SIZE : Joint (64 bytes) — property_ptr
        vertex_offset = POBJECT_SIZE
        joint_offset = POBJECT_SIZE + VERTEX_SIZE

        data = (
            build_pobject(
                flags=POBJ_SKIN,
                vertex_list_ptr=vertex_offset,
                property_ptr=joint_offset,
                display_list_chunk_count=0,
                display_list_address=0,
            )
            + build_vertex_list_terminator()
            + build_joint()
        )
        pobj = _parse(PObject, 0, data)

        assert isinstance(pobj.property, Joint)


# ---------------------------------------------------------------------------
# AnimationJoint — 20 bytes: child(4) next(4) animation(4) render_animation(4) flags(4)
# ---------------------------------------------------------------------------

class TestAnimationJointNode:

    def test_animjoint_solo(self):
        """An AnimationJoint with all zeros should parse cleanly."""
        data = build_animjoint()
        aj = _parse(AnimationJoint, 0, data)

        assert aj.child is None
        assert aj.next is None
        assert aj.animation is None
        assert aj.render_animation is None
        assert aj.flags == 0

    def test_animjoint_solo_representative(self):
        """An AnimationJoint with a non-zero flags value stores it correctly."""
        data = build_animjoint(flags=0xBEEF)
        aj = _parse(AnimationJoint, 0, data)

        assert aj.flags == 0xBEEF
        assert aj.child is None
        assert aj.next is None
        assert aj.animation is None
        assert aj.render_animation is None

    def test_animjoint_with_child(self):
        """child_ptr pointing to a second AnimationJoint; both have distinct flags."""
        data = build_animjoint(child_ptr=ANIMJOINT_SIZE, flags=0x01) + build_animjoint(flags=0x02)
        aj = _parse(AnimationJoint, 0, data)

        assert aj.flags == 0x01
        assert isinstance(aj.child, AnimationJoint)
        assert aj.child.flags == 0x02
        assert aj.child.child is None

    def test_animjoint_with_render_animation(self):
        """AnimationJoint with a render_animation pointer to a RenderAnimation node."""
        ra_offset = ANIMJOINT_SIZE  # RenderAnimation follows immediately
        data = build_animjoint(render_animation_ptr=ra_offset) + build_render_animation()
        aj = _parse(AnimationJoint, 0, data)

        assert isinstance(aj.render_animation, RenderAnimation)
        assert aj.render_animation.next is None
        assert aj.render_animation.animation is None

    def test_animjoint_with_render_animation_chain(self):
        """RenderAnimation linked list (next pointer)."""
        ra1_offset = ANIMJOINT_SIZE
        ra2_offset = ANIMJOINT_SIZE + 8
        data = (
            build_animjoint(render_animation_ptr=ra1_offset)
            + build_render_animation(next_ptr=ra2_offset)
            + build_render_animation()
        )
        aj = _parse(AnimationJoint, 0, data)

        assert isinstance(aj.render_animation, RenderAnimation)
        assert isinstance(aj.render_animation.next, RenderAnimation)
        assert aj.render_animation.next.next is None

    def test_animjoint_render_animation_with_aobj(self):
        """RenderAnimation pointing to an Animation (AOBJ) object."""
        ra_offset = ANIMJOINT_SIZE
        aobj_offset = ANIMJOINT_SIZE + 8  # Animation follows RenderAnimation
        data = (
            build_animjoint(render_animation_ptr=ra_offset)
            + build_render_animation(animation_ptr=aobj_offset)
            + build_animation(flags=0x20000000, end_frame=30.0)
        )
        aj = _parse(AnimationJoint, 0, data)

        assert isinstance(aj.render_animation, RenderAnimation)
        assert isinstance(aj.render_animation.animation, Animation)
        assert aj.render_animation.animation.flags == 0x20000000
        assert abs(aj.render_animation.animation.end_frame - 30.0) < 1e-5


# ---------------------------------------------------------------------------
# RenderAnimation — 8 bytes: next(4) animation(4)
# ---------------------------------------------------------------------------

class TestRenderAnimationNode:

    def test_render_animation_solo(self):
        """A RenderAnimation with all zeros should parse cleanly."""
        data = build_render_animation()
        ra = _parse(RenderAnimation, 0, data)

        assert ra.next is None
        assert ra.animation is None

    def test_render_animation_with_next(self):
        """Linked list of two RenderAnimation nodes."""
        data = build_render_animation(next_ptr=8) + build_render_animation()
        ra = _parse(RenderAnimation, 0, data)

        assert isinstance(ra.next, RenderAnimation)
        assert ra.next.next is None

    def test_render_animation_with_animation(self):
        """RenderAnimation pointing to an Animation (AOBJ)."""
        data = build_render_animation(animation_ptr=8) + build_animation(flags=0x20000000, end_frame=60.0)
        ra = _parse(RenderAnimation, 0, data)

        assert isinstance(ra.animation, Animation)
        assert ra.animation.flags == 0x20000000
        assert abs(ra.animation.end_frame - 60.0) < 1e-5
