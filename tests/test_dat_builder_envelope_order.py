"""Unit tests for DATBuilder's envelope struct emission order.

The builder reconstructs the compiler's envelope allocation order (see
``DATBuilder._envelope_emission_order``):

* membership — a combo shared between DObjects belongs to the first DObject
  in processing order (reverse joint pre-order, forward mesh chains);
* emission — per-DObject blocks appear in reverse processing order;
* within a block — PObject palette-slot chains are merged, popping the chain
  head with the smallest first-use display-list position index.
"""
import io

from shared.Nodes.Classes.Joints.Joint import Joint
from shared.Nodes.Classes.Joints.Envelope import EnvelopeList, Envelope
from shared.Nodes.Classes.Mesh.Mesh import Mesh
from shared.Nodes.Classes.Mesh.PObject import PObject
from shared.Nodes.Classes.Mesh.VertexList import VertexList
from shared.Nodes.Classes.Mesh.Vertex import Vertex
from shared.Constants import gx
from exporter.phases.serialize.helpers.dat_builder import DATBuilder


def _joint():
    j = Joint(None, None)
    j.child = None
    j.next = None
    j.property = None
    return j


def _envelope_list(weight_targets):
    """EnvelopeList over [(joint, weight), ...]."""
    el = EnvelopeList(None, None)
    el.envelopes = []
    for joint, weight in weight_targets:
        env = Envelope(None, None)
        env.joint = joint
        env.weight = weight
        el.envelopes.append(env)
    return el


def _vertex(attribute, attribute_type):
    v = Vertex(None, None)
    v.attribute = attribute
    v.attribute_type = attribute_type
    v.component_count = 0
    v.component_type = 0
    v.component_frac = 0
    v.stride = 0
    v.base_pointer = 0
    return v


def _pobject(env_lists, dl_vertices):
    """PObject with a PNMTXIDX+POS(INDEX8) descriptor pair and a display
    list drawing ``dl_vertices`` as [(matrix_slot, pos_index), ...]."""
    po = PObject(None, None)
    po.next = None
    po.property = list(env_lists)
    vl = VertexList(None, None)
    vl.vertices = [
        _vertex(gx.GX_VA_PNMTXIDX, gx.GX_DIRECT),
        _vertex(gx.GX_VA_POS, gx.GX_INDEX8),
    ]
    po.vertex_list = vl
    dl = bytearray()
    dl.append(0x90)  # GX_TRIANGLES
    dl += len(dl_vertices).to_bytes(2, 'big')
    for slot, pos in dl_vertices:
        dl.append(slot * 3)
        dl.append(pos)
    dl.append(0x00)  # GX_NOP terminator
    po.raw_display_list = bytes(dl)
    return po


def _mesh(pobject):
    m = Mesh(None, None)
    m.next = None
    m.mobject = None
    m.pobject = pobject
    return m


def _build_fixture():
    """Joint tree: root -> child A, sibling B. A and B each own one mesh.

    Combos: E1 unique to A's mesh; E2 shared by both; E3 unique to B's mesh.
    Processing order (reverse pre-order) is B, A — so B owns E2 and E3, and
    emission order (reversed blocks) is A's block then B's block.
    Within B's block the slot chain is [E3(slot0), E2(slot1)], and E3 must
    emit first even though E2's first position index is smaller (the chain
    hides E2 until E3 pops).
    """
    root, joint_a, joint_b = _joint(), _joint(), _joint()
    root.child = joint_a
    joint_a.next = joint_b

    e1 = _envelope_list([(root, 1.0)])
    e2 = _envelope_list([(root, 0.5), (joint_a, 0.5)])
    e2_alias = _envelope_list([(root, 0.5), (joint_a, 0.5)])
    e3 = _envelope_list([(joint_b, 1.0)])

    joint_a.property = _mesh(_pobject([e1, e2_alias], [(0, 0), (1, 7)]))
    joint_b.property = _mesh(_pobject([e3, e2], [(0, 5), (1, 0), (1, 1)]))

    builder = DATBuilder(io.BytesIO(), [root], ['test_joint'])
    return builder, (e1, e2, e2_alias, e3)


def test_dl_slot_first_positions():
    po = _pobject([], [(0, 5), (1, 0), (1, 1)])
    assert DATBuilder._dl_slot_first_positions(po) == {0: 5, 1: 0}


def test_membership_blocks_and_chain_merge():
    builder, (e1, e2, e2_alias, e3) = _build_fixture()
    rank = builder._envelope_emission_order()
    key = DATBuilder._envelope_content_key
    # A's block first (emission reverses processing), then B's block with the
    # slot chain forcing E3 before the shared E2.
    assert rank[key(e1)] == 0
    assert rank[key(e3)] == 1
    assert rank[key(e2)] == 2
    assert key(e2_alias) == key(e2)  # aliases share the content key


def test_ordered_node_list_applies_envelope_rank():
    builder, (e1, e2, e2_alias, e3) = _build_fixture()
    ordered = builder._ordered_node_list()
    env_lists = [n for n in ordered if isinstance(n, EnvelopeList)]
    assert env_lists.index(e1) < env_lists.index(e3) < env_lists.index(e2)


def test_no_envelopes_returns_empty_rank():
    root = _joint()
    builder = DATBuilder(io.BytesIO(), [root], ['test_joint'])
    assert builder._envelope_emission_order() == {}
