from __future__ import print_function
import sys
import os

def ensureStarted():
   notStarted = os.system("vmkload_mod -l | grep osfs > /dev/null")
   if notStarted:
      print("OSFS is not running.")
      exit(1)

def setupPath():
   vmtree = os.environ['VMTREE']
   sys.path.append(vmtree + '/vmkernel/tests/osfs/')

def getPidCid(path):
   path = os.path.realpath(path) # canonical path
   (pid,cid) = path.split('/')[3].split(':')
   cid = cid.replace('-','')
   return (pid,cid)
