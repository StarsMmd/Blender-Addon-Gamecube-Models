from shared.DAT_io import *
from shared.nodes import Node

from shared.nodes.node_types.ArchiveHeader import ArchiveHeader
from shared.nodes.node_types.SectionInfo import SectionInfo

#TODO list
#features:
#implement comp tev
#implement texture animations
#animations of other properties
#culling?
#figure out how the skyboxes are rendered shadeless (just no lights assigned?)
#needed optimizations (bottlenecks):
#image conversion
#bugs:
#fix custom normals #done?
#fix texture transforms
#why are the shadows in pyrite white?
#misc:
#deprecate blender internal material

class Importer:

	@staticmethod
	def parseDAT(operator, context, filepath="", section_name='scene_data', data_type='SCENE', import_animation=True, ik_hack=True, max_frame=1000, verbose=False):

		parser_options = {
			"ik_hack": ik_hack,
			"verbose": verbose
		}

		parser_options["max_frame"] = max_frame if max_frame > 0 else 1000000000

		# We will most likely need to pass the flags and settings into the parser
		# When the parser is asked to parse a node which references one of these it can pass the requried
		# flags into the constructor
		parser = DATParser(filepath, parser_options)
		header = parser.read('ArchiveHeader', 0, 0, False)

		for (address, is_public) in header.section_addresses:
			
			# Recursively parse Node tree based on the section info
		    # The top level node will recursively call parseNode() on any leaves
			section = SectionInfo.readFromBinary(parser, address, is_public, header.section_names_offset)
			print(section)

			# Gives the flexibility to either import all sections or filter to just one
			# Could maybe update this in future so we get an array of section names to include

			if section_name == None or section_name == section.section_name:

		    	# Recursively convert node into blender objects
		    	# The top level node will recursively call toBlender() on any leaves
				if context != None:
					section.root_node.toBlender(context)

		return {'FINISHED'}









