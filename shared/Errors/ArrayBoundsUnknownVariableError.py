class ArrayBoundsUnknownVariableError(Exception):
	def __init__(self, variable_name):
		self.variable_name = variable_name

	def __str__(self):
		return "Array field with unknown variable name: " + self.variable_name