import file_io
import nodes
import nodes.node_types


# Helpers
def _isPrimitiveType(field_type):
	return field_type in primitive_field_types

def _isBracketedType(field_type):
	return field_type[0:1] == "(" and field_type[-1:] == ")"

def _isPointerType(field_type):
	return !_isArrayType(field_type) and field_type[0:1] == "*" or field_type[0:1] in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" or field_type == "string"

def _isUnboundedArrayType(field_type):
	return field_type[-2:] == "[]"

def _isBoundedArrayType(field_type):
	return !_isUnboundedArrayType(field_type) and "[" in field_type and  field_type[-1:] == "]"

def _isArrayType(field_type):
	return _isUnboundedArrayType(field_type) or _isBoundedArrayType(field_type)

def _isNodeClassType(field_type):
	return !_isArrayType(field_type) and _getClassWithName(field_type) != None

def _getClassWithName(class_name):
	return globals()[field_type]

def _getBracketedSubType(field_type):
	sub_type = field_type
	while _isBracketedType(sub_type):
		sub_type = sub_type[1:-1]
	return sub_type

def _getPointerSubType(field_type):
	sub_type = field_type[1:]
	return _getBracketedSubType(sub_type)

def _getArraySubType(field_type):
	sub_type = field_type
	last = field_type[-1:]
	if last == "]":
		while last != "[":
			last = sub_type[-1:]
			sub_type = sub_type[0:-1]

	return _getBracketedSubType(sub_type)

def _getArrayTypeBound(field_type):
	bound_string = ""
	current_char_index = -1
	current_char = field_type[-1:]
	if current_char == "]":
		while current_char != "[":
			current_char_index -= 1
			current_char = field_type[current_char_index:current_char_index+1]
			if current_char != "[":
				bound_string = current_char + bound_string

	if bound_string == "":
		return None

	return int(bound_string)
	

def _getTypeLength(field_type):
	if _isBracketedType(field_type):
		return _getTypeLength(_getBracketedSubType(field_type))

	elif _isPrimitiveType(field_type):
		if field_type == 'uchar' or field_type == 'char':
			return 1
		elif field_type == 'ushort' or field_type == 'short':
			return 2
		elif field_type == 'string':
			# strings are always pointers to a string elsewhere
			return 4
		elif field_type == 'double':
			return 8
		else:
			return 4

    elif _isPointerType(field_type):
    	return 4

    elif _isUnboundedArrayType(field_type):
    	# These should never be the sub type of another field other than pointer
    	# so we should never need to stride by their length
    	return None

    elif _isBoundedArrayType(field_type):
    	return _getTypeLength(_getArraySubType(field_type)) * _getArrayTypeBound(field_type)

    elif _isNodeClassType(field_type):
    	return _getClassWithName(field_type).length

    else:
    	return None

def _alignmentForTypeAtAddress(field_type, address):
	if _isBracketedType(field_type):
		return _alignmentForTypeAtAddress(_getBracketedSubType(field_type), address)

	elif _isPrimitiveType(field_type):
		length = _getTypeLength(field_type)
		return address % length

    elif _isPointerType(field_type):
    	return address % 4

    elif _isUnboundedArrayType(field_type):
    	return _alignmentForTypeAtAddress(_getArraySubType(field_type), address)

    elif _isBoundedArrayType(field_type):
    	return _alignmentForTypeAtAddress(_getArraySubType(field_type), address)

    elif _isNodeClassType(field_type):
    	first_field = _getClassWithName(field_type).fields[0]
    	first_field_type = first_field[1]
    	return _alignmentForTypeAtAddress(first_field_type, address)

    else:
    	return None

def _byteChunkIsNull(chunk):
	for byte in chunk:
		if byte != 0:
			return False

	return True

