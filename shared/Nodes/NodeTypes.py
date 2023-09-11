from ..Constants import *
from .Classes import *
from .Dummy import *
from .Node import *

from ..Constants import *

# define node class as anything unrecognised to allow for unimplemented node classes to be recognised as node classes
def isNodeClassType(field_type):
	return (not isArrayType(field_type)) and (not is_primitive_type(field_type)) and (not isBracketedType(field_type)) and (not isPointerType(field_type))

def getClassWithName(class_name):
	try:
		class_reference = globals()[class_name]
		return class_reference
	except KeyError:
		return globals()["Dummy"]

def get_type_length(field_type):
	if isBracketedType(field_type):
		return get_type_length(getBracketedSubType(field_type))

	elif is_primitive_type(field_type):
		return get_primitive_type_length(field_type)

	elif isPointerType(field_type):
		return 4

	elif isUnboundedArrayType(field_type):
		# These should never be the sub type of another field other than pointer
		# so we should never need to stride by their length
		return 0

	elif isBoundedArrayType(field_type):
		return get_type_length(getArraySubType(field_type)) * getArrayTypeBound(field_type)

	elif isNodeClassType(field_type):
		class_ref = getClassWithName(field_type)
		length = 0
		for field in class_ref.fields:
			field_type = markUpFieldType(field[1])
			field_length = get_type_length(field_type) + get_alignment_at_offset(field_type, length)
			length += field_length
		return length

	else:
		return 0

def get_alignment_at_offset(field_type, offset):
	if isBracketedType(field_type):
		return get_alignment_at_offset(getBracketedSubType(field_type), offset)

	elif is_primitive_type(field_type):
		return get_primitive_alignment_at_offset(field_type, offset)

	elif isPointerType(field_type):
		return get_alignment_at_offset('uint', offset)

	elif isUnboundedArrayType(field_type):
		return get_alignment_at_offset(getArraySubType(field_type), offset)

	elif isBoundedArrayType(field_type):
		return get_alignment_at_offset(getArraySubType(field_type), offset)

	elif isNodeClassType(field_type):
		fields = getClassWithName(field_type).fields
		if len(fields) == 0:
			return 0
		longest_field = None
		for field in fields:
			field_type = markUpFieldType(field[1])
			field_alignment = get_alignment_at_offset(field_type, offset)
			if longest_field == None or longest_field < field_alignment:
				longest_field = field_alignment
				
		return longest_field

	else:
		return 0

# This adds a pointer reference symbol to a Node class type if present in the type signature for a field
# e.g. 'Joint' becomes '*Joint'. This means the Node classes can have cleaner type signatures but the *
# is useful so the parser can recursively read the value by first treating it as a pointer when it reads the *
# and then reading the actual struct at that address. If we omit the * then it's hard to tell which
# recursive call is for the pointer and which one is for the struct.
# Unbounded array types will also be assumed to be a pointer to the unbounded array.
# In order to clarify any precedence between * and [] types, the result will be bracketed
# e.g. `Joint[]` becomes `*((*Joint)[])`
# In scenarios where there's a pointer to pointer or pointer to an array the additional *s should still be 
# added to the type signature in the Node class.
# The @ symbol can be added before a Node class type to prevent it from being treated as a pointer to the node class.
# A * won't be added and the @ will be removed from the final type output.
# e.g. `@Joint[]` becomes `(Joint)[]`
def markUpFieldType(type_string):

	if type_string[0] == "@":
		return "(" + type_string[1:] + ")"

	if isNodeClassType(type_string) or (type_string == 'string') or (type_string == 'matrix'):
		return "(*" + type_string + ")"

	if isUnboundedArrayType(type_string):
		sub_type = getSubType(type_string)
		return "(*(" + markUpFieldType(sub_type) + "[]))"

	if isBracketedType(type_string):
		sub_type = getSubType(type_string)
		return "(" + markUpFieldType(sub_type) + ")"

	if isPointerType(type_string):
		sub_type = getSubType(type_string)
		return "*(" + markUpFieldType(sub_type) + ")"

	return type_string

def byteChunkIsNull(chunk):
	for byte in chunk:
		if byte != 0:
			return False

	return True
