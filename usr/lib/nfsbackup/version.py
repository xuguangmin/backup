#!/usr/bin/python

import apt
import sys

try:
	cache = apt.Cache()	
	pkg = cache["nfsbackup"]
	print pkg.installed.version
except:
	pass


