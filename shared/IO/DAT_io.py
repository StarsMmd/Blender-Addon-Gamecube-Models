import struct

from ..Nodes import *
from ..Errors import *

from .File_io import *

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
	if _isBracketedType(sub_type):
		sub_type = _getBracketedSubType(sub_type)
		return _getSubType(sub_type)
	if _isArrayType(sub_type):
		sub_type = _getArraySubType(sub_type)
		return _getSubType(sub_type)
	if _isPointerType(sub_type):
		sub_type = _getPointerSubType(sub_type)
		return _getSubType(sub_type)

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

	bounds = 0
	try:
		bounds = int(bound_string)
	except:
		raise ArrayBoundsUnknownVariableError(bound_string)

	return bounds
	

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
		class_ref = _getClassWithName(field_type)
		length = 0
		for field in class_ref.fields:
			field_type = _markUpFieldType(field[1])
			field_length = _getTypeLength(field_type) + _alignmentForTypeAtAddress(field_type, length)
			length += field_length
		return length

	else:
		return 0

def _alignmentForTypeAtAddress(field_type, address):
	if _isBracketedType(field_type):
		return _alignmentForTypeAtAddress(_getBracketedSubType(field_type), address)

	elif _isPrimitiveType(field_type):
		if field_type == 'string':
			return _alignmentForTypeAtAddress('uchar', address)
		if field_type == 'vec3':
			return _alignmentForTypeAtAddress('float', address)
		if field_type == 'matrix':
			return _alignmentForTypeAtAddress('float', address)
		else:
			length = _getTypeLength(field_type)
			if length <= 0:
				return 0

			alignment = length - (address % length)
			if alignment == length:
				alignment = 0
			return alignment

	elif _isPointerType(field_type):
		return _alignmentForTypeAtAddress('uint', address)

	elif _isUnboundedArrayType(field_type):
		return _alignmentForTypeAtAddress(_getArraySubType(field_type), address)

	elif _isBoundedArrayType(field_type):
		return _alignmentForTypeAtAddress(_getArraySubType(field_type), address)

	elif _isNodeClassType(field_type):
		fields = _getClassWithName(field_type).fields
		if len(fields) == 0:
			return 0
		longest_field = None
		for field in fields:
			field_type = _markUpFieldType(field[1])
			field_alignment = _alignmentForTypeAtAddress(field_type, address)
			if longest_field == None or longest_field < field_alignment:
				longest_field = field_alignment
				
		return longest_field

	else:
		return 0

def _byteChunkIsNull(chunk):
	for byte in chunk:
		if byte != 0:
			return False

	return True

