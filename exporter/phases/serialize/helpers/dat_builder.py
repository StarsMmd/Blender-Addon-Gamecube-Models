try:
    from .....shared.Nodes import *
    from .....shared.Constants import *
    from .....shared.helpers.file_io import *
except (ImportError, SystemError):
    from shared.Nodes import *
    from shared.Constants import *
    from shared.helpers.file_io import *

def _coerce_pointer(value, node, field_name):
	"""Coerce a field value to a uint pointer address for serialization.

	Handles None (→ 0), Node (→ address), empty list (→ 0, null pointer),
	and int (pass through). Raises ValueError with context for anything else.
	"""
	if value is None or (isinstance(value, list) and len(value) == 0):
		return 0
	if isinstance(value, Node):
		return value.address if value.address is not None else 0
	if isinstance(value, int):
		return value
	raise ValueError(
		"Cannot serialize {}.{}: expected Node, None, or int for pointer field, "
		"got {} ({})".format(type(node).__name__, field_name, type(value).__name__, repr(value)[:60]))


# Struct types that make up the materials phase (the first phase Sysdolphin
# emits). RGBAColors are inline (@-fields) so they ride with their Material
# and never appear here.
_MATERIAL_TYPES = frozenset({
	'Image', 'Texture', 'Material', 'MaterialObject',
	'PixelEngine', 'TextureLOD', 'TextureTEV',
})
_ENVELOPE_TYPES = frozenset({'EnvelopeList', 'Envelope'})
_VERTEX_TYPES = frozenset({'Vertex', 'VertexList'})
_GEOMETRY_TYPES = frozenset({'PObject', 'Mesh'})