# A class for managing the recursive parsing of the Node tree. It handles caching
# loaded nodes and reading the next node from the cache or calling its constructor.
# It also inherits all the BinaryReader methods for reading individual fields.
class DATParser(BinaryReader):

	# Length of the Header data of a DAT model. Pointers in the data are relative to the end of this header.
	DAT_header_length = 32

	# Where in the file the dat model itself starts. E.g. .pkx files have extra metadata before the model
	file_start_offset = 0

	# Nodes that have already been parsed. If a node is in the cache then return the cached
	# one when that offset is parsed again
	nodes_cache_by_offset = {}

	def __init__(self, path):
		super().__init__(path)
		if filepath[-4:] == '.pkx':
	        # check for byte pattern unique to XD pkx models
	        isXDModel = struct.unpack('>I', data[32:32+4])[0] == 0xFFFFFFFF

	        pkx_header_size = 0xE60 if isXDModel else 0x40
	        gpt1SizeOffset = 8 if isXDModel else 4
	        gpt1Size = struct.unpack('>I', data[gpt1SizeOffset:gpt1SizeOffset+4])[0]

	        if (gpt1Size > 0) and isXDModel:
	            pkx_header_size += gpt1Size + ((0x20 - (gpt1Size % 0x20)) % 0x20)
	        
	        self.file_start_offset = pkx_header_size

	def _startOffset(self, relative_to_header):
		return file_start_offset + (DAT_header_length if relative_to_header else 0)

    def parseNode(self, node_class, address, offset=0, relative_to_header=True):
        #switch the name of the node class and call the fromBinary class method on that class to load the Node
        #add the node to the nodes cache before returning it. If node is already cached for this offset, return that instead
        final_offset = address + offset + _startOffset(relative_to_header)
        cached = nodes_cache_by_offset[final_offset]
        if cached != None:
        	return cached

        new_node = node_class.fromBinary(self, address + offset)
        # TODO: check if flags like ik need to set on the node if they affect its toBlender()

        nodes_cache_by_offset[final_offset] = new_node

        return new_node

    def parseStruct(self, address, node_class, fields=None, relative_to_header=True):
    	if fields == None:
    		fields = node_class.fields

		new_node = node_class(address + _startOffset(relative_to_header), None)
		current_offset = 0
    	for field in fields:
    		field_name = field[0]
    		field_type = field[1]
    		field_length = _getTypeLength(field_type)

    		current_offset += _alignmentForTypeAtAddress(field_type, address + current_offset + _startOffset(relative_to_header))

    		value = read(field_type, address, current_offset, relative_to_header)
    		new_node.setattr(field_name, value)
    		current_offset += field_length

    	return new_node

    def read(self, field_type, address, offset=0, relative_to_header=True, whence='start'):

    	if _isBracketedType(field_type):
    		return read(_getBracketedSubType(field_type), address, offset, relative_to_header, whence)

    	elif _isPrimitiveType(field_type):
    		final_offset = offset + _startOffset(relative_to_header)
	    	return super().read(field_type, address, final_offset, whence)

	    elif _isPointerType(field_type):
	    	pointer = read("uint", address, offset, relative_to_header, whence)
	    	return read(_getPointerSubType(field_type), pointer)

	    elif _isUnboundedArrayType(field_type):
	    	sub_type = _getArraySubType(field_type)
	    	sub_type_length = _getTypeLength(sub_type)

	    	values = []
	    	current_offset = offset
	    	while True:
	    		# First check if all the data of the length we're about to read is zeroes.
	    		# If so treat it as the end of the array
	    		length_of_element = _getTypeLength(sub_type)
	    		raw_bytes = read_chunk(sub_type_length, address, current_offset + _startOffset(relative_to_header))
	    		if _byteChunkIsNull(raw_bytes):
	    			break

	    		value = read(sub_type, address, current_offset, relative_to_header, whence)
	    		values.append(value)
	    		current_offset += sub_type_length

	    	return values

	    elif _isBoundedArrayType(field_type):
	    	sub_type = _getArraySubType(field_type)
	    	sub_type_length = _getTypeLength(sub_type)
	    	count = _getArrayTypeBound(field_type)

	    	values = []
	    	current_offset = offset
	    	for i in range(count):
	    		value = read(sub_type, address, current_offset, relative_to_header, whence)
	    		values.append(value)
	    		current_offset += sub_type_length

	    	return values

	    elif _isNodeClassType(field_type):
	    	pointer = read("uint", address, offset, relative_to_header, whence)
	    	node_class = _getClassWithName(field_type)
	    	return parseNode(node_class, pointer)

	    else:
	    	return None


