#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import log, CreateLocalizedException
from .fcoeCatalogKeys import *


def RaiseLocalizedException(obj, str, keyValDict):
   """Util method to raise an exception by creating a localized message
   """

   fault = CreateLocalizedException(obj, str, keyValDict)
   raise fault


def MacToAdapterMap(fcoeAdapters):
   """Create a map of mac addr to adapter info using the list of fcoe
      adapters
   """
   dictObj = {}

   log.debug("Mapping mac addr for %d adapters" % len(fcoeAdapters))

   for adapter in fcoeAdapters:
      macAddr = adapter['Source MAC']
      dictObj[macAddr] = adapter

   return dictObj


def AdapterNameToDriverMap(hostServices):
   """Create a map of adapter names to driver names
   """
   dictObj = {}
   nicInfoList = ListNicInfo(hostServices)

   for nic in nicInfoList:
      dictObj[nic['Name']] = nic['Driver']

   return dictObj


def ListFCoEAdapters(hostServices):
   """Internal method that will invoke esxcli to get the list of FCoE
      Adapters.
   """

   # Get list of fcoe capable adapters
   cliNamespace, cliApp, cliOp = 'fcoe', 'nic', 'list'
   status, output = hostServices.ExecuteEsxcli(cliNamespace, cliApp, cliOp)
   if status != 0:
      log.info('Failed to execute "esxcli fcoe nic list" ' + \
         'command. Status = %d, Error = %s' % (status, output))
      keyValDict = {
                    'Status'  : status,
                    'Message' : output
                   }
      RaiseLocalizedException(None, FCoE_ESXCLI_EXECUTE_FAIL_KEY,
                                  keyValDict)

   return output


def ListNicInfo(hostServices):

   """Internal method that will invoke esxcli to get the list of Nic Info.
   """

   # Get list of fcoe capable adapters
   cliNamespace, cliApp, cliOp = 'network', 'nic', 'list'
   status, output = hostServices.ExecuteEsxcli(cliNamespace, cliApp, cliOp)
   if status != 0:
      log.error('Failed to execute "esxcli network nic list" ' + \
         'command. Status = %d, Error = %s' % (status, output))
      keyValDict = {
                    'Status'  : status,
                    'Message' : output
                   }
      RaiseLocalizedException(None, FCoE_ESXCLI_EXECUTE_FAIL_KEY,
                                  keyValDict)

   return output


def ActivateFCoEAdapter(hostServices, vmnicName):
   """Internal method that will invoke esxcli to activae a FCoE Adapter
   """

   # Initiate a discover operation on a nic
   cliNamespace, cliApp, cliOp = 'fcoe', 'nic', 'discover'
   optionStr = '--nic-name %s' % vmnicName
   status, output = hostServices.ExecuteEsxcli(cliNamespace, cliApp, cliOp,
                                               optionStr)
   if status:
      log.error('Failed to execute "esxcli fcoe nic discover ' + \
                '%s". Status = %d, Error = %s.' % \
                   (optionStr, status, output))
      keyValDict = {
                    'Status'  : status,
                    'Message' : output
                   }
      RaiseLocalizedException(None, FCoE_ESXCLI_EXECUTE_FAIL_KEY,
                                  keyValDict)
   else:
      log.info('Activation succeeded for adapter %s. Discovery Enabled.' \
              % vmnicName)


def DeactivateFCoEAdapter(hostServices, vmnicName):
   """Internal method that will invoke esxcli to remove a NFS datastore from
      the system.
   """

   cliNamespace, cliApp, cliOp = 'fcoe', 'nic', 'disable'
   optionStr = '--nic-name %s' % vmnicName
   status, output = hostServices.ExecuteEsxcli(cliNamespace, cliApp, cliOp,
                                               optionStr)
   if status:
      log.error('Failed to execute "esxcli fcoe nic disable ' + \
                '%s". Status = %d, Error = %s.' % \
                   (optionStr, status, output))
      keyValDict = {
                    'Status'  : status,
                    'Message' : output
                   }
      RaiseLocalizedException(None, FCoE_ESXCLI_EXECUTE_FAIL_KEY,
                                  keyValDict)
   else:
      log.info('De-activation succeeded for adapter %s. Discovery disabled.' \
              % vmnicName)


def FindDupMac(macsSupplied):
   """ Util for finding a dup mac.
   """

   for mac in macsSupplied.keys():
      count = macsSupplied[mac]
      if count > 1:
         return mac

   return None


def SearchStringKey(dictObj, s):
   """ Util for performing a case insensitive search of dict string key
   """
   for str in dictObj.keys():
      if str.lower() == s.lower():
         return (str, dictObj[str])

   return None


def CmpVersion(ver1, ver2):
   """Version check algorithm for FCoE related profiles
   """
  
   (major1, minor1) = ver1.split('.')
   (major2, minor2) = ver2.split('.')

   return int(major2) == int(major1)

