from .NodeTypes import get_type_length, get_alignment_at_offset, markUpFieldType, isNodeClassType
from ..Constants.RecursiveTypes import (
    isBracketedType, getBracketedSubType, isPointerType, getPointerSubType,
    isUnboundedArrayType, getArraySubType, isArrayType
)
from ..Constants.PrimitiveTypes import is_primitive_type

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

    # Override in subclasses that have SHARED raw data written at the very start
    # of the data section (Phase 1). In practice this is only VertexList today —
    # palettes and images now write later via writePaletteData / writeImageData
    # so the data section matches Sysdolphin's compiler layout (vertex buffers
    # first, parsed structs in the middle, palettes + images last).
    def writePrimitivePointers(self, builder):
        pass

    # Write palette LUT data (Phase 3a). Default no-op — Palette overrides.
    def writePaletteData(self, builder):
        pass

    # Write image pixel data (Phase 3b). Default no-op — Image overrides.
    def writeImageData(self, builder):
        pass

    # Subtree serialization order. Sysdolphin writes some subtrees (the bone
    # and material animation joint trees) in a non-DFS order — all of the
    # tree's leaf data first, then each structural layer. A node type that
    # owns such a subtree sets ``serializes_subtree = True`` and overrides
    # this on its *root* node to return a flat, ordered list of the subtree's
    # nodes; the DATBuilder writes that list as a block (pooling consecutive
    # Frame runs). Default None = use the builder's DFS order.
    serializes_subtree = False

    def serializationOrder(self):
        return None

    # Direct-children traversal order. Some node types emit their immediate
    # child structs in an order that differs from field-declaration order
    # (e.g. MaterialObject leads with its PixelEngine). A node type overrides
    # this with a list of field names to declare the order its Node-typed
    # fields are visited (and thus emitted) during the builder's DFS; listed
    # fields go first in the given order, the rest keep their declared order.
    # None = use field-declaration order.
    serialization_field_order = None

    # Write this node's PRIVATE raw data immediately before the node's struct allocation.
    # Called during Phase 2 (DFS post-order) for each node.
    # Handles: pointer-to-primitive fields (strings, matrices), pointer arrays for
    # unbounded Node array fields, and subclass-specific data (display lists, frame ad, etc.)
    #
    # Subclasses that write raw data for 'uint' fields (which are actually pointers) should:
    #   1. Call super().writePrivateData(builder) first
    #   2. Write additional data and set the field to the address
    #   3. Add the field name to self._raw_pointer_fields so a relocation is recorded in Phase 3
    def writePrivateData(self, builder):
        if not hasattr(self, '_raw_pointer_fields'):
            self._raw_pointer_fields = set()

        for field in self.fields:
            field_name = field[0]
            raw_field_type = field[1]
            field_type = markUpFieldType(raw_field_type)
            field_value = getattr(self, field_name)

            # Skip inline struct types (@-prefixed) — they're written as part of the node struct
            if raw_field_type.startswith('@') or '(@' in raw_field_type:
                continue

            # Write pointer-to-primitive data (strings, matrices)
            if isBracketedType(field_type):
                inner = getBracketedSubType(field_type)
                if isPointerType(inner):
                    sub_type = getPointerSubType(inner)
                    if field_value is None:
                        setattr(self, field_name, 0)
                    elif is_primitive_type(sub_type):
                        pointer = builder.write(field_value, sub_type)
                        setattr(self, field_name, pointer)
                    elif isinstance(field_value, list):
                        # Only write pointer arrays for lists of nodes that have allocated addresses
                        has_addressed_nodes = (len(field_value) > 0
                            and hasattr(field_value[0], 'address')
                            and field_value[0].address is not None)
                        if has_addressed_nodes:
                            # Pointer array for unbounded Node array fields (e.g. ModelSet[], LightSet[])
                            resolved = []
                            for v in field_value:
                                if hasattr(v, 'address') and v.address is not None:
                                    resolved.append(v.address)
                                elif v is None:
                                    resolved.append(0)
                                else:
                                    resolved.append(v)

                            builder.seek(0, 'end')
                            array_addr = builder._currentRelativeAddress()
                            for addr in resolved:
                                if addr != 0:
                                    builder.relocations.append(builder._currentRelativeAddress())
                                builder.write(addr, 'uint')
                            # Null terminator
                            builder.write(0, 'uint')
                            setattr(self, field_name, array_addr)

            elif isPointerType(field_type):
                sub_type = getPointerSubType(field_type)
                if field_value is None:
                    setattr(self, field_name, 0)
                elif is_primitive_type(sub_type):
                    pointer = builder.write(field_value, sub_type)
                    setattr(self, field_name, pointer)
                # Pointer-to-array fields with list values (e.g.
                # '*(Image[count])') are materialized by _writePointerTables
                # during writeBinary — the entry nodes only receive their new
                # addresses after this phase, so writing the table here would
                # bake stale pointers.

    def pointerTableFields(self):
        """Fields declared as a pointer to an array whose current value is a
        list of parsed entries — e.g. '*(Image[image_table_count])'. The
        parser reads these into lists; the write side materializes each list
        as a pointer table placed immediately before the struct (space
        reserved via allocationSize/allocationOffset, bytes emitted by
        _writePointerTables). Returns [(field_name, element_type, values,
        null_terminated)] in field-declaration order."""
        tables = []
        for field_name, declared in self.fields:
            marked = markUpFieldType(declared)
            if not isPointerType(marked):
                continue
            pointee = getPointerSubType(marked)
            if not isArrayType(pointee):
                continue
            values = getattr(self, field_name, None)
            if isinstance(values, list) and values:
                tables.append((field_name, getArraySubType(pointee), values,
                               isUnboundedArrayType(pointee)))
        return tables

    def pointerTablesSize(self):
        """Total bytes of all pointer tables this node materializes."""
        total = 0
        for _, element_type, values, terminated in self.pointerTableFields():
            total += (len(values) + (1 if terminated else 0)) * get_type_length(element_type)
        return total

    def _writePointerTables(self, builder):
        """Write this node's pointer tables into the reserved space directly
        before the struct, then point each field at its table."""
        tables = self.pointerTableFields()
        if not tables:
            return
        cursor = self.address - self.pointerTablesSize()
        for field_name, element_type, values, terminated in tables:
            element_length = get_type_length(element_type)
            table_address = cursor
            for value in values:
                if isinstance(value, Node) or value is None:
                    address = value.address if value is not None and value.address is not None else 0
                    if value is not None:
                        builder.relocations.append(cursor)
                    builder.write(address, 'uint', cursor, relative_to_header=True)
                else:
                    builder.write(value, element_type, cursor, relative_to_header=True)
                cursor += element_length
            if terminated:
                if element_length != 4:
                    raise ValueError(
                        'Null-terminated pointer table %s.%s has element size %d (expected 4)'
                        % (type(self).__name__, field_name, element_length))
                builder.write(0, 'uint', cursor, relative_to_header=True)
                cursor += element_length
            setattr(self, field_name, table_address)
            if table_address == 0:
                # writeNode only relocates non-zero pointer fields; a table at
                # data-section offset 0 needs the forced-relocation path.
                self._raw_pointer_fields.add(field_name)

    # Tells the builder how many bytes to reserve for this node.
    def allocationSize(self):
        size = 0
        for field in self.fields:
            field_type = markUpFieldType(field[1])
            size += get_type_length(field_type) + get_alignment_at_offset(field_type, size)
        return size + self.pointerTablesSize()

    # Tells the builder how far into the reserved region the node itself should start.
    # Some nodes may need to output some data within that region so pointers to the node need to
    # be offset to the point in the allocated region where the node's own data starts.
    def allocationOffset(self):
        return self.pointerTablesSize()

    # Tells the builder how to write this node's data to the binary file.
    # The node should have had its write address allocated by the builder by the time this is called.
    def writeBinary(self, builder):
        if self.address == None:
            return
        self._writePointerTables(builder)
        builder.writeNode(self, relative_to_header=True)

        # Record relocations for 'uint' fields that actually hold pointer addresses
        # (set by subclass writePrimitivePointers via _raw_pointer_fields)
        raw_fields = getattr(self, '_raw_pointer_fields', set())
        if raw_fields:
            offset = 0
            for field in self.fields:
                field_type = markUpFieldType(field[1])
                offset += get_alignment_at_offset(field_type, self.address + offset)
                if field[0] in raw_fields:
                    # Pointer-declared fields are already relocated by
                    # writeNode (its force_reloc path covers value 0);
                    # relocating here too would emit a duplicate entry.
                    inner = getBracketedSubType(field_type) if isBracketedType(field_type) else field_type
                    handled_by_write_node = isPointerType(inner) or isNodeClassType(inner)
                    value = getattr(self, field[0])
                    if isinstance(value, int) and not handled_by_write_node:
                        # Always relocate _raw_pointer_fields — even value 0
                        # is a valid data-section-relative pointer (offset 0).
                        builder.relocations.append(self.address + offset)
                offset += get_type_length(field_type)

    # TODO: confirm if the convention is depth first or breadth first write.
    # Converts the node tree into an list of every node present in the tree.
    def toList(self):
        # Prevent infinite cycles
        if self.is_being_listed:
            return []

        self.is_being_listed = True

        node_list = [self]
        seen_addresses = {self.address}

        def addToListUniquely(nodes):
            for node in nodes:
                if node.address not in seen_addresses:
                    seen_addresses.add(node.address)
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
                return "-> " + value.class_name + " @" + hex(value.address) + " (" + str(getattr(value, '_struct_size', '?')) + " bytes)"
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

        text = "-> " + self.class_name + " @" + hex(self.address) + " (" + str(getattr(self, '_struct_size', '?')) + " bytes)\n"

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
