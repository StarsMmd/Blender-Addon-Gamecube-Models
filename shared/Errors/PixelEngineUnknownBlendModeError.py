class PixelEngineUnknownBlendModeError(Exception):
	def __init__(self, blend_mode):
		self.blend_mode = blend_mode

	def __str__(self):
		return "Pixel Engine data with unknown blend mode: " + str(self.blend_mode)