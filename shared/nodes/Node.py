import bpy

# Main node class
class Node:
    # The number of bytes to represent this node, treating sub nodes as pointers
    length = 0

    # This constructor should be overriden with a constructor which also includes the 
    # specific fields for that node. This constructor should be called via super() in the sub
    # sub class' constructor.
    # When initialised in fromBinary(), blender_obj should be None. It will be filled in when the tree
    # is parsed to import into blender.
    # When initialised in fromBlender(), address should be None. It will be filled in when the tree
    # is parsed to write to the output file.
    def __init__(self, className, address, blender_obj):
        # The offset where the node starts in the binary file.
        # When writing the file this offset won't be known until the node is written.
        # At that time, this can be updated so it's clear if it still needs to be written or not
        self.address = address
        # Reference to corresponding blender object, should only be set to persistent objects (e.g not edit bones).
        # When reading the file this won't have been created yet but it can be updated later.
        self.blender_obj = blender_obj
        # The name of the node's class
        self.className = className

    # Parse struct from binary file.
    # Use the parser to read the binary for the fields and then do any conversions or calculations
    # required to turn that value into the final field values to pass into the constructor.
    @classmethod
    def fromBinary(cls, parser, address):
        #Override this in sub classes
        pass

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        #Override this in sub classes
        pass

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    # At the time most nodes are being written, the builder's position should be at the end of the file
    # so no address needs to be specified. Just write it at the end. If the write location needs to be specific
    # then seek() to the end of the file before returning.
    # This function should return the address where the first field for this node is written, after all sub nodes have
    # finished being written.
    def write(self, builder):
        #Override this in sub classes
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        #Override this in sub classes
        pass