"""markUpFieldType structure preservation.

The markup pass must descend one structural level at a time. It previously
recursed straight to the bottom type for pointer/bracket/array cases, which
silently discarded intermediate layers — '*(Image[image_table_count])'
(pointer to a counted array of Image pointers) collapsed to '*((*Image))'
(a plain double pointer), so only the first table entry was ever parsed.
"""
from shared.Nodes.NodeTypes import markUpFieldType


def test_single_level_types_unchanged():
    """Every field-type shape declared across the node classes keeps its
    established markup."""
    assert markUpFieldType('Joint') == '(*Joint)'
    assert markUpFieldType('string') == '(*string)'
    assert markUpFieldType('matrix') == '(*matrix)'
    assert markUpFieldType('float') == 'float'
    assert markUpFieldType('uint') == 'uint'
    assert markUpFieldType('vec3') == 'vec3'
    assert markUpFieldType('uchar[3]') == 'uchar[3]'
    assert markUpFieldType('ushort[4]') == 'ushort[4]'
    assert markUpFieldType('*vec3') == '*(vec3)'
    assert markUpFieldType('@RGBAColor') == '(RGBAColor)'
    assert markUpFieldType('AnimationJoint[]') == '(*((*AnimationJoint)[]))'
    assert markUpFieldType('(@Vertex)[]') == '(*((Vertex)[]))'


def test_pointer_to_counted_array_preserves_structure():
    marked = markUpFieldType('*(Image[image_table_count])')
    assert marked == '*(((*Image))[image_table_count])'


def test_explicit_pointer_to_class_is_not_double_pointered():
    """An explicit '*' before a class name is already the pointer — the
    implicit bare-class pointer level must not stack on top (this keeps
    re-marking an already-marked type from growing extra indirection)."""
    assert markUpFieldType('*Image') == '*(Image)'


def test_bounded_primitive_array_stays_inline():
    """Primitive bounded arrays are inline struct data, never pointered."""
    assert markUpFieldType('float[4]') == 'float[4]'
    assert markUpFieldType('float[some_count]') == 'float[some_count]'
