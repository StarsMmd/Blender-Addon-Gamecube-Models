from .. import Node
from .. import PointerArray

class ModelSetArray(PointerArray):
    node_class = ModelSet
    node_type = "Model Set"

# Scene Data
class SceneData(Node):
    def __init__(self, blender_obj, address, model_sets, camera_set, light_sets, fog):
        super().__init__("Scene Data", address, blender_obj)
        self.model_sets = model_sets
        self.camera_set = camera_set
        self.light_sets = light_sets
        self.fog = fog

    # Parse struct from binary file.
    @classmethod
    def fromBinary(cls, parser, address):
        model_sets_pointer = parser.read("uint", address,  0)
        camera_set_pointer = parser.read("uint", address,  4)
        light_sets_pointer = parser.read("uint", address,  8)
        fog_pointer        = parser.read("uint", address, 12) 

        model_sets = parser.parseNode(ModelSetArray, model_sets_pointer)
        camera_set = parser.parseNode(CameraSet, camera_set_pointer)
        light_sets = parser.parseNode(LightSetArray, light_sets_pointer)
        fog        = parser.parseNode(Fog, fog_pointer)

        return SceneData(None, address, model_sets, camera_set, light_sets, fog)

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def write(self, builder):
        model_sets_pointer = builder.writeNode(self.model_sets)
        camera_set_pointer = builder.writeNode(self.camera_set)
        light_sets_pointer = builder.writeNode(self.light_sets)
        fog_pointer        = builder.writeNode(self.fog)

        writeAddress = builder.currentRelativeAddress()

        builder.write("uint", model_sets_pointer)
        builder.write("uint", camera_set_pointer)
        builder.write("uint", light_sets_pointer)
        builder.write("uint", fog_pointer)
        
        return writeAddress

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        model_sets.toBlender(context)
        camera_set.toBlender(context)
        light_sets.toBlender(context)
        fog.toBlender(context)

        # TODO: each of these sub nodes should now have their .blender_obj field set
        # Use this to set up the blender object for the scene and assign the result to this node's
        # blender_obj field






