import sys
import struct
import traceback

try:
    from .....shared.Nodes import *
    from .....shared.Constants import *
    from .....shared.helpers.file_io import *
    from .....shared.helpers.logger import Logger, StubLogger
except (ImportError, SystemError):
    from shared.Nodes import *
    from shared.Constants import *
    from shared.helpers.file_io import *
    from shared.helpers.logger import Logger, StubLogger

# A class for managing the recursive parsing of the Node tree. It handles caching
# loaded nodes and reading the next node from the cache or calling its constructor.
# It also inherits all the BinaryReader methods for reading individual fields.
class DATParser(BinaryReader):

	# Length of the Header data of a DAT model. Pointers in the data are relative to the end of this header
	DAT_header_length = 32

	def __init__(self, stream, options, logger=None):
		super().__init__(stream)

		self.options = options
		self.logger = logger or StubLogger()
		self.file_start_offset = 0
		self.relocation_table = {}
		self.nodes_cache_by_offset = {}

		self.header = self.read('ArchiveHeader', 0, 0, False)

		for i in range(self.header.relocations_count):
			relocatable_offset = self.read('uint', self.header.data_size, i * 4)
			self.relocation_table[relocatable_offset] = True


	def parseSections(self):
		self.sections = []
		section_names_to_include = self.options.get("section_names") or []
		section_map = self.options.get("section_map")
		for (address, is_public) in self.header.section_addresses:

			# Recursively parse Node tree based on the section info
		    # The top level node will recursively call parseNode() on any leaves
			section = SectionInfo.readFromBinary(self, address, is_public, self.header.section_names_offset)

			if (len(section_names_to_include) == 0) or (section.section_name in section_names_to_include):
				try:
					if section_map and section.section_name in section_map:
						# Phase 2 provided the type mapping — use it directly
						node_type = section_map[section.section_name]
						if node_type != 'Dummy':
							section.root_node = self.read(node_type, section.root_node)
						else:
							dummy = Dummy(section.root_node, None)
							dummy.class_name = "Unrecognised: " + section.section_name
							section.root_node = dummy
							self.logger.leniency("unrecognised_section",
							                     "Section '%s' has no registered node type; wrapped in Dummy",
							                     section.section_name)
					else:
						# Legacy path — section resolves its own type
						section.readNodeTree(self)
				except Exception as error:
					traceback.print_exc()
					self.logger.leniency("section_parse_error",
					                     "Section '%s' raised during parse: %s",
					                     section.section_name, error)
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
		self.logger.debug("reading field type: %s at: 0x%X", field_type, address + offset + self._startOffset(relative_to_header))

		if isBracketedType(field_type):
			return self.read(getBracketedSubType(field_type), address, offset, relative_to_header, whence)

		elif is_primitive_type(field_type):
			final_offset = offset + self._startOffset(relative_to_header)
			type_length = 1 if field_type == 'string' else get_type_length(field_type)

			if address + final_offset + type_length > self.filesize:
				raise ValueError('Failed to read %s at address: 0x%X (file size: 0x%X)' % (field_type, address + offset, self.filesize))

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

		elif (node_class := get_class_from_name(field_type)) is not None:
			# Instantiate a node of the specified class then call fromBinary() on it to load its fields.
			# Add the node to the nodes cache before returning it. If node is already cached for this offset, return that instead

			final_offset = address + offset

			if node_class.is_cachable:
				cached = self.nodes_cache_by_offset.get(final_offset)
				if cached is not None:
						return cached
			
			node = node_class(final_offset, None)
			# Cache the node before parsing its sub nodes.
			if node.is_cachable:
				self.nodes_cache_by_offset[final_offset] = node

			node.loadFromBinary(self)

			# For debugging purposes
			node._struct_size = 0
			for field in node.fields:
				field_type = markUpFieldType(field[1])
				field_length = get_type_length(field_type) + get_alignment_at_offset(field_type, node._struct_size)
				node._struct_size += field_length

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
		if not node:
			return

		self.logger.debug("parsing struct: %s at: 0x%X", node.class_name, node.address)

		if not fields:
			fields = node.fields

		if not fields or (len(fields) == 0):
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
		# Build replacement map once, then single pass over fields
		bound_replacements = {}
		for name, number in uint_fields.items():
			bound_replacements["[" + name + "]"] = "[" + str(number) + "]"

		if bound_replacements:
			for i, field in enumerate(fields):
				field_type = markUpFieldType(field[1])
				for bound_string, replacement_bound in bound_replacements.items():
					if bound_string in field_type:
						self.logger.debug("replacing bounded array var: %s -> %s", bound_string, replacement_bound)
						field_type = field_type.replace(bound_string, replacement_bound)
						fields[i] = (field[0], field_type)


		current_offset = 0
		for field in fields:
			field_name = field[0]
			field_type = markUpFieldType(field[1])
			field_length = get_type_length(field_type)

			current_offset += get_alignment_at_offset(field_type, node.address + current_offset)
			self.logger.debug("reading field: %s at: 0x%X", field_name, node.address + current_offset)

			value = self.read(field_type, node.address, current_offset, relative_to_header)
			setattr(node, field_name, value)
			current_offset += field_length

