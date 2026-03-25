import sys
import struct
import traceback

from ..Nodes import *
from ..Errors import *
from ..Constants import *
from ..helpers.file_io import *
from ..helpers.logger import Logger, StubLogger

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

	def __init__(self, path_or_stream, root_nodes, section_names=None):
		super().__init__(path_or_stream)
		# Reserve space for the header (will be overwritten at the end)
		self.file.write(b'\x00' * self.DAT_header_length)

		self.root_nodes = root_nodes
		self.section_names = section_names or [None] * len(root_nodes)
		self.relocations = []

		# Build the node list via DFS post-order (children before parents).
		# Uses identity-based dedup to handle shared nodes and None addresses.
		self.node_list = []
		visited = set()
		for root_node in root_nodes:
			self._dfsPostOrder(root_node, visited)

	def _dfsPostOrder(self, node, visited):
		"""DFS traversal matching SysDolphin compiler conventions:
		- 'child'/'next'/'link' fields (same-type tree/list pointers) are written AFTER the node
		- All other Node-typed fields are written BEFORE the node (DFS into them first)
		- Inline structs (@-prefixed) are skipped (they're part of the parent struct)
		- Deduplicates by object identity"""
		if node is None or id(node) in visited:
			return
		visited.add(id(node))

		if not hasattr(node, 'fields'):
			self.node_list.append(node)
			return

		deferred = []  # (field_name, value) for child/next/link fields

		# First pass: recurse into non-link fields (written BEFORE this node)
		for field in node.fields:
			raw_type = field[1]
			field_name = field[0]

			# Skip inline struct fields (@-prefixed)
			if raw_type.startswith('@') or '(@' in raw_type:
				continue

			value = getattr(node, field_name, None)

			# Defer child/next/link fields (same-type tree/list pointers)
			if field_name in ('child', 'next', 'link'):
				if isinstance(value, Node):
					deferred.append(value)
				elif isinstance(value, list):
					for item in value:
						if isinstance(item, Node):
							deferred.append(item)
				continue

			# Recurse into other Node-typed fields now (BEFORE this node)
			if isinstance(value, Node):
				self._dfsPostOrder(value, visited)
			elif isinstance(value, list):
				for item in value:
					if isinstance(item, Node):
						self._dfsPostOrder(item, visited)

		# Write this node
		self.node_list.append(node)

		# Second pass: recurse into deferred child/next/link fields (written AFTER this node)
		for child in deferred:
			self._dfsPostOrder(child, visited)

	def _currentRelativeAddress(self, relative_to_header=True):
		return super().currentAddress() - (self.DAT_header_length if relative_to_header else 0)

	def build(self):
		# --- Phase 1: Write shared raw data ---
		# Vertex buffers (deduplicated), image pixels, palette data.
		# Save original base_pointers for dedup before any modification.
		for node in self.node_list:
			if type(node).__name__ == 'VertexList':
				for vertex in node.vertices:
					vertex._orig_base_pointer = vertex.base_pointer

		for node in self.node_list:
			node.writePrimitivePointers(self)

		# --- Phase 2: DFS post-order — write private data + allocate structs ---
		# For each node (already in DFS post-order from __init__):
		#   1. Write private raw data (display lists, matrices, frame data, strings, pointer arrays)
		#   2. Allocate the node's struct space
		self.seek(0, 'end')
		for node in self.node_list:
			# Write private data immediately before the node struct
			node.writePrivateData(self)

			# Allocate struct space
			node_size = node.allocationSize()
			if node_size > 0:
				self.seek(0, 'end')
				if len(node.fields) > 0:
					first_field = node.fields[0]
					alignment = get_alignment_at_offset(markUpFieldType(first_field[1]), self._currentRelativeAddress())
				else:
					# Nodes with no declared fields (e.g. EnvelopeList) — 4-byte align
					alignment = (4 - (self._currentRelativeAddress() % 4)) % 4
				for i in range(alignment):
					_ = self.write(0, 'uchar')

				node.address = self._currentRelativeAddress() + node.allocationOffset()
				for i in range(node_size):
					_ = self.write(0, 'uchar')
			else:
				# Stub nodes (e.g. RenderAnimation) — clear stale address from parsing
				# so pointer resolution writes 0 instead of an invalid original address
				node.address = None

		# --- Phase 3: Write node structs at allocated addresses ---
		for node in self.node_list:
			node.writeBinary(self)

		# --- Phase 4: Finalize ---
		# 16-byte align data section
		self.seek(0, 'end')
		while (self._currentRelativeAddress()) % 16 != 0:
			_ = self.write(0, 'uchar')
		data_section_length = self._currentRelativeAddress()

		# Write relocation table
		self.seek(0, 'end')
		for relocation in self.relocations:
			_ = self.write(relocation, 'uint')

		# Write Section Info
		string_offset = 0
		names_to_write = []
		for i, root_node in enumerate(self.root_nodes):
			self.write(root_node.address, 'uint')
			name = self.section_names[i] if i < len(self.section_names) and self.section_names[i] else root_node.class_name
			names_to_write.append(name)
			self.write(string_offset, 'uint')
			string_offset += len(name) + 1  # +1 for null terminator

		# Write section name strings
		for name in names_to_write:
			self.write(name, 'string')

		# Write Archive Header
		while (self._currentRelativeAddress()) % 16 != 0:
			_ = self.write(0, 'uchar')
		file_size = self._currentRelativeAddress()
		relocations_count = len(self.relocations)
		self.write(file_size, 'uint', 0, False)
		self.write(data_section_length, 'uint', 4, False)
		self.write(relocations_count, 'uint', 8, False)
		self.write(len(self.root_nodes), 'uint', 12, False)
		self.write(0, 'uint', 16, False)  # external_nodes_count

	# If no address is specified then append to end of file
	def write(self, value, field_type, address=None, relative_to_header=True, whence='start'):
		if address is not None:
			address = address + (self.DAT_header_length if relative_to_header else 0)
			self.seek(address)
		else:
			self.seek(0, 'end')

		padding = get_alignment_at_offset(field_type, self.currentAddress())
		if address is not None:
			address += padding
		for i in range(padding):
			_ = self.write(0, 'uchar')

		if isBracketedType(field_type):
			return self.write(value, getBracketedSubType(field_type), address, relative_to_header, whence)

		elif is_primitive_type(field_type):
			write_address = self._currentRelativeAddress() if relative_to_header else self.currentAddress()
			super().write(field_type, value)
			return write_address

		elif isPointerType(field_type):
			if value is None:
				value = 0
			elif isinstance(value, Node):
				value = value.address if value.address is not None else 0
			if relative_to_header and value != 0:
				# Use the actual write position if no address was specified
				reloc_addr = address if address is not None else self._currentRelativeAddress()
				self.relocations.append(reloc_addr)
			return self.write(value, 'uint', address, relative_to_header, whence)

		elif isUnboundedArrayType(field_type) or isBoundedArrayType(field_type):
			sub_type = getArraySubType(field_type)
			sub_type_length = get_type_length(sub_type)
			values = value

			# Resolve Node references to addresses before writing
			if isPointerType(sub_type) or isNodeClassType(sub_type):
				resolved = []
				for v in values:
					if isinstance(v, Node):
						resolved.append(v.address if v.address is not None else 0)
					elif v is None:
						resolved.append(0)
					else:
						resolved.append(v)
				values = resolved

			write_address = self._currentRelativeAddress() if relative_to_header else self.currentAddress()
			for v in values:
				if isPointerType(sub_type) or isNodeClassType(sub_type):
					# Write as uint pointer, record relocation
					if relative_to_header and v != 0:
						self.relocations.append(self._currentRelativeAddress())
					self.write(v, 'uint')
				else:
					self.write(v, sub_type)

			if isUnboundedArrayType(field_type):
		    	# End with empty entry to mark end of array
				for i in range(sub_type_length):
					_ = self.write(0, 'uchar')

			return write_address

		elif isNodeClassType(field_type):
			if isinstance(value, Node) and value.address is not None:
				return value.address
			address = self.writeNode(value, relative_to_header)
			return address

		else: 
			return 0


	def writeNode(self, node, relative_to_header, fields=None):
		if not node:
			return 0

		if not fields:
			fields = node.fields

		# Resolve Node references to addresses. Raw data and pointer arrays are
		# already written by writePrivateData() in Phase 2.
		for field in fields:
			field_name = field[0]
			field_type = markUpFieldType(field[1])
			field_value = getattr(node, field_name)

			if isBracketedType(field_type):
				inner = getBracketedSubType(field_type)
				if isPointerType(inner):
					if field_value is None:
						setattr(node, field_name, 0)
					elif isinstance(field_value, Node):
						setattr(node, field_name, field_value.address if field_value.address is not None else 0)
					# int values are already addresses (from writePrivateData)

			elif isNodeClassType(field_type):
				if field_value is None:
					setattr(node, field_name, 0)
				elif isinstance(field_value, Node):
					setattr(node, field_name, field_value.address if field_value.address is not None else 0)

		# Seek to the node's pre-allocated address before writing its fields
		write_address = node.address
		absolute_address = write_address + (self.DAT_header_length if relative_to_header else 0)
		self.seek(absolute_address)

		current_offset = 0
		for field in fields:
			field_name = field[0]
			field_type = markUpFieldType(field[1])
			field_value = getattr(node, field_name)

			# Flatten pointer/node types to uint for writing, track if it's a relocation
			is_inline_struct = False
			is_pointer_field = False
			if isBracketedType(field_type):
				inner = getBracketedSubType(field_type)
				if isPointerType(inner):
					field_type = 'uint'
					is_pointer_field = True
					if field_value is None:
						field_value = 0
					elif isinstance(field_value, Node):
						field_value = field_value.address if field_value.address is not None else 0
				elif isNodeClassType(inner):
					# Inline struct (@-prefixed) — write its fields directly
					is_inline_struct = True
			elif isPointerType(field_type):
				field_type = 'uint'
				is_pointer_field = True
				if field_value is None:
					field_value = 0
				elif isinstance(field_value, Node):
					field_value = field_value.address if field_value.address is not None else 0
			elif isNodeClassType(field_type):
				field_type = 'uint'
				is_pointer_field = True
				if field_value is None:
					field_value = 0
				elif isinstance(field_value, Node):
					field_value = field_value.address if field_value.address is not None else 0

			if is_inline_struct:
				# Write inline struct by delegating to its writeBinary
				if field_value is not None and hasattr(field_value, 'fields'):
					# Set the inline struct's address so writeNode writes at the right position
					inline_address = write_address + current_offset
					field_value.address = inline_address
					field_value.writeBinary(self)
					# Advance current_offset by the inline struct's total size
					for sub_field in field_value.fields:
						sub_type = sub_field[1]
						sub_alignment = get_alignment_at_offset(sub_type, write_address + current_offset)
						current_offset += sub_alignment + get_type_length(sub_type)
					# Seek back to the correct position for the next field
					self.seek(absolute_address + current_offset)
			elif isBoundedArrayType(field_type) or isUnboundedArrayType(field_type):
				# Write array elements sequentially
				sub_type = getArraySubType(field_type)
				is_pointer_array = isPointerType(sub_type) or isNodeClassType(sub_type)
				if field_value is not None:
					for element in field_value:
						sub_alignment = get_alignment_at_offset(sub_type, write_address + current_offset)
						for _ in range(sub_alignment):
							self.file.write(b'\x00')
						current_offset += sub_alignment
						if isinstance(element, Node):
							addr = element.address if element.address is not None else 0
							if relative_to_header and addr != 0:
								self.relocations.append(write_address + current_offset)
							super().write('uint', addr)
						else:
							super().write(sub_type, element)
						current_offset += get_type_length(sub_type)
					if isUnboundedArrayType(field_type):
						# Null terminator for unbounded arrays
						for _ in range(get_type_length(sub_type)):
							self.file.write(b'\x00')
						current_offset += get_type_length(sub_type)
			else:
				# Insert alignment padding (mirrors parseNode logic)
				alignment = get_alignment_at_offset(field_type, write_address + current_offset)
				for _ in range(alignment):
					self.file.write(b'\x00')
				current_offset += alignment

				# Record relocation for non-zero pointer fields
				if is_pointer_field and relative_to_header and field_value != 0:
					self.relocations.append(write_address + current_offset)

				# Write at current position (sequential within the node's allocated space)
				super().write(field_type, field_value)
				current_offset += get_type_length(field_type)

		return write_address







