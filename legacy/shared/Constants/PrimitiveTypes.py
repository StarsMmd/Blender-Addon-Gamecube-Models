from ..Errors import *

primitive_field_types = [
    'void', 'uchar', 'ushort', 'uint', 'char', 'short', 'int', 'float', 'double', 'string', 'vec3', 'matrix'
]

def is_primitive_type(field_type):
	return field_type in primitive_field_types

def get_primitive_type_length(type_name):
	if type_name == 'void':
		return 0
	elif type_name == 'uchar' or type_name == 'char':
		return 1
	elif type_name == 'ushort' or type_name == 'short':
		return 2
	elif type_name == 'uint' or type_name == 'int':
		return 4
	elif type_name == 'float':
		return 4
	elif type_name == 'double':
		return 8
	elif type_name == 'vec3':
		return 12
	elif type_name == 'matrix':
		return 48
	elif type_name == 'string':
		raise StringTypeLengthError()
	else:
		raise InvalidPrimitiveTypeError(type_name)

def get_primitive_type_format(type_name):
	if type_name == 'void':
		raise VoidTypeStructFormatError()
	elif type_name == 'uchar':
		return '>B'
	elif type_name == 'ushort':
		return '>H'
	elif type_name == 'uint':
		return '>I'
	elif type_name == 'char':
		return '>b'
	elif type_name == 'short':
		return '>h'
	elif type_name == 'int':
		return '>i'
	elif type_name == 'float':
		return '>f'
	elif type_name == 'double':
		return '>d'
	elif type_name == 'vec3':
		return '>3f'
	elif type_name == 'string':
		raise StringTypeStructFormatError()
	elif type_name == 'matrix':
		raise MatrixTypeStructFormatError()
	else:
		raise InvalidPrimitiveTypeError(type_name)

def get_primitive_alignment_at_offset(type_name, offset):
	if type_name == 'string':
		return get_primitive_alignment_at_offset('uchar', offset)
	if type_name == 'vec3':
		return get_primitive_alignment_at_offset('float', offset)
	if type_name == 'matrix':
		return get_primitive_alignment_at_offset('float', offset)
	else:
		length = get_primitive_type_length(type_name)
		if length <= 0:
			return 0

		alignment = length - (offset % length)
		if alignment == length:
			alignment = 0
		return alignment


