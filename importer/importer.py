import bpy

from shared.Nodes import *
from shared.IO import *

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
	def parseDAT(context, filepath="", section_name='', ik_hack=True, max_frame=1000, verbose=False, print_tree=False):
		
		importer_options = {
			"ik_hack": ik_hack,
			"verbose": verbose
		}

		importer_options["max_frame"] = max_frame if max_frame > 0 else 1000000000

		# We will most likely need to pass the flags and settings into the parser
		# When the parser is asked to parse a node which references one of these it can pass the requried
		# flags into the constructor
		parser = DATParser(filepath, importer_options)
		header = parser.read('ArchiveHeader', 0, 0, False)

		# Make sure the current selection doesn't mess with anything
		if bpy.ops.object.select_all.poll():
			bpy.ops.object.select_all(action='DESELECT')

		for (address, is_public) in header.section_addresses:
			
			# Recursively parse Node tree based on the section info
		    # The top level node will recursively call parseNode() on any leaves
			section = SectionInfo.readFromBinary(parser, address, is_public, header.section_names_offset)
			if print_tree:
				print(section)

			# Gives the flexibility to either import all sections or filter to just one
			# Could maybe update this in future so we get an array of section names to include

			if section_name == None or section_name == '' or section_name == section.section_name:
		    	# Pass the section object to the model builder to import it into blender
				if context != None:
					builder = ModelBuilder(context, section, importer_options)
					builder.build()

		return {'FINISHED'}









