#!/usr/bin/env python3
"""
Node tree deserializer: JSON → node trees → IR

Reads a JSON file produced by dat_to_json.py, reconstructs the parsed
node trees, and pipes them through the describe phase (Phase 4) to
produce an IRScene. Prints an IR summary to stdout.

Usage:
    python3 utilities/json_to_ir.py <input.json>
"""
import sys
import os
import json
import base64

# Add the addon directory to the path so shared modules are importable
addon_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

# Mock Blender modules so imports don't fail outside Blender
from unittest.mock import MagicMock
for mod in ('bpy', 'bpy.types', 'bpy.props', 'bpy_extras', 'bpy_extras.io_utils', 'mathutils'):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from shared.Nodes.Node import Node
from shared.Nodes.NodeTypes import markUpFieldType, isNodeClassType
from shared.Constants.PrimitiveTypes import is_primitive_type
from shared.Constants.RecursiveTypes import (
    isBracketedType, getBracketedSubType,
    isPointerType, getPointerSubType,
    isUnboundedArrayType, isBoundedArrayType,
    getArraySubType, getSubType,
)
from shared.ClassLookup.get_class_from_name import get_class_from_name
from shared.Nodes.Classes.RootNodes.SectionInfo import SectionInfo

from importer.phases.describe.describe import describe_scene


# Extra attributes that need to be restored (mirrors dat_to_json.EXTRA_ATTRS)
EXTRA_ATTRS = {
    'Frame': [('raw_ad', 'bytes')],
    'PObject': [
        ('raw_display_list', 'bytes'),
        ('sources', 'json'),
        ('face_lists', 'json'),
        ('normals', 'json'),
    ],
    'Image': [('raw_image_data', 'bytes')],
    'Palette': [('raw_data', 'bytes')],
    'Vertex': [('raw_vertex_data', 'bytes')],
    'BoundBox': [('raw_aabb_data', 'bytes')],
    'Reference': [('sub_type', 'int')],
    'BoneReference': [('pole_flip', 'bool')],
}


def deserialize_node_trees(json_data):
    """Reconstruct parsed sections from JSON data.

    Two-pass approach:
      Pass 1: Instantiate nodes, set primitive fields.
      Pass 2: Resolve node references (address strings → Node objects).

    Args:
        json_data: dict loaded from JSON (as produced by dat_to_json.serialize_node_trees)

    Returns:
        list of SectionInfo with reconstructed root nodes.
    """
    nodes_json = json_data['nodes']
    sections_json = json_data['sections']

    # Pass 1: Instantiate all nodes and set primitive fields
    nodes_by_addr = {}
    for addr_hex, node_data in nodes_json.items():
        addr = int(addr_hex, 16)
        type_name = node_data['type']
        node_class = get_class_from_name(type_name)
        if node_class is None:
            raise ValueError(f"Unknown node type: {type_name}")

        node = node_class(addr, None)
        nodes_by_addr[addr_hex] = node

    # Pass 2: Set fields and resolve references
    for addr_hex, node_data in nodes_json.items():
        node = nodes_by_addr[addr_hex]
        fields_json = node_data.get('fields', {})

        for field_name, raw_field_type in node.fields:
            json_value = fields_json.get(field_name)
            resolved = _resolve_field_value(json_value, raw_field_type, nodes_by_addr)
            setattr(node, field_name, resolved)

        # Restore extra attributes
        extra = node_data.get('extra', {})
        type_name = node_data['type']
        for attr_name, encoding in EXTRA_ATTRS.get(type_name, []):
            if attr_name not in extra:
                # Set defaults for expected extra attrs
                if encoding == 'bytes':
                    setattr(node, attr_name, b'')
                continue
            value = extra[attr_name]
            if encoding == 'bytes':
                setattr(node, attr_name, base64.b64decode(value))
            elif encoding == 'json':
                setattr(node, attr_name, value)
            elif encoding == 'int':
                setattr(node, attr_name, int(value))
            elif encoding == 'bool':
                setattr(node, attr_name, bool(value))
            else:
                setattr(node, attr_name, value)

    # Build SectionInfo wrappers
    sections = []
    for section_data in sections_json:
        section = SectionInfo(0, None)
        section.section_name = section_data['section_name']
        section.is_public = section_data.get('is_public', True)

        root_id = section_data.get('root_node_id')
        if root_id and root_id in nodes_by_addr:
            section.root_node = nodes_by_addr[root_id]
        else:
            section.root_node = None

        sections.append(section)

    return sections


