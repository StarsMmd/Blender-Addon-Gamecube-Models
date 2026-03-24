class ShapeSetDimensionMismatchError(Exception):
	def __init__(self, vertex_count, normal_count):
		self.vertex_count = vertex_count
		self.normal_count = normal_count

	def __str__(self):
		return "Shape set should have the same number of vertices as normals.\nVertex count: " + str(self.vertex_count) + "\nnormal count: " + str(self.normal_count)