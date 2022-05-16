# Abstract node class
class Node(object):
    # The name of this type of Node
    class_name = "Node"

    # A list of the field names and field types for each field in this array
    fields = []

    # Most nodes can be cached but some need to skip the caching logic
    # Such as some which are sub structs which don't represent their own individual node.
    # If they are the first field of the containing node then that address would already be cached
    # as the container but we'd still need to read the sub struct at that address.
    is_cachable = True

    # Determines if the node should be in the main data section of the model. The header and section
    # info nodes are outside of this but for nodes within it we can make sure they're being read
    # from within the expected range. Attempting to read one from outside the data section tells us
    # something went wrong.
    is_in_data_section = True

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
        # Prevent reference cycles when traversing tree
        self.is_being_printed = False
        self.is_being_listed = False

    # Parse struct from binary file.
    # Use the parser to read the binary for the fields and then do any conversions or calculations
    # required to update those values or set extra meta data
    def loadFromBinary(self, parser):
        parser.parseNode(self)

    # For any fields which are a pointer where the underlying sub type is a primitive type (but not a string),
    # write them to the builder's output and replace the field with the address it was written to
    def writePrimitivePointers(self, builder):
        pass

    # For any fields which are a pointer to a string, write the string to the builder and replace
    # the property's value with the address it was written to
    def writeStringPointers(self, builder):
        pass

    # Tells the builder how many bytes to reserve for this node.
    def allocationSize(self):
        pass

    # Tells the builder how far into the reserved region the node itself should start.
    # Some nodes may need to output some data within that region so pointers to the node need to
    # be offset to the point in the allocated region where the node's own data starts.
    def allocationOffset(self):
        return 0

    # Tells the builder how to write this node's data to the binary file.
    # The node should have had its write address allocated by the builder by the time this is called.
    def writeBinary(self, builder):
        if self.address == None:
            return
        builder.writeNode(self)

    # TODO: confirm if the convention is depth first or breadth first write.
    # Converts the node tree into an list of every node present in the tree.
    def toList(self):
        # Prevent infinite cycles
        if self.is_being_listed:
            return []

        self.is_being_listed = True

        node_list = [self]

        def isNodeAlreadyInList(new_node):
            for node in node_list:
                if new_node.address == node.address:
                    return True
            return False

        def addToListUniquely(nodes):
            for node in nodes:
                if not isNodeAlreadyInList(node):
                    node_list.append(node)

        # Recursively get the lists for any sub nodes. If a field is a list then
        # get the node lists of each node in that list.
        for field in self.fields:
            field_name = field[0]
            value = getattr(self, field_name)

            if isinstance(value, Node):
                addToListUniquely(value.toList())

            elif isinstance(value, list):
                for element in value:
                    if isinstance(element, Node):
                        addToListUniquely(element.toList())

                    elif isinstance(element, list):
                        # We should never have deeper than a 2-dimensional list
                        for sub_element in element:
                            if isinstance(sub_element, Node):
                                addToListUniquely(sub_element.toList())

        self.is_being_listed = False

        return node_list

    # Get a simple representation of just this node
    def stringRepresentation(self):

        def fieldWeight(field):
            field_name = field[0]
            attr = getattr(self, field_name)
            if isinstance(attr, list):
                if len(attr) > 0:
                    if isinstance(attr[0], Node):
                        return 4
                return 2
            elif isinstance(attr, Node):
                return 3
            else:
                return 1

        def stringRep(value):
            if isinstance(value, Node) and value.is_cachable:
                return "-> " + value.class_name + " @" + hex(value.address) + " (" + str(value.length) + " bytes)"
            else:
                return str(value)

        text = stringRep(self).replace("-> ", "*") + "\n"

        sorted_fields = sorted(self.fields, key=fieldWeight)
        for (field_name, field_type) in sorted_fields:
            attr = getattr(self, field_name)

            if isinstance(attr, list):
                text += "  " + field_name.replace("_", " ") + ": \n"
                for index, sub_attr in enumerate(attr):
                    substring = stringRep(sub_attr)
                    sublines = substring.split("\n")
                    
                    field_name_prefix = "    " + str(index + 1) + " "
                    if field_type == 'matrix':
                        field_name_prefix = "    "
                    spacing = "    "

                    for i, line in enumerate(sublines):
                        if len(line) > 0:
                            if i == 0:
                                text += field_name_prefix
                            else:
                                text += spacing
                            text += line + "\n"
            else:
                substring = stringRep(attr)
                sublines = substring.split("\n")
                
                field_name_prefix = "  " + field_name.replace("_", " ") + ": "
                spacing = "    "

                for i, line in enumerate(sublines):
                    if len(line) > 0:
                        if i == 0:
                            text += field_name_prefix
                        else:
                            text += spacing
                        text += line + "\n"

        return text

    # Converts node tree to list format and print each node in order
    def printListRepresentation(self):
        for node in self.toList():
            print(node.stringRepresentation())

    # This recursively creates a textual representation of the tree starting at this node.
    def __str__(self):

        # Prevent infinite cycles
        if self.is_being_printed:
            return "-> " + self.class_name + " @" + hex(self.address) + " (already printed)\n"

        self.is_being_printed = True

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
                        if len(line) > 0:
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
                    if len(line) > 0:
                        if i == 0:
                            text += field_name_prefix
                        else:
                            text += spacing
                        text += line + "\n"

        self.is_being_printed = False

        return text










