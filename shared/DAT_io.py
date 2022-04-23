import struct
from . import file_io
from . import nodes
from .nodes import *
from .file_io import *

# Helpers
# Precedence rules:-
# () > * > [] > primitive > vector > NodeClass
# e.g.
# (*Joint[])[]
# Is an array of pointers to an array of Joint Nodes where each elemt of the latter array is a pointer to a Joint Node.
# All Node Class types will be assumed to be a pointer to a Node of that class.

def _isPrimitiveType(field_type):
	return field_type in primitive_field_types

def _isBracketedType(field_type):
	return field_type[0:1] == "(" and field_type[-1:] == ")"

def _isVectorType(field_type):
	return field_type == "vec3"

def _isPointerType(field_type):
	return field_type[0:1] == "*"

def _isUnboundedArrayType(field_type):
	return (not _isPointerType(field_type)) and field_type[-2:] == "[]"

def _isBoundedArrayType(field_type):
	return (not _isPointerType(field_type)) and "[" in field_type and  field_type[-1:] == "]"

def _isArrayType(field_type):
	return _isUnboundedArrayType(field_type) or _isBoundedArrayType(field_type)

# define node class as anything unrecognised to allow for unimplemented node classes to be recognised as node classes
def _isNodeClassType(field_type):
	return (not _isArrayType(field_type)) and (not _isPrimitiveType(field_type)) and (not _isBracketedType(field_type)) and (not _isVectorType(field_type)) and (not _isPointerType(field_type))

def _getClassWithName(class_name):
	try:
		class_reference = globals()[class_name]
		return class_reference
	except KeyError:
		return globals()["Dummy"]

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

# Gets the lowest level type from a compound type which is either a Node class or primitive (i.e. without * () or [])
def _getSubType(field_type):
	sub_type = field_type
	if _isBracketedType(sub_type) or _isArrayType(sub_type) or _isPointerType(sub_type):
		if _isBracketedType(sub_type):
			sub_type = _getBracketedSubType(sub_type)
		if _isArrayType(sub_type):
			sub_type = _getArraySubType(sub_type)
		if _isPointerType(sub_type):
			sub_type = _getPointerSubType(sub_type)

	return sub_type

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
			# These should never be the sub type of another field other than pointer
			# so we should never need to stride by their length
			return 0
		elif field_type == 'double':
			return 8
		elif field_type == 'matrix':
			return 48
		else:
			return 4

	elif _isVectorType(field_type):
		return 12

	elif _isPointerType(field_type):
		return 4

	elif _isUnboundedArrayType(field_type):
		# These should never be the sub type of another field other than pointer
		# so we should never need to stride by their length
		return 0

	elif _isBoundedArrayType(field_type):
		return _getTypeLength(_getArraySubType(field_type)) * _getArrayTypeBound(field_type)

	elif _isNodeClassType(field_type):
		return _getClassWithName(field_type).length

	else:
		return 0

def _alignmentForTypeAtAddress(field_type, address):
	if _isBracketedType(field_type):
		return _alignmentForTypeAtAddress(_getBracketedSubType(field_type), address)

	elif _isPrimitiveType(field_type):
		if field_type == 'matrix':
			return address % 4
		if field_type == 'string':
			return 0
		else:
			length = _getTypeLength(field_type)
			return address % length

	elif _isVectorType(field_type):
		return address % 4

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