# This adds a pointer reference symbol to a Node class type if present in the type signature for a field
# e.g. 'Joint' becomes '*Joint'. This means the Node classes can have cleaner type signatures but the *
# is useful so the parser can recursively read the value by first treating it as a pointer when it reads the *
# and then reading the actual struct at that address. If we omit the * then it's hard to tell which
# recursive call is for the pointer and which one is for the struct.
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

	def __init__(self, filepath, options):
		super().__init__(filepath)

		# Where in the file the dat model itself starts. E.g. .pkx files have extra metadata before the model
		self.file_start_offset = 0

		# The relocation data section of the model. It's parsed after the calling class provides the offset
		self.relocation_table = {}

		# Nodes that have already been parsed. If a node is in the cache then return the cached
		# one when that offset is parsed again
		self.nodes_cache_by_offset = {}

		# Images that have been loaded from their texture data
		self.images_cache_by_image_id_and_tlut_id = {}

		# Settings chosen for the parser
		# - "verbose"   : Prints more output for debugging purposes
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

		self.header = self.read('ArchiveHeader', 0, 0, False)

		for i in range(self.header.relocations_count):
			relocatable_offset = self.read('uint', self.header.data_size, i * 4)
			self.relocation_table[relocatable_offset] = True


	def _startOffset(self, relative_to_header):
		return self.file_start_offset + (self.DAT_header_length if relative_to_header else 0)

	def getTypeLength(self, field_type):
		return _getTypeLength(field_type)

	def read(self, field_type, address, offset=0, relative_to_header=True, whence='start'):
		if self.options.get("verbose"):
			print("reading field type:", field_type, " at:", hex(address + offset + self._startOffset(relative_to_header)))

		if address + offset + self._startOffset(relative_to_header) + _getTypeLength(field_type) > self.filesize:
			return None

		if _isBracketedType(field_type):
			return self.read(_getBracketedSubType(field_type), address, offset, relative_to_header, whence)

		elif _isVectorType(field_type):
			vx = self.read('float', address + offset, 0, relative_to_header, whence)
			vy = self.read('float', address + offset, 4, relative_to_header, whence)
			vz = self.read('float', address + offset, 8, relative_to_header, whence)
			return (vx, vy, vz)

		elif _isPrimitiveType(field_type):
			final_offset = offset + self._startOffset(relative_to_header)

			if final_offset + _getTypeLength(field_type) > self.filesize:
				raise InvalidReadAddressError(final_offset, field_type, self.filesize)

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
			# Instantiate a node of the specified class then call fromBinary() on it to load its fields.
			# Add the node to the nodes cache before returning it. If node is already cached for this offset, return that instead

			final_offset = address + offset
			node_class = _getClassWithName(field_type)

			if node_class.is_cachable:
				cached = self.nodes_cache_by_offset.get(final_offset)
				if cached != None:
						return cached
			
			node = node_class(final_offset, None)
			# Cache the node before parsing its sub nodes.
			if node.is_cachable:
				self.nodes_cache_by_offset[final_offset] = node

			node.loadFromBinary(self)

			# For debugging purposes
			node.length = 0
			for field in node.fields:
				field_type = _markUpFieldType(field[1])
				field_length = _getTypeLength(field_type) + _alignmentForTypeAtAddress(field_type, node.length)
				node.length += field_length

			# If the class hasn't been implemented it is replaced with a Dummy implementation.
			# We can set the class name to the intended type so when reading the tree structure
			# we can see what it's supposed to be in future.
			if node.class_name == "Dummy":
				node.class_name = field_type

			return node

		else:
			return None

	# Used by node objects to read their fields and set the properties on the node.
	# Pass in a set of fields to the fields argument to use those instead of the ones set on the node.
	def parseNode(self, node, fields=None, relative_to_header=True):
		if node == None:
			return

		if self.options.get("verbose"):
			print("parsing struct:", node.class_name)
			print("at:", node.address)

		if fields == None:
			fields = node.fields

		if (fields == None) or (len(fields) == 0):
			return

		# Initial parse to get any fields which are array bounds so the bounded array fields
		# can have their length injected
		current_offset = 0
		uint_fields = {}
		for field in fields:
			field_name = field[0]
			field_type = field[1]
			field_length = _getTypeLength(field_type)

			current_offset += _alignmentForTypeAtAddress(field_type, node.address + current_offset)

			if (field_type == 'uchar') or (field_type == 'ushort') or (field_type == 'uint'):
				value = self.read(field_type, node.address, current_offset, relative_to_header)
				uint_fields[field_name] = value

			current_offset += field_length

		# Inject array bounds into fields as appropriate
		for name, number in uint_fields.items():
			bound_string = "[" + name + "]"
			replacement_bound =  "[" + str(number) + "]"
			for i, field in enumerate(fields):
				field_name = field[0]
				field_type = field[1]

				if bound_string in field_type:
					if self.options.get("verbose"):
						print("replacing bounded array var:", bound_string, "->", replacement_bound)
					updated_type = field_type.replace(bound_string, replacement_bound)
					fields[i] = (field_name, updated_type)


		current_offset = 0
		for field in fields:
			field_name = field[0]
			field_type = _markUpFieldType(field[1])
			field_length = _getTypeLength(field_type)

			current_offset += _alignmentForTypeAtAddress(field_type, node.address + current_offset)
			if self.options.get("verbose"):
				print("reading field:", field_name, " at:", node.address + current_offset)

			value = self.read(field_type, node.address, current_offset, relative_to_header)
			setattr(node, field_name, value)
			current_offset += field_length

	def cacheImage(self, image_id, tlut_id, image_data):
		self.images_cache_by_image_id_and_tlut_id[(image_id, tlut_id)] = image_data

	def getCachedImage(self, image_id, tlut_id):
		return self.images_cache_by_image_id_and_tlut_id.get((image_id, tlut_id))

