class IKEffectorWithoutParentError(Exception):
	def __str__(self):
		return "IK Effector has no Parent"