# Serializes a node tree to DAT binary format.
# The build process has 4 internal steps:
# 1) Collect nodes via DFS post-order traversal into an ordered list (leaf-first).
# 2) Write shared raw data (vertex buffers, image pixels, palette data) with deduplication.
# 3) For each node: write private data, then allocate struct address space.
# 4) Write node structs at allocated addresses, resolve pointers, record relocations.
# Auto-closes the file after build() if the builder opened it from a path.
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
		# Also records which root each node was first reached from so size
		# accounting can attribute bytes to the owning section.
		self.node_list = []
		self.section_ownership = {}  # id(node) -> index into root_nodes
		self.node_sizes = {}         # id(node) -> data section bytes contributed (populated in build())
		visited = set()
		for section_index, root_node in enumerate(root_nodes):
			self._current_section_index = section_index
			self._dfsPostOrder(root_node, visited)
		self._current_section_index = None

	def _dfsPostOrder(self, node, visited):
		"""DFS traversal matching SysDolphin compiler conventions:
		- 'child'/'next'/'link' fields (same-type tree/list pointers) are written AFTER the node
		- All other Node-typed fields are written BEFORE the node (DFS into them first)
		- Inline structs (@-prefixed) are skipped (they're part of the parent struct)
		- Deduplicates by object identity"""
		if node is None or id(node) in visited:
			return
		visited.add(id(node))
		if self._current_section_index is not None:
			self.section_ownership[id(node)] = self._current_section_index

		if not hasattr(node, 'fields'):
			self.node_list.append(node)
			return

		deferred = []  # (field_name, value) for child/next/link fields

		# A node may declare a custom direct-children traversal order; listed
		# fields are visited first (in that order), the rest keep declared order.
		field_order = getattr(node, 'serialization_field_order', None)
		if field_order:
			listed = [f for name in field_order for f in node.fields if f[0] == name]
			ordered_fields = listed + [f for f in node.fields if f[0] not in field_order]
		else:
			ordered_fields = node.fields

		# First pass: recurse into non-link fields (written BEFORE this node)
		for field in ordered_fields:
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

	def align_buffer(self):
		"""Pad to 32-byte alignment before writing a raw data buffer.

		Matches HSDLib's IsBuffer alignment: buffers (vertex data, textures,
		palettes, display lists) must be 32-byte aligned for GX hardware.
		Called by node writePrimitivePointers/writePrivateData before writing
		any raw data blob.
		"""
		while self._currentRelativeAddress() % 32 != 0:
			self.write(0, 'uchar')

	def _serialization_blocks(self):
		"""Collect the explicit serialization order of every subtree whose
		root node declares one (``serializes_subtree`` types — currently the
		bone and material animation joint trees). Each node owns the ordering
		of its own subtree via ``serializationOrder``; the builder only finds
		the roots and writes the resulting blocks.

		Returns a list of flat node-lists, one per subtree, ordered by first
		appearance in node_list.
		"""
		candidates = [n for n in self.node_list if getattr(n, 'serializes_subtree', False)]
		if not candidates:
			return []
		# A subtree root is a candidate not referenced as a child/next of
		# another candidate of the same kind.
		referenced = set()
		for n in candidates:
			for fn in ('child', 'next'):
				v = getattr(n, fn, None)
				if isinstance(v, Node):
					referenced.add(id(v))
				elif isinstance(v, list):
					for it in v:
						if isinstance(it, Node):
							referenced.add(id(it))
		blocks = []
		for n in candidates:
			if id(n) in referenced:
				continue
			order = n.serializationOrder()
			if order:
				blocks.append(order)
		return blocks

	def _write_block(self, nodes):
		"""Write a declared serialization block: consecutive Frame runs are
		pooled (buffers then structs), other nodes are written inline."""
		di, m = 0, len(nodes)
		while di < m:
			if type(nodes[di]).__name__ == 'Frame':
				de = di
				while de < m and type(nodes[de]).__name__ == 'Frame':
					de += 1
				self._write_frame_run(nodes[di:de])
				di = de
			else:
				self._write_node(nodes[di])
				di += 1

	def _ordered_node_list(self):
		"""The overarching emission order — the builder's responsibility.

		node_list is DFS post-order and already carries each node's declared
		direct-child order (``serialization_field_order``). This pass reorders
		it into the game's struct phase sequence — materials → envelopes →
		vertex descriptors → geometry → skeleton → (animations + scene) —
		preserving each node's node_list-relative order *within* its phase
		(which already matches game-native for every phase except materials,
		handled specially, and envelopes, see below).

		Envelopes are grouped at their phase position but **not** internally
		reordered (their convention isn't cracked yet): because the set of
		envelope structs is fixed, the grouped region has the correct total
		size, so the downstream phases still land at the right offsets — only
		the envelope structs themselves stay internally mis-ordered. See
		technical-docs/implementation_notes.md § Struct ordering convention.
		"""
		nl = self.node_list
		kind = lambda n: type(n).__name__
		mobj_rank = self._material_object_order()
		vl_rank = self._vertex_list_order()

		# Materials and vertex descriptors are emitted as blocks (a contiguous
		# node_list run ending at the MaterialObject / VertexList) ordered by
		# their leaf's reverse joint-post rank. Envelopes are *grouped* at
		# their phase position but kept in node_list order (their convention
		# isn't cracked); grouping them — even mis-ordered internally — keeps
		# the downstream phases contiguous so they stay correctly ordered.
		# Geometry, skeleton and the rest (animations + scene) keep their
		# node_list-relative order.
		material_blocks, mat_cur = [], []
		vertex_blocks, vtx_cur = [], []
		envelopes, geometry, skeleton, rest = [], [], [], []
		for n in nl:
			k = kind(n)
			if k in _MATERIAL_TYPES:
				mat_cur.append(n)
				if k == 'MaterialObject':
					material_blocks.append(mat_cur)
					mat_cur = []
			elif k in _VERTEX_TYPES:
				vtx_cur.append(n)
				if k == 'VertexList':
					vertex_blocks.append(vtx_cur)
					vtx_cur = []
			elif k in _ENVELOPE_TYPES:
				envelopes.append(n)
			elif k in _GEOMETRY_TYPES:
				geometry.append(n)
			elif k == 'Joint':
				skeleton.append(n)
			else:
				rest.append(n)
		rest.extend(mat_cur)
		rest.extend(vtx_cur)
		material_blocks.sort(key=lambda b: mobj_rank.get(id(b[-1]), 1 << 30))
		vertex_blocks.sort(key=lambda b: vl_rank.get(id(b[-1]), 1 << 30))

		ordered = [n for block in material_blocks for n in block]
		ordered.extend(envelopes)
		ordered.extend(n for block in vertex_blocks for n in block)
		ordered.extend(geometry)
		ordered.extend(skeleton)
		ordered.extend(rest)
		return ordered

	def _reverse_joint_post_order(self, extract):
		"""Compute the emission rank of a per-mesh leaf struct (a
		MaterialObject or a VertexList) — the reverse of (joint post-order →
		each joint's mesh list → ``extract(mesh)``, first-encounter dedup).
		Cross-validated against game-native PKX for both materials and vertex
		descriptors. ``extract(mesh)`` yields the leaf node(s) for a mesh.
		Returns id(leaf) → rank."""
		nl = self.node_list
		kind = lambda n: type(n).__name__
		joints = [n for n in nl if kind(n) == 'Joint']
		referenced = set()
		for j in joints:
			for fn in ('child', 'next'):
				v = getattr(j, fn, None)
				if isinstance(v, Node):
					referenced.add(id(v))
		roots = [j for j in joints if id(j) not in referenced]
		mesh_by_addr = {n.address: n for n in nl if kind(n) == 'Mesh'}

		post = []
		seen_j = set()

		def visit(j):
			if not isinstance(j, Node) or kind(j) != 'Joint' or id(j) in seen_j:
				return
			seen_j.add(id(j))
			visit(getattr(j, 'child', None))
			visit(getattr(j, 'next', None))
			post.append(j)
		for r in roots:
			visit(r)

		fwd = []
		seen = set()
		for j in post:
			prop = getattr(j, 'property', None)
			mesh = mesh_by_addr.get(prop) if isinstance(prop, int) else (
				prop if isinstance(prop, Node) and kind(prop) == 'Mesh' else None)
			while isinstance(mesh, Node):
				for leaf in extract(mesh):
					if isinstance(leaf, Node) and id(leaf) not in seen:
						seen.add(id(leaf))
						fwd.append(leaf)
				mesh = getattr(mesh, 'next', None)
		return {id(x): r for r, x in enumerate(reversed(fwd))}

	def _material_object_order(self):
		"""Emission rank of each MaterialObject (one per mesh)."""
		return self._reverse_joint_post_order(
			lambda mesh: [getattr(mesh, 'mobject', None)])

	def _vertex_list_order(self):
		"""Emission rank of each VertexList (via each mesh's PObject chain)."""
		def extract(mesh):
			po = getattr(mesh, 'pobject', None)
			while isinstance(po, Node) and type(po).__name__ == 'PObject':
				yield getattr(po, 'vertex_list', None)
				po = getattr(po, 'next', None)
		return self._reverse_joint_post_order(extract)

	def _write_frame_run(self, frames):
		"""Pool a run of Frame nodes: every keyframe buffer (4-byte aligned)
		first, then every Frame struct — matching Sysdolphin's layout."""
		starts = {}
		for f in frames:
			self.seek(0, 'end')
			while self._currentRelativeAddress() % 4 != 0:
				self.write(0, 'uchar')
			starts[id(f)] = self._currentRelativeAddress()
			f.writePrivateData(self)
		for f in frames:
			self._allocate_struct(f)
			self.seek(0, 'end')
			self.node_sizes[id(f)] = self._currentRelativeAddress() - starts[id(f)]

	def _write_node(self, node):
		"""Generic single-node write: private data, then struct allocation."""
		start = self._currentRelativeAddress()
		node.writePrivateData(self)
		self._allocate_struct(node)
		self.seek(0, 'end')
		self.node_sizes[id(node)] = self._currentRelativeAddress() - start

	def _allocate_struct(self, node):
		"""Reserve struct address space at the end of the file with the
		parser-expected first-field alignment. Sets node.address (None for
		zero-size stub nodes)."""
		node_size = node.allocationSize()
		if node_size > 0:
			self.seek(0, 'end')
			if len(node.fields) > 0:
				first_field = node.fields[0]
				alignment = get_alignment_at_offset(markUpFieldType(first_field[1]), self._currentRelativeAddress())
			else:
				alignment = (4 - (self._currentRelativeAddress() % 4)) % 4
			for _ in range(alignment):
				self.write(0, 'uchar')
			node.address = self._currentRelativeAddress() + node.allocationOffset()
			for _ in range(node_size):
				self.write(0, 'uchar')
		else:
			node.address = None

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

		# --- Phase 2: write private data + allocate structs ---
		# Frame keyframe buffers are pooled per animation: a consecutive run
		# of Frame nodes writes every buffer first, then every struct —
		# matching Sysdolphin's [buffers][structs] layout. Subtrees whose root
		# declares a serialization order (``serializes_subtree`` — the bone /
		# material animation joint trees) are written as a single block in
		# that declared order, triggered on the first of their nodes seen in
		# node_list and skipped thereafter. See implementation_notes.md.
		blocks = self._serialization_blocks()
		block_of_node = {}
		for bi, block in enumerate(blocks):
			for nd in block:
				block_of_node[id(nd)] = bi
		written_blocks = set()

		ordered_nodes = self._ordered_node_list()
		self.seek(0, 'end')
		idx, n = 0, len(ordered_nodes)
		while idx < n:
			node = ordered_nodes[idx]

			bi = block_of_node.get(id(node))
			if bi is not None:
				if bi not in written_blocks:
					written_blocks.add(bi)
					self._write_block(blocks[bi])
				idx += 1
				continue

			# Generic path (pools any stray Frame run too)
			if type(node).__name__ == 'Frame':
				end = idx
				while end < n and type(ordered_nodes[end]).__name__ == 'Frame':
					end += 1
				self._write_frame_run(ordered_nodes[idx:end])
				idx = end
				continue
			self._write_node(node)
			idx += 1

		# --- Phase 2.5a: Write palette LUT data ---
		# Sysdolphin's compiler places palettes and image pixels at the very
		# end of the data section, after all parsed structs. Palettes come
		# just before the image data they index.
		for node in self.node_list:
			node.writePaletteData(self)

		# --- Phase 2.5b: Write image pixel data ---
		# Identical pixel buffers across Image instances are deduplicated so
		# shared textures contribute one block to the file.
		for node in self.node_list:
			node.writeImageData(self)

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
		# file_size = total file size including the 0x20 header, ending right
		# after the last string null terminator (no trailing padding).
		file_size = self._currentRelativeAddress() + self.DAT_header_length
		relocations_count = len(self.relocations)
		self.write(file_size, 'uint', 0, False)
		self.write(data_section_length, 'uint', 4, False)
		self.write(relocations_count, 'uint', 8, False)
		self.write(len(self.root_nodes), 'uint', 12, False)
		self.write(0, 'uint', 16, False)  # external_nodes_count

		# Auto-close if we opened the file ourselves (from a path).
		# External streams (e.g. BytesIO) are left open for the caller.
		if self.filepath is not None:
			self.close()

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
			# Track whether the field points at an actual allocation, so
			# `address == 0` (start of data section — possible when the
			# referenced node was the first thing written) still records a
			# relocation. Discriminating on value != 0 alone collapses
			# "null pointer" and "valid offset 0" and silently drops the
			# latter, leaving the runtime to read an unrebased zero.
			referenced = False
			if value is None:
				value = 0
			elif isinstance(value, Node):
				if value.address is not None:
					value = value.address
					referenced = True
				else:
					value = 0
			else:
				# Plain int — assume non-zero values are real pointers; we
				# can't tell a non-Node 0 from null at this level, so leave
				# the old behaviour (caller must use _raw_pointer_fields or
				# pass a Node to force a relocation on a zero offset).
				referenced = (value != 0)
			if relative_to_header and referenced:
				reloc_addr = address if address is not None else self._currentRelativeAddress()
				self.relocations.append(reloc_addr)
			return self.write(value, 'uint', address, relative_to_header, whence)

		elif isUnboundedArrayType(field_type) or isBoundedArrayType(field_type):
			sub_type = getArraySubType(field_type)
			sub_type_length = get_type_length(sub_type)
			values = value

			# Resolve Node references to addresses before writing. Carry a
			# parallel "referenced" flag per element so an entry whose
			# referenced node sits at address 0 still records a relocation
			# (mirrors the singleton-pointer path above).
			referenced_flags = []
			if isPointerType(sub_type) or isNodeClassType(sub_type):
				resolved = []
				for v in values:
					if isinstance(v, Node):
						if v.address is not None:
							resolved.append(v.address)
							referenced_flags.append(True)
						else:
							resolved.append(0)
							referenced_flags.append(False)
					elif v is None:
						resolved.append(0)
						referenced_flags.append(False)
					else:
						resolved.append(v)
						referenced_flags.append(v != 0)
				values = resolved

			write_address = self._currentRelativeAddress() if relative_to_header else self.currentAddress()
			for i, v in enumerate(values):
				if isPointerType(sub_type) or isNodeClassType(sub_type):
					if relative_to_header and referenced_flags[i]:
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
					field_value = _coerce_pointer(field_value, node, field_name)
				elif isNodeClassType(inner):
					# Inline struct (@-prefixed) — write its fields directly
					is_inline_struct = True
			elif isPointerType(field_type):
				field_type = 'uint'
				is_pointer_field = True
				field_value = _coerce_pointer(field_value, node, field_name)
			elif isNodeClassType(field_type):
				field_type = 'uint'
				is_pointer_field = True
				field_value = _coerce_pointer(field_value, node, field_name)

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
							if relative_to_header and (addr != 0 or element.address == 0):
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

				# Record relocation for pointer fields. Normally skip zero (null
				# pointer), but fields in _raw_pointer_fields are real data pointers
				# that happen to point to offset 0 (start of data section).
				force_reloc = hasattr(node, '_raw_pointer_fields') and field_name in node._raw_pointer_fields
				if is_pointer_field and relative_to_header and (field_value != 0 or force_reloc):
					self.relocations.append(write_address + current_offset)

				# Write at current position (sequential within the node's allocated space)
				try:
					super().write(field_type, field_value)
				except (ValueError, Exception) as e:
					raise ValueError(
						"Serializing {}.{} (type '{}'): {}".format(
							node.__class__.__name__, field_name, field[1], e)) from e
				current_offset += get_type_length(field_type)

		return write_address







