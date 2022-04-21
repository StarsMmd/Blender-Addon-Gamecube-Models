from shared import DAT_io
from shared.nodes import SectionInfo

from shared.nodes.node_types import ArchiveHeader
#TODO: add imports for any root node types or header info this function needs to know about

class Exporter():

	@staticmethod
	def writeDAT(path, context):
		
		builder = DATBuilder(path)

		sections = []

		# TODO: Complete implementation for parsing node tree from blender context

		scene_data_node = SectionInfo.fromBlender(context, "scene_data") # replace with correct root node type
		if scene_data_node != None:
			sections.append(scene_data_node)
			scene_data_node.root_node.write(builder)

		bound_box_node = SectionInfo.fromBlender(contextm "bound_box") # replace with correct root node type
		if bound_box_node != None:
			sections.append(bound_box_node)
			bound_box_node.root_node.write(builder)

		# TODO: any other section types?

		for section in sections:
			# TODO: calculate the address where the name string for this section will be
			# and write the string later
			string_address = 0
			section.write(builder)

		data_size = builder.currentRelativeAddress()

		# TODO: write relocations table
		relocations_count = 0 # TODO: calculate number of relocations

		public_nodes_count = 0
		external_nodes_count = 0

		for section in sections:
			builder.write("string", section.section_name)
			if section.isPublic:
				public_nodes_count += 1
			else:
				external_nodes_count += 1

		file_size = builder.currentAddress()

		header = ArchiveHeader(None, None, file_size, data_size, relocations_count, public_nodes_count, external_nodes_count)
		header.write(builder)

		builder.close()


