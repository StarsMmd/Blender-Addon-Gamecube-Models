class VertexListTerminatorError(Exception):
	def __str__(self):
		return "Vertex List is missing terminator vertex with attribute 0xFF"