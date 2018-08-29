#!/usr/bin/env python
# Copyright 2016 VMware, Inc.  All rights reserved. -- VMware Confidential
#
# FCD info for vm-support

__author__ = "VMware, Inc."

import os
import subprocess
import shutil
import tarfile
import sys

from esxutils import getFsList

"""
FCD vm-support
"""

def getDataStores():
   allFs = getFsList()
   return (item["Volume Name"] for item in allFs)


def fcdCopy(src, dst):
   # On Vsan datastore even if some file is shown as present, it may not be
   # availabe totally on the node causing copytree to throw exception.
   # Ignore all copytree exceptions. Grab whatever is possible.
   try:
      shutil.copytree(src, dst)
   except:
      pass


def archiveFcd():
   archievePath = "fcd-support"

   if os.path.isdir(archievePath):
      shutil.rmtree(archievePath)
   os.mkdir(archievePath)

   for dsName in getDataStores():
      catalogPath = "/vmfs/volumes/" + dsName + "/catalog"
      catlogCanonicalPath = os.path.realpath(catalogPath)

      if not os.path.isdir(catlogCanonicalPath):
         continue

      # Close the catalog using notifyDatastore
      command = ["/usr/lib/vmware/hostd/bin/notifyDatastore.py",
                 "-t", "PreUnmount",
                 "-d", dsName]
      subprocess.call(command)

      catalogArchievePath = archievePath + "/" + dsName + "/catalog"
      os.makedirs(catalogArchievePath)

      # In case of Vsan and Vvol catlogCanonicalPath is nothing but a
      # local volume which has many VMFS header (hidden) files.
      # in fcd-support VMFS header files are not required.
      # It significantly reduces time to copy the fcd related information if
      # VMFS headers are excluded.

      # tidy
      tidy = catlogCanonicalPath + "/tidy"
      if os.path.isdir(tidy):
         fcdCopy(tidy, catalogArchievePath + "/tidy")

      # shard
      shard = catlogCanonicalPath + "/shard"
      if os.path.isdir(shard):
         fcdCopy(shard, catalogArchievePath + "/shard")

      # vclock
      vclock = catlogCanonicalPath + "/vclock"
      if os.path.isdir(vclock):
         fcdCopy(vclock, catalogArchievePath + "/")

      # mutex
      mutex = catlogCanonicalPath + "/mutex"
      if os.path.isdir(mutex):
         fcdCopy(mutex, catalogArchievePath)

      # logs
      logs = catlogCanonicalPath + "/catalog.log"
      if os.path.exists(logs):
         shutil.copy(logs, catalogArchievePath)

      logs0 = catlogCanonicalPath + "/catalog.0"
      if os.path.exists(logs0):
         shutil.copy(logs0, catalogArchievePath)

   # create a tar and print it on the stdout. so that vm-support can capture it.
   with tarfile.open(name=None,
                     mode="w|gz",
                     fileobj=sys.stdout.buffer) as tar:
      tar.add(archievePath)

   # remove the fcd-support dir
   shutil.rmtree(archievePath)

if __name__ == "__main__":
   archiveFcd()
