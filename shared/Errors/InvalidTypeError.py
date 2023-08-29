class InvalidPrimitiveTypeError(Exception):
	def __init__(self, type_name):
		self.type_name = type_name

	def __str__(self):
		return "Couldn't recognise primitive type with name: " + type_name

class InvalidTypeError(Exception):
	def __init__(self, type_name):
		self.type_name = type_name

	def __str__(self):
		return "Couldn't recognise type with name: " + type_name

class StringTypeLengthError(Exception):
	def __str__(self):
		return "Strings can have varying lengths. Never stride by the length of a string type. They should usually be accessed via a pointer which has a predefined length."

class VoidTypeStructFormatError(Exception):
	def __str__(self):
		return "Void data can't be unpacked from structs"

class StringTypeStructFormatError(Exception):
	def __str__(self):
		return "Strings can't be unpacked from structs"

class MatrixTypeStructFormatError(Exception):
	def __str__(self):
		return "Matrices can't be unpacked directly from structs. The floats should be unpacked separately and the last row appended manually."