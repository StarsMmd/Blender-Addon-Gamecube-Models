from shared.IO import *
from shared.Nodes import SectionInfo

class Exporter():

	@staticmethod
	def writeDAT(context, path):
		sections = []

		# TODO: Complete implementation for parsing node tree from blender context
		# Parse context into section info nodes

		root_nodes = []
		for section in sections:
			if isinstance(section, SectionInfo):
				if section.root_node:
					root_nodes.append(section.root_node)

		builder = DATBuilder(path, root_nodes)
		builder.build()


