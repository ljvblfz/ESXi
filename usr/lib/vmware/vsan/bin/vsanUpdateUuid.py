#!/usr/bin/python
'''
Copyright 2013-2014 VMware, Inc. All rights reserved. -- VMware Confidential
Created on July 30, 2013
@author: lkrishnarajpet@vmware.com

Tool to update the VSAN UUID in VM files - vmx, vmsd, vmtx and vmdk files
'''

import os
import re
import sys
import time
import socket
import subprocess
import binascii
import uuid
import vmware.vsi
import errno
import pyVim
import pyVmomi
import fileinput
import shutil

import tempfile
from tempfile import mkstemp
from shutil import move
from os import remove, close

from optparse import OptionParser

from pyVim.connect import SmartConnect, Disconnect, GetSi
from pyVim import folder, host, path, vm, vmconfig
from pyVmomi.VmomiSupport import ResolveLink
from pyVmomi import Vim


# 
# InsertDash --
#    Helper function to insert "-" in VSAN UUID
#
def InsertDash(string, index):
   return string[:index] + '-' + string[index:]

# 
# GetClusterInfo --
#    Helper function to get VSAN Cluster inforamtion on the ESX host
#
def GetClusterInfo():
   cmd = "localcli --formatter=python vsan cluster get"
   s = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).communicate()[0]
   if not s:
      print("Failed to get cluster info")

   info = eval(s, None, None)
   info['state'] = info['Local Node State']
   info['masterUUID'] = info['Sub-Cluster Master UUID']
   info['backupUUID'] = info['Sub-Cluster Backup UUID']
   info['localUUID'] = info['Local Node UUID']
   info['subClusterUUID'] = info['Sub-Cluster UUID']
   info['members'] = info['Sub-Cluster Member UUIDs']
   return info

# 
# GetClusterUuid --
#    Helper function to get the VSAN Cluster UUID on the ESX host
#
def GetClusterUuid():
   try:
      clusterInfo = GetClusterInfo()
      uuid = clusterInfo['subClusterUUID']
      uuid = uuid.replace("-", "")
      uuid = InsertDash(uuid, 16)
      return 0, uuid
   except Exception as e:
      print("Failed to get cluster info: %s" % e)
      return 1, ""

# 
# UpdateVSANUuid --
#    This function finds and replaces VSAN UUID with New VSAN UUID in VM 
#    files. If isDryRun flag is set then no changes will be done to VM 
#    files.
#
def UpdateVSANUuid(fileName, NewUuid, isDryRun):
   if os.path.isdir(fileName):
      print(('Warning: %s is a directory' % (fileName)))
      return 1

   stat = os.stat(fileName)
   mode, uid, gid = stat[0], stat[4], stat[5]

   tempfh, tempfileName = tempfile.mkstemp()
   temp_file = open(tempfileName, 'w')
   old_file = open(fileName)

   for line in old_file:
      if re.search('vsan:(\d)', line):
         vsanString = line.split('/')
         vsanString[3] = "vsan:" + NewUuid
         temp_file.write("/".join(vsanString))
      else:
         temp_file.write(line)

   temp_file.close()
   close(tempfh)
   old_file.close()

   if isDryRun == 0:
      remove(fileName)
      move(tempfileName, fileName)
      os.chown(fileName, uid, gid)
      os.chmod(fileName, mode)
   else:
      remove(tempfileName)
   return

# 
# UpdateVMFiles --
#    This function finds VM files names and filters out -flat.vmdk,
#    CBRC files -digest-delta.vmdk/-delta.vmdk files
#
def UpdateVMFiles(args, dirname, files):
   for file in files:
      if file.endswith('.vmdk'):
         if not (re.search('-flat.vmdk', file) or 
                 re.search('-delta.vmdk', file) or 
                 re.search('-digest-delta.vmdk', file)):
            UpdateVSANUuid(os.path.join(dirname, file), args[0], args[1])
      elif file.endswith('.vmx'):
         UpdateVSANUuid(os.path.join(dirname, file), args[0], args[1])
      elif file.endswith('.vmsd'):
         UpdateVSANUuid(os.path.join(dirname, file), args[0], args[1])
      elif file.endswith('.vmtx'):
         UpdateVSANUuid(os.path.join(dirname, file), args[0], args[1])

# 
# CheckIfVSANConfigured --
#    Helper function to check VSAN is configuredon the ESX host.
#
def CheckIfVSANConfigured():
   notConfigured = os.system("/sbin/esxcli vsan cluster get > /dev/null")
   if notConfigured:
      print("VSAN Clustering is not enabled on this host. ")
      print("Please re-run the script after configuring VSAN") 
      exit(1)

# 
# Usage --
#    Helper function to log Usage of this command.
#
def Usage(parser, command = None):
   parser.print_help()

def main():
   global opts
   usageStr = 'Usage: %s [options]' % sys.argv[0]
   parser = OptionParser(usageStr)

   dryrunHelp = '''Display the files that would have been changed, but do not 
actually change them.'''
   parser.add_option('-d', "--dryrun", dest='dryrun', action='store_true', 
                     default=False, help=dryrunHelp)

   opts, args = parser.parse_args()

   if opts.dryrun:
       dryRun = 1
   else:
       dryRun = 0

   CheckIfVSANConfigured()
   ret, clusterUuid = GetClusterUuid()
   if (ret != 0):
       print ("Failed to get VSAN Cluster UUID")
       return 1
   print("Updating VM files with VSAN UUID vsan:%s" % (clusterUuid))

   args = [ clusterUuid, dryRun ]
   vsanUuid= 'vsan:'+ clusterUuid
   vsanPath = os.path.join("/vmfs", "volumes", vsanUuid)
   for rootdir, dirs, files in os.walk(vsanPath):
            UpdateVMFiles(args, rootdir, files)

if __name__ == '__main__':
   try:
     sys.exit(main())
   except Exception as e:
     import traceback
     exc_type, exc_val, exc_trace = sys.exc_info()
     print(exc_type, exc_val)
     print("Trace:")
     traceback.print_tb(exc_trace, file=sys.stdout)
     sys.exit(1)
