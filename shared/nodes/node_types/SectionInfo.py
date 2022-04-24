from ..Node import Node
from .SceneData import SceneData

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
        # TODO: parse bound box and any other section types that may be present in other games

        return node

    def loadFromBinary(self, parser):
        parser.parseNode(self)

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder, string_address):
        writeAddress = builder.currentRelativeAddress()

        # The root node is written beforehand so all sections have their trees written before the section info is added
        # at the end in bulk
        builder.write("uint", root_node.address)
        builder.write("uint", string_address)
        
        return writeAddress

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass