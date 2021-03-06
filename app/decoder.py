# These classes implement a decoder for Mode S packets
# prereqs: bitstring simplekml PyUSB 
# 	"easy_install bitstring simplekml PyUSB"
# B. Kuschak, OpenADSB Project <brian@openadsb.com>
# Some parts based on:
# 	gr-air-modes # Copyright 2010, 2012 Nick Foster
#

import sys
import bitstring 
import time, math
#import simplekml
import binascii
import aircraft

from PyQt4.QtCore import *
from PyQt4.QtGui import *


# Just a struct to hold statistics
class DecoderStats:
	def __init__(self):
		self.reset()

	def reset(self):
		self.logfileSize = 0
		self.rxLevel = 0
		self.badShortPkts = 0
		self.badLongPkts = 0
		self.totalPkts = 0
		self.DF0 = 0
		self.DF4 = 0
		self.DF5 = 0
		self.DF11 = 0
		self.DF16 = 0
		self.DF17 = 0
		self.DF18 = 0
		self.DF20 = 0
		self.DF21 = 0
		self.DFOther = 0
		self.CrcErrs = 0
		self.goodPkts = 0	# CRC good, decoded properly
		self.uniqueAA = 0
		self.ACASonly = 0	# AAs that only send ACAS, not other ADS-B
		self.IICSeen = [False] * 16; # which interrogator codes have we seen 
		self.lastPressure = 0	# last reported pressure in mbar

