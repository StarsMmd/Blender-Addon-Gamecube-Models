#!/usr/bin/env python3
"""
Node tree serializer: .dat/.pkx → JSON

Parses a DAT/PKX model file through the import pipeline (phases 1–3)
and serializes the resulting node trees to a human-readable JSON file.
The JSON format uses a flat node dictionary keyed by hex address to
handle the DAG structure (shared node references).

Usage:
    python3 utilities/dat_to_json.py <input.dat> [output.json]

If no output path is given, writes to <input_stem>_nodes.json in the
same directory as the input file.
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

from importer.phases.extract.extract import extract_dat
from importer.phases.route.route import route_sections
from importer.phases.parse.parse import parse_sections


# Extra attributes set during loadFromBinary that aren't in the fields list.
# Maps class name → list of (attr_name, encoding) where encoding is
# 'bytes' (base64), 'json' (direct), 'int', or 'bool'.
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

# Reverse map from class_name display names to constructor names
# (e.g. "Scene Data" → "SceneData"). Built lazily.
_CLASS_NAME_TO_TYPE = None

def _get_type_name(node):
    """Get the constructor class name for a node (e.g. 'Joint', 'SceneData')."""
    return type(node).__name__


def _collect_all_nodes(sections):
    """Collect all unique nodes from all sections into a dict keyed by address."""
    all_nodes = {}
    for section in sections:
        if section.root_node is None:
            continue
        for node in section.root_node.toList():
            if node.address is not None and node.address not in all_nodes:
                all_nodes[node.address] = node
    return all_nodes


def _serialize_field_value(value, raw_field_type, all_nodes_by_addr):
    """Serialize a single field value to a JSON-compatible representation.

    Some fields are declared as 'uint' in the Node schema but get resolved
    to Node objects during loadFromBinary (e.g. Joint.property, PObject.property).
    We detect this by checking the actual Python type of the value.
    """
    if value is None:
        return None

    # Early check: if the value is a Node regardless of declared type,
    # serialize as a node reference. This handles fields like Joint.property
    # and PObject.property which are declared as 'uint' but resolved to Nodes.
    if isinstance(value, Node) and not raw_field_type.startswith('@'):
        return _node_ref(value)

    # Similarly, if the value is a list of Nodes but the type says 'uint'
    if isinstance(value, list) and len(value) > 0 and isinstance(value[0], Node) and raw_field_type == 'uint':
        return [_node_ref(v) if isinstance(v, Node) else v for v in value]

    marked_up = markUpFieldType(raw_field_type)

    # Inline struct (@-prefixed): serialize as a nested object
    if raw_field_type.startswith('@'):
        if isinstance(value, Node):
            return _node_fields_to_json(value, all_nodes_by_addr)
        return value

    # Peel off brackets
    effective = marked_up
    while isBracketedType(effective):
        effective = getBracketedSubType(effective)

    # Pointer type
    if isPointerType(effective):
        sub = getPointerSubType(effective)
        # Peel sub brackets
        while isBracketedType(sub):
            sub = getBracketedSubType(sub)

        # Pointer to primitive (string, matrix, vec3)
        if is_primitive_type(sub):
            return _serialize_primitive(value, sub)

        # Pointer to unbounded array
        if isUnboundedArrayType(sub):
            if isinstance(value, list):
                elem_sub = getArraySubType(sub)
                while isBracketedType(elem_sub):
                    elem_sub = getBracketedSubType(elem_sub)
                return [_serialize_single_element(v, elem_sub, all_nodes_by_addr) for v in value]
            return value

        # Pointer to bounded array
        if isBoundedArrayType(sub):
            if isinstance(value, list):
                elem_sub = getArraySubType(sub)
                while isBracketedType(elem_sub):
                    elem_sub = getBracketedSubType(elem_sub)
                return [_serialize_single_element(v, elem_sub, all_nodes_by_addr) for v in value]
            return value

        # Pointer to node
        if isinstance(value, Node):
            return _node_ref(value)

        # Pointer to something else (e.g. a raw int that wasn't resolved)
        return value

    # Unbounded array at top level (shouldn't happen after markup, but handle)
    if isUnboundedArrayType(effective):
        if isinstance(value, list):
            elem_sub = getSubType(effective)
            return [_serialize_single_element(v, elem_sub, all_nodes_by_addr) for v in value]

    # Bounded array at top level
    if isBoundedArrayType(effective):
        if isinstance(value, list):
            elem_sub = getSubType(effective)
            return [_serialize_single_element(v, elem_sub, all_nodes_by_addr) for v in value]

    # Plain primitive
    if is_primitive_type(effective):
        return _serialize_primitive(value, effective)

    # Node class type (shouldn't reach here after markup, but handle)
    if isinstance(value, Node):
        return _node_ref(value)

    return value


def _serialize_single_element(value, sub_type, all_nodes_by_addr):
    """Serialize a single element of an array."""
    if value is None:
        return None
    if isinstance(value, Node):
        return _node_ref(value)
    if is_primitive_type(sub_type):
        return _serialize_primitive(value, sub_type)
    # Nested list (e.g. list of lists)
    if isinstance(value, list):
        return [_serialize_single_element(v, sub_type, all_nodes_by_addr) for v in value]
    return value


def _serialize_primitive(value, type_name):
    """Serialize a primitive value."""
    if type_name == 'string':
        return value  # already a string or None
    if type_name == 'vec3':
        return list(value) if hasattr(value, '__iter__') else value
    if type_name == 'matrix':
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return [list(row) for row in value]
        return value
    # Numeric types
    return value


def _node_ref(node):
    """Return a hex address string for a node reference."""
    if node is None:
        return None
    if hasattr(node, 'address') and node.address is not None:
        return hex(node.address)
    return None


def _node_fields_to_json(node, all_nodes_by_addr):
    """Serialize all fields of a node to a dict."""
    fields = {}
    for field_name, raw_field_type in node.fields:
        value = getattr(node, field_name, None)
        fields[field_name] = _serialize_field_value(value, raw_field_type, all_nodes_by_addr)
    return fields


def _serialize_extra_attrs(node):
    """Serialize extra attributes (set in loadFromBinary, not in fields)."""
    type_name = _get_type_name(node)
    extras = EXTRA_ATTRS.get(type_name, [])
    if not extras:
        return {}

    result = {}
    for attr_name, encoding in extras:
        value = getattr(node, attr_name, None)
        if value is None:
            continue

        if encoding == 'bytes':
            if isinstance(value, (bytes, bytearray)):
                result[attr_name] = base64.b64encode(value).decode('ascii')
            else:
                result[attr_name] = value
        elif encoding == 'json':
            result[attr_name] = _deep_convert(value)
        elif encoding == 'int':
            result[attr_name] = int(value)
        elif encoding == 'bool':
            result[attr_name] = bool(value)
        else:
            result[attr_name] = value

    return result


def _deep_convert(value):
    """Recursively convert tuples to lists and ensure JSON compatibility."""
    if isinstance(value, tuple):
        return [_deep_convert(v) for v in value]
    if isinstance(value, list):
        return [_deep_convert(v) for v in value]
    if isinstance(value, dict):
        return {k: _deep_convert(v) for k, v in value.items()}
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(value).decode('ascii')
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    if value is None:
        return None
    # Fallback: try converting to string
    return str(value)


def serialize_node_trees(sections):
    """Convert parsed sections to a JSON-serializable dict.

    Args:
        sections: list of SectionInfo from DATParser.parseSections()

    Returns:
        dict suitable for json.dump()
    """
    all_nodes = _collect_all_nodes(sections)

    # Serialize sections metadata
    sections_json = []
    for section in sections:
        entry = {
            'section_name': section.section_name,
            'root_node_id': hex(section.root_node.address) if section.root_node else None,
        }
        if hasattr(section, 'is_public'):
            entry['is_public'] = section.is_public
        sections_json.append(entry)

    # Serialize each unique node
    nodes_json = {}
    for addr, node in sorted(all_nodes.items()):
        node_data = {
            'class_name': node.class_name,
            'type': _get_type_name(node),
            'fields': _node_fields_to_json(node, all_nodes),
        }
        extra = _serialize_extra_attrs(node)
        if extra:
            node_data['extra'] = extra
        nodes_json[hex(addr)] = node_data

    return {
        'sections': sections_json,
        'nodes': nodes_json,
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    if not os.path.exists(input_path):
        print(f"Error: input file not found: {input_path}")
        sys.exit(1)

    # Determine output path
    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        input_dir = os.path.dirname(input_path)
        input_stem = os.path.splitext(os.path.basename(input_path))[0]
        output_path = os.path.join(input_dir, input_stem + '_nodes.json')

    # Read input file
    with open(input_path, 'rb') as f:
        raw_bytes = f.read()

    filename = os.path.basename(input_path)

    # Phase 1: Extract DAT bytes
    results = extract_dat(raw_bytes, filename)
    if not results:
        print("Error: no DAT data found in file")
        sys.exit(1)

    # Use the first extracted DAT (for multi-model FSYS, could be extended)
    dat_bytes, metadata = results[0]

    # Phase 2: Route sections
    section_map = route_sections(dat_bytes)

    # Phase 3: Parse node trees
    options = {}
    sections = parse_sections(dat_bytes, section_map, options)

    print(f"Parsed {len(sections)} section(s):")
    for s in sections:
        root_type = _get_type_name(s.root_node) if s.root_node else 'None'
        print(f"  {s.section_name} -> {root_type}")

    # Serialize to JSON
    json_data = serialize_node_trees(sections)

    with open(output_path, 'w') as f:
        json.dump(json_data, f, indent=2)

    node_count = len(json_data['nodes'])
    print(f"Wrote {node_count} nodes to {output_path}")


if __name__ == '__main__':
    main()