def _resolve_field_value(json_value, raw_field_type, nodes_by_addr):
    """Resolve a JSON field value back to its Python representation."""
    if json_value is None:
        return None

    marked_up = markUpFieldType(raw_field_type)

    # Inline struct (@-prefixed): resolve as a sub-node with fields set
    if raw_field_type.startswith('@'):
        struct_type = raw_field_type[1:]
        node_class = get_class_from_name(struct_type)
        if node_class and isinstance(json_value, dict):
            struct_node = node_class(0, None)
            struct_node.is_cachable = False
            for fname, ftype in node_class.fields:
                if fname in json_value:
                    setattr(struct_node, fname, _resolve_field_value(json_value[fname], ftype, nodes_by_addr))
            return struct_node
        return json_value

    # Peel off brackets
    effective = marked_up
    while isBracketedType(effective):
        effective = getBracketedSubType(effective)

    # Pointer type
    if isPointerType(effective):
        sub = getPointerSubType(effective)
        while isBracketedType(sub):
            sub = getBracketedSubType(sub)

        # Pointer to primitive
        if is_primitive_type(sub):
            return _resolve_primitive(json_value, sub)

        # Pointer to unbounded array
        if isUnboundedArrayType(sub):
            if isinstance(json_value, list):
                elem_sub = getArraySubType(sub)
                while isBracketedType(elem_sub):
                    elem_sub = getBracketedSubType(elem_sub)
                return [_resolve_single_element(v, elem_sub, nodes_by_addr) for v in json_value]
            return json_value

        # Pointer to bounded array
        if isBoundedArrayType(sub):
            if isinstance(json_value, list):
                elem_sub = getArraySubType(sub)
                while isBracketedType(elem_sub):
                    elem_sub = getBracketedSubType(elem_sub)
                return [_resolve_single_element(v, elem_sub, nodes_by_addr) for v in json_value]
            return json_value

        # Pointer to node: resolve hex address string
        if isinstance(json_value, str) and json_value.startswith('0x'):
            return nodes_by_addr.get(json_value)

        return json_value

    # Plain primitive
    if is_primitive_type(effective):
        return _resolve_primitive(json_value, effective)

    # Node reference
    if isinstance(json_value, str) and json_value.startswith('0x'):
        return nodes_by_addr.get(json_value)

    return json_value


def _resolve_single_element(value, sub_type, nodes_by_addr):
    """Resolve a single element of an array."""
    if value is None:
        return None
    if isinstance(value, str) and value.startswith('0x'):
        return nodes_by_addr.get(value)
    if is_primitive_type(sub_type):
        return _resolve_primitive(value, sub_type)
    if isinstance(value, list):
        return [_resolve_single_element(v, sub_type, nodes_by_addr) for v in value]
    return value


def _resolve_primitive(value, type_name):
    """Resolve a JSON primitive value to its Python representation."""
    if type_name == 'string':
        return value
    if type_name == 'vec3':
        if isinstance(value, list) and len(value) == 3:
            return tuple(value)
        return value
    if type_name == 'matrix':
        if isinstance(value, list):
            return [list(row) if isinstance(row, list) else row for row in value]
        return value
    # Numeric types: JSON already stores them correctly
    return value


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    if not os.path.exists(input_path):
        print(f"Error: input file not found: {input_path}")
        sys.exit(1)

    with open(input_path, 'r') as f:
        json_data = json.load(f)

    print(f"Loaded {len(json_data['nodes'])} nodes from {input_path}")

    # Reconstruct node trees
    sections = deserialize_node_trees(json_data)
    print(f"Reconstructed {len(sections)} section(s):")
    for s in sections:
        root_type = type(s.root_node).__name__ if s.root_node else 'None'
        print(f"  {s.section_name} -> {root_type}")

    # Run describe phase
    options = {}
    ir_scene = describe_scene(sections, options)

    # Print IR summary
    print(f"\n--- IR Summary ---")
    print(f"Models: {len(ir_scene.models)}")
    for i, model in enumerate(ir_scene.models):
        print(f"  Model {i}: '{model.name}'")
        print(f"    Bones: {len(model.bones)}")
        print(f"    Meshes: {len(model.meshes)}")
        print(f"    Bone animations: {len(model.bone_animations)}")
        print(f"    IK constraints: {len(model.ik_constraints)}")
        print(f"    Copy location constraints: {len(model.copy_location_constraints)}")
        print(f"    Track-to constraints: {len(model.track_to_constraints)}")
        print(f"    Copy rotation constraints: {len(model.copy_rotation_constraints)}")
        print(f"    Limit rotation constraints: {len(model.limit_rotation_constraints)}")
        print(f"    Limit location constraints: {len(model.limit_location_constraints)}")
    print(f"Lights: {len(ir_scene.lights)}")

    return ir_scene


if __name__ == '__main__':
    main()
