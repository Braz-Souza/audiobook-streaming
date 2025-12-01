from tkinter import *
import tkinter.messagebox as tkMessageBox
import socket, threading, sys, traceback, os
import pygame
import io

from RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".mp3"

class Client:
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT
	
	SETUP = 0
	PLAY = 1
	PAUSE = 2
	TEARDOWN = 3
	
	# Initiation..
	def __init__(self, master, serveraddr, serverport, rtpport, filename):
		self.master = master
		self.master.protocol("WM_DELETE_WINDOW", self.handler)
		self.createWidgets()
		self.serverAddr = serveraddr
		self.serverPort = int(serverport)
		self.rtpPort = int(rtpport)
		self.fileName = filename
		self.rtspSeq = 0
		self.sessionId = 0
		self.requestSent = -1
		self.teardownAcked = 0
		self.connectToServer()
		self.frameNbr = 0
		
		os.environ["SDL_VIDEODRIVER"] = "dummy"
		pygame.init()  
		pygame.mixer.init()
		self.playlist = []
		self.playIndex = 0
		self.SONG_END = pygame.USEREVENT + 1
		pygame.mixer.music.set_endevent(self.SONG_END)
		self.audioBuffer = b''
		self.audioStarted = False
		self.receivingPackets = False
		self.currentCacheIndex = 0
		self.maxCacheSize = 150000
		self.cacheFiles = {}
		
		self.checkMusicEvents()
			
	def checkMusicEvents(self):
		"""Monitora eventos do Pygame para gerenciar a fila sem pular faixas."""
		
		for event in pygame.event.get():
			if event.type == self.SONG_END:
				self.queueNextSong()

		if not pygame.mixer.music.get_busy() and len(self.playlist) > self.playIndex:
			self.playImmediate()

		self.master.after(100, self.checkMusicEvents)

	def playImmediate(self):
		"""Carrega e toca imediatamente (usado no início ou após buffer vazio)."""
		if self.playIndex < len(self.playlist):
			song = self.playlist[self.playIndex]
			try:
				print(f"[PLAYER] Tocando agora: {song}")
				pygame.mixer.music.load(song)
				pygame.mixer.music.play()
				self.playIndex += 1
				self.queueNextSong()
			except Exception as e:
				print(f"[PLAYER] Erro ao tocar: {e}")

	def queueNextSong(self):
		"""Coloca a próxima música na fila de espera do Pygame."""
		if self.playIndex < len(self.playlist) and self.state == self.PLAYING:
			next_song = self.playlist[self.playIndex]
			try:
				print(f"[PLAYER] Enfileirando próxima: {next_song}")
				pygame.mixer.music.queue(next_song)
				self.playIndex += 1
			except Exception as e:
				print(f"[PLAYER] Erro ao enfileirar: {e}")
		
	def createWidgets(self):
		"""Build GUI."""
		# Create Setup button
		self.setup = Button(self.master, width=20, padx=3, pady=3)
		self.setup["text"] = "Setup"
		self.setup["command"] = self.setupMovie
		self.setup.grid(row=1, column=0, padx=2, pady=2)
		
		# Create Play button		
		self.start = Button(self.master, width=20, padx=3, pady=3)
		self.start["text"] = "Play"
		self.start["command"] = self.playMovie
		self.start.grid(row=1, column=1, padx=2, pady=2)
		
		# Create Pause button			
		self.pause = Button(self.master, width=20, padx=3, pady=3)
		self.pause["text"] = "Pause"
		self.pause["command"] = self.pauseMovie
		self.pause.grid(row=1, column=2, padx=2, pady=2)
		
		# Create Teardown button
		self.teardown = Button(self.master, width=20, padx=3, pady=3)
		self.teardown["text"] = "Teardown"
		self.teardown["command"] =  self.exitClient
		self.teardown.grid(row=1, column=3, padx=2, pady=2)
		
		# Create a label to display the audio status
		self.label = Label(self.master, height=19, text="Audiobook Player\n\nAguardando conexão...", font=("Arial", 16))
		self.label.grid(row=0, column=0, columnspan=4, sticky=W+E+N+S, padx=5, pady=5) 
	
	def setupMovie(self):
		"""Setup button handler."""
		if self.state == self.INIT:
			self.sendRtspRequest(self.SETUP)
			self.updateAudioStatus("Configurando conexão...")
	
	def exitClient(self):
		"""Teardown button handler."""
		self.sendRtspRequest(self.TEARDOWN)
		pygame.mixer.quit()
		self.master.destroy() # Close the gui window
		
		for index, cachefile in self.cacheFiles.items():
			if os.path.exists(cachefile):
				os.remove(cachefile)
				
		cachefile = CACHE_FILE_NAME + str(self.sessionId) + f"-{self.currentCacheIndex}" + CACHE_FILE_EXT
		if os.path.exists(cachefile):
			os.remove(cachefile)

	def pauseMovie(self):
		"""Pause button handler."""
		if self.state == self.PLAYING:
			self.receivingPackets = False
			pygame.mixer.music.pause()
			self.updateAudioStatus("Audiobook pausado")
			self.sendRtspRequest(self.PAUSE)
	
	def playMovie(self):
		"""Play button handler."""
		if self.state == self.READY:
			print("Iniciando reprodução...")
			
			if self.audioStarted:
				try:
					pygame.mixer.music.unpause()
					self.receivingPackets = True
					threading.Thread(target=self.listenRtp).start()
					self.playEvent = threading.Event()
					self.playEvent.clear()
					self.updateAudioStatus("Reproduzindo audiobook...")
					self.sendRtspRequest(self.PLAY)
					return
				except Exception as e:
					print(f"Erro ao despausar: {e}")
			
			self.audioStarted = False
			self.receivingPackets = True
			threading.Thread(target=self.listenRtp).start()
			self.playEvent = threading.Event()
			self.playEvent.clear()
			self.sendRtspRequest(self.PLAY)
			self.updateAudioStatus("Carregando audiobook...")
	
	def listenRtp(self):		
		"""Listen for RTP packets."""
		while True:
			try:
				data = self.rtpSocket.recv(20480)
				if data:
					rtpPacket = RtpPacket()
					rtpPacket.decode(data)
					
					currFrameNbr = rtpPacket.seqNum()
					
					if currFrameNbr > self.frameNbr:
						self.frameNbr = currFrameNbr
			except:
				if self.playEvent.isSet(): 
					break
				
				if self.teardownAcked == 1:
					self.rtpSocket.shutdown(socket.SHUT_RDWR)
					self.rtpSocket.close()
					break
		self.receivingPackets = False
					
	def writeAudioFrame(self, data):
		"""Write the received audio data to a cache file and play it."""
		self.audioBuffer += data
		if len(self.audioBuffer) >= self.maxCacheSize and self.receivingPackets:
			cachename = CACHE_FILE_NAME + str(self.sessionId) + f"-{self.currentCacheIndex}" + CACHE_FILE_EXT
			
			with open(cachename, "wb") as file:
				file.write(self.audioBuffer)

			self.playlist.append(cachename)
			print(f"Arquivo salvo e adicionado à playlist: {cachename}")
			
			# Adicionar ao dicionário com índice
			self.cacheFiles[self.currentCacheIndex] = cachename
			print(f"Cache #{self.currentCacheIndex} criado: {len(self.audioBuffer)} bytes -> {cachename}")
			
			if not self.audioStarted and self.currentCacheIndex == 0:
				try:
					pygame.mixer.music.load(cachename)
					pygame.mixer.music.play()
					self.audioStarted = True
					self.updateAudioStatus("Reproduzindo audiobook...")
					print(f"========== INICIOU REPRODUÇÃO ==========")
					print(f"Buffer inicial: {len(self.audioBuffer)} bytes")
					print(f"Frame atual: {self.frameNbr}")
					print(f"=========================================")
				except Exception as e:
					print(f"Erro ao reproduzir áudio: {e}")
			
			self.audioBuffer = b''
			self.currentCacheIndex += 1
		else:
			cachename = CACHE_FILE_NAME + str(self.sessionId) + f"-{self.currentCacheIndex}" + CACHE_FILE_EXT
			with open(cachename, "wb") as file:
				file.write(self.audioBuffer)
			
			if len(self.audioBuffer) % 81920 == 0:
				print(f"Buffer acumulado: {len(self.audioBuffer)} bytes")
	
	def updateAudioStatus(self, status):
		"""Update the audio status in the GUI."""
		self.label.configure(text=f"Audiobook Player\n\n{status}")
		
	def connectToServer(self):
		"""Connect to the Server. Start a new RTSP/TCP session."""
		self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			self.rtspSocket.connect((self.serverAddr, self.serverPort))
		except:
			tkMessageBox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr)
	
	def sendRtspRequest(self, requestCode):
		"""Send RTSP request to the server."""	
		#-------------
		# COMPLETED
		#-------------
		
		# Setup request
		if requestCode == self.SETUP and self.state == self.INIT:
			threading.Thread(target=self.recvRtspReply).start()
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			request = "SETUP %s RTSP/1.0\nCSeq: %d\nTransport: RTP/UDP; client_port= %d\n" % (self.fileName, self.rtspSeq, self.rtpPort)
			
			# Keep track of the sent request.
			self.requestSent = self.SETUP
		
		# Play request
		elif requestCode == self.PLAY and self.state == self.READY:
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			request = "PLAY %s RTSP/1.0\nCSeq: %d\nSession= %d\n" % (self.fileName, self.rtspSeq, self.rtpPort)
			
			# Keep track of the sent request.
			self.requestSent = self.PLAY
		
		# Pause request
		elif requestCode == self.PAUSE and self.state == self.PLAYING:
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			request = "PAUSE %s RTSP/1.0\nCSeq: %d\nSession= %d\n" % (self.fileName, self.rtspSeq, self.rtpPort)
			
			# Keep track of the sent request.
			self.requestSent = self.PAUSE
			
		# Teardown request
		elif requestCode == self.TEARDOWN and not self.state == self.INIT:
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			request = "TEARDOWN %s RTSP/1.0\nCSeq: %d\nSession= %d\n" % (self.fileName, self.rtspSeq, self.rtpPort)
			
			# Keep track of the sent request.
			self.requestSent = self.TEARDOWN
		else:
			return
		
		# Send the RTSP request using rtspSocket.
		self.rtspSocket.send(request.encode())
		
		print('\nData sent:\n' + request)
	
	def recvRtspReply(self):
		"""Receive RTSP reply from the server."""
		while True:
			reply = self.rtspSocket.recv(1024)
			
			if reply: 
				self.parseRtspReply(reply)
			
			# Close the RTSP socket upon requesting Teardown
			if self.requestSent == self.TEARDOWN:
				self.rtspSocket.shutdown(socket.SHUT_RDWR)
				self.rtspSocket.close()
				break
	
	def parseRtspReply(self, data):
		"""Parse the RTSP reply from the server."""
		if isinstance(data, bytes):
			data = data.decode('utf-8')
		lines = data.split('\n')
		seqNum = int(lines[1].split(' ')[1])
		
		# Process only if the server reply's sequence number is the same as the request's
		if seqNum == self.rtspSeq:
			session = int(lines[2].split(' ')[1])
			# New RTSP session ID
			if self.sessionId == 0:
				self.sessionId = session
			
			# Process only if the session ID is the same
			if self.sessionId == session:
				if int(lines[0].split(' ')[1]) == 200: 
					if self.requestSent == self.SETUP:
						#-------------
						# COMPLETED
						#-------------
						# Update RTSP state.
						self.state = self.READY
						
						# Open RTP port.
						self.openRtpPort() 
					elif self.requestSent == self.PLAY:
						self.state = self.PLAYING
					elif self.requestSent == self.PAUSE:
						self.state = self.READY
						
						# The play thread exits. A new thread is created on resume.
						self.playEvent.set()
					elif self.requestSent == self.TEARDOWN:
						self.state = self.INIT
						
						# Flag the teardownAcked to close the socket.
						self.teardownAcked = 1 
	
	def openRtpPort(self):
		"""Open RTP socket binded to a specified port."""
		#-------------
		# COMPLETED
		#-------------
		# Create a new datagram socket to receive RTP packets from the server
		self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		
		# Set the timeout value of the socket to 0.5sec
		self.rtpSocket.settimeout(0.5)
		
		try:
			# Bind the socket to the address using the RTP port given by the client user
			self.rtpSocket.bind(('', self.rtpPort))
		except:
			tkMessageBox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtpPort)

	def handler(self):
		"""Handler on explicitly closing the GUI window."""
		self.pauseMovie()
		if tkMessageBox.askokcancel("Quit?", "Are you sure you want to quit?"):
			self.exitClient()
		else: # When the user presses cancel, resume playing.
			self.playMovie()