# A class for managing the recursive writing of the Node tree. 
# This happens in 3 steps:
# 1) Convert the node tree into an ordered array of nodes.
#    The order of the array should match the write order of the nodes.
#    To match the conventions of official models append nodes to the list in a breadth/depth first order
#    and then reverse the list so the nodes towards the top of the tree are written towards the end of the file.
# 2) For each node in the list, allocate an address range of the output to that node.
#    Each node is allocated the address following the preceding node, adjusting for alignment.
# 3) Write each node's data to the pre allocated address. For fields which are a pointer to a sub node,
#    write the pre allocated address of the sub node.
class DATBuilder(BinaryWriter):

	# Length of the Header data of a DAT model. Pointers in the data are relative to the end of this header.
	DAT_header_length = 32

	def __init__(self, path, root_nodes):
		super().__init__(path)
		self.seek(DAT_header_length) # leave some padding bytes to be overwritten with the header at the end

		self.root_nodes = root_nodes
		self.relocations = []
		self.node_list = []
		for root_node in root_nodes:
			self.node_list += root_node.toList().reverse()


	def _currentRelativeAddress(self, relative_to_header=True):
		return super().currentAddress() - (DAT_header_length if relative_to_header else 0)

	def build():
		# Write primitive pointers for each node
		for node in self.node_list:
			node.writePrimitivePointers(self)

		# Allocate address for each node
		self.seek(0, 'end')
		for node in self.node_list:
			first_field = node.fields[0]
			alignment = _alignmentForTypeAtAddress(first_field[1], self._currentRelativeAddress())
			for i in range(alignment):
				_ = self.write(0, 'uchar')

			node.address = self._currentRelativeAddress() + node.allocationOffset()
			node_length = node.allocationSize()
			for i in range(node_length):
				_ = self.write(0, 'uchar')

		# Tidy up alignment and record data section size
		while (self._currentRelativeAddress()) % 16 != 0:
			_ = self.write(0, 'uchar')
		data_section_length = self._currentRelativeAddress()

		# Write each node
		for node in self.node_list:
			node.writeBinary(self)

		# Write relocation list
		self.seek(0, 'end')
		for relocation in self.relocations:
			_ = self.write(relocation, 'uint')

		# Write Section Info
		section_names_offset = 0
		section_names = []
		for root_node in self.root_nodes:
			self.write(root_node.address, 'uint')
			if isinstance(root_node, SceneData):
				section_names.append("scene_data")
				self.write(section_names_offset, 'uint')
				section_names_offset += 11
			elif isinstance(root_node, BoundBox):
				section_names.append("bound_box")
				self.write(section_names_offset, 'uint')
				section_names_offset += 10

		# Write strings section
		for section_name in section_names:
			self.write(section_name, 'string')

		# Write Archive Header
		while (self._currentRelativeAddress()) % 16 != 0:
			_ = self.write(0, 'uchar')
		file_size = self._currentRelativeAddress()
		relocations_count = len(self.relocations)
		self.write(file_size, 'uint', 0, False)
		self.write(data_size, 'uint', 4, False)
		self.write(relocations_count, 'uint', 8, False)
		self.write(len(self.root_nodes), 'uint', 12, False)

	# If no address is specified then append to end of file
	def write(self, value, field_type, address=None, relative_to_header=True, whence='start'):
		if address != None:
			final_address = address + self._startOffset(relative_to_header)
			self.seek(final_address)
		else:
			self.seek(0, 'end')

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
			if relative_to_header:
				self.relocations.append(address)
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
			address = self.writeNode(value, relative_to_header)
			return address

		else: 
			return 0


	def writeNode(self, node, fields=None):
		if node == None:
			return 0

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







