#!/usr/bin/env python
"""
Copyright 2015 VMware, Inc.  All rights reserved. -- VMware Confidential

"""
from __future__ import print_function

__author__ = "VMware, Inc"

import sys
from pyVmomi import Vim
from pyVmomi import VmomiSupport
from pyVmomi.VmomiSupport import newestVersions
from pyVim import host
from pyVim.connect import Connect, Disconnect
from pyVim import arguments
from pyVim.task import WaitForTask
import atexit

datastoreSystem = None

def main():
   supportedArgs = [
      (["t:", "eventType="], "",          "Event Type",     "eventType"),
      (["d:", "datastore="], "",          "Comma separated list of datastore MOIDs", "datastore"),
   ]

   supportedToggles = [ (["usage", "help"], False, "Show usage information", "usage") ]

   args = arguments.Arguments(sys.argv, supportedArgs, supportedToggles)
   if args.GetKeyValue("usage") == True:
      args.Usage()
      sys.exit(0)

   passedDsIds = args.GetKeyValue("datastore")
   dsIds = passedDsIds.split(",")
   eventType = args.GetKeyValue("eventType")

   try:
      reqCtx = VmomiSupport.GetRequestContext()
      reqCtx["realUser"] = 'datastore-notification'
      si = Connect(host="localhost",
                   user="dcui",
                   version=newestVersions.Get('vim'))
      atexit.register(Disconnect, si)
   except:
      print("Unable to connect")
      sys.exit(1)

   global datastoreSystem
   datastoreSystem = host.GetHostConfigManager(si).GetDatastoreSystem()

   datastores = []
   for datastore in datastoreSystem.GetDatastore():
      try:
         dsIds.index(datastore.name)
         datastores.append(datastore)
      except ValueError:
         try:
            dsIds.index(datastore._moId)
            datastores.append(datastore)
         except ValueError:
            pass

   datastoreSystem.NotifyDatastore(eventType, datastores)

if __name__ == "__main__":
   main()


