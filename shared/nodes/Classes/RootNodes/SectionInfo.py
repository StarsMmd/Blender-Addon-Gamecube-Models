from ...Node import Node
from .SceneData import SceneData
from .BoundBox import BoundBox

# Section Info
class SectionInfo(Node):
    class_name = "Section"

    length = 8

    fields = [
        ("root_node", "uint"), # the type of node to parse depends on the section name
        ("section_name", "uint")
    ]

    @classmethod
    def readFromBinary(cls, parser, address, is_public, strings_offset):
        node = parser.read('SectionInfo', address)
        node.is_public = is_public
        node.section_name = parser.read('string', strings_offset, node.section_name)

        # We initially parse the root node as the raw pointer, then based on the section name
        # we can now decide what type of node to parse from that address
        if node.section_name == "scene_data":
            node.root_node = parser.read('SceneData', node.root_node)
        if node.section_name == "bound_box":
            node.root_node = parser.read('BoundBox', node.root_node)
        # TODO: parse any other section types that may be present in other games

        return node

