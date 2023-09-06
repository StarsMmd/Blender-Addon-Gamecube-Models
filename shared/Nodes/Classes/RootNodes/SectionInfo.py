from ...Node import Node
from ...Dummy import Dummy

# Section Info
class SectionInfo(Node):
    class_name = "Section"

    length = 8
    is_in_data_section = False

    fields = [
        ("root_node", "uint"), # the type of node to parse depends on the section name
        ("section_name", "uint")
    ]

    @classmethod
    def readFromBinary(cls, parser, address, is_public, strings_offset):
        node = parser.read('SectionInfo', address)
        node.is_public = is_public
        node.section_name = parser.read('string', strings_offset, node.section_name)
        return node

    def readNodeTree(self, parser):
        # We initially parse the root node as the raw pointer, then based on the section name
        # we can now decide what type of node to parse from that address
        if self.section_name == "scene_data":
            self.root_node = parser.read('SceneData', self.root_node)
        elif self.section_name == "bound_box":
            self.root_node = parser.read('BoundBox', self.root_node)
        elif self.section_name == "scene_camera":
            self.root_node = parser.read('CameraSet', self.root_node)
        elif "shapeanim_joint" in self.section_name.lower():
            self.root_node = parser.read('AnimatedShapeJoint', self.root_node)
        elif "matanim_joint" in self.section_name.lower():
            self.root_node = parser.read('AnimatedMaterialJoint', self.root_node)
        elif "_joint" in self.section_name.lower():
            self.root_node = parser.read('Joint', self.root_node)
        else:
            # TODO: Either add more string analysis to figure out the intended section type
            # or get the user to decide to provide the section type
            dummy = Dummy(self.root_node, None)
            dummy.class_name = "Unrecognised root node at section_name: " + self.section_name
            self.root_node = dummy
            
        # TODO: parse any other section types that may be present in other games


