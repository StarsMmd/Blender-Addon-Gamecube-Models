import bpy

# Abstract node class
class Node(object):
    # The name of this type of Node
    class_name = "Node"
    # The number of bytes to represent this node, treating sub nodes as pointers
    length = 0
    # A list of the field names and field types for each field in this array
    fields = []

    # When initialised in fromBinary(), blender_obj should be None. It will be filled in when the tree
    # is parsed to import into blender.
    # When initialised in fromBlender(), address should be None. It will be filled in when the tree
    # is parsed to write to the output file.
    def __init__(self, address, blender_obj):
        # The offset where the node starts in the binary file.
        # When writing the file this offset won't be known until the node is written.
        # At that time, this can be updated so it's clear if it still needs to be written or not
        self.address = address
        # Reference to corresponding blender object, should only be set to persistent objects (e.g not edit bones).
        # When reading the file this won't have been created yet but it can be updated later.
        self.blender_obj = blender_obj

    # Parse struct from binary file.
    # Use the parser to read the binary for the fields and then do any conversions or calculations
    # required to update those values or set extra meta data
    @classmethod
    def fromBinary(cls, parser, address):
        #Override this in sub classes
        pass

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    # This function returns the address where the first field for this node is written, after all sub nodes have
    # finished being written.
    def writeBinary(self, builder):
        #Override this in sub classes
        pass

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        #Override this in sub classes
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        #Override this in sub classes
        pass

    # This recursively creates a textual representation of the tree starting at this node
    def __str__(self):
        text = "-> " + self.class_name + " @" + hex(self.address) + " (" + str(self.length) + " bytes)\n"

        for (field_name, _) in self.fields:
            attr = getattr(self, field_name)

            if isinstance(attr, list):
                text += "  " + field_name.replace("_", " ") + ": \n"
                for index, sub_attr in enumerate(attr):
                    substring = str(sub_attr)
                    sublines = substring.split("\n")
                    
                    field_name_prefix = "    " + str(index + 1) + " "
                    spacing = "    "

                    for i, line in enumerate(sublines):
                        if i == 0:
                            text += field_name_prefix
                        else:
                            text += spacing
                        text += line + "\n"
            else:
                substring = str(attr)
                sublines = substring.split("\n")
                
                field_name_prefix = "  " + field_name.replace("_", " ") + ": "
                spacing = "    "

                for i, line in enumerate(sublines):
                    if i == 0:
                        text += field_name_prefix
                    else:
                        text += spacing
                    text += line + "\n"

        return text










