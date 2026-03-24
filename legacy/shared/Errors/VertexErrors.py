class UnknownVertexAttributeError(Exception):
	def __init__(self, vertex):
		self.vertex = vertex

	def __str__(self):
		return "Vertex with unknown attribute type: " + str(self.vertex.attribute) + "\n" + str(self.vertex)

class VertexListTerminatorError(Exception):
	def __str__(self):
		return "Vertex List is missing terminator vertex with attribute 0xFF"