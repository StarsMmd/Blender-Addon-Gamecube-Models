class InvalidReadAddressError(Exception):
	def __init__(self, read_address, value_type, file_size):
		self.read_address = read_address
		self.value_type = value_type
		self.file_size = file_size

	def __str__(self):
		return "Failed to read " + self.value_type + " at address: " + hex(self.read_address) + "\nFile size: " + hex(self.file_size)