# This class parses and decodes the ADS-B messages.
class AdsbDecoder(QObject):

	def __init__(self, args, reader):
		QObject.__init__(self, parent = None)
		self.args = args
		self.reader = reader
		self.recentAircraft = {}
		self.origin = self.args.origin
		self.stats = DecoderStats()

	def __del__(self):
		pass
		# delete array of recent aircraft
		#for aa in self.recentAircraft.keys():
			#del self.recentAircraft[aa]


	# Some statistics are maintained by the decoder, but are gleaned from the reader or elsewhere
	def updateStats(self, rxLevel, badShort, badLong, logfilesize):
		self.stats.logfileSize = int(logfilesize)
		self.stats.rxLevel = int(rxLevel)
		self.stats.badShortPkts = int(badShort)
		self.stats.badLongPkts = int(badLong)
		self.emit(SIGNAL("rxLevelChanged(int)"), self.stats.rxLevel)
		self.emit(SIGNAL("updateStats(PyQt_PyObject)"), self.stats)
		

	# Send a message to the Qt log window
	def logMsg(self, str):
		txt = QString(str)
		self.emit(SIGNAL("appendText(const QString&)"), txt)

	# the bitstring bit positions are a little strange:  bits[A:B], where B is one number greater than the ending bit position
	def decode(self, d):
		self.stats.totalPkts += 1

		# convert to a bitstring
		b = bitstring.BitArray(bytearray(d))

		df = b[0:5].uint
		if df == 0:
			self.DecodeDF0(b)
			self.stats.DF0 += 1
		elif df == 4:
			self.DecodeDF4(b)
			self.stats.DF4 += 1
		elif df == 5:
			self.DecodeDF5(b)
			self.stats.DF5 += 1
		elif df == 11:
			self.DecodeDF11(b)
			self.stats.DF11 += 1
		elif df == 16:
			self.DecodeDF16(b)
			self.stats.DF16 += 1
		elif df == 17:
			self.DecodeDF17(b)
			self.stats.DF17 += 1
		elif df == 18:
			self.DecodeDF18(b)
			self.stats.DF18 += 1
		elif df == 20:
			self.DecodeDF20(b)
			self.stats.DF20 += 1
		elif df == 21:
			self.DecodeDF21(b)
			self.stats.DF21 += 1
		else:
			print "  Need decoder for DF %u: " % (df), self.ba2hex(d)
			self.stats.DFOther += 1
	
	def ba2hex(self, d):
		mystr = ""
		for byte in d:
			mystr += "%02hx " % byte
		return mystr

	def capabilitiesStr(self, ca):
		if ca == 0:
			caStr = "Level 1 transponder."
		elif ca >= 1 and ca <= 3:
			caStr = "Reserved field %u." % (ca)
		elif ca == 4:
			caStr = "Level 2 transponder. On-Ground capability."
		elif ca == 5:
			caStr = "Level 2 transponder. Airborne capability."
		elif ca == 6 or ca ==7:
			caStr = "Level 2 transponder. Airborne and on-ground capability"
		else:
			 caStr = "Unknown."
		return caStr

	def getOrigin(self):
		return self.origin

	def DecodeDF0(self, pkt):
		# Short Air-to-air surveillance
		# 56-bit packet
		df = pkt[0:5].uint
		vs = pkt[5:6].uint
		cc = pkt[6:7].uint
		sl = pkt[8:11].uint
		ri = pkt[13:17].uint
		ac = pkt[19:32]
		ap = pkt[32:56]
		[alt, altStr] = self.AltitudeCode(ac)
		if vs == 0:
			vsStr = "Airborne"
		else:
			vsStr = "On Ground"

		if sl == 0:
			slStr = "ACAS not operating"
		else:
			slStr = "Sensitivity level %d" % (sl)

		# fixme - these come in in sequential packets to describe both ACAS and max speed.  Fill these into two different vars
		riStr = ""
		acasStr = ""
		if ri == 0:
			acasStr = "No operating ACAS"
		if ri >= 1:
			acasStr = "Reserved"
		if ri >= 2:
			acasStr = "ACAS (resolution inhibited)"
		if ri >= 3:
			acasStr = "ACAS (vertical only)"
		if ri >= 4:
			acasStr = "ACAS (vert and horz)"
		if ri >= 5 and ri <= 7:
			acasStr = "Reserved"
		if ri == 8:
			riStr = "No Max Avail"
		if ri == 9:
			riStr = "Max <75 kts"
		if ri == 10:
			riStr = "Max 75-150 kts"
		if ri == 11:
			riStr = "Max 150-300 kts"
		if ri == 12:
			riStr = "Max 300-600 kts"
		if ri == 13:
			riStr = "Max 600-1200 kts"
		if ri == 15:
			riStr = "Max >1200 kts"
		if cc == 0:
			ccStr = "No crosslink"
		else:
			ccStr = "Crosslink supported"
		crc = self.calcParity(pkt[0:32])
		aa = crc ^ ap;	

		a = self.lookupAircraft(aa.uint)
		if (a != None):
			# AA exists in roll-call list so CRC must have been good
			crcStr = "Aircraft ID %x." % (aa.uint)
			a.setACASInfo(ccStr, alt, riStr, acasStr, vsStr)
			self.emit(SIGNAL("updateAircraft(PyQt_PyObject)"), a)
			self.stats.goodPkts += 1
		else:
			crcStr = "CRC error or no all-call received yet from ID %x." % (aa.uint)
			self.stats.CrcErrs += 1
		self.logMsg("  DF%u (Short ACAS Air-to-Air): %s. %s. %s. %s. %s. %s. %s" % (df, vsStr, altStr, riStr, acasStr, slStr, ccStr, crcStr))

	def DecodeDF4(self, pkt):
		# Surveillance altitude reply
		# 56-bit packet
		df = pkt[0:5].uint
		fs = pkt[5:8].uint
		dr = pkt[8:13].uint
		um = pkt[13:19]			# fixme - ?
		ac = pkt[19:32]
		ap = pkt[32:56]
		iis = um[0:4].uint
		fsStr = self.flightStatusStr(fs)
		drStr = self.downlinkReqStr(dr)
		[alt, altStr] = self.AltitudeCode(ac)
		crc = self.calcParity(pkt[0:32])
		aa = crc ^ ap;	
		a = self.lookupAircraft(aa.uint)
		if (a != None):
			# AA exists in roll-call list so CRC must have been good
			crcStr = "Aircraft ID %x." % (aa.uint)
			a.setAltitude(iis, fsStr, alt, drStr)
			self.emit(SIGNAL("updateAircraft(PyQt_PyObject)"), a)
			self.stats.goodPkts += 1
		else:
			crcStr = "CRC error or no all-call received yet from ID %x." % (aa.uint)
			self.stats.CrcErrs += 1
		self.logMsg("  DF%u (Altitude Roll-Call): IID=%u. %s. %s. %s. %s" % (df, iis, fsStr, altStr, drStr, crcStr))
		
	def downlinkReqStr(self, dr):
		if dr == 0:
			drStr = "No downlink request"
		elif dr == 1:
			drStr = "Comm-B TX request"
		elif dr == 2 or dr == 3 or dr == 6 or dr == 7:
			drStr = "ACAS type %u request" % (dr)
		elif dr == 4:
			drStr = "Comm-B broadcast 1 request"
		elif dr == 5:
			drStr = "Comm-B broadcast 2 request"
		elif dr == 6:
			drStr = "Comm-B broadcast 1 and ACAS request"
		elif dr == 7:
			drStr = "Comm-B broadcast 2 and ACAS request"
		elif dr >= 16:
			drStr = "ELM protocol"
		else:
			drStr = "Unassigned DR %u" % (dr)
		return drStr

	def flightStatusStr(self, fs):
		if fs == 0:
			fsStr = "Airborne"
		elif fs == 1:
			fsStr = "On Ground"
		elif fs == 2:
			fsStr = "Alert, Airborne"
		elif fs == 3:
			fsStr = "Alert, On Ground"
		elif fs == 4:
			fsStr = "Alert, Ident"
		elif fs == 5:
			fsStr = "Ident"
		else:
			fsStr = "Reserved FS %u" % (fs)
		return fsStr

	def squawkDecode(self, b):
		# refer to section 3.1.1.6
		# fixme - test this comparing to the Mode C/A decoding table
		c1 = b[0:1]
		a1 = b[1:2]
		c2 = b[2:3]
		a2 = b[3:4]
		c4 = b[4:5]
		a4 = b[5:6]
		if b[6] != 0:
			print "Error - expected 0 for bit 6 of mode A response."
		b1 = b[7:8]
		d1 = b[8:9]
		b2 = b[9:10]
		d2 = b[10:11]
		b4 = b[11:12]
		d4 = b[12:13]
		# bitarray concatenation
		a = a4 + a2 + a1
		b = b4 + b2 + b1
		c = c4 + c2 + c1
		d = d4 + d2 + d1
		squawk = (a.uint * 1000) + (b.uint * 100) + (c.uint * 10) + d.uint
		return squawk

	# decode 6-bit encoded characters
	def decodeChars(self, c):
		set1 = [' ', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O']
		set2 = ['P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z']
		set3 = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']

		str = ""
		while len(c) != 0:
			b_hi = c[0:2].uint
			b_lo = c[2:6].uint
			if b_hi == 0:
				if b_lo == 0:
					str += '_'	# illegal
				else:
					str += set1[b_lo]	
			elif b_hi == 1:
				if b_lo < 0xB:
					str += set2[b_lo] 
				else:
					str += '_'	# illegal
			elif b_hi == 2:
				str += ' '		# space
			elif b_hi == 3:
				if b_lo < 0xA:
					str += set3[b_lo] 
				else:
					str += '_'	# illegal
			del c[0:6]			# move to next char
		return str


	def DecodeDF5(self, pkt):
		# Surveillance identity reply
		# 56-bit packet
		df = pkt[0:5].uint
		fs = pkt[5:8].uint
		dr = pkt[8:13].uint
		um = pkt[13:19]
		id = pkt[19:32]
		ap = pkt[32:56]
		iis = um[0:4].uint
		fsStr = self.flightStatusStr(fs)
		squawk = self.squawkDecode(id)
		drStr = self.downlinkReqStr(dr)
		crc = self.calcParity(pkt[0:32])
		aa = crc ^ ap;	
		a = self.lookupAircraft(aa.uint)
		if (a != None):
			# AA exists in roll-call list so CRC must have been good
			crcStr = "Aircraft ID %x." % (aa.uint)
			a.setCommBIdent(squawk, fsStr, drStr)
			self.emit(SIGNAL("updateAircraft(PyQt_PyObject)"), a)
			self.stats.goodPkts += 1
		else:
			crcStr = "CRC error or no all-call received yet from ID %x." % (aa.uint)
			self.stats.CrcErrs += 1
		self.logMsg( "  DF%u (Identity Reply): IID=%u. %s. Squawk %04u. %s. %s" % (df, iis, fsStr, squawk, drStr, crcStr ))

	def DecodeDF11(self, pkt):
		# All-call reply
		# 56-bit packet
		df = pkt[0:5].uint
		ca = pkt[5:8].uint
		aa = pkt[8:32].uint
		pi = pkt[32:56]
		caStr = self.capabilitiesStr(ca)
		crc = self.calcParity(pkt[0:32])

		# replies to interrogators XOR their IIC and SI with the last 7 bits of the CRC	
		(good, ic, cl, broadcastStr) = self.checkParityInterrogator(pi, crc)

		if good:
			# CRC good and AA known
			a = self.lookupAircraft(aa)
			if a == None:
				a = self.recordAircraft(aa)
			errStr = ""
			self.stats.goodPkts += 1
			if cl == 0:			# IC is the IIC
				self.stats.IICSeen[ic] = True
				a.setIICSeen(ic)
		else:
			errStr = "CRC error (expected %x, rx %x)." % (crc.uint, pi.uint)
			self.stats.CrcErrs += 1
		self.logMsg("  DF%u (Mode S All-Call Reply): %s Aircraft ID %03hx. IIC %d, CL %d. %s %s" % (df, caStr, aa, ic, cl, broadcastStr, errStr))


	# Problem - Mode S protocol doesn't identify the register number in the reply.  So 
	# unless we know apriori which register this is, we don't know how to decode.  Only the interrogator
	# knows, since it knows which register it asked for..
	# Only exception is for 'downlink broadcasts' which include the register number as the first 8 bits,
	# followed by 48 user bits: 0x00, 0x02, 0x10, 0x20, 0xFE, 0xFF.  
	# Also, DF16 packets include the register number to decode
	def decodeBDS(self, bds, mb):
		# Comm-B message payload, 56 bits
		# contents of a transponder register
		#bds = mb[0:8].uint	# BDS register number for some registers
		print "FIXME - Got BDS register 0x%x: 0x%x %s" % (bds, mb[8:].uint, self.decodeChars(mb[8:]))
		#print "FIXME - Got Comm-B BDS register 0x%014x %s" % (mb[0:].uint, self.decodeChars(mb[8:]))

		# Comm-B register assignments (BDS)
		# ELS: 20, 30
		# EHS: 40, 50, 60
		# ADS-B: 05, 06, 07, 08, 09, 0A, 41, 42, 61, 64, 65
		# capabilities: 10, 18, 19, 1A, 1B, 1C

		# 00 Not valid
		# 01 Unassigned
		# 02 Linked Comm-B, segment 2
		# 03 Linked Comm-B, segment 3
		# 04 Linked Comm-B, segment 4
		# 05 Extended squitter airborne position
		# 06 Extended squitter surface position
		# 07 Extended squitter status
		# 08 Extended squitter identification and type 
		# 09 Extended squitter airborne velocity
		# 0A Extended squitter event-driven information 
		# 0B Air/air information 1 (aircraft state)
		# 0C Air/air information 2 (aircraft intent)
		# 0D-0E Reserved for air/air state information 
		# 0F Reserved for ACAS

		# 10 Data link capability report (register self identifies)
		if bds == 0x10 and mb[0:8] == 0x10:
			continues = mb[8:9]		# 1 continues in next reg
			modes_ver = mb[16:23]  		# 0 unavailable, 1, 2, 3
			if mb[23:24] == 0:
				transponderLevelStr = "2 to 4";
			else:
				transponderLevelStr = "5";
			srvc_cap = mb[24:25]		# 1 available
			uplink_throughput = mb[25:28]	# 0 none, otherwise 16 segments in 1/2n seconds
			downlink_throughput = mb[28:32]	# 0 none
			id_cap = mb[32:33]		# 1 id capability
			print "Mode S version %d, transponder level, ID capability %d." % (modes_ver, transponderLvlStr, id_cap)
			
		# 11-16 Reserved for extension to data link capability reports 
		# 17 Common usage GICB capability report
		# 18-1F Mode S specific services capability reports 

		# 20 Aircraft identification (register self-identifies)
		elif bds == 0x20 and mb[0:8] == 0x20:
			if mb[8:].uint != 0:
				acid = self.decodeChars(mb[8:])
				print "Aircraft identifies as %s" % acid

		# 21 Aircraft and airline registration markings 
		# 22 Antenna positions
		# 23 Reserved for antenna position
		# 24 Reserved for aircraft parameters
		# 25 Aircraft type
		# 26-2F Unassigned
		# 30 ACAS active resolution advisory
		# 31-3F Unassigned
		# 40 Selected vertical intention
		#if bds == 0x40:
			#mcp_selected_alt = mb[0:13]
			#fms_selected_alt = mb[13:26]
			#barometric = mb[26:39]		# minus 800 mb
			#mcp_mode_bits = mb[47:51]
			#target_alt = mb[53:56]
		# 41 Next waypoint identifier
		# 42 Next waypoint position
		# 43 Next waypoint information
		# 44 Meteorological routine air report
		# 45 Meteorological hazard report
		# 46 Reserved for flight management system Mode 1 
		# 47 Reserved for flight management system Mode 2 
		# 48 VHF channel report
		# 49-4F Unassigned
		# 50 Track and turn report 
		elif bds == 0x50:
			roll = mb[0:11]
			true_track = mb[11:23]
			gnd_speed = mb[23:34]
			track_ang_rate = mb[34:45]
			true_airspeed = mb[45:56]
		
		# 51 Position report coarse
		# 52 Position report fine
		# 53 Air-referenced state vector 
		# 54 Waypoint 1
		# 55 Waypoint 2
		# 56 Waypoint 3
		# 57-5E Unassigned
		# 5F Quasi-static parameter monitoring
		# 60 Heading and speed report
		#if bds == 0x60:
			#heading = mb[0:12]
			#ind_airspeed = mb[12:23]
			#mach = mb[23:34]
			#baro_alt_rate = mb[34:45]
			#vert_vel = mb[45:56]

		# 61 Extended squitter emergency/priority status  - bk decoded elsewhere
		# 62 Reserved for target state and status information  - bk decoded elsewhere
		# 63 Reserved for extended squitter
		# 64 Reserved for extended squitter
		# 65 Aircraft operational status - bk decoded elsewhere
		# 66-6F Reserved for extended squitter
		# 70-75 Reserved for future aircraft downlink parameters 
		# 76-E0 Unassigned
		# E1-E2 Reserved for Mode S BITE
		# E3 Transponder type/part number
		# E4 Transponder software revision number 
		# E5 ACAS unit part number
		# E6 ACAS unit software revision number
		# E7-F0 Unassigned
		# F1 Military applications 
		# F2 Military applications
		# F3-FD Unassigned
		# FE Update Request
		# FF Search Request
		else:
			print "unknown CommB register contents: %s" % mb


	def DecodeDF16(self, pkt):
		# Long ACAS air-to-air
		# 112-bit packet
		if len(pkt) < 112:
			print "short DF16 pkt"
			return

		# FIXME - some of this decoding same as DF0
		df = pkt[0:5].uint
		vs = pkt[5:6].uint
		sl = pkt[8:11].uint
		ri = pkt[13:17].uint
		# 2 spare bits
		ac = pkt[19:32]
		mv = pkt[32:88]
		ap = pkt[88:112]

		[alt, altStr] = self.AltitudeCode(ac)

		if vs == 0:
			vsStr = "Airborne"
		else:
			vsStr = "On Ground"

		if sl == 0:
			slStr = "ACAS not operating"
		else:
			slStr = "Sensitivity level %d" % (sl)

		# fixme - these come in in sequential packets to describe both ACAS and max speed.  Fill these into two different vars
		riStr = ""
		if ri == 0:
			acasStr = "No operating ACAS"
		if ri >= 1:
			acasStr = "Reserved"
		if ri >= 2:
			acasStr = "ACAS (resolution inhibited)"
		if ri >= 3:
			acasStr = "ACAS (vertical only)"
		if ri >= 4:
			acasStr = "ACAS (vert and horz)"
		if ri >= 5 and ri <= 7:
			acasStr = "Reserved"

		# Decode MV message
		# Fixme - this doesn't work since often this MV field will contain register contents that 
		# was requested by the interrogator, and we have no idea which reigster it is.
		# only sometimes will it contain 0x30 as the first byte, in which case it *might* be an ACAS
		# message. But we don't know for sure since we're only listening to one side of the conversation.
		#vds = mv[0:8].uint	# might be the BDS register number
		#ara = mv[8:22]
		#rac = mv[22:26]
		#rat = mv[26:27].uint
		#mte = mv[27:28].uint
		#raStr = ""

		# This might be BDS 3,0: ACAS active resolution advisory
		#if vds == 0x30:

			#if ara[0:1].uint == 0 and mte == 1:
				# multiple threats
				#raStr += "Multple-threat RA"
				#if ara[1:2].uint == 1:
					#raStr += ", Upward sense correction required"
				#if ara[2:3].uint == 1:
					#raStr += ", Positive climb required"
				#if ara[3:4].uint == 1:
					#raStr += ", Downward sense correction required"
				#if ara[4:5].uint == 1:
					#raStr += ", Positive descent required"
				#if ara[5:6].uint == 1:
					#raStr += ", Crossing required"
				#if ara[6:7].uint == 1:
					#raStr += ", Sense reversal"
				# FIXME - decode ACAS III fields, next 6 bits

			#elif ara[0:1].uint == 1:
				## single threat
				#if ara[1:2].uint == 1:
					#raStr += "Corrective RA"
				#else:
					#raStr += "Preventive RA"
				#if ara[2:3].uint == 1:
					#raStr += ", Downward sense"
				#else:
					#raStr += ", Upward sense"
				#if ara[3:4].uint == 1:
					#raStr += ", Increased rate"
				#if ara[4:5].uint == 1:
					#raStr += ", Sense reversal"
				#if ara[5:6].uint == 1:
					#raStr += ", Altitude crossing"
				#if ara[6:7].uint == 1:
					#raStr += ", RA positive"
				#else:
					#raStr += ", vertical speed limit"
				## FIXME - decode ACAS III fields, next 6 bits
			
			#else:
				## no threat, no RA
				#pass

			#if rac[0:1].uint == 1:
				#raStr += ",  Do not pass below"
			#if rac[1:2].uint == 1:
				#raStr += ",  Do not pass above"
			#if rac[2:3].uint == 1:
				#raStr += ",  Do not turn left"
			#if rac[3:4].uint == 1:
				#raStr += ",  Do not turn right"

			#if rat == 1:
				#raStr += ", RA terminated"

		##elif vds == 0x60:
			## BDS 6,0
			## Heading and Speed Report
			## Magnetic heading (units 90/512 degrees, -180 to +180 deg) 11 bits
			## Indicated Airspeed (units 1kt, 0 to 1023 knots) 10 bits
			# Mach (units 0.004 mach, 0 to 4.09 mach) 10 bits
			# Barometric Altitude rate (units 32 ft/min, -6384 to 16352 ft/min) 9+x bits?
			# Intertial vertical velocity (units 32 ft/min, -6384 to 16352 ft/min) 9+x bits?
			#print "FIXME - DF16: BDS register 0x%x = 0x%x" % (vds, mv[8:].uint)
		#else:
			#print "FIXME - DF16: BDS register 0x%x = 0x%x" % (vds, mv[8:].uint)

		crc = self.calcParity(pkt[0:88])
		aa = crc ^ ap;	
		a = self.lookupAircraft(aa.uint)
		if (a != None):
			# AA exists in roll-call list so CRC must have been good
			crcStr = "Aircraft ID %x." % (aa.uint)
			a.setACASInfo(None, alt, riStr, acasStr, vsStr)
			self.emit(SIGNAL("updateAircraft(PyQt_PyObject)"), a)
			self.stats.goodPkts += 1
		else:
			crcStr = "CRC error or no all-call received yet from ID %x." % (aa.uint)
			self.stats.CrcErrs += 1
		#print "  DF%u (Long Air-to-Air ACAS): Aircraft ID %03hx. %d ft. %s. %s. %s" % (df, aa.uint, alt, vsStr, acasStr, crcStr)
		self.logMsg("  DF%u (Long Air-to-Air ACAS): Aircraft ID %03hx. %d ft. %s. %s. %s" % (df, aa.uint, alt, vsStr, acasStr, crcStr))
	

	# "TYPE" subcode fields are the same for DF17 and DF18
	def DecodeCommon_DF17_DF18(self, pkt):
		pass
		posStr = ""
		logStr = ""
		posUncertStr = ""
		nonIcaoFlag = False
		nonIcaoStr = ""

		# 112-bit packet
		# fixme - decode ca, me, lookup ICAO24
		df = pkt[0:5].uint
		ca_cf = pkt[5:8].uint	# CA field for DF17, CF field for DF18
		aa = pkt[8:32].uint
		me = pkt[32:88]
		pi = pkt[88:112]
		tc = me[0:5].uint	# type code 
		st = me[5:8].uint	# subtype

		# check parity, flag if bad
		# replies to interrogators XOR their IIC and SI with the last 7 bits of the CRC	
		crc = self.calcParity(pkt[0:88])
		(good, ic, cl, broadcastStr) = self.checkParityInterrogator(pi, crc)

		if good:
			crcgood = True
			errStr = ""
			self.stats.goodPkts += 1
			if cl == 0:			# IC is the IIC
				self.stats.IICSeen[ic] = True
		else:
			crcgood = False
			errStr = "CRC error (expected %x, rx %x)." % (crc.uint, pi.uint)
			self.stats.CrcErrs += 1

		if aa == 0x555555:
			aaStr = "Anonymous"
		else:
			aaStr = "%hx" % (aa)
			
		if df == 17:
			caStr = self.capabilitiesStr(ca_cf)
		else:	
			caStr = ""

		tcStr = self.typeCodeStrDF17_18(tc)

		# If this is a TIS-B message, it may have a fake AA
		if df == 18:
			imf = me[7:8].uint      			# ICAO/Mode A flag
			[ nonIcaoFlag, nonIcaoStr ] = self.decodeDF18_NonICAO(ca_cf, imf)

		# decode the TYPE field
		if tc >= 1 and tc <=4:
			# Aircraft Identification String BDS0,8
			cat = me[5:8].uint
			catStr = ""
			if tc == 1:			# ID Set D
				catStr = "Reserved (%u)" % (cat)
			elif tc == 2:			# ID Set C
				if cat == 0:
					catStr = "A/C category unavailable"
				elif cat == 1:
					catStr = "Emergency Vehicle"
				elif cat == 2:
					catStr = "Service Vehicle"
				elif cat == 3:
					catStr = "Fixed Obstruction"
				else:
					catStr = "Category %u" % (cat)
			elif tc == 3:			# ID Set B
				if cat == 0:
					catStr = "A/C category unavailable"
				elif cat == 1:
					catStr = "Glider/Sailplane"
				elif cat == 2:
					catStr = "Lighter than air"
				elif cat == 3:
					catStr = "Parachutist/Skydiver"
				elif cat == 4:
					catStr = "Ultralight/hang-glider/paraglider"
				elif cat == 5:
					catStr = "Reserved"
				elif cat == 6:
					catStr = "UAV"
				elif cat == 7:
					catStr = "Space Vehicle"
				else:
					catStr = "Category %u" % (cat)
			else:				# ID Set A
				if cat == 0:
					catStr = "A/C category unavailable"
				elif cat == 1:
					catStr = "Light weight <15K pounds"
				elif cat == 2:
					catStr = "Medium weight <75K pounds"
				elif cat == 3:
					catStr = "Medium weight <300K pounds"
				elif cat == 4:
					catStr = "Strong vortex aircraft"
				elif cat == 5:
					catStr = "Heavy weight >300K pounds"
				elif cat == 6:
					catStr = "High performance, high speed"
				elif cat == 7:
					catStr = "Rotorcraft"
				else:
					catStr = "Category %u" % (cat)

			id = self.decodeChars(me[8:56])
			if crcgood:
				a = self.lookupAircraft(aa)
				if a == None:
					a = self.recordAircraft(aa)
				if nonIcaoFlag:
					a.setFakeICAO24(True)
				a.setIdentityInfo(id, catStr)
				if cl == 0:
					a.setIICSeen(ic)
				logStr = "Identifier: %s, %s." % (id, catStr)
				self.emit(SIGNAL("updateAircraft(PyQt_PyObject)"), a)
			
		elif tc >=5 and tc <=8:
			# Surface position BDS0,6
			movement = me[5:12].uint
			gtv = me[12:13].uint
			track = me[13:20].uint
			timesync = me[20:21].uint
			oddeven = me[21:22].uint
			cprlat = me[22:39].uint
			cprlong = me[39:56].uint
			[lat, lon] = self.decodeCPR(cprlong, cprlat, 17, 90, oddeven)
			posStr = "at (%f, %f)" % (lat, lon)
			[vel, velStr] = self.decodeMovement(movement)
			if crcgood:
				# store aa, ONGROUND, posStr, moveStr
				a = self.lookupAircraft(aa)
				if a == None:
					a = self.recordAircraft(aa)
				if nonIcaoFlag:
					a.setFakeICAO24(True)
				a.setGroundPos(lat, lon, velStr, caStr)
				if cl == 0:
					a.setIICSeen(ic)
				logStr = "%s CPR: %u, %u %s. %s." % ("Odd" if oddeven else "Even", cprlat, cprlong, posStr, velStr)
				self.emit(SIGNAL("updateAircraftPosition(PyQt_PyObject)"), a)
			
		elif tc >=9 and tc <=22 and tc != 19:	
			# Airborne position BDS0,5
			ss = me[5:7].uint				# Surveillance Status
			imf = me[7:8].uint      			# ICAO/Mode A flag
			ac = me[8:20]
			timesync = me[20:21].uint
			oddeven = me[21:22].uint
			cprlat = me[22:39].uint
			cprlong = me[39:56].uint

			ssStr = self.decodeSurveillanceStatus(ss)		# fixme - make note of Alert condition

			# decode altitude
			if tc >= 20 and tc <= 22:
				alt = ac.uint				# GPS HAE (fixme - units?)
				altStr = "%d units?" % (alt)
				altTypeStr =  "GPS HAE"
			else:
				# m bit is omitted, add it back
				ac = ac[0:6] + bitstring.BitArray(bin='0') + ac[6:12] 	
				[alt, altStr] = self.AltitudeCode(ac)	# barometric
				altTypeStr =  "barometric"
	
			# convert CPR to lat, lon
			[lat, lon] = self.decodeCPR(cprlong, cprlat, 17, 360, oddeven)
			posStr = "at (%f, %f)" % (lat, lon)

			if crcgood:
				# store aa, AIRBORNE, posStr, altStr, posUncertStr, altTypeStr
				a = self.lookupAircraft(aa)
				if a == None:
					a = self.recordAircraft(aa)
				if nonIcaoFlag:
					a.setFakeICAO24(True)
				a.setAirbornePos(lat, lon, alt, posUncertStr, altTypeStr, caStr)
				if cl == 0:
					a.setIICSeen(ic)
				logStr = "%s CPR: %u, %u %s. %s." % ("Odd" if oddeven else "Even", cprlat, cprlong, posStr, ssStr)
				self.emit(SIGNAL("updateAircraftPosition(PyQt_PyObject)"), a)

		elif tc == 19:
			# Airborne velocity BDS0,9
			subtype = me[5:8].uint		# Subtype 
			icf = me[8:9].uint		# Intent change flag
			ifr = me[9:10].uint
			nuc = me[10:13].uint		# Navigational accuracy
			baro = me[35:36]
			down = me[36:37]
			vrate = me[37:46].uint
			diff = me[49:56].uint		# Difference between Geometric and Barometric alt
			diff_below = me[48:49]

			if subtype == 1 or subtype == 2:
				# ground referenced velocity
				west = me[13:14]
				vel_ew = me[14:24].uint - 1
				south = me[24:25]
				vel_ns = me[25:35].uint - 1
				if subtype == 2:
					vel_ew *= 4		
					vel_ns *= 4
				if west:
					vel_ew *= -1
				if south: 
					vel_ns *= -1

				vel = math.sqrt(math.pow(vel_ew, 2) + math.pow(vel_ns, 2))
				if vel == 0:
					velStr = "Speed unavailable"
				else:
					velStr = "Ground speed %u kts" % vel

				heading = math.atan2(vel_ew, vel_ns) / math.pi * 180
				if heading < 0:
					heading += 360
				headingStr = "%u deg True" % heading

			elif subtype == 3 or subtype == 4:
				# air referenced velocity
				heading_valid = me[13:14]
				heading = me[14:24].uint
				heading = 360.0 * heading / 1024	#units of 360/1024
				if heading_valid == False:
					heading = 0
				mag_heading = me[54:55]
				if mag_heading:
					headingStr = "%u deg Magnetic" % heading
				else:
					headingStr = "%u deg True" % heading
				vel = me[25:35].uint - 1
				if subtype == 4:
					vel *= 4
				if vel == 0:
					velStr = "Speed unavailable"
				else:
					velStr = "Ground speed %u kts" % vel
			else:
				# not assigned for velocity
				heading = 0
				headingStr = ""
				vel = 0
				velStr = "Reserved"
			
			if vrate == 0:
				vertStr = "Vertical rate unavailable"
			else:	
				if down:
					vrate *= -1;
				if baro:
					vertStr = "%d ft/min (barometric)" % (vrate*64)
				else:
					vertStr = "%d ft/min (GPS)" % (vrate*64)

			# difference between barometric and geometric altitude
			diffStr = ""
			if diff_below:
				diff *= -1;
			if diff != 0:
				feetDiff = (diff-1)*25
				baroPressure = (1013.25 + feetDiff/30)		 # is this right?
				diffStr = "Baro-Geo Alt = %d ft. Calculated barometric %.2f mbar" % (feetDiff, baroPressure)
			else:
				baroPressure = 0
				diffStr = ""

			if crcgood:
				# store aa, velStr, heading, vertStr
				a = self.lookupAircraft(aa)
				if a == None:
					a = self.recordAircraft(aa)
				if nonIcaoFlag:
					a.setFakeICAO24(True)
				a.setAirborneVel(velStr, heading, vertStr, caStr)		# fixme add diff, true/magnetic
				if cl == 0:
					a.setIICSeen(ic)
				if baroPressure != 0:
					self.stats.lastPressure = baroPressure
				logStr = "Heading %s. %s. %s. %s." %  (headingStr, velStr, vertStr, diffStr)
				self.emit(SIGNAL("updateAircraft(PyQt_PyObject)"), a)

		elif tc == 28:
			# Emergency/Priority status or TCAS RA broadcast
			# contents of register BDS 6,1
			st = me[5:8].uint
			if st == 1:
				# Emergency/Priority status and Mode A
				es = me[8:11].uint
				modea = me[11:24]
				res = me[24:56]
				esStr = self.decodeEmergencyStatus(es)
				squawk = self.squawkDecode(modea)

				if crcgood:
					a = self.lookupAircraft(aa)
					if a == None:
						a = self.recordAircraft(aa)
					if nonIcaoFlag:
						a.setFakeICAO24(True)
					a.setEmergStatus(squawk, esStr)
					if cl == 0:
						a.setIICSeen(ic)
					logStr = "Squawk %u. %s." %  (squawk, esStr)
					self.emit(SIGNAL("updateAircraft(PyQt_PyObject)"), a)

			elif st == 2:
				# TCAS RA Broadcast.  See Annex 10, 4.3.8.4.2.2
				# subtype 1 is contents of register BDS 3,0
				ara = me[8:22]
				rac = me[22:26]
				ra_term = me[26:27].uint
				multiple = me[27:28]
				tti = me[28:30].uint
				identity = me[30:56]

				if multiple:
					threatStr = "Multiple threats"
					if ra_term:
						threatStr += " (terminated)"
				elif not ara[0:1]:
					threatStr = "No threats"
				else:
					threatStr = "Single threat"
					if ra_term:
						threatStr += " (terminated)"

				if ara[0:1]:
					threatStr += ". RA is "
					if ara[1:2]:
						threatStr += "corrective, "
					else:
						threatStr += "preventative, "
					if ara[2:3]:
						threatStr += "downward, "
					else:
						threatStr += "upward, "
					if ara[3:4]:
						threatStr += "increased rate, "
					if ara[4:5]:
						threatStr += "sense reversal, "
					if ara[5:6]:
						threatStr += "altitude crossing, "
					if ara[6:7]:
						threatStr += "positive, "
					else:
						threatStr += "vert limit, "
					if ara[7:15]:
						threatStr += "ACAS 3, "

				elif multiple:
					if ara[1:2]:
						threatStr += "upward correction, "
					if ara[2:3]:
						threatStr += "positive climb, "
					if ara[3:4]:
						threatStr += "downward correction, "
					if ara[4:5]:
						threatStr += "positive descend, "
					if ara[5:6]:
						threatStr += "crossing, "
					if ara[6:7]:
						threatStr += "sense reversal, "
					if ara[7:15]:
						threatStr += "ACAS 3, "
				threatStr.strip(", ") 		# strip trailing comma
				threatStr += "."

				racStr = ""
				if rac[0:1]:
					racStr += "Do not pass below"
				if rac[1:2]:
					if len(racStr) > 0:
						racStr += ", "
					racStr += "Do not pass above"
				if rac[2:3]:
					if len(racStr) > 0:
						racStr += ", "
					racStr += "Do not turn left"
				if rac[3:4]:
					if len(racStr) > 0:
						racStr += ", "
					racStr += "Do not turn right"
				if len(racStr) > 0:
					racStr += "."
	
				aid = 0
				rangeStr = ""
				if tti == 1:
					aid = identity[0:24].uint				# mode S aircraft ID
					rangeStr = "Threat ID: %hx" % (aid)
				elif tti == 2:
					[alt, altStr] = self.AltitudeCode(identity[0:13])	# altitude of threat
					tidr = identity[13:20].uint
					tidb = identity[20:26].uint
					if tidr == 0:
						rangeStr = "Range unavailable. "
					elif tidr == 127:
						rangeStr = "Range > 12.6 NM. "
					else:
						rangeStr = "Range %.1f NM. " % ((tidr-1)/10.0)
					if tidb == 0:
						rangeStr += "Bearing unavailable"
					else:
						rangeStr += "Bearing %u to %u" % (6*(tidb-1), 6*tidb)

				if crcgood:
					a = self.lookupAircraft(aa)
					if a == None:
						a = self.recordAircraft(aa)
					if nonIcaoFlag:
						a.setFakeICAO24(True)
					if cl == 0:
						a.setIICSeen(ic)
					#FIXME - Store TCAS RA
					#log in separate window by timestamp, AA, thread ID, threatStr, rangeStr
					#snapshot other data at that time: position, alt, airspeed, heading, target alt, 
					#keep logging until RA is terminated.
					logStr =  "Aircraft ID %s. %s. %s. %s" %  (aaStr, threatStr, rangeStr, racStr)
					print "FIXME - DF17/DF18 %s" % (logStr)
				
			else:
				print "need decoder for DF%u, type %u, subtype %u:" % (df, tc, st), self.ba2hex(pkt)

		elif tc == 29:
			# Target State and Status
			# subtype 1 is contents of register BDS 6,2
			st = me[5:7].uint
			if st == 0:
				vert = me[7:9].uint
				alt_t = me[9:10].uint
				alt_cap = me[11:13].uint
				vmode = me[13:15].uint
				alt = me[15:25].uint
				horz = me[25:27].uint
				head = me[27:36].uint
				head_track = me[36:37].uint
				hmode = me[37:39].uint
				nacp = me[39:43].uint
				nacbaro = me[43:44].uint
				sil = me[44:46].uint
				cap = me[51:53].uint
				es = me[53:56].uint
				esStr = self.decodeEmergencyStatus(es)
				print "FIXME - DF%u Target Status: %s, %u, %u, %u, %u, %u, %u, %u, %u, %u, %u, %u, %u, %u" % (df, esStr, vert, alt_t, alt_cap, vmode, alt, horz, head, head_track, hmode, nacp, nacbaro, sil, cap)
				
			elif st == 1:
				altsel = me[8:9].uint
				alt = me[9:20].uint
				baro = me[20:29].uint	
				stat = me[29:30].uint
				sign = me[30:31].uint	
				head = me[31:39].uint
				nacp = me[39:43].uint
				altselValid = me[46:47].uint
				autopilot = me[47:48].uint
				vnav = me[48:49].uint
				altHold = me[49:50].uint
				adsr = me[50:51].uint
				approachMode = me[51:52].uint
				tcas = me[52:53].uint

				targStr = ""
				if alt == 0:
					altStr = "Unknown altitude target"
				else:
					altStr = "%u ft target" % ((alt-1)*32)

				if baro == 0:
					mbar = 0
					baroStr = "Unknown"
				else:
					mbar = 0.8*(baro-1)+800
					baroStr = "%.1f mbar" % (mbar)

				if autopilot:
					targStr += "Autopilot engaged. "
				if altHold:
					targStr += "Altitude Hold. "
				if approachMode:
					targStr += "Approach Mode. "
				
				if crcgood:
					a = self.lookupAircraft(aa)
					if a == None:
						a = self.recordAircraft(aa)
					if nonIcaoFlag:
						a.setFakeICAO24(True)
					if cl == 0:
						a.setIICSeen(ic)
					if mbar != 0:
						self.stats.lastPressure = mbar
					# FIXME - update aircraft
					logStr =  "%s. %s. %s" %  (altStr, baroStr, targStr)
					print "FIXME - DF17/DF18 %s" % (logStr)

			else:
				print "need decoder for DF%u, type %u, subtype %u:" % (df, tc, st), self.ba2hex(pkt)
		
		
		elif tc == 31:
			# Aircraft operational status, register BDS 6,5
			st = me[5:8].uint
			ver = me[40:43].uint
			hrd = me[53:54].uint
			ccStr = ""
			omStr = ""
			if st == 0:
				cc = me[8:24]
				om = me[24:40]
				ccStr = "Capabilities: "
				if cc[0:2].uint == 0 and cc[2:3]:
					ccStr += "TCAS, "
				if cc[0:2].uint == 0 and cc[3:4]:
					ccStr += "Ext Squitter Rx, "
				if cc[0:2].uint == 0 and cc[6:7]:
					ccStr += "Air-reference velocity report, "
				if cc[0:2].uint == 0 and cc[7:8]:
					ccStr += "Target-state report, "
				if cc[0:2].uint == 0 and cc[8:10]:
					ccStr += "Target-change report, "
				if cc[0:2].uint == 0 and cc[10:11]:
					ccStr += "UAT Rx, "
				ccStr.strip(", ")					# remove trailing comma

				if om[0:2].uint == 0 and om[2:3]:
					omStr += "TCAS RA active, "			# fixme - this should be indicated in table
				if om[0:2].uint == 0 and om[3:4]:
					omStr += "IDENT active, "			# fixme - this should be indicated in table
				if om[0:2].uint == 0 and om[5:6]:
					omStr += "Single antenna, "			# fixme - this should be indicated in table
				omStr.strip(", ")					# remove trailing comma

				if crcgood:
					a = self.lookupAircraft(aa)
					if a == None:
						a = self.recordAircraft(aa)
					if nonIcaoFlag:
						a.setFakeICAO24(True)
					if cl == 0:
						a.setIICSeen(ic)
					logStr =  "Version %u. %s. %s." %  (ver, ccStr, omStr)
					print "FIXME - DF17/DF18 %s" % (logStr)
					# FIXME emit signal

			else:
				print "need decoder for DF%u, type %u, subtype %u:" % (df, tc, st), self.ba2hex(pkt)
		else:
			print "need decoder for DF%u, type %u:" % (df, tc), self.ba2hex(pkt)

		return [ df, ic, tcStr, aaStr, nonIcaoStr, logStr, errStr ]


	# DF 18 uses the CF/IMF to denote non-ICAO AA.  
	def decodeDF18_NonICAO(self, cf, imf):
		if cf == 1:
			flag = True
			nonIcaoStr = " (anonymous non-ICAO)"
		elif cf == 2 and imf == 1:		# fixme - Mode A code and track number
			flag = True
			nonIcaoStr = " (Mode A + Track num)"
		elif cf == 3 and imf == 1:		# fixme - Mode A code and track number
			flag = True
			nonIcaoStr = " (Mode A + Track num)"
		elif cf == 4:			# fixme -  TIS-B service volume ID 
			flag = True
			nonIcaoStr = " (non-ICAO mgmt info)"
		elif cf == 5: # and imf == 0:	# fixme - reserved if IMF=1
			flag = True
			nonIcaoStr = " (non-ICAO)"
		elif cf == 6 and imf == 1:			
			flag = True
			nonIcaoStr = " (anonymous non-ICAO)"
		else:
			flag = False
			nonIcaoStr = ""
		return [ flag, nonIcaoStr ]


	def DecodeDF17(self, pkt):
		if len(pkt) < 112:
			print "short DF17 pkt"
			return
		[ df, ic, tcStr, aaStr, nonIcaoStr, logStr, errStr ] = self.DecodeCommon_DF17_DF18(pkt)
		self.logMsg("  DF%u (Extended Squitter): %s Aircraft ID %s. IIC %d. %s %s" % (df, tcStr, aaStr, ic, logStr, errStr))
		return


	def DecodeDF18(self, pkt):
		if len(pkt) < 112:
			print "short DF18 pkt"
			return

		[ df, ic, tcStr, aaStr, nonIcaoStr, logStr, errStr ] = self.DecodeCommon_DF17_DF18(pkt)
		self.logMsg("  DF%u (TIS-B): %s Aircraft ID %s%s. IIC %d. %s %s" % (df, tcStr, aaStr, nonIcaoStr, ic, logStr, errStr))
		return

	def decodeSurveillanceStatus(self, ss):
		if ss == 1:
			ssStr = "Emergency Alert"
		elif ss == 2:
			ssStr = "Temporary Alert"	# change in Mode A identity code, other than emergency
		elif ss == 3:
			ssStr = "SPI condition"
		else:
			ssStr = ""
		return ssStr

	def decodeEmergencyStatus(self, es):
		if es == 0:
			esStr = "No emergency"
		elif es == 1:
			esStr = "General emergency (7700)"
		elif es == 2:
			esStr = "Medical emergency"
		elif es == 3:
			esStr = "Minimum-fuel emergency"
		elif es == 4:
			esStr = "No-communications emergency (7600)"
		elif es == 5:
			esStr = "Unlawful interference emergency (7500)"
		elif es == 6:
			esStr = "Downed-aircraft emergency"
		elif es == 7:
			esStr = "Reserved"
		else:
			esStr = ""
		return esStr

	# these are used for DF17, DF18
	def typeCodeStrDF17_18(self, tc):
		if tc == 0:
			tcStr = "No position info."
		elif tc == 1:
			tcStr = "Identification (set D)."
		elif tc == 2:
			tcStr = "Identification (set C)."
		elif tc == 3:
			tcStr = "Identification (set B)."
		elif tc == 4:
			tcStr = "Identification (set A)."
		elif tc == 5:
			tcStr = "Surface position within 3m."
			posUncertStr = "3m"
		elif tc == 6:
			tcStr = "Surface position within 10m."
			posUncertStr = "10m"
		elif tc == 7:
			tcStr = "Surface position within 100m."
			posUncertStr = "100m"
		elif tc == 8:
			tcStr = "Surface position within >100m."
			posUncertStr = ">100m"
		elif tc == 9:
			tcStr = "Airborne position within 3m. Barometric altitude."
		elif tc == 10:
			tcStr = "Airborne position within 10m. Barometric altitude."
		elif tc == 11:
			tcStr = "Airborne position within 100m. Barometric altitude."
		elif tc == 12:
			tcStr = "Airborne position within 200m. Barometric altitude."
			posUncertStr = ">100m"
		elif tc == 13:
			tcStr = "Airborne position within 500m. Barometric altitude."
		elif tc == 14:
			tcStr = "Airborne position within 1km. Barometric altitude."
		elif tc == 15:
			tcStr = "Airborne position within 2km. Barometric altitude."
		elif tc == 16:
			tcStr = "Airborne position within 10km. Barometric altitude."
		elif tc == 17:
			tcStr = "Airborne position within 20km. Barometric altitude."
		elif tc == 18:
			tcStr = "Airborne position within >20km. Barometric altitude."
		elif tc == 19:
			tcStr = "Airborne velocity. Delta altitude."
		elif tc == 20:
			tcStr = "Airborne position within 4m. GPS altitude."
		elif tc == 21:
			tcStr = "Airborne position within 15m. GPS altitude."
		elif tc == 22:
			tcStr = "Airborne position within >15m. GPS altitude."
		elif tc == 23:
			tcStr = "Reserved for test purposes."
		elif tc == 24:
			tcStr = "Reserved for surface system status."
		elif (tc >= 25 and tc <=27) or tc == 30:
			tcStr = "Reserved type %u." % (tc)
		elif tc == 28:
			tcStr = "Emergency/priority status."
		elif tc == 29:
			tcStr = "Target state and status."
		elif tc == 31:
			tcStr = "Aircraft operational status."
		return tcStr

	# used for TIS-B NACp decoding.  Maybe others
	def decodeNavAccuracy(self, p):
		if p == 0:
			s = "accuracy unknown"
		elif p == 1:
			s = "within 20km"
		elif p == 2:
			s = "within 10km"
		elif p == 3:
			s = "within 5km"
		elif p == 4:
			s = "within 2km"
		elif p == 5:
			s = "within 1km"
		elif p == 6:
			s = "within 500m"
		elif p == 7:
			s = "within 200m"
		elif p == 8:
			s = "within 100m"
		elif p == 9:
			s = "within 30m"
		elif p == 10:
			s = "within 10m"
		elif p == 11:
			s = "within 3m"
		else:
			s = "reserved"
		return s
		
	def decodeMovement(self, m):
		# refer to A.2.3.3.1
		if m == 0:
			str = "Ground speed unavailable"
			vel = -1
		elif m == 1:
			vel = 0
			str = "Aircraft stopped"
		elif m >= 2 and m <= 8:
			vel = (m-2)*0.125 + 0.125
			str = "Ground speed %.1f kts" % (vel)
		elif m >= 9 and m <= 12:
			vel = (m-9)*0.25 + 1.0
			str = "Ground speed %.1f kts" % (vel)
		elif m >= 13 and m <= 38:
			vel = (m-13)*0.5 + 2.0
			str = "Ground speed %.1f kts" % (vel)
		elif m >= 39 and m <= 93:
			vel = (m-39)*1.0 + 15.0
			str = "Ground speed %.1f kts" % (vel)
		elif m >= 94 and m <= 108:
			vel = (m-94)*2.0 + 70.0
			str = "Ground speed %.1f kts" % (vel)
		elif m >= 109 and m <= 123:
			vel = (m-109)*5.0 + 100.0
			str = "Ground speed %.1f kts" % (vel)
		elif m == 124:
			vel = 176
			str = "Ground speed > 175 kts"
		else:
			vel = -1
			str = "Ground speed reserved field"
		return [vel, str]

	# compact position record decoding
	# Nb = 17 for airborne, 14 for intent, and 12 for TIS-B
	# odd is True for odd packet, False for even
	# range is 360.0 deg for airborne format, 90.0 deg for surface format
	# fixme - the ODD packet seems to decode incorrectly... still a problem for some A/C
	def decodeCPR(self, xz, yz, nbits, _range, odd):
		# refer to C.2.6.5 and C.2.6.6
		nz = 15		# number of latitude zones (fixed)
		yz = float(yz)	# make sure treated as floating point
		xz = float(xz)	# make sure treated as floating point
		_range = float(_range)	# must be floating point

		# our 'reference position' within 300 miles of airborne a/c or 45 miles on ground
		[lats, lons] = self.origin

		if odd:
			i = float(1)
		else:
			i = float(0)
		# first latitude
		dlat = _range / (4 * nz - i)
		j = math.floor(lats / dlat) + math.floor(0.5 + (self.mod(lats, dlat, _range)/dlat) - (yz/2**nbits))
		rlat = dlat * (j + yz/2**nbits)
		# then longitude
		if self.NL(rlat, nz)-i > 0:
			dlon = _range / (self.NL(rlat, nz)-i)
		else:	
			dlon = _range
		m = math.floor(lons / dlon) + math.floor(0.5 + (self.mod(lons, dlon, _range)/dlon) - (xz/2**nbits))
		rlon = dlon * (m + xz/2**nbits)
		return [rlat, rlon]

	def mod(self, a, b, _range):
		if a < 0:
			a += _range
		m = a - b * math.floor(a / b)
		#print "a, b, m = ", a, b, m
		return m

	# NL - compute number of "longitude zones"
	# refer to C.2.6.2
	def NL(self, lat, nz):
		nl = math.floor (2.0 * math.pi * pow(math.acos( 1.0 - ((1.0 - math.cos(math.pi/2.0/nz)) / pow(math.cos(math.pi/180.0*abs(lat)), 2.0))), -1))
		#print "NL=", nl
		return nl;

	def DecodeDF20(self, pkt):
		# Comm-B altitude reply
		# 112-bit packet
		if len(pkt) < 112:
			print "short DF20 packet"
			return
		df = pkt[0:5].uint
		fs = pkt[5:8].uint
		dr = pkt[8:13].uint
		um = pkt[13:20]
		ac = pkt[19:32]
		mb = pkt[32:88]		# we can't decode this since we don't know which register it is
		ap = pkt[88:112]
		iis = um[0:4].uint
		fsStr = self.flightStatusStr(fs)
		drStr = self.downlinkReqStr(dr)
		[alt, altStr] = self.AltitudeCode(ac)
		crc = self.calcParity(pkt[0:88])
		aa = crc ^ ap;	
		a = self.lookupAircraft(aa.uint)
		if (a != None):
			# AA exists in roll-call list so CRC must have been good
			crcStr = "Aircraft ID %x." % (aa.uint)
			a.setCommBAltitude(alt, iis, fsStr, drStr)
			self.emit(SIGNAL("updateAircraft(PyQt_PyObject)"), a)
			self.stats.goodPkts += 1
		else:
			crcStr = "CRC error or no all-call received yet from ID %x." % (aa.uint)
			self.stats.CrcErrs += 1
		self.logMsg("  DF%u (Comm-B Altitude Reply): IID=%u. %s. %s. %s. %s" % (df, iis, altStr, fsStr, drStr, crcStr))

		
	def DecodeDF21(self, pkt):
		# Comm-B identity reply
		# 112-bit packet
		df = pkt[0:5].uint
		fs = pkt[5:8].uint
		dr = pkt[8:13].uint
		um = pkt[13:20]
		id = pkt[19:32]
		mb = pkt[32:88]		# we can't decode this since we don't know which register it is
		ap = pkt[88:112]
		iis = um[0:4].uint
		fsStr = self.flightStatusStr(fs)
		drStr = self.downlinkReqStr(dr)
		squawk = self.squawkDecode(id)
		if len(pkt) < 112:
			print "Short DF21 packet"
			return
		crc = self.calcParity(pkt[0:88])
		aa = crc ^ ap;	
		a = self.lookupAircraft(aa.uint)
		if (a != None):
			# AA exists in roll-call list so CRC must have been good
			crcStr = "Aircraft ID %x." % (aa.uint)
			a.setCommBIdent(squawk, fsStr, drStr)
			self.emit(SIGNAL("updateAircraft(PyQt_PyObject)"), a)
			self.stats.goodPkts += 1
		else:
			crcStr = "CRC error or no all-call received yet from ID %x." % (aa.uint)
			self.stats.CrcErrs += 1
		self.logMsg("  DF%u (Comm-B Identity Reply): IID=%u. Squawk %04u. %s. %s %s" % (df, iis, squawk, fsStr, drStr, crcStr))

		
	# FIXME - this is pressure-altitude.  height = PA - 30*(1013-QNH) or PA - 1000*(29.92 - alt. setting)
	def AltitudeCode(self, ac):
		# Refer to section 3.1.2.6.5.4
		# The bit number in the ICAO annex assume this ac covers bit positions 20-32
		if len(ac) != 13:
			print "Bad length %u for AltitudeCode!" % (len(ac))
			return [-1, "Bad Altitude Code" ];
		if ac.uint == 0:
			return [-1, "Altitude not available" ];
		alt = 0
		m = ac[26-20]		# feet(0) or meters(1)
		q = ac[28-20]		
		#print "AltitudeCode: m=%u, q=%u, ac=%s" % (m, q, ac.bin)	
		if m:
			ustr = "m"
			conv = 3.2808399;	# feet per meter
		else:
			ustr = "ft"
			conv = 1.0;
			if q:
				units = 25
			else:
				units = 100
		if m == 1:
			# altitude in meters
			alt = (ac[20-20:26-20] + ac[27-20:32-20]).uint
			#print "meters altitude encoding. alt = %u" % (alt)
			conv = 3.2808399;	# feet per meter
			return [alt*conv, "%d m (%d ft)" % (alt, alt*conv)]
		elif q == 0:
			# m = 0, q = 0
			# mode c encoding - gillham code
			# FIXME - this is pressure-altitude.  height = PA - 30*(1013-QNH) or PA - 1000*(29.92 - alt. setting)
			c1 = ac[20-20]
			a1 = ac[21-20]
			c2 = ac[22-20]
			a2 = ac[23-20]
			c4 = ac[24-20]
			a4 = ac[25-20]
			x  = ac[26-20]
			b1 = ac[27-20]
			d1 = 0
			b2 = ac[29-20]
			d2 = ac[30-20]
			b4 = ac[31-20]
			d4 = ac[32-20]
			code = bitstring.BitArray([d2, d4, a1, a2, a4, b1, b2, b4, c1, c2, c4])
			alt = self.modeCtoAltitude(code.uint)
			return [alt, "%d ft (mode c encoding)" % (alt)]
		else:
			# m = 0, q = 1
			# feet
			# 11-bit field represented by bits 20 to 25, 27 and 29 to 32 
			n = ac[20-20:26-20] + ac[27-20:28-20] + ac[29-20:33-20]
			alt = 25*n.uint - 1000;
			return [alt*conv, "%d ft (direct encoding)" % (alt)]

	# these three from Ron Silvernail http://control.com/thread/1011798010	
	def grayToBinary(self, g):
		b = g ^ (g>>8)
		b ^= (b>>4)
		b ^= (b>>2)
		b ^= (b>>1)
		return b

	def getParity(self, v):
		v ^= (v>>16)
		v ^= (v>>8)
		v ^= (v>>4)
		v &= 0xf
		return (0x6996>>v) & 1;

	# takes a uint
	def modeCtoAltitude(self, code):
		c = self.grayToBinary(code & 0x7) - 1
		if(c == 6):
			c = 4
		dab = code >> 3
		if(self.getParity(dab)):
			c = 4 - c
		return ((self.grayToBinary(dab)*500)-1200) + (c*100)

	def recordAircraft(self, aa):
		# The aircraft has been identified by an all-call reply
		a = aircraft.Aircraft(self, aa)
		self.recentAircraft[ aa ] =  a
		self.emit(SIGNAL("addAircraft(PyQt_PyObject)"), a)
		return a

	def oldRecordAircraft(self, aa):
		# The aircraft has been identified by an all-call reply
		self.recentAircraft[ aa ] =  time.time() 

	def lookupAircraft(self, aa):
		# return TRUE if this AA is listed in our roll-call list
		if aa in self.recentAircraft:
			return self.recentAircraft[aa]
		else:
			return None

	def oldLookupAircraft(self, aa):
		# return TRUE if this AA is listed in our roll-call list
		if aa in self.recentAircraft:
			return True;
		else:
			return False;

	def ageRecentAircraft(self):
		# remove aircraft IDs older than 5 minutes
		for aa in self.recentAircraft.keys():
			a = self.recentAircraft[aa]
			t = a.getTimestamp()
			if time.time() > (t+(2*60)):
				print "aging %x out of queue." % (aa)
				a.dumpTrack()
				self.emit(SIGNAL("delAircraft()"))
				del self.recentAircraft[aa]
				# fixme - restart iterator after deletion

	def dumpAircraftTracks(self):
		for aa in sorted(self.recentAircraft.keys()):
			a = self.recentAircraft[aa]
			if a != None:
				a.dumpTrack()
		
	def dumpAircraft(self):
		for aa in sorted(self.recentAircraft.keys()):
			a = self.recentAircraft[aa]
			if a != None:
				a.printInfo()
		
	def printRecentAircraft(self):
		str = "%u recent aircraft: " % (len(self.recentAircraft))
		for aa in sorted(self.recentAircraft.keys()):
			c = self.lookupCountry(aa)
			if c != "":
				str += "%x (%s), " % (aa, c)
			else:
				str += "%x, " % (aa)
		print str

	# Decode the 24 bit PI field
	def checkParityInterrogator(self, pi, crc):
		# CL and IC are overlaid with parity
		par_check = crc ^ pi
		cl = par_check[17:20].uint		# if 0, IC = IIC (interrogator code), otherwise its an SI code
		ic = par_check[20:24].uint
		if ic == 0 and cl == 0:
			broadcastStr = "Broadcast."
		else:
			broadcastStr = ""
		good = par_check[0:17].uint == 0
		return (good, ic, cl, broadcastStr)

	# refer to 3.1.2.3.3 and "EUROCONTROL - CRC Calculation for Mode-S Transponders"
	def calcParity(self, data):
		# try to speed up the calculation.  It was by far taking the most CPU time
		if(len(data) == 32):
			return self.calcParityFast32(data)
		elif(len(data) == 88):
			return self.calcParityFast88(data)	
		else:
			return 0		# shouldn't happen
	
	def calcParityFast32(self, data):
		poly = 0xFFFA0480
		data = data.uint
		for i in range(32):
			if (data & 0x80000000):
				data ^= poly
			data = (data<<1) & 0xFFFFFFFF
		# return only the 24 MSBs of the result
		return bitstring.BitArray(uint=(data>>8), length=24)

	def calcParityFast88(self, data):
		poly = 0xFFFA0480
		data0 = data[0:32].uint
		data1 = data[32:64].uint
		data2 = data[64:88].uint << 8
		for i in range(88):
			if (data0 & 0x80000000):
				data0 ^= poly
			data0 = ((data0<<1) | (data1>>31)) & 0xFFFFFFFF
			data1 = ((data1<<1) | (data2>>31)) & 0xFFFFFFFF
			data2 = ((data2<<1)) & 0xFFFFFFFF
		# return only the 24 MSBs of the result
		return bitstring.BitArray(uint=(data0>>8), length=24)

	# Alternate parity calculation for testing purposes only
	# from https://github.com/antirez/dump1090/blob/master/dump1090.c
	#
	# Parity table for MODE S Messages.
	# The table contains 112 elements, every element corresponds to a bit set
	# in the message, starting from the first bit of actual data after the
	# preamble.
	# 
	# For messages of 112 bit, the whole table is used.
	# For messages of 56 bits only the last 56 elements are used.
	# 
	# The algorithm is as simple as xoring all the elements in this
	# table
	# for which the corresponding bit on the message is set to 1.
	# 
	# The latest 24 elements in this table are set to 0 as the
	# checksum at the
	# end of the message should not affect the computation.
	# 
	# Note: this function can be used with DF11 and DF17, other
	# modes have
	# the CRC xored with the sender address as they are reply to
	# interrogations,
	# but a casual listener can't split the address from the
	# checksum.
	# 
	def calcParityAlternate(self, data):
		modes_checksum_table = (
		0x3935ea, 0x1c9af5, 0xf1b77e, 0x78dbbf, 0xc397db, 0x9e31e9, 0xb0e2f0, 0x587178,
		0x2c38bc, 0x161c5e, 0x0b0e2f, 0xfa7d13, 0x82c48d, 0xbe9842, 0x5f4c21, 0xd05c14,
		0x682e0a, 0x341705, 0xe5f186, 0x72f8c3, 0xc68665, 0x9cb936, 0x4e5c9b, 0xd8d449,
		0x939020, 0x49c810, 0x24e408, 0x127204, 0x093902, 0x049c81, 0xfdb444, 0x7eda22,
		0x3f6d11, 0xe04c8c, 0x702646, 0x381323, 0xe3f395, 0x8e03ce, 0x4701e7, 0xdc7af7,
		0x91c77f, 0xb719bb, 0xa476d9, 0xadc168, 0x56e0b4, 0x2b705a, 0x15b82d, 0xf52612,
		0x7a9309, 0xc2b380, 0x6159c0, 0x30ace0, 0x185670, 0x0c2b38, 0x06159c, 0x030ace,
		0x018567, 0xff38b7, 0x80665f, 0xbfc92b, 0xa01e91, 0xaff54c, 0x57faa6, 0x2bfd53,
		0xea04ad, 0x8af852, 0x457c29, 0xdd4410, 0x6ea208, 0x375104, 0x1ba882, 0x0dd441,
		0xf91024, 0x7c8812, 0x3e4409, 0xe0d800, 0x706c00, 0x383600, 0x1c1b00, 0x0e0d80,
		0x0706c0, 0x038360, 0x01c1b0, 0x00e0d8, 0x00706c, 0x003836, 0x001c1b, 0xfff409,
		0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000,
		0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000,
		0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000, 0x000000 )
		data = data + bitstring.BitArray(uint=0, length=24)	# append zeros for parity
		bits = len(data) 
		crc = 0;
		if bits == 112:
			offset = 0
		else:
			offset = 112-56
		j = 0
		while j<bits:
			byte = int(j / 8)
			bit = j % 8
			bitmask = 1 << (7-bit)
			d = data[byte*8:(byte+1)*8].uint 
			if d & bitmask:
				crc = crc ^ modes_checksum_table[j+offset]
			j = j + 1
		return bitstring.BitArray(uint=crc, length=24)	# 24 bit checksum


	def lookupCountry(self, aa):
		# lookup country assigment for an AA
		# taken from http://www.libhomeradar.org/databasequery/icao24allocations.php using this:
		# cat /tmp/tmp1 |sed "s? - ?    ?g" |awk 'BEGIN { FS = "[\t]" } { print $3 "\t" $4 "\t" $1 }' |sort |awk 'BEGIN { FS = "[\t]" } {print "elif aa >= 0x" $1 " and aa < 0x" $2 ":\n\techo \"" $3 "\"" }' > /tmp/tmp2
		# then some additions and modifications
		if aa >= 0xA00000 and aa < 0xADFE00:		# most common first
			c = "USA"
		elif aa >= 0xADFE00 and aa < 0xAF0000:		
			c = "US Military"
		elif aa >= 0xAF0000 and aa < 0xB00000:		
			c = "USA"
		elif aa >= 0x000000 and aa < 0x000000:		# then the rest
			c = "(undefined)"
		elif aa >= 0x004000 and aa < 0x004400:
			c = "Zimbabwe"
		elif aa >= 0x006000 and aa < 0x007000:
			c = "Mozambique"
		elif aa >= 0x008000 and aa < 0x010000:
			c = "South Africa"
		elif aa >= 0x010000 and aa < 0x018000:
			c = "Egypt"
		elif aa >= 0x018000 and aa < 0x020000:
			c = "Libyan Arab Jamahiriya"
		elif aa >= 0x020000 and aa < 0x028000:
			c = "Morocco"
		elif aa >= 0x028000 and aa < 0x030000:
			c = "Tunisia"
		elif aa >= 0x030000 and aa < 0x030400:
			c = "Botswana"
		elif aa >= 0x032000 and aa < 0x033000:
			c = "Burundi"
		elif aa >= 0x034000 and aa < 0x035000:
			c = "Cameroon"
		elif aa >= 0x035000 and aa < 0x035400:
			c = "Comoros"
		elif aa >= 0x036000 and aa < 0x037000:
			c = "Congo"
		elif aa >= 0x038000 and aa < 0x039000:
			c = "Ivory Coast"
		elif aa >= 0x03E000 and aa < 0x03F000:
			c = "Gabon"
		elif aa >= 0x040000 and aa < 0x041000:
			c = "Ethiopia"
		elif aa >= 0x042000 and aa < 0x043000:
			c = "Equatorial Guinea"
		elif aa >= 0x044000 and aa < 0x045000:
			c = "Ghana"
		elif aa >= 0x046000 and aa < 0x047000:
			c = "Guinea"
		elif aa >= 0x048000 and aa < 0x048400:
			c = "Guinea-Bissau"
		elif aa >= 0x04A000 and aa < 0x04A400:
			c = "Lesotho"
		elif aa >= 0x04C000 and aa < 0x04D000:
			c = "Kenya"
		elif aa >= 0x050000 and aa < 0x051000:
			c = "Liberia"
		elif aa >= 0x054000 and aa < 0x055000:
			c = "Madagascar"
		elif aa >= 0x058000 and aa < 0x059000:
			c = "Malawi"
		elif aa >= 0x05A000 and aa < 0x05A400:
			c = "Maldives"
		elif aa >= 0x05C000 and aa < 0x05D000:
			c = "Mali"
		elif aa >= 0x05E000 and aa < 0x05E400:
			c = "Mauritania"
		elif aa >= 0x060000 and aa < 0x060400:
			c = "Mauritius"
		elif aa >= 0x062000 and aa < 0x063000:
			c = "Niger"
		elif aa >= 0x064000 and aa < 0x065000:
			c = "Nigeria"
		elif aa >= 0x068000 and aa < 0x069000:
			c = "Uganda"
		elif aa >= 0x06A000 and aa < 0x06A400:
			c = "Qatar"
		elif aa >= 0x06C000 and aa < 0x06D000:
			c = "Central African Republic"
		elif aa >= 0x06E000 and aa < 0x06F000:
			c = "Rwanda"
		elif aa >= 0x070000 and aa < 0x071000:
			c = "Senegal"
		elif aa >= 0x074000 and aa < 0x074400:
			c = "Seychelles"
		elif aa >= 0x076000 and aa < 0x076400:
			c = "Sierra Leone"
		elif aa >= 0x078000 and aa < 0x079000:
			c = "Somalia"
		elif aa >= 0x07A000 and aa < 0x07A400:
			c = "Swaziland"
		elif aa >= 0x07C000 and aa < 0x07D000:
			c = "Sudan"
		elif aa >= 0x080000 and aa < 0x081000:
			c = "Tanzania"
		elif aa >= 0x084000 and aa < 0x085000:
			c = "Chad"
		elif aa >= 0x088000 and aa < 0x089000:
			c = "Togo"
		elif aa >= 0x08A000 and aa < 0x08B000:
			c = "Zambia"
		elif aa >= 0x08C000 and aa < 0x08D000:
			c = "Democratic Republic of Congo"
		elif aa >= 0x090000 and aa < 0x091000:
			c = "Angola"
		elif aa >= 0x094000 and aa < 0x094400:
			c = "Benin"
		elif aa >= 0x096000 and aa < 0x096400:
			c = "Cape Verde"
		elif aa >= 0x098000 and aa < 0x098400:
			c = "Djibouti"
		elif aa >= 0x09A000 and aa < 0x09B000:
			c = "Gambia"
		elif aa >= 0x09C000 and aa < 0x09D000:
			c = "Burkina Faso"
		elif aa >= 0x09E000 and aa < 0x09E400:
			c = "Sao Tome and Principe"
		elif aa >= 0x0A0000 and aa < 0x0A8000:
			c = "Algeria"
		elif aa >= 0x0A8000 and aa < 0x0A9000:
			c = "Bahamas"
		elif aa >= 0x0AA000 and aa < 0x0AA400:
			c = "Barbados"
		elif aa >= 0x0AB000 and aa < 0x0AB400:
			c = "Belize"
		elif aa >= 0x0AC000 and aa < 0x0AD000:
			c = "Colombia"
		elif aa >= 0x0AE000 and aa < 0x0AF000:
			c = "Costa Rica"
		elif aa >= 0x0B0000 and aa < 0x0B1000:
			c = "Cuba"
		elif aa >= 0x0B2000 and aa < 0x0B3000:
			c = "El Salvador"
		elif aa >= 0x0B4000 and aa < 0x0B5000:
			c = "Guatemala"
		elif aa >= 0x0B6000 and aa < 0x0B7000:
			c = "Guyana"
		elif aa >= 0x0B8000 and aa < 0x0B9000:
			c = "Haiti"
		elif aa >= 0x0BA000 and aa < 0x0BB000:
			c = "Honduras"
		elif aa >= 0x0BC000 and aa < 0x0BC400:
			c = "Saint Vincent and the Grenadines"
		elif aa >= 0x0BE000 and aa < 0x0BF000:
			c = "Jamaica"
		elif aa >= 0x0C0000 and aa < 0x0C1000:
			c = "Nicaragua"
		elif aa >= 0x0C2000 and aa < 0x0C3000:
			c = "Panama"
		elif aa >= 0x0C4000 and aa < 0x0C5000:
			c = "Dominican Republic"
		elif aa >= 0x0C6000 and aa < 0x0C7000:
			c = "Trinidad and Tobago"
		elif aa >= 0x0C8000 and aa < 0x0C9000:
			c = "Suriname"
		elif aa >= 0x0CA000 and aa < 0x0CA400:
			c = "Antigua and Barbuda"
		elif aa >= 0x0CC000 and aa < 0x0CC400:
			c = "Grenada"
		elif aa >= 0x0D0000 and aa < 0x0D8000:
			c = "Mexico"
		elif aa >= 0x0D8000 and aa < 0x0E0000:
			c = "Venezuela"
		elif aa >= 0x100000 and aa < 0x200000:
			c = "Russian Federation"
		elif aa >= 0x201000 and aa < 0x201400:
			c = "Namibia"
		elif aa >= 0x202000 and aa < 0x202400:
			c = "Eritrea"
		elif aa >= 0x300000 and aa < 0x340000:
			c = "Italy"
		elif aa >= 0x340000 and aa < 0x380000:
			c = "Spain"
		elif aa >= 0x380000 and aa < 0x3C0000:
			c = "France"
		elif aa >= 0x3C0000 and aa < 0x400000:
			c = "Germany"
		elif aa >= 0x400000 and aa < 0x440000:
			c = "United Kingdom"
		elif aa >= 0x400080 and aa < 0x4000FF:
			c = "Bermuda"
		elif aa >= 0x400100 and aa < 0x40017F:
			c = "Bermuda"
		elif aa >= 0x400180 and aa < 0x4001BF:
			c = "Bermuda"
		elif aa >= 0x424000 and aa < 0x4240FF:
			c = "Bermuda"
		elif aa >= 0x440000 and aa < 0x448000:
			c = "Austria"
		elif aa >= 0x448000 and aa < 0x450000:
			c = "Belgium"
		elif aa >= 0x450000 and aa < 0x458000:
			c = "Bulgaria"
		elif aa >= 0x458000 and aa < 0x460000:
			c = "Denmark"
		elif aa >= 0x460000 and aa < 0x468000:
			c = "Finland"
		elif aa >= 0x468000 and aa < 0x470000:
			c = "Greece"
		elif aa >= 0x470000 and aa < 0x478000:
			c = "Hungary"
		elif aa >= 0x478000 and aa < 0x480000:
			c = "Norway"
		elif aa >= 0x480000 and aa < 0x488000:
			c = "Netherlands"
		elif aa >= 0x488000 and aa < 0x490000:
			c = "Poland"
		elif aa >= 0x490000 and aa < 0x498000:
			c = "Portugal"
		elif aa >= 0x498000 and aa < 0x4A0000:
			c = "Czech Republic"
		elif aa >= 0x4A0000 and aa < 0x4A8000:
			c = "Romania"
		elif aa >= 0x4A8000 and aa < 0x4B0000:
			c = "Sweden"
		elif aa >= 0x4B0000 and aa < 0x4B8000:
			c = "Switzerland"
		elif aa >= 0x4B8000 and aa < 0x4C0000:
			c = "Turkey"
		elif aa >= 0x4C0000 and aa < 0x4C8000:
			c = "Yugoslavia"
		elif aa >= 0x4C8000 and aa < 0x4C8400:
			c = "Cyprus"
		elif aa >= 0x4CA000 and aa < 0x4CB000:
			c = "Ireland"
		elif aa >= 0x4CC000 and aa < 0x4CD000:
			c = "Iceland"
		elif aa >= 0x4D0000 and aa < 0x4D0400:
			c = "Luxembourg"
		elif aa >= 0x4D2000 and aa < 0x4D2400:
			c = "Malta"
		elif aa >= 0x4D4000 and aa < 0x4D4400:
			c = "Monaco"
		elif aa >= 0x500000 and aa < 0x500400:
			c = "San Marino"
		elif aa >= 0x501000 and aa < 0x501400:
			c = "Albania"
		elif aa >= 0x501C00 and aa < 0x502000:
			c = "Croatia"
		elif aa >= 0x502C00 and aa < 0x503000:
			c = "Latvia"
		elif aa >= 0x503C00 and aa < 0x504000:
			c = "Lithuania"
		elif aa >= 0x504C00 and aa < 0x505000:
			c = "Moldova"
		elif aa >= 0x505C00 and aa < 0x506000:
			c = "Slovakia"
		elif aa >= 0x506C00 and aa < 0x507000:
			c = "Slovenia"
		elif aa >= 0x507C00 and aa < 0x508000:
			c = "Uzbekistan"
		elif aa >= 0x508000 and aa < 0x510000:
			c = "Ukraine"
		elif aa >= 0x510000 and aa < 0x510400:
			c = "Belarus"
		elif aa >= 0x511000 and aa < 0x511400:
			c = "Estonia"
		elif aa >= 0x512000 and aa < 0x512400:
			c = "Macedonia"
		elif aa >= 0x513000 and aa < 0x513400:
			c = "Bosnia and Herzegovina"
		elif aa >= 0x514000 and aa < 0x514400:
			c = "Georgia"
		elif aa >= 0x515000 and aa < 0x515400:
			c = "Tajikistan"
		elif aa >= 0x516000 and aa < 0x516400:
			c = "Montenegro"
		elif aa >= 0x600000 and aa < 0x600400:
			c = "Armenia"
		elif aa >= 0x600800 and aa < 0x600C00:
			c = "Azerbaijan"
		elif aa >= 0x601000 and aa < 0x601400:
			c = "Kyrgyzstan"
		elif aa >= 0x601800 and aa < 0x601C00:
			c = "Turkmenistan"
		elif aa >= 0x680000 and aa < 0x680400:
			c = "Bhutan"
		elif aa >= 0x681000 and aa < 0x681400:
			c = "Micronesia"
		elif aa >= 0x682000 and aa < 0x682400:
			c = "Mongolia"
		elif aa >= 0x683000 and aa < 0x683400:
			c = "Kazakhstan"
		elif aa >= 0x684000 and aa < 0x684400:
			c = "Palau"
		elif aa >= 0x700000 and aa < 0x701000:
			c = "Afghanistan"
		elif aa >= 0x702000 and aa < 0x703000:
			c = "Bangladesh"
		elif aa >= 0x704000 and aa < 0x705000:
			c = "Myanmar"
		elif aa >= 0x706000 and aa < 0x707000:
			c = "Kuwait"
		elif aa >= 0x708000 and aa < 0x709000:
			c = "Laos"
		elif aa >= 0x70A000 and aa < 0x70B000:
			c = "Nepal"
		elif aa >= 0x70C000 and aa < 0x70C400:
			c = "Oman"
		elif aa >= 0x70E000 and aa < 0x70F000:
			c = "Cambodia"
		elif aa >= 0x710000 and aa < 0x718000:
			c = "Saudi Arabia"
		elif aa >= 0x718000 and aa < 0x720000:
			c = "Korea"
		elif aa >= 0x720000 and aa < 0x728000:
			c = "Korea"
		elif aa >= 0x728000 and aa < 0x730000:
			c = "Iraq"
		elif aa >= 0x730000 and aa < 0x738000:
			c = "Iran"
		elif aa >= 0x738000 and aa < 0x740000:
			c = "Israel"
		elif aa >= 0x740000 and aa < 0x748000:
			c = "Jordan"
		elif aa >= 0x748000 and aa < 0x750000:
			c = "Lebanon"
		elif aa >= 0x750000 and aa < 0x758000:
			c = "Malaysia"
		elif aa >= 0x758000 and aa < 0x760000:
			c = "Philippines"
		elif aa >= 0x760000 and aa < 0x768000:
			c = "Pakistan"
		elif aa >= 0x768000 and aa < 0x770000:
			c = "Singapore"
		elif aa >= 0x770000 and aa < 0x778000:
			c = "Sri Lanka"
		elif aa >= 0x778000 and aa < 0x780000:
			c = "Syrian Arab Republic"
		elif aa >= 0x780000 and aa < 0x7C0000:
			c = "China"
		elif aa >= 0x7C0000 and aa < 0x800000:
			c = "Australia"
		elif aa >= 0x800000 and aa < 0x840000:
			c = "India"
		elif aa >= 0x840000 and aa < 0x880000:
			c = "Japan"
		elif aa >= 0x880000 and aa < 0x888000:
			c = "Thailand"
		elif aa >= 0x888000 and aa < 0x890000:
			c = "Vietnam"
		elif aa >= 0x890000 and aa < 0x891000:
			c = "Yemen"
		elif aa >= 0x894000 and aa < 0x895000:
			c = "Bahrain"
		elif aa >= 0x895000 and aa < 0x895400:
			c = "Brunei"
		elif aa >= 0x896000 and aa < 0x897000:
			c = "United Arab Emirates"
		elif aa >= 0x897000 and aa < 0x897400:
			c = "Solomon Islands"
		elif aa >= 0x898000 and aa < 0x899000:
			c = "Papua New Guinea"
		elif aa >= 0x899000 and aa < 0x899400:
			c = "Taiwan"
		elif aa >= 0x8A0000 and aa < 0x8A8000:
			c = "Indonesia"
		elif aa >= 0x900000 and aa < 0x900400:
			c = "Marshall Islands"
		elif aa >= 0x901000 and aa < 0x901400:
			c = "Cook Islands"
		elif aa >= 0x902000 and aa < 0x902400:
			c = "Samoa"
		elif aa >= 0xC00000 and aa < 0xC40000:
			c = "Canada"
		elif aa >= 0xC80000 and aa < 0xC87E00:
			c = "New Zealand"
		elif aa >= 0xC87E00 and aa < 0xC87F00:
			c = "New Zealand (Ground)"
		elif aa >= 0xC87F00 and aa < 0xC88000:
			c = "New Zealand Military"
		elif aa >= 0xC88000 and aa < 0xC89000:
			c = "Fiji"
		elif aa >= 0xC8A000 and aa < 0xC8A400:
			c = "Nauru"
		elif aa >= 0xC8C000 and aa < 0xC8C400:
			c = "Saint Lucia"
		elif aa >= 0xC8D000 and aa < 0xC8D400:
			c = "Tonga"
		elif aa >= 0xC8E000 and aa < 0xC8E400:
			c = "Kiribati"
		elif aa >= 0xC90000 and aa < 0xC90400:
			c = "Vanuatu"
		elif aa >= 0xE00000 and aa < 0xE40000:
			c = "Argentina"
		elif aa >= 0xE40000 and aa < 0xE80000:
			c = "Brazil"
		elif aa >= 0xE80000 and aa < 0xE81000:
			c = "Chile"
		elif aa >= 0xE84000 and aa < 0xE85000:
			c = "Ecuador"
		elif aa >= 0xE88000 and aa < 0xE89000:
			c = "Paraguay"
		elif aa >= 0xE8C000 and aa < 0xE8D000:
			c = "Peru"
		elif aa >= 0xE90000 and aa < 0xE91000:
			c = "Uruguay"
		elif aa >= 0xE94000 and aa < 0xE95000:
			c = "Bolivia"
		elif aa >= 0xF00000 and aa < 0xF08000:
			c = "ICAO (1)"
		elif aa >= 0xF09000 and aa < 0xF09400:
			c = "ICAO (3)"
		else:
			c = ""	
		return c

	# Haversine formula example in Python
	# return distance in km bewteen origin and position (not incl altitude)
	# Author: Wayne Dyck
	def rangeAndBearingToAircraft(self, origin, position, alt):
	    lat1, lon1 = origin
	    lat2, lon2 = position
	    radius = 6371 # km
	    dlat = math.radians(lat2-lat1)
	    dlon = math.radians(lon2-lon1)
	    a = math.sin(dlat/2) * math.sin(dlat/2) + math.cos(math.radians(lat1)) \
		* math.cos(math.radians(lat2)) * math.sin(dlon/2) * math.sin(dlon/2)
	    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
	    d = radius * c

	    # compute initial bearing
	    # http://www.movable-type.co.uk/scripts/latlong.html
	    y = math.sin(dlon) * math.cos(math.radians(lat2))
	    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - \
		math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dlon)
	    brng = math.degrees(math.atan2(y, x))
	    if(brng < 0):		# atan2 is -180 to +180
		brng += 360.0

	    # compute elevation angle from origin
	    # FIXME - for now assume observer at sea level.
	    el = math.degrees(math.atan2(alt, d*1000.0))		# d in km
	    if(el < 0):		# atan2 is -180 to +180
		el += 360.0

	    return [ d, brng, el ]

        def feet2meters(m):
	    return m / 3.2808399 

	def testParity(self):
		# Test the parity checker
		d = bitstring.BitArray(hex='0x5D3C6614')
		pe = bitstring.BitArray(hex='0xc315d2')
		pc = calcParity(d)
		if pe != pc: 
			print "Parity check failed on %d bit input:" % (len(d)), pe, pc
		else:
			print "Parity check successful on %d bit input:" % (len(d)), pe, pc

		d = bitstring.BitArray(hex='0x8F45AC5260BDF348222A58')
		pe = bitstring.BitArray(hex='0xB98284')
		pc = calcParity(d)
		if pe != pc: 
			print "Parity check failed on %d bit input:" % (len(d)), pe, pc
		else:
			print "Parity check successful on %d bit input:" % (len(d)), pe, pc

	def testPackets(self):
		#d = (0xa8, 0x00, 0x0b, 0x0a, 0x10, 0x01, 0x00, 0x00)
		#d = (0x5d, 0xae, 0x01, 0x3f, 0x79, 0x48, 0xba, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x50)
		#d = (0x20, 0x00, 0x0c, 0x80, 0x61, 0x3b, 0xa0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x09, 0x50)
		#d = (0x8d,0xa9,0xd5,0xe7,0x58,0x2d,0x6c,0x74,0x06,0xcb,0x41,0xa2,0x09,0x50)
		#d = (8d 89 90 d2 58 bf 00 ce 2f 05 5f 47 d0 25)
		#d = (0x00,0xa1,0x01,0x0e,0xb1,0x9d,0x69)
		#d = (0x8d, 0xa8, 0x23, 0x3e, 0x58, 0x1b, 0x84, 0x86, 0xcc, 0x32, 0x53, 0x6f, 0x41, 0x23)
		#d = (0x8d , 0xa6 , 0xb2 , 0x49 , 0x26 , 0x51 , 0x0d , 0x47 , 0x9a , 0x10 , 0x21 , 0xac , 0x93 , 0x83)
		#d = (0x8d,0xac,0xf1,0x5b,0x99,0x44,0xcf,0x87,0xe8,0x44,0x86,0x32,0x94,0x52)
		# debugging CPR decoding...
		#d = (0x8d ,0xa7 ,0x1e ,0xfa ,0x36 ,0x09 ,0x51 ,0x30 ,0x2a ,0x32 ,0x09 ,0x04 ,0x3e ,0xb2)
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x99 ,0x11 ,0xb0 ,0x9a ,0x20 ,0x08 ,0x29 ,0xb7 ,0xd3 ,0xea )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x99 ,0x11 ,0xb1 ,0x9a ,0x20 ,0x04 ,0x29 ,0xfc ,0x83 ,0x24 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x99 ,0x11 ,0xb0 ,0x9a ,0x40 ,0x04 ,0x29 ,0x30 ,0x0d ,0x91 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x60 ,0xbd ,0xf4 ,0x75 ,0x15 ,0xca ,0x1e ,0x51 ,0x0f ,0x21 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x99 ,0x11 ,0xb0 ,0x9a ,0x40 ,0x04 ,0x29 ,0x30 ,0x0d ,0x91 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x60 ,0xbd ,0xf0 ,0xde ,0xe5 ,0x99 ,0x70 ,0x74 ,0x4a ,0x80 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x99 ,0x11 ,0xb0 ,0x9a ,0x40 ,0x04 ,0x29 ,0x30 ,0x0d ,0x91 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x99 ,0x11 ,0xb0 ,0x9a ,0x40 ,0x04 ,0x29 ,0x30 ,0x0d ,0x91 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x99 ,0x11 ,0xb0 ,0x9a ,0x40 ,0x04 ,0x29 ,0x30 ,0x0d ,0x91 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x20 ,0x04 ,0xe0 ,0x71 ,0xc3 ,0x0d ,0xa0 ,0x21 ,0x0d ,0x67 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x60 ,0xbd ,0xf4 ,0x73 ,0xf3 ,0xcb ,0x33 ,0x50 ,0x09 ,0xf8 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x99 ,0x11 ,0xb0 ,0x9a ,0x48 ,0x04 ,0x29 ,0x5e ,0xaf ,0x99 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x99 ,0x11 ,0xb0 ,0x9a ,0x40 ,0x04 ,0x29 ,0x30 ,0x0d ,0x91 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x60 ,0xbf ,0x00 ,0xdd ,0xb2 ,0xc4 ,0x66 ,0x58 ,0x72 ,0x13 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x99 ,0x11 ,0xb0 ,0x9a ,0x40 ,0x04 ,0x29 ,0x30 ,0x0d ,0x91 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x58 ,0xbd ,0xf4 ,0x72 ,0x9d ,0x67 ,0x8a ,0x2b ,0x40 ,0x4e )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x20 ,0x04 ,0xe0 ,0x71 ,0xc3 ,0x0d ,0xa0 ,0x21 ,0x0d ,0x67 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x58 ,0xbf ,0x00 ,0xdc ,0x8a ,0xc5 ,0x90 ,0x25 ,0x5e ,0xe4 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x99 ,0x11 ,0xb0 ,0x9a ,0x40 ,0x04 ,0x29 ,0x30 ,0x0d ,0x91 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x58 ,0xbf ,0x00 ,0xdc ,0x60 ,0xc5 ,0xba ,0x74 ,0x79 ,0x7f )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x99 ,0x91 ,0xb0 ,0x9a ,0x48 ,0x04 ,0x29 ,0xcf ,0x68 ,0xe6 )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x99 ,0x91 ,0xb0 ,0x9a ,0x40 ,0x04 ,0x29 ,0xa1 ,0xca ,0xee )
		#self.decode(d)
		#d = (0x8d ,0x86 ,0x91 ,0x44 ,0x58 ,0xbf ,0x04 ,0x71 ,0x79 ,0x68 ,0xaf ,0x1d ,0xba ,0xe2 )
		#self.decode(d)
		# testing TIS-B
		#d = (0x95, 0xac, 0x07, 0x6a, 0x99, 0x3c, 0x2f, 0x08, 0xe0, 0x5a, 0x20, 0x47, 0xc7, 0x12)
		#self.decode(d)
		#d = (0x95, 0xac, 0x0b, 0x14, 0x68, 0x17, 0xf0, 0xf9, 0x92, 0x30, 0x86, 0x99, 0xe0, 0xec)
		#self.decode(d)
		#d = (0x95, 0xac, 0x0b, 0x14, 0x68, 0x17, 0xf4, 0x8f, 0x02, 0xdd, 0xca, 0x64, 0x53, 0xc5)
		#self.decode(d)
		#d = (0x95, 0xac, 0x04, 0x12, 0x68, 0x0f, 0xf1, 0x17, 0x3a, 0x1c, 0xb4, 0xc4, 0x67, 0xb8)
		#self.decode(d)
		#d = (0x95, 0xac, 0x04, 0x12, 0x99, 0x38, 0x2b, 0x1c, 0x40, 0x6a, 0x20, 0xe1, 0xab, 0x56)
		#self.decode(d)
		#d = (0x95, 0xac, 0x0f, 0x46, 0x68, 0x13, 0xb4, 0x77, 0xe2, 0xe1, 0x07, 0x9e, 0x54, 0x60)
		#self.decode(d)
		#d = (0x95, 0xac, 0x03, 0x06, 0x68, 0x07, 0x70, 0xe3, 0x9c, 0x32, 0x2e, 0x77, 0x28, 0x26)
		#self.decode(d)
		#d = (0x95, 0xac, 0x03, 0x06, 0x68, 0x07, 0x74, 0x79, 0x6a, 0xdf, 0x69, 0xe7, 0x4e, 0xde)
		#self.decode(d)
		#d = (0x95, 0xac, 0x03, 0x06, 0x99, 0x38, 0x33, 0x87, 0x80, 0x06, 0x20, 0xdd, 0xb1, 0x6b)
		#self.decode(d)
		#d = (0x95, 0xac, 0x0b, 0x14, 0x99, 0x40, 0x05, 0x0a, 0x60, 0x26, 0x20, 0x79, 0x23, 0x42)
		#self.decode(d)
		#d = (0x95, 0xac, 0x0b, 0x14, 0x68, 0x19, 0x00, 0xf9, 0xe6, 0x30, 0x8d, 0xc2, 0x14, 0x97)
		#self.decode(d)
		#d = (0x95, 0xac, 0x04, 0x12, 0x68, 0x11, 0x94, 0xac, 0xf2, 0xca, 0x64, 0x04, 0x20, 0x6b)
		#self.decode(d)
		#d = (0x95, 0xac, 0x0f, 0x46, 0x68, 0x13, 0xe0, 0xe1, 0xb4, 0x33, 0xe7, 0x21, 0x79, 0x7c)
		#self.decode(d)
		#d = (0x95, 0xac, 0x03, 0x06, 0x99, 0x38, 0x33, 0x87, 0x60, 0x06, 0x20, 0xf8, 0x31, 0xbd)
		#self.decode(d)
		#d = (0x95, 0xac, 0x0f, 0x46, 0x68, 0x13, 0xe0, 0xe1, 0x82, 0x33, 0xf0, 0x6a, 0x88, 0x3f)
		#self.decode(d)
		#d = (0x95, 0xac, 0x0f, 0x46, 0x68, 0x13, 0xe4, 0x77, 0x5a, 0xe1, 0x22, 0x8e, 0xd8, 0x13)
		#self.decode(d)
		#d = (0x95, 0xac, 0x0f, 0x46, 0x99, 0x38, 0x28, 0x8c, 0x40, 0x2a, 0x20, 0x29, 0x58, 0x78)
		#self.decode(d)
		#d = (0x95, 0xac, 0x07, 0xe3, 0x68, 0x0d, 0x11, 0x19, 0xd4, 0x17, 0x4d, 0xab, 0xaa, 0x1e)
		#self.decode(d)
		#d = (0x95, 0xac, 0x07, 0xe3, 0x68, 0x0d, 0x14, 0xae, 0xba, 0xc5, 0x1a, 0x41, 0x64, 0x1d)
		#self.decode(d)
		#d = (0x95, 0xac, 0x0b, 0x14, 0x68, 0x19, 0x10, 0xfa, 0x14, 0x30, 0x89, 0x6d, 0xeb, 0xf0)
		##self.decode(d)
		#d = (0x95, 0xac, 0x0b, 0x14, 0x68, 0x19, 0x14, 0x8f, 0x82, 0xdd, 0xcd, 0xc0, 0xd6, 0xc6)
		#self.decode(d)
		#d = (0x95, 0xac, 0x0b, 0x14, 0x99, 0x40, 0x05, 0x0a, 0x60, 0x22, 0x20, 0x41, 0x15, 0x42)
		#self.decode(d)

		# testing DF16
		d = (0x80, 0xa1, 0x86, 0x39, 0x58, 0x33, 0x94, 0x99, 0xde, 0xbe, 0x88, 0x96, 0xe6, 0xf0)
		self.decode(d)
		d = (0x80, 0x81, 0x83, 0x17, 0x60, 0x19, 0x78 , 0xd, 0x12, 0x1a, 0xa3, 0x4e, 0x8d, 0xd5)
		self.decode(d)
		d = (0x80, 0xa1, 0x86, 0x30, 0x58, 0x33, 0x14, 0x98, 0x2e, 0xbf, 0x04, 0x41, 0xec, 0x56)
		self.decode(d)
		d = (0x80, 0x81, 0x83, 0x13, 0x60, 0x19, 0x38, 0xfd, 0xe0, 0x1a, 0x76, 0x90, 0x67, 0xd7)
		self.decode(d)
		d = (0x80, 0xa1, 0x86, 0x1d, 0x58, 0x31, 0xd1, 0x01, 0xfe, 0x11, 0x57, 0x53, 0x47, 0x4b)
		self.decode(d)
		d = (0x80, 0xa1, 0x85, 0x1c, 0x58, 0x29, 0xc4, 0x94, 0x02, 0xd7, 0x84, 0x9b, 0x02, 0x7d)
		self.decode(d)
		d = (0x80, 0x81, 0x83, 0x31, 0x58, 0x1b, 0x11, 0x04, 0x8c, 0x1f, 0x31, 0x94, 0xdc, 0x9b)
		self.decode(d)
		d = (0x80, 0x81, 0x83, 0x15, 0x58, 0x19, 0x51, 0x05, 0x78, 0x1e, 0x12, 0x77, 0xe3, 0x0c)
		self.decode(d)
		d = (0x80, 0xa1, 0x83, 0x9f, 0x60, 0x1f, 0x04, 0x9f, 0xe6, 0xcc, 0x5e, 0x3f, 0xd6, 0x0f)
		self.decode(d)
		d = (0x80, 0xa1, 0x83, 0x95, 0x60, 0x1d, 0x54, 0x9f, 0x24, 0xcd, 0x03, 0xa5, 0x7a, 0x12)
		self.decode(d)
		d = (0x80, 0x81, 0x83, 0x1f, 0x60, 0x19, 0xf1, 0x08, 0x08, 0x20, 0x38, 0x84, 0xf1, 0x47)
		self.decode(d)
		d = (0x80, 0x81, 0x00, 0xc4, 0x58, 0x06, 0x48, 0x41, 0x38, 0x08, 0x02, 0x51, 0x9c, 0x22)
		self.decode(d)
		d = (0x80, 0xa1, 0x84, 0x9f, 0x60, 0x25, 0xf0, 0xff, 0x8e, 0x25, 0x1b, 0x70, 0x48, 0x73)
		self.decode(d)
		d = (0x80, 0xa1, 0x84, 0x9e, 0x60, 0x25, 0xf4, 0x94, 0xfa, 0xd2, 0x87, 0xf2, 0xe5, 0x77)
		self.decode(d)
		return

	    
if __name__ == "__main__":
	class a:
		def __init__(self, args):
			self.args = args
	args = a
	args.origin = (37.7, -122.02)
	reader = None
	d = AdsbDecoder(args, reader)
	d.testPackets()
