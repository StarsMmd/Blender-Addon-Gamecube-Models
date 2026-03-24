from .PrimitiveTypes import *

# Helpers
# Precedence rules:-
# () > * > [] > primitive > NodeClass
# e.g.
# (*Joint[])[]
# Is an array of pointers to an array of Joint Nodes where each elemt of the latter array is a pointer to a Joint Node.
# All Node Class types will be assumed to be a pointer to a Node of that class.

def isBracketedType(field_type):
	return field_type[0:1] == "(" and field_type[-1:] == ")"

def isPointerType(field_type):
	return field_type[0:1] == "*"

def isUnboundedArrayType(field_type):
	return (not isPointerType(field_type)) and field_type[-2:] == "[]"

def isBoundedArrayType(field_type):
	return (not isPointerType(field_type)) and "[" in field_type and  field_type[-1:] == "]"

def isArrayType(field_type):
	return isUnboundedArrayType(field_type) or isBoundedArrayType(field_type)

def getBracketedSubType(field_type):
	sub_type = field_type
	while isBracketedType(sub_type):
		sub_type = sub_type[1:-1]
	return sub_type

def getPointerSubType(field_type):
	sub_type = field_type[1:]
	return getBracketedSubType(sub_type)

def getArraySubType(field_type):
	sub_type = field_type
	last = field_type[-1:]
	if last == "]":
		while last != "[":
			last = sub_type[-1:]
			sub_type = sub_type[0:-1]

	return getBracketedSubType(sub_type)

# Gets the lowest level type from a compound type which is either a Node class or primitive (i.e. without * () or [])
def getSubType(field_type):
	sub_type = field_type
	if isBracketedType(sub_type):
		sub_type = getBracketedSubType(sub_type)
		return getSubType(sub_type)
	if isArrayType(sub_type):
		sub_type = getArraySubType(sub_type)
		return getSubType(sub_type)
	if isPointerType(sub_type):
		sub_type = getPointerSubType(sub_type)
		return getSubType(sub_type)

	return sub_type

def getArrayTypeBound(field_type):
	bound_string = ""
	current_char_index = -1
	current_char = field_type[-1:]
	if current_char == "]":
		while current_char != "[":
			current_char_index -= 1
			current_char = field_type[current_char_index:current_char_index+1]
			if current_char != "[":
				bound_string = current_char + bound_string

	if bound_string == "":
		return None

	bounds = 0
	try:
		bounds = int(bound_string)
	except:
		raise ArrayBoundsUnknownVariableError(bound_string)

	return bounds