# This adds a pointer reference symbol to a Node class type if present in the type signature for a field
# e.g. 'Joint' becomes '*Joint'. This means the Node classes can have cleaner type signatures but the *
# is useful so the parser can recursively read the value by first treating it as a pointer when it reads the *
# and then reading the actual struct at that address. If we omit the * then it's hard to tell which
# recurisve call is for the pointer and which one is for the struct.
# Unbounded array types will also be assumed to be a pointer to the unbounded array.
# In order to clarify any precedence between * and [] types, the result will be bracketed
# e.g. `Joint[]` becomes `*((*Joint)[])`
# In scenarios where there's a pointer to pointer or pointer to an array the additional *s should still be 
# added to the type signature in the Node class.
# The @ symbol can be added before a Node class type to prevent it from being treated as a pointer to the node class.
# A * won't be added and the @ will be removed from the final type output.
# e.g. `@Joint[]` becomes `(Joint)[]`
def _markUpFieldType(type_string):

	if type_string[0] == "@":
		return "(" + type_string[1:] + ")"

	if _isNodeClassType(type_string) or (type_string == 'string') or (type_string == 'matrix'):
		return "(*" + type_string + ")"

	if _isUnboundedArrayType(type_string):
		sub_type = _getSubType(type_string)
		return "(*(" + _markUpFieldType(sub_type) + "[]))"

	if _isBracketedType(type_string):
		sub_type = _getSubType(type_string)
		return "(" + _markUpFieldType(sub_type) + ")"

	if _isPointerType(type_string):
		sub_type = _getSubType(type_string)
		return "*(" + _markUpFieldType(sub_type) + ")"

	return type_string

