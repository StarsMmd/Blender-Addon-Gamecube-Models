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

# Scene-tail struct types (the SceneData subtree + BoundBox). Emitted last,
# after the palette structs — matching the compiler's [animations][palettes]
# [scene tail][BoundBox] layout.
_SCENE_TYPES = frozenset({
	'SceneData', 'LightSet', 'Light', 'CameraSet', 'Camera',
	'WObject', 'ModelSet', 'Fog', 'BoundBox',
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

	def __init__(self, path_or_stream, root_nodes, section_names=None, dedup_buffers=False):
		super().__init__(path_or_stream)
		# Reserve space for the header (will be overwritten at the end)
		self.file.write(b'\x00' * self.DAT_header_length)

		self.root_nodes = root_nodes
		self.section_names = section_names or [None] * len(root_nodes)
		self.relocations = []

		# Content-addressed buffer dedup. Maps a namespace (e.g. 'image',
		# 'palette', 'frame_ad') to a {bytes: header-relative offset} cache so
		# identical raw buffers within a category share a single written block.
		# Kept per-namespace rather than global so each category keeps its own
		# alignment/layout discipline (see write_dedup_blob).
		self._blob_caches = {}
		# Whether to apply the *optional* buffer dedups (palette LUTs, keyframe
		# streams) that shrink the output but diverge from the original
		# compiler's layout. Off by default: the original compiler did not dedup
		# these, so exports stay layout-faithful and binary round-trips match
		# game files byte-for-byte. Opt in by passing True to recover the size
		# win on arbitrary models. Dedups flagged matches_original=True (image
		# pixels) are applied regardless of this flag.
		self.dedup_buffers = dedup_buffers

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

	def _dfsPostOrder(self, node, visited, skip_next=False):
		"""DFS traversal matching SysDolphin compiler conventions:
		- 'child'/'next'/'link' fields (same-type tree/list pointers) are written AFTER the node
		- All other Node-typed fields are written BEFORE the node (DFS into them first)
		- Inline structs (@-prefixed) are skipped (they're part of the parent struct)
		- Deduplicates by object identity

		``skip_next`` suppresses the node's own ``next`` deferral: used when a
		caller is walking a ``next``-linked chain itself (see
		``serialization_reverse_chain_fields``) so the chain isn't followed
		twice."""
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

		# Fields whose value heads a ``next``-linked chain emitted in reverse
		# (deepest element first, head last) — the compiler's order for e.g. a
		# MaterialObject's multi-texture chain.
		reverse_chains = getattr(node, 'serialization_reverse_chain_fields', None) or ()

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
				if skip_next and field_name == 'next':
					continue
				if isinstance(value, Node):
					deferred.append(value)
				elif isinstance(value, list):
					for item in value:
						if isinstance(item, Node):
							deferred.append(item)
				continue

			# A reversed ``next``-chain field: walk the chain, recurse into each
			# element deepest-first (suppressing its own ``next`` so the chain
			# isn't re-followed).
			if field_name in reverse_chains and isinstance(value, Node):
				chain = []
				cur = value
				while isinstance(cur, Node):
					chain.append(cur)
					cur = getattr(cur, 'next', None)
				for link_node in reversed(chain):
					self._dfsPostOrder(link_node, visited, skip_next=True)
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

	def write_dedup_blob(self, raw, namespace, align=0, matches_original=False):
		"""Write a raw byte buffer at the file tail, deduplicated by content
		within ``namespace``. Identical buffers in the same namespace share one
		written block; returns the header-relative offset of the (possibly
		shared) block. Returns 0 for an empty/None buffer.

		``align`` pads to that byte boundary before a freshly-written block (the
		shared block inherits the alignment of its first write). Namespaces are
		kept separate so one category's buffers can't land at another's expected
		alignment. Used for image pixels, palette LUTs and keyframe (Frame.ad)
		buffers; the same primitive could back any other pointer-referenced blob.

		``matches_original=True`` marks a dedup the original compiler also
		performed (image pixels) — always applied. The default is an *optional*
		size optimisation gated by ``self.dedup_buffers``: skipped (every buffer
		written fresh) when that flag is off, so binary round-trips reproduce the
		original layout.
		"""
		if not raw:
			return 0
		key = bytes(raw)
		dedup = matches_original or self.dedup_buffers
		if dedup:
			cache = self._blob_caches.setdefault(namespace, {})
			cached = cache.get(key)
			if cached is not None:
				return cached
		self.seek(0, 'end')
		if align:
			while self._currentRelativeAddress() % align != 0:
				self.write(0, 'uchar')
		offset = self._currentRelativeAddress()
		self.file.write(key)
		if dedup:
			cache[key] = offset
		return offset

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

	@staticmethod
	def _envelope_content_key(envelope_list):
		"""Identity key for an EnvelopeList by its contents — the (joint, weight)
		sequence. Keyed on joint object identity (joint addresses aren't assigned
		yet when envelopes are written; identical envelopes share joint objects
		because Joint is cachable)."""
		return tuple(
			(id(env.joint) if isinstance(env.joint, Node) else env.joint,
			 round(env.weight, 6))
			for env in getattr(envelope_list, 'envelopes', [])
		)

	def _ordered_node_list(self):
		"""The overarching emission order — the builder's responsibility.

		node_list is DFS post-order and already carries each node's declared
		direct-child order (``serialization_field_order``). This pass reorders
		it into the game's struct phase sequence — materials → envelopes →
		vertex descriptors → geometry → skeleton → (animations + scene) —
		preserving each node's node_list-relative order *within* its phase
		(which already matches game-native for every phase except materials,
		handled specially, and envelopes, see below).

		Envelopes are grouped at their phase position and internally ordered
		by the reconstructed allocation convention (see
		``_envelope_emission_order``); because the set of envelope structs is
		fixed, the grouped region always has the correct total size, so the
		downstream phases land at the right offsets even where the internal
		order is only approximate. See
		technical-docs/implementation_notes.md § Struct ordering convention.
		"""
		nl = self.node_list
		kind = lambda n: type(n).__name__
		mobj_rank = self._material_object_order()
		vl_rank = self._vertex_list_order()

		# Materials and vertex descriptors are emitted as blocks (a contiguous
		# node_list run ending at the MaterialObject / VertexList) ordered by
		# their leaf's reverse joint-post rank. Envelopes are grouped at
		# their phase position and sorted by the reconstructed allocation
		# order; grouping keeps the downstream phases contiguous so they stay
		# correctly ordered even where the internal order is approximate.
		# Geometry, skeleton and the rest (animations + scene) keep their
		# node_list-relative order.
		material_blocks, mat_cur = [], []
		vertex_blocks, vtx_cur = [], []
		envelopes, geometry, skeleton, rest = [], [], [], []
		palettes, scene = [], []
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
			elif k == 'Palette':
				palettes.append(n)
			elif k in _SCENE_TYPES:
				scene.append(n)
			else:
				rest.append(n)
		rest.extend(mat_cur)
		rest.extend(vtx_cur)
		material_blocks.sort(key=lambda b: mobj_rank.get(id(b[-1]), 1 << 30))
		vertex_blocks.sort(key=lambda b: vl_rank.get(id(b[-1]), 1 << 30))

		# Envelope structs: sort by the reconstructed allocation order (stable,
		# so aliases of one content key and any unranked stragglers keep their
		# node_list-relative order).
		env_rank = self._envelope_emission_order()
		if env_rank:
			default_rank = len(env_rank)
			envelopes.sort(key=lambda n: env_rank.get(
				self._envelope_content_key(n), default_rank)
				if kind(n) == 'EnvelopeList' else default_rank)

		# Palette structs and the scene tail trail the rest: the compiler emits
		# them after the animation region as [palettes][scene tail][BoundBox].
		ordered = [n for block in material_blocks for n in block]
		ordered.extend(envelopes)
		ordered.extend(n for block in vertex_blocks for n in block)
		ordered.extend(geometry)
		ordered.extend(skeleton)
		ordered.extend(rest)
		ordered.extend(palettes)
		ordered.extend(scene)
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

	# Byte width of each display-list vertex component format (Vertex.getFormat()).
	_DL_FORMAT_SIZES = {
		'uchar': 1, 'char': 1, 'ushort': 2, 'short': 2,
		'float': 4, 'uint': 4, 'void': 0, 'RGBAColor': 4, 'RGBColor': 3,
	}

	@classmethod
	def _dl_format_size(cls, fmt):
		"""Byte width of one display-list component, supporting 'base[n]' forms."""
		if fmt.endswith(']'):
			base, count = fmt[:-1].split('[')
			return cls._DL_FORMAT_SIZES[base] * int(count)
		return cls._DL_FORMAT_SIZES[fmt]

	@classmethod
	def _dl_slot_first_positions(cls, pobj):
		"""Scan a PObject's raw display list and return {matrix_slot:
		position_index_at_first_use}. Position indices are only meaningful for
		indexed POS attributes; direct-position or missing data yields no
		entry (callers fall back to a large sentinel)."""
		data = getattr(pobj, 'raw_display_list', b'') or b''
		vertex_list = getattr(pobj, 'vertex_list', None)
		if not data or vertex_list is None:
			return {}
		descs = []
		for v in vertex_list.vertices:
			try:
				size = cls._dl_format_size(v.getFormat())
			except (KeyError, ValueError):
				return {}
			descs.append((v.attribute, v.attribute_type, size))
		stride = sum(size for _, _, size in descs)
		if stride == 0:
			return {}
		first = {}
		off = 0
		end = len(data)
		while off < end:
			opcode = data[off] & gx.GX_OPCODE_MASK
			off += 1
			if opcode == gx.GX_NOP or off + 2 > end:
				break
			count = int.from_bytes(data[off:off + 2], 'big')
			off += 2
			for _ in range(count):
				if off + stride > end:
					return first
				o = off
				slot = pos = None
				for attr, attr_type, size in descs:
					if attr == gx.GX_VA_PNMTXIDX and size == 1:
						slot = data[o] // 3
					elif attr == gx.GX_VA_POS and attr_type != gx.GX_DIRECT:
						if size == 1:
							pos = data[o]
						elif size == 2:
							pos = int.from_bytes(data[o:o + 2], 'big')
					o += size
				if slot is not None and pos is not None and slot not in first:
					first[slot] = pos
				off += stride
		return first

	def _envelope_emission_order(self):
		"""Rank envelope structs by the compiler's reconstructed allocation order.

		Convention (validated against game-native models — see
		technical-docs/implementation_notes.md § struct ordering convention):
		- Combos are allocated per mesh (DObject). DObjects are processed in
		  reverse pre-order of the joint tree with each joint's mesh chain in
		  forward order; a combo shared between DObjects belongs to the first
		  processing DObject that uses it.
		- The finished per-DObject blocks are emitted in reverse processing
		  order (head-inserted list), each block's internal order preserved.
		- Within a block, combos follow the original tool's vertex scan,
		  reconstructed by merging the PObject palette-slot chains (slot index
		  ≈ local first-need order), always popping the chain head whose first
		  display-list position index is smallest.

		Returns {content_key: rank} over unique envelope contents; empty when
		the tree has no enveloped meshes.
		"""
		nl = self.node_list
		kind = lambda n: type(n).__name__
		joints = [n for n in nl if kind(n) == 'Joint']
		if not joints:
			return {}
		referenced = set()
		for j in joints:
			for fn in ('child', 'next'):
				v = getattr(j, fn, None)
				if isinstance(v, Node):
					referenced.add(id(v))
		roots = [j for j in joints if id(j) not in referenced]
		mesh_by_addr = {n.address: n for n in nl if kind(n) == 'Mesh'}

		pre = []
		seen_j = set()

		def visit(j):
			while isinstance(j, Node) and kind(j) == 'Joint' and id(j) not in seen_j:
				seen_j.add(id(j))
				pre.append(j)
				visit(getattr(j, 'child', None))
				j = getattr(j, 'next', None)
		for r in roots:
			visit(r)

		# Collect DObjects in traversal order with their envelope usage stats:
		# per content key, per local PObject index -> (slot, first position).
		SENTINEL = 1 << 30
		dobjs = []  # (joint_rank, mesh_i, {key: {p_local: (slot, fpos)}})
		seen_m = set()
		seen_p = set()
		for j_rank, j in enumerate(pre):
			prop = getattr(j, 'property', None)
			mesh = mesh_by_addr.get(prop) if isinstance(prop, int) else (
				prop if isinstance(prop, Node) and kind(prop) == 'Mesh' else None)
			mesh_i = 0
			while isinstance(mesh, Node):
				if id(mesh) in seen_m:
					break
				seen_m.add(id(mesh))
				stats = {}
				pobj = getattr(mesh, 'pobject', None)
				p_local = 0
				while isinstance(pobj, Node) and kind(pobj) == 'PObject':
					if id(pobj) in seen_p:
						break
					seen_p.add(id(pobj))
					slots = getattr(pobj, 'property', None)
					if isinstance(slots, list) and slots:
						first_pos = self._dl_slot_first_positions(pobj)
						for slot, env_list in enumerate(slots):
							if env_list is None:
								continue
							key = self._envelope_content_key(env_list)
							uses = stats.setdefault(key, {})
							if p_local not in uses:
								uses[p_local] = (slot, first_pos.get(slot, SENTINEL))
					pobj = getattr(pobj, 'next', None)
					p_local += 1
				if stats:
					dobjs.append((j_rank, mesh_i, stats))
				mesh = getattr(mesh, 'next', None)
				mesh_i += 1
		if not dobjs:
			return {}

		# Membership: the first DObject in processing order (reverse pre-order
		# of joints, forward mesh chains) that uses a combo owns it.
		processing = sorted(range(len(dobjs)),
		                    key=lambda i: (-dobjs[i][0], dobjs[i][1]))
		owner = {}
		for di in processing:
			for key in dobjs[di][2]:
				owner.setdefault(key, di)

		# Emission: blocks in reverse processing order; within a block, merge
		# the per-PObject slot chains by smallest first-position head.
		rank = {}
		for di in reversed(processing):
			stats = dobjs[di][2]
			block = [key for key in stats if owner[key] == di]
			chains = {}
			for key in block:
				for p_local, (slot, _) in stats[key].items():
					chains.setdefault(p_local, []).append((slot, key))
			for p_local in chains:
				chains[p_local].sort()
			pointers = {p_local: 0 for p_local in chains}
			emitted = set()
			for _ in range(len(block)):
				best = None
				for p_local, chain in chains.items():
					i = pointers[p_local]
					while i < len(chain) and chain[i][1] in emitted:
						i += 1
					pointers[p_local] = i
					if i < len(chain):
						key = chain[i][1]
						fpos = min(f for _, f in stats[key].values())
						head = (fpos, p_local, chain[i][0], key)
						if best is None or head < best:
							best = head
				if best is None:
					break
				key = best[3]
				emitted.add(key)
				rank[key] = len(rank)
			for key in block:
				if key not in emitted:
					rank[key] = len(rank)
		return rank

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

		# Envelope lists are content-deduplicated: the compiler emits one struct
		# per unique (joint, weight) sequence and shares it across PObject slots.
		# Our parse creates a separate object per slot (EnvelopeList is
		# is_cachable=False), so collapse them here — the first object of each
		# content key is written and every later duplicate aliases its address.
		# Aliases are skipped at struct-write time (Phase 3) so they neither
		# re-emit bytes nor add duplicate relocation entries.
		env_canonical = {}

		# Palette structs and the scene tail are emitted *after* the texture
		# data buffers (image pixels, palette LUTs) at the very end of the file:
		# [image data][palette LUT + struct interleaved][scene tail][BoundBox].
		# They are deferred out of this struct pass and written below.
		deferred_palettes, deferred_scene = [], []

		ordered_nodes = self._ordered_node_list()
		self.seek(0, 'end')
		idx, n = 0, len(ordered_nodes)
		while idx < n:
			node = ordered_nodes[idx]
			tn = type(node).__name__
			if tn == 'Palette':
				deferred_palettes.append(node)
				idx += 1
				continue
			if tn in _SCENE_TYPES:
				deferred_scene.append(node)
				idx += 1
				continue

			bi = block_of_node.get(id(node))
			if bi is not None:
				if bi not in written_blocks:
					written_blocks.add(bi)
					self._write_block(blocks[bi])
				idx += 1
				continue

			if type(node).__name__ == 'EnvelopeList':
				key = self._envelope_content_key(node)
				canon = env_canonical.get(key)
				if canon is not None:
					node.address = canon.address
					node._envelope_alias = True
					idx += 1
					continue
				env_canonical[key] = node
				self._write_node(node)
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

		# --- Phase 2.5: Write image pixel data ---
		# Image pixels go at the file tail, in struct-address order (the order the
		# owning Image structs were emitted, *not* node_list/DFS order) so their
		# data pointers ascend with the structs. Identical pixel buffers across
		# Images are deduplicated (first by struct order owns the block).
		by_struct_addr = sorted(
			self.node_list,
			key=lambda n: n.address if n.address is not None else (1 << 40),
		)
		for node in by_struct_addr:
			node.writeImageData(self)

		# --- Phase 2.6: Palettes — LUT data then struct, interleaved ---
		# After the image data, each palette writes its LUT block immediately
		# followed by its struct, in struct-emission order.
		for palette in deferred_palettes:
			palette.writePaletteData(self)
			self._write_node(palette)

		# --- Phase 2.7: Scene tail (then BoundBox) ---
		# The scene structs trail every data buffer. The SceneData subtree is a
		# serialization block (triggered on its first node); BoundBox, a separate
		# root, follows via the generic path.
		for node in deferred_scene:
			bi = block_of_node.get(id(node))
			if bi is not None:
				if bi not in written_blocks:
					written_blocks.add(bi)
					self._write_block(blocks[bi])
				continue
			self._write_node(node)

		# --- Phase 3: Write node structs at allocated addresses ---
		# Skip envelope-list aliases (they share a written canonical's address).
		for node in self.node_list:
			if getattr(node, '_envelope_alias', False):
				continue
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







