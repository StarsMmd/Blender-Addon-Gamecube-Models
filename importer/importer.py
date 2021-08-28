from ..shared import DAT_io
from ..shared.nodes import Node

from ..shared.nodes.node_types import ArchiveHeader
from ..shared.nodes.node_types import SectionInfo
#TODO: add imports for any root node types or header info this function needs to know about

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

class Importer():

	@staticmethod
	def parseDAT(operator, context, filepath="", section_name='scene_data', data_type='SCENE', import_animation=True, ik_hack=True, max_frame=1000, use_max_frame=True):
	    if use_max_frame:
	        anim_max_frame = max_frame
	    else:
	        anim_max_frame = 1000000000

	    # We will most likely need to pass the flags and settings into the parser
	    # When the parser is asked to parse a node which references one of these it can pass the requried
	    # flags into the constructor
	    parser = DATParser(path)
	    header = parser.parseNode(ArchiveHeader, 0, 0, False)

	    relocations_size = relocations_count * 4
	    header_size = 32
	    sections_start = header.data_size + relocations_size + header_size
	    section_size = 8

	    # Parse sections info
	    section_addresses = []

	    current_offset = sections_start
	    for i in range(header.public_nodes_count):
	    	section_addresses.append( (current_offset, True) )
	    	current_offset += section_size

	    for i in range(header.external_nodes_count):
	    	section_addresses.append( (current_offset, False) )
	    	current_offset += section_size

	    for (address, isPublic) in section_addresses:
	    	
	    	# Recursively parse Node tree based on the section info
		    # The top level node will recursively call parseNode() on any leaves
	    	section = SectionInfo(parser, address, isPublic)

	    	# Gives the flexibility to either import all sections or filter to just one
	    	# Could maybe update this in future so we get an array of section names to include

	    	if section_name == None or section_name == section.section_name:

		    	# Recursively convert node into blender objects
		    	# The top level node will recursively call toBlender() on any leaves
		    	section.root_node.toBlender(context)

	    return {'FINISHED'}










