import file_io
import nodes
import nodes.node_types

# A class for managing the recursive parsing of the Node tree. It handles caching
# loaded nodes and reading the next node from the cache or calling its constructor.
# It also inherits all the BinaryReader methods for reading individual fields.
class DATParser(BinaryReader):

	# Length of the Header data of a DAT model. Pointers in the data are relative to the end of this header.
	DAT_header_length = 32

	# Nodes that have already been parsed. If a node is in the cache then return the cached
	# one when that offset is parsed again
	nodes_cache_by_offset = {}

	def __init__(self, path, file_start_offset=0):
		super().__init__(path)
		self.file_start_offset = file_start_offset

	def _startOffset(self, relative_to_header):
		return file_start_offset + (DAT_header_length if relative_to_header else 0)

    def parseNode(self, node_class, address, offset=0, relative_to_header=True):
        #switch the name of the node class and call the fromBinary class method on that class to load the Node
        #add the node to the nodes cache before returning it. If node is already cached for this offset, return that instead
        final_offset = address + offset + _startOffset(relative_to_header)
        cached = nodes_cache_by_offset[final_offset]
        if cached != None:
        	return cached

        new_node = node_class.fromBinary(self, final_offset)
        # TODO: check if flags like ik need to set on the node if they affect its toBlender()

        nodes_cache_by_offset[final_offset] = new_node

        return new_node

    def read(self, type, address, offset=0, relative_to_header=True, whence='start'):
    	final_offset = offset + _startOffset(relative_to_header)
    	return super().read(type, address, final_offset, whence)

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

	def __init__(self, path):
		super().__init__(path)
        self.seek(DAT_header_length) # leave some padding bytes to be overwritten with the header at the end

	def currentRelativeAddress(self):
    	return super().currentAddress() - DAT_header_length

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

        address = node.write(self)
        node.address = address

        nodes_still_processing.remove(node)

        return address












