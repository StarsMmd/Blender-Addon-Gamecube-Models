import math

class Color:

	def __init__(self, red, green, blue, alpha):
		self.red = red
		self.green = green
		self.blue = blue
		self.alpha = alpha

	#normalize u8 to float
	#only used for color so we can do srgb conversion here
	def normalize(self):
		self.red = self.red / 255
		self.green = self.green / 255
		self.blue = self.blue / 255
		self.alpha = self.alpha / 255

	# Convert srgb colors to linear color space.
	# Blender does this for images but it assumes raw color inputs are already linear so we need to do the conversion.
	def linearize(self):
		def linearize_component(component):
			if(component <= 0.0404482362771082):
				return component / 12.92
			else:
				return pow(((component + 0.055) / 1.055), 2.4)

		self.red = linearize_component(self.red)
		self.green = linearize_component(self.green)
		self.blue = linearize_component(self.blue)

	def transform(self):
		self.normalize()
		self.linearize()

	# If some colors need to be normalized and/or linearized but not all then remove this
	# and handle the transformations as and when they are needed
	def prepareForBlender(self, builder):
		super().prepareForBlender(builder)
		self.transform()

	def asRGBList(self):
		return [self.red, self.green, self.blue]

	def asRGBAList(self):
		return [self.red, self.green, self.blue, self.alpha]

	def __str__(self):
		return "red: " + str(self.red) + "\ngreen: " + str(self.green) + "\nblue: " + str(self.blue) + "\nalpha: " + str(self.alpha)

