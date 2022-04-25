import bpy

# Abstract node class
class Node(object):
    # The name of this type of Node
    class_name = "Node"
    # A list of the field names and field types for each field in this array
    fields = []
    # Most nodes can be cached by some like convenience nodes for handling lists may not be good to cache
    is_cachable = True

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
    def loadFromBinary(self, parser):
        parser.parseNode(self)

    # For any fields which are a pointer where the underlying sub type is a primitive type,
    # write them to the builder's output and replace the field with the address it was written to
    def writePrimitivePointers(self, builder):
        pass

    # Tells the builder how many bytes to reserve for this node.
    def alocationSize(self):
        pass

    # Tells the builder how to write this node's data to the binary file.
    # The node should have had its write address allocated by the builder by the time this is called.
    def writeBinary(self, builder):
        if self.address == None:
            return
        

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        #Override this in sub classes
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        #Override this in sub classes
        pass

    # TODO: confirm if the convention is depth first or breadth first write
    def toList(self):
        node_list = [self]

        for field in self.fields:
            value = getattr(self, field)
            if isinstance(value, Node):
                node_list += value.toList()

        return node_list

    # This recursively creates a textual representation of the tree starting at this node.
    # This implementation may lead to an infinite cycle if there are nodes with cyclic references.
    # We'll cross that bridge when we get to it. 
    def __str__(self):

        def fieldWeight(field):
            field_name = field[0]
            attr = getattr(self, field_name)
            if isinstance(attr, Node):
                return 3
            elif isinstance(attr, list):
                return 2
            else:
                return 1

        text = "-> " + self.class_name + " @" + hex(self.address) + " (" + str(self.length) + " bytes)\n"

        sorted_fields = sorted(self.fields, key=fieldWeight)
        for (field_name, field_type) in sorted_fields:
            attr = getattr(self, field_name)

            if isinstance(attr, list):
                text += "  " + field_name.replace("_", " ") + ": \n"
                for index, sub_attr in enumerate(attr):
                    substring = str(sub_attr)
                    sublines = substring.split("\n")
                    
                    field_name_prefix = "    " + str(index + 1) + " "
                    if field_type == 'matrix':
                        field_name_prefix = "    "
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










