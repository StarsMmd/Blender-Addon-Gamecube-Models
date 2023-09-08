import sys
import struct
import traceback

from ..Nodes import *
from ..Errors import *
from ..Constants import *
from .file_io import *

# A class for managing the recursive parsing of the Node tree. It handles caching
# loaded nodes and reading the next node from the cache or calling its constructor.
# It also inherits all the BinaryReader methods for reading individual fields.
class DATParser(BinaryReader):

	# Length of the Header data of a DAT model. Pointers in the data are relative to the end of this header
	DAT_header_length = 32

	def __init__(self, filepath, options):
		super().__init__(filepath)

		# Settings chosen for the parser
		# - "verbose"       : Prints more output for debugging purposes
		# - "print_tree"    : Prints a tree representation of each section parsed
		# - "section_names" : Only parses sections in this list. If empty, parses all sections possible
		self.options = options

		# Where in the file the dat model itself starts. E.g. .pkx files have extra metadata before the model
		self.file_start_offset = 0

		# The relocation data section of the model. It's parsed after the calling class provides the offset
		self.relocation_table = {}

		# Nodes that have already been parsed. If a node is in the cache then return the cached
		# one when that offset is parsed again
		self.nodes_cache_by_offset = {}

		if filepath[-4:] == '.pkx':
	        # check for byte pattern unique to Colosseum pkx models
			self.isXDModel = self.read('uint', 0, 0, False) != self.read('uint', 0x40, 0, False)

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


	def parseSections(self):
		self.sections = []
		section_names_to_include = self.options.get("section_names")
		for (address, is_public) in self.header.section_addresses:
			
			# Recursively parse Node tree based on the section info
		    # The top level node will recursively call parseNode() on any leaves
			section = SectionInfo.readFromBinary(self, address, is_public, self.header.section_names_offset)

			if (len(section_names_to_include) == 0) or (section.section_name in section_names_to_include):
				try:
					section.readNodeTree(self)
				except Exception as error:
					traceback.print_exc()
					print("\nFailed to parse section:", section.section_name, file=sys.stderr)
					print(error,"\n", file=sys.stderr)
					continue

				if self.options.get("print_tree"):
					section.printListRepresentation()

				if not isinstance(section.root_node, Dummy):
					self.sections.append(section)


	def _startOffset(self, relative_to_header):
		return self.file_start_offset + (self.DAT_header_length if relative_to_header else 0)

	def getTypeLength(self, field_type):
		return get_type_length(field_type)

	def read(self, field_type, address, offset=0, relative_to_header=True, whence='start'):
		if self.options.get("verbose"):
			print("reading field type:", field_type, " at:", hex(address + offset + self._startOffset(relative_to_header)))

		if isBracketedType(field_type):
			return self.read(getBracketedSubType(field_type), address, offset, relative_to_header, whence)

		elif is_primitive_type(field_type):
			final_offset = offset + self._startOffset(relative_to_header)
			type_length = 1 if field_type == 'string' else get_type_length(field_type)

			if address + final_offset + type_length > self.filesize:
				raise InvalidReadAddressError(final_offset, field_type, self.filesize)

			return super().read(field_type, address, final_offset, whence)

		elif isPointerType(field_type):
			pointer = self.read('uint', address, offset, relative_to_header, whence)
			if pointer == 0:
				if self.relocation_table.get(pointer) == None:
					return None
			return self.read(getPointerSubType(field_type), pointer)

		elif isUnboundedArrayType(field_type):
			sub_type = getArraySubType(field_type)
			sub_type_length = get_type_length(sub_type)

			values = []
			current_offset = offset
			while True:
				# First check if all the data of the length we're about to read is zeroes.
				# If so treat it as the end of the array
				raw_bytes = self.read_chunk(sub_type_length, address, current_offset + self._startOffset(relative_to_header))
				if byteChunkIsNull(raw_bytes):
					return values

				value = self.read(sub_type, address, current_offset, relative_to_header, whence)
				values.append(value)
				current_offset += sub_type_length

		elif isBoundedArrayType(field_type):
			sub_type = getArraySubType(field_type)
			sub_type_length = get_type_length(sub_type)
			count = getArrayTypeBound(field_type)

			values = []
			current_offset = offset
			for i in range(count):
				value = self.read(sub_type, address, current_offset, relative_to_header, whence)
				values.append(value)
				current_offset += sub_type_length

			return values

		elif isNodeClassType(field_type):
			# Instantiate a node of the specified class then call fromBinary() on it to load its fields.
			# Add the node to the nodes cache before returning it. If node is already cached for this offset, return that instead

			final_offset = address + offset
			node_class = getClassWithName(field_type)

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
				field_type = markUpFieldType(field[1])
				field_length = get_type_length(field_type) + get_alignment_at_offset(field_type, node.length)
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
			field_type = markUpFieldType(field[1])
			field_length = get_type_length(field_type)

			current_offset += get_alignment_at_offset(field_type, node.address + current_offset)

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
				field_type = markUpFieldType(field[1])

				if bound_string in field_type:
					if self.options.get("verbose"):
						print("replacing bounded array var:", bound_string, "->", replacement_bound)
					updated_type = field_type.replace(bound_string, replacement_bound)
					fields[i] = (field_name, updated_type)


		current_offset = 0
		for field in fields:
			field_name = field[0]
			field_type = markUpFieldType(field[1])
			field_length = get_type_length(field_type)

			current_offset += get_alignment_at_offset(field_type, node.address + current_offset)
			if self.options.get("verbose"):
				print("reading field:", field_name, " at:", node.address + current_offset)

			value = self.read(field_type, node.address, current_offset, relative_to_header)
			setattr(node, field_name, value)
			current_offset += field_length

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
			alignment = get_alignment_at_offset(first_field[1], self._currentRelativeAddress())
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

		padding = get_alignment_at_offset(field_type, currentAddress())
		address += padding
		for i in range(padding):
			_ = self.write(0, 'uchar')

		if isBracketedType(field_type):
			return self.write(value, getBracketedSubType(field_type), address, relative_to_header, whence)

		elif is_primitive_type(field_type):
			write_address = self.currentRelativeAddress() if relative_to_header else self.currentAddress()
			super().write(field_type, value)
			return address

		elif isPointerType(field_type):
			if relative_to_header:
				self.relocations.append(address)
			return self.write(value, 'uint', address, relative_to_header, whence)

		elif isUnboundedArrayType(field_type) or isBoundedArrayType(field_type):
			sub_type = getArraySubType(field_type)
			sub_type_length = get_type_length(sub_type)
			values = value

			if isPointerType(sub_type):
				pointers_array = []
				for value in values:
					pointer = self.write(value, sub_type)
					pointers_array.append(pointer)

				values = pointers_array

			write_address = currentRelativeAddress() if relative_to_header else currentAddress()
			for value in values:
				_ = self.write(value, sub_type)

			if isUnboundedArrayType(field_type):
		    	# End with empty entry to mark end of array
				for i in range(sub_type_length):
					_ = self.write(0, 'uchar')

			return write_address

		elif isNodeClassType(field_type):
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
			field_type = markUpFieldType(field[1])
			field_value = node.getattr(field_name)
			field_length = get_type_length(field_type)

			# Dump values that are pointed to first and replace them with their pointers
			if isPointerType(field_type):
				sub_type = getPointerSubType(field_type)
				pointer = self.write(field_value, sub_type)
				setattr(node, field_name, pointer)

			elif isNodeClassType(field_type):
			    pointer = self.write(field_value, field_type)
			    field_value.address = pointer
			    setattr(node, field_name, pointer)

			elif isBoundedArrayType(field_type) or isUnboundedArrayType(field_type):
				sub_type = getArraySubType(field_type)
				if isPointerType(sub_type) or isNodeClassType(sub_type):
					pointers_array = []
					for value in field_value:
						pointer = self.write(value, sub_type)

						if isNodeClassType(sub_type):
							value.address = pointer

						pointers_array.append(value)

					setattr(node, field_name, pointers_array)

			write_address = (self.currentRelativeAddress() if relative_to_header else self.currentAddress())

		for field in fields:
			field_name = field[0]
			field_type = field[1]
			field_value = node.getattr(field_name)
			if isNodeClassType(field_type) or isPointerType(field_type):
				field_type = 'uint'
			
			_ = self.write(field_value, field_type)

		return write_address