# A class for managing the recursive writing of the Node tree. It handles checking if the node
# already has an offset assigned, in which case it just returns the offset
# or calling the node's write method and returning the newly written to offset
# It also inherits all the BinaryWriter methods for writing individual fields.
class DATBuilder(BinaryWriter):

	# Length of the Header data of a DAT model. Pointers in the data are relative to the end of this header.
	DAT_header_length = 32

	# Some nodes keep a reference to the previous node.
	# To handle this we'll need to keep track of nodes which have started their write process
	# if trying to write a node that is already being written, return 0 for now but keep track
	# that the value. Make sure to loop through this when the node tree has finished writing, before
	# writing the file header, so the remaining offsets can be set properly
	nodes_still_processing = []
	nodes_to_write_pointers_by_offset = []

	def _startOffset(self, relative_to_header):
		return DAT_header_length if relative_to_header else 0

	def __init__(self, path):
		super().__init__(path)
        self.seek(DAT_header_length) # leave some padding bytes to be overwritten with the header at the end

	def currentRelativeAddress(self, relative_to_header):
    	return super().currentAddress() - (DAT_header_length if relative_to_header else 0)

	# A node can call this to say that the value at this address should be updated with the node it need's address
	# later, once that node has been completed
	def deferPointerWriteForNode(self, address, node):
		nodes_to_write_pointers_by_offset.append( (address + DAT_header_length, node) )

	def writeDeferredPointers(self):
		for address, node in nodes_to_write_pointers_by_offset:
			if node.offset != None:
				write("uint", node.offset, address)


	# Returns the offset where this node's data was written
	# Returns None if the offset calculation should be deferred due to the node still being processed
	# and the calling node can write 0 for now but mark that address to be overwritten at the end
    def writeNode(self, node, relative_to_header=True):

    	if node.address != None:
        	return node.address
        
        if node in nodes_still_processing:
        	return None

    	nodes_still_processing.append(node)

        address = node.writeBinary(self)
        node.address = address

        nodes_still_processing.remove(node)

        return address

    def writeStruct(self, node, fields=None, relative_to_header=True):
    	if fields == None:
    		fields = node.fields

    	for field in fields:
    		field_name = field[0]
    		field_type = field[1]
    		field_value = node.getattr(field_name)
    		field_length = _getTypeLength(field_type)

    		# Dump values that are pointed to first and replace them with their pointers
    		if _isPointerType(field_type):
    			sub_type = _getPointerSubType(field_type)
    			pointer = write(field_value, sub_type)
    			node.setattr(field_name, pointer)

	    	elif _isNodeClassType(sub_type):
	    			pointer = write(field_value, field_type)
	    			field_value.address = pointer
    				node.setattr(field_name, pointer)

    		elif _isBoundedArrayType(field_type) or _isUnboundedArrayType(field_type):
    			sub_type = _getArraySubType(field_type)
    			if _isPointerType(sub_type) or _isNodeClassType(sub_type):
    				pointers_array = []
    				for value in field_value:
    					pointer = write(value, sub_type)

    					if _isNodeClassType(sub_type):
		    				value.address = pointer

		    			pointers_array.append(value)

    				node.setattr(field_name, pointers_array)

    	write_address = (currentRelativeAddress() if relative_to_header else currentAddress())

    	for field in fields:
    		field_name = field[0]
    		field_type = field[1]
    		field_value = node.getattr(field_name)
    		if _isNodeClassType(field_type):
    			field_type = 'uint'
    		
    		_ = write(field_value, field_type)

    	return write_address

    # If no address is specified then append to end of file
    def write(self, value, field_type, address=None, relative_to_header=True, whence='start'):
    	if address != None:
    		final_address = address + _startOffset(relative_to_header)
    		seek(final_address)
    	else:
    		seek(0, 'end')

		padding = _alignmentForTypeAtAddress(field_type, currentAddress())
		address += padding
		for i in range(padding):
			_ = write(0, 'uchar')

    	if _isBracketedType(field_type):
    		return write(value, _getBracketedSubType(field_type), address, relative_to_header, whence)

    	elif _isPrimitiveType(field_type):
    		write_address = currentRelativeAddress() if relative_to_header else currentAddress()
	    	super().write(field_type, value)
	    	return address

	    elif _isPointerType(field_type):
	    	# If that node is still being written then find out its address at the end
	    	if value == None:
	    		# deferPointerWriteForNode(currentAddress(), )
	    		return 0
	    	else:
	    		return write(value, 'uint', address, relative_to_header, whence)

	    elif _isUnboundedArrayType(field_type) or _isBoundedArrayType(field_type):
	    	sub_type = _getArraySubType(field_type)
	    	sub_type_length = _getTypeLength(sub_type)
	    	values = value

	    	if _isPointerType(sub_type):
				pointers_array = []
				for value in values:
					pointer = write(value, sub_type)
					pointers_array.append(pointer)

				values = pointers_array

			write_address = currentRelativeAddress() if relative_to_header else currentAddress()
	    	for value in values:
	    		_ = write(value, sub_type)

	    	if _isUnboundedArrayType(field_type):
		    	# End with empty entry to mark end of array
		    	for i in range(sub_type_length):
		    		_ = write(0, 'uchar')

	    	return write_address

	    elif _isNodeClassType(field_type):
	    	return writeNode(value, relative_to_header)

	    else:
	    	return None