# A class for managing the recursive parsing of the Node tree. It handles caching
# loaded nodes and reading the next node from the cache or calling its constructor.
# It also inherits all the BinaryReader methods for reading individual fields.
class DATParser(BinaryReader):

	# Length of the Header data of a DAT model. Pointers in the data are relative to the end of this header
	DAT_header_length = 32

	# Where in the file the dat model itself starts. E.g. .pkx files have extra metadata before the model
	file_start_offset = 0

	# The relocation data section of the model. It's parsed after the calling class provides the offset
	relocation_table = {}

	# Nodes that have already been parsed. If a node is in the cache then return the cached
	# one when that offset is parsed again
	nodes_cache_by_offset = {}

	# Settings chosen for the parser
	# - "ik_hack"   : A boolean for whether or not to scale down bones so ik works correctly
	# - "max_frame" : An integer for the maximum number of frames to read from an animation, 0 for no limit
	options = {} 

	def __init__(self, filepath, options):
		super().__init__(filepath)

		self.options = options

		if filepath[-4:] == '.pkx':
	        # check for byte pattern unique to XD pkx models
			self.isXDModel = self.read('uint', 32, 0, False) == 0xFFFFFFFF

			pkx_header_size = 0xE60 if self.isXDModel else 0x40
			gpt1SizeOffset = 8 if self.isXDModel else 4
			gpt1Size = self.read('uint', gpt1SizeOffset, 0, False)

			if (gpt1Size > 0) and self.isXDModel:
			    pkx_header_size += gpt1Size + ((0x20 - (gpt1Size % 0x20)) % 0x20)

			self.file_start_offset = pkx_header_size

	def registerRelocationTable(self, offset, count):
		start_address = offset
		for i in range(count):
			relocatable_offset = self.read('uint', start_address, i * 4)
			self.relocation_table[relocatable_offset] = True

	def _startOffset(self, relative_to_header):
		return self.file_start_offset + (self.DAT_header_length if relative_to_header else 0)

	def parseNode(self, node_class, address, offset=0, relative_to_header=True):
		# Call the fromBinary class method on the specified Node class to instantiate the Node
		# add the node to the nodes cache before returning it. If node is already cached for this offset, return that instead

		final_offset = address + offset + self._startOffset(relative_to_header)
		cached = self.nodes_cache_by_offset.get(final_offset)
		if cached != None:
			return cached

		# The new node is cached in parseStruct() so it can be cached before the leaves are recursively parsed
		new_node = node_class.fromBinary(self, address + offset)

		for field in new_node.fields:
			field_type = _markUpFieldType(field[1])
			field_length = _getTypeLength(field_type)
			new_node.length += field_length

		return new_node

	def parseStruct(self, node_class, address, fields=None, relative_to_header=True):
		if self.options["verbose"]:
			print("parsing struct:", node_class.class_name)

		if fields == None:
			fields = node_class.fields

		new_node = node_class(address + self._startOffset(relative_to_header), None)
		self.nodes_cache_by_offset[new_node.address] = new_node

		if self.options["verbose"]:
			print("at:", new_node.address)

		current_offset = 0
		for field in fields:
			field_name = field[0]
			field_type = _markUpFieldType(field[1])
			field_length = _getTypeLength(field_type)

			current_offset += _alignmentForTypeAtAddress(field_type, new_node.address + current_offset)
			if self.options["verbose"]:
				print("reading field:", field_name, " at:", new_node.address + current_offset)

			value = self.read(field_type, address, current_offset, relative_to_header)
			setattr(new_node, field_name, value)
			current_offset += field_length

		return new_node

	def read(self, field_type, address, offset=0, relative_to_header=True, whence='start'):
		if self.options["verbose"]:
			print("reading field type:", field_type, " at:", address + offset + self._startOffset(relative_to_header))

		if address + offset + self._startOffset(relative_to_header) + _getTypeLength(field_type) > self.filesize:
			return None

		if _isBracketedType(field_type):
			return self.read(_getBracketedSubType(field_type), address, offset, relative_to_header, whence)

		elif _isVectorType(field_type):
			adjusted_offset = offset + self._startOffset(relative_to_header)
			vx = self.read('float', address + adjusted_offset, 0, relative_to_header)
			vy = self.read('float', address + adjusted_offset, 4, relative_to_header)
			vz = self.read('float', address + adjusted_offset, 8, relative_to_header)
			return (vx, vy, vz)

		elif _isPrimitiveType(field_type):
			final_offset = offset + self._startOffset(relative_to_header)
			return super().read(field_type, address, final_offset, whence)

		elif _isPointerType(field_type):
			pointer = self.read('uint', address, offset, relative_to_header, whence)
			if pointer == 0:
				if self.relocation_table.get(pointer) == None:
					return None
			return self.read(_getPointerSubType(field_type), pointer)

		elif _isUnboundedArrayType(field_type):
			sub_type = _getArraySubType(field_type)
			sub_type_length = _getTypeLength(sub_type)

			values = []
			current_offset = offset
			while True:
				# First check if all the data of the length we're about to read is zeroes.
				# If so treat it as the end of the array
				raw_bytes = self.read_chunk(sub_type_length, address, current_offset + self._startOffset(relative_to_header))
				if _byteChunkIsNull(raw_bytes):
					return values

				value = self.read(sub_type, address, current_offset, relative_to_header, whence)
				values.append(value)
				current_offset += sub_type_length

		elif _isBoundedArrayType(field_type):
			sub_type = _getArraySubType(field_type)
			sub_type_length = _getTypeLength(sub_type)
			count = _getArrayTypeBound(field_type)

			values = []
			current_offset = offset
			for i in range(count):
				value = self.read(sub_type, address, current_offset, relative_to_header, whence)
				values.append(value)
				current_offset += sub_type_length

			return values

		elif _isNodeClassType(field_type):

			node_class = _getClassWithName(field_type)
			node = self.parseNode(node_class, address, offset)

			# If the class hasn't been implemented it is replaced with a Dummy implementation.
			# We can set the class name to the intended type so when reading the tree structure
			# we can see what it's supposed to be in future.
			if node.class_name == "Dummy":
				node.class_name = field_type

			return node

		else:
			return None


	# TODO: maybe rewrite the builder to write the output in two phases. First calculate the address to write each value.
	# since we know the number of bytes each struct or value requires, we can allocate the space in advance, figure out
	# where everything will go and then recurse through a second time to write the data into those spaces. 
	# This will mean we don't have to have fully written the leaves yet to get their pointers and can avoid weird deferred logic
	# when two nodes have pointers to each other.


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

	# A node can call this to say that the value at this address should be updated with the node it needs' address
	# later, once that node has been completed
	def deferPointerWriteForNode(self, address, node):
		nodes_to_write_pointers_by_offset.append( (address + DAT_header_length, node) )

	def writeDeferredPointers(self):
		for address, node in nodes_to_write_pointers_by_offset:
			if node.offset != None:
				self.write('uint', node.offset, address)


	# Returns the offset where this node's data was written
	# Returns None if the offset calculation should be deferred due to the node still being processed
	# and the calling node can write 0 for now but mark that address to be overwritten at the end
	def writeNode(self, node, relative_to_header=True):

		if node.address != None:
			return node.address
	    
		if node in nodes_still_processing:
			return None

		self.nodes_still_processing.append(node)

		address = node.writeBinary(self)
		node.address = address

		self.nodes_still_processing.remove(node)

		return address

	def writeStruct(self, node, fields=None, relative_to_header=True):
		if fields == None:
			fields = node.fields

		for field in fields:
			field_name = field[0]
			field_type = _markUpFieldType(field[1])
			field_value = node.getattr(field_name)
			field_length = _getTypeLength(field_type)

			# Dump values that are pointed to first and replace them with their pointers
			if _isPointerType(field_type):
				sub_type = _getPointerSubType(field_type)
				pointer = self.write(field_value, sub_type)
				setattr(node, field_name, pointer)

			elif _isNodeClassType(field_type):
			    pointer = self.write(field_value, field_type)
			    field_value.address = pointer
			    setattr(node, field_name, pointer)

			elif _isBoundedArrayType(field_type) or _isUnboundedArrayType(field_type):
				sub_type = _getArraySubType(field_type)
				if _isPointerType(sub_type) or _isNodeClassType(sub_type):
					pointers_array = []
					for value in field_value:
						pointer = self.write(value, sub_type)

						if _isNodeClassType(sub_type):
							value.address = pointer

						pointers_array.append(value)

					setattr(node, field_name, pointers_array)

			write_address = (self.currentRelativeAddress() if relative_to_header else self.currentAddress())

		for field in fields:
			field_name = field[0]
			field_type = field[1]
			field_value = node.getattr(field_name)
			if _isNodeClassType(field_type) or _isPointerType(field_type):
				field_type = 'uint'
			
			_ = self.write(field_value, field_type)

		return write_address

	# If no address is specified then append to end of file
	def write(self, value, field_type, address=None, relative_to_header=True, whence='start'):
		if address != None:
			final_address = address + self._startOffset(relative_to_header)
			self.seek(final_address)
		else:
			seek(0, 'end')

		padding = _alignmentForTypeAtAddress(field_type, currentAddress())
		address += padding
		for i in range(padding):
			_ = self.write(0, 'uchar')

		if _isBracketedType(field_type):
			return self.write(value, _getBracketedSubType(field_type), address, relative_to_header, whence)

		elif _isPrimitiveType(field_type):
			write_address = self.currentRelativeAddress() if relative_to_header else self.currentAddress()
			super().write(field_type, value)
			return address

		elif _isVectorType(field_type):
			write_address = self.currentRelativeAddress() if relative_to_header else self.currentAddress()
			_ = self.write(value[0], 'float')
			_ = self.write(value[1], 'float')
			_ = self.write(value[2], 'float')
			return write_address


		elif _isPointerType(field_type):
			# If that node is still being written then find out its address at the end
			if value == None:
				# deferPointerWriteForNode(currentAddress(), )
				return 0
			else:
				return self.write(value, 'uint', address, relative_to_header, whence)

		elif _isUnboundedArrayType(field_type) or _isBoundedArrayType(field_type):
			sub_type = _getArraySubType(field_type)
			sub_type_length = _getTypeLength(sub_type)
			values = value

			if _isPointerType(sub_type):
				pointers_array = []
				for value in values:
					pointer = self.write(value, sub_type)
					pointers_array.append(pointer)

				values = pointers_array

			write_address = currentRelativeAddress() if relative_to_header else currentAddress()
			for value in values:
				_ = self.write(value, sub_type)

			if _isUnboundedArrayType(field_type):
		    	# End with empty entry to mark end of array
				for i in range(sub_type_length):
					_ = self.write(0, 'uchar')

			return write_address

		elif _isNodeClassType(field_type):
			return self.writeNode(value, relative_to_header)

		else:
			return None









