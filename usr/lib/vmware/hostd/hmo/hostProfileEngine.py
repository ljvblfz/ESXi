#!/usr/bin/python
"""
Copyright 2010-2014 VMware, Inc.  All rights reserved. -- VMware Confidential
"""
import hostprofiles
import sys
import PyVmomiServer
import SoapHandler
import threading
from contrib.vorb import RunVmomiOrb
from hpCommon.serviceManager import serviceMgr

# Initailize the service based on feature switches.
serviceMgr.InitializeService()

from pyEngine import hostprofilemanager, compliancemanager, hostservices,\
   hpConfig

gGlobalHPELock = threading.Lock()

class HPESoapHandler(SoapHandler.SoapHandler):
   def HandleRequest(self, request, nsAndVersion=None):
      global gGlobalHPELock
      with gGlobalHPELock:
         return SoapHandler.SoapHandler.HandleRequest(self, request,
                                                      nsAndVersion)

def RegisterManagedObjects(vorb):
   """Registers Host Profile Engine components with the VORB server.
   """
   vorb.RegisterObject(hostprofilemanager.hostProfileManager)
   vorb.RegisterObject(compliancemanager.hostComplianceManager)

def setupService():
   PyVmomiServer.SetSoapHandlerCls(HPESoapHandler)
   config = hpConfig.HostProfilesConfig({'soapPort' : 8338})
   sys.argv.extend(['-P', config.soapPort, '-H', 'localhost'])

# Create VORB server
hostservices.log.debug('Starting to run VORB server for Host Profile Engine')
if serviceMgr.IsEnabled():
   setupService()
RunVmomiOrb(RegisterManagedObjects)
hostservices.log.info('Ran VORB server for Host Profile Engine')
