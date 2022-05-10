class InvalidEnvelopeError(Exception):
	def __str__(self):
		return "Vertex list does not contain vertex with attribute GX_VA_PNMTXIDX"