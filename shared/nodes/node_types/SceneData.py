from .. import Node

# Scene Data
class SceneData(Node):
    class_name = "Scene Data"
    length = 16
    fields = [
        ('model_sets', '*(ModelSet[])'),
        ('camera_set', 'CameraSet'),
        ('light_sets', '*(LightSet[])'),
        ('fog', 'Fog')
    ]

    # Parse struct from binary file.
    @classmethod
    def fromBinary(cls, parser, address):
        return parser.parseStruct(cls, address)

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder):
        return builder.writeStruct(self)

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        model_sets.toBlender(context)
        camera_set.toBlender(context)
        light_sets.toBlender(context)
        fog.toBlender(context)

        # TODO: each of these sub nodes should now have their .blender_obj field set
        # Use this to set up the blender object for the scene and assign the result to this node's
        # blender_obj field






