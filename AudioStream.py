class AudioStream:
	def __init__(self, filename):
		self.filename = filename
		try:
			self.file = open(filename, 'rb')
		except:
			raise IOError
		self.frameNum = 0
		self.CHUNK_SIZE = 4096
		
	def nextFrame(self):
		"""Get next audio chunk."""
		data = self.file.read(self.CHUNK_SIZE)
		
		if data:
			self.frameNum += 1
			return data
		else:
			return None
		
	def frameNbr(self):
		"""Get frame number."""
		return self.frameNum
	
	def reset(self):
		"""Reset the stream to the beginning."""
		self.file.seek(0)
		self.frameNum = 0
