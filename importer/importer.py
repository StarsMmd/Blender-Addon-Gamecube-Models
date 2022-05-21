import bpy
import sys
import traceback

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
			"verbose": verbose,
			"print_tree": print_tree
		}

		importer_options["max_frame"] = max_frame if max_frame > 0 else 1000000000
		importer_options["section_names"] = [section_name] if len(section_name) > 0 else []

		# Make sure the current selection doesn't mess with anything
		if bpy.ops.object.select_all.poll():
			bpy.ops.object.select_all(action='DESELECT')

		# We will most likely need to pass the flags and settings into the parser
		# When the parser is asked to parse a node which references one of these it can pass the requried
		# flags into the constructor
		parser = DATParser(filepath, importer_options)
		parser.parseSections()
		parser.close()

    	# Pass the section objects to the model builder to import them into blender
		if context != None and len(parser.sections) > 0:
			builder = ModelBuilder(context, parser.sections, importer_options)
			try:
				builder.build()
			except Exception as error:
				traceback.print_exc()
				print("\nFailed to build model.", file=sys.stderr)
				print(error,"\n", file=sys.stderr)
				return {'CANCELLED'}

		return {'FINISHED'}









