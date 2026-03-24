import bpy
import os
import sys
import traceback

# Blender uses a different relative path structure to the command line
try:
	from ..shared.IO import *
except:
	from legacy.shared.IO import *

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
		
		model_name = os.path.basename(filepath).split('.')[0] if filepath else "unknown"
		logger = Logger(verbose=verbose, model_name=model_name)

		importer_options = {
			"ik_hack": ik_hack,
			"verbose": verbose,
			"print_tree": print_tree,
			"max_frame": max_frame if max_frame > 0 else 1000000000,
			"section_names": [section_name] if len(section_name) > 0 else [],
			"filepath": filepath,
		}

		# Make sure the current selection doesn't mess with anything
		if bpy.ops.object.select_all.poll():
			bpy.ops.object.select_all(action='DESELECT')

		# We will most likely need to pass the flags and settings into the parser
		# When the parser is asked to parse a node which references one of these it can pass the requried
		# flags into the constructor
		parser = DATParser(filepath, importer_options, logger=logger)
		parser.parseSections()
		parser.close()

		# Pass the section objects to the model builder to import them into blender
		if context is not None and len(parser.sections) > 0:
			builder = ModelBuilder(context, parser.sections, importer_options, logger=logger)
			try:
				builder.build()
			except Exception as error:
				traceback.print_exc()
				logger.error("Failed to build model: %s", error)
				logger.info("Log file: %s", logger.log_path)
				logger.close()
				raise

		if logger.warning_count > 0 or logger.error_count > 0:
			logger.warning("Import finished with %d warning(s) and %d error(s)", logger.warning_count - 1, logger.error_count)

		logger.info("Log file: %s", logger.log_path)
		logger.close()

		return {'FINISHED'}









