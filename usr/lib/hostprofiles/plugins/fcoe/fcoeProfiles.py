#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from .fcoeCatalogKeys import *
from .fcoeUtils import CmpVersion, ListFCoEAdapters, MacToAdapterMap,\
                      AdapterNameToDriverMap, RaiseLocalizedException,\
                      ActivateFCoEAdapter, DeactivateFCoEAdapter,\
                      FindDupMac, SearchStringKey
from .fcoePolicies import FCoEActivationPolicy, FCoEActivationByMACPolicyOption,\
                         FCoEActivationByDriverPolicyOption

from pluginApi import GenericProfile,  \
                      ProfileComplianceChecker, \
                      CreateLocalizedMessage, log, \
                      TASK_LIST_REQ_REBOOT, TASK_LIST_RES_OK

from pluginApi import CATEGORY_STORAGE, COMPONENT_FCOE

from pyEngine.policy import ExecuteError
from pyEngine import storageprofile

"""
               FCoE Profile Structure

+ StorageProfile
   + FCoEProfile
         + FCoEAdapterProfile
            + Activation Profile
                  + Profile 1
                          |__ FCoEActivationPolicy
                                    |__ FCoEActivationByDriverPolicyOption

                  + Profile 2
                          |__ FCoEActivationPolicy
                                    |__ FCoEActivationByMACPolicyOption

"""


FCoEProfileVersion = "1.0"


class FCoEProfile(GenericProfile):
   """A Host Profile that manages FCoE configuration
   """

   # FCoE Profile will just be have single instance
   singleton = True
   version = FCoEProfileVersion
   parentProfiles = [ storageprofile.StorageProfile ]

   category = CATEGORY_STORAGE
   component = COMPONENT_FCOE

   @classmethod
   def CheckVersion(cls, version):
      """Version verification for this profile
      """

      isCompatible = CmpVersion(version, cls.version)

      if (not isCompatible):
         log.error("Version mismatch for FCoEProfile %s != %s" % \
                  (version, cls.version))

      return isCompatible


class FCoEAdapterProfile(GenericProfile):
   """A Host Profile that manages FCoE adapter configuration
   """

   # This profile will just be have single instance
   singleton = True
   version = FCoEProfileVersion
   parentProfiles = [ FCoEProfile ]

   @classmethod
   def CheckVersion(cls, version):
      """Version verification for this profile
      """

      isCompatible = CmpVersion(version, cls.version)

      if (not isCompatible):
         log.error("Version mismatch for FCoEAdapterProfile %s != %s" % \
                  (version, cls.version))

      return isCompatible


   @classmethod
   def GatherData(cls, hostServices):
      """ Implements this interface for gathering data used by other interfaces.
      """

      fcoeAdapters = ListFCoEAdapters(hostServices)
      macAddrMap = MacToAdapterMap(fcoeAdapters)
      adapterToDriverMap = AdapterNameToDriverMap(hostServices)

      profileData = (fcoeAdapters, macAddrMap, adapterToDriverMap)

      return profileData


   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData, validationErrors):
      """Implementation of the GenericProfile.VerifyProfile(). Calls the individual
         profile to verify its instance profiles.
      """
      adapterActProfInstances = profileInstance.FCoEAdapterActivationProfile
      if adapterActProfInstances:
         FCoEAdapterActivationProfile.VerifyActProfiles(adapterActProfInstances,
                                     hostServices, profileData, validationErrors)

      return (len(validationErrors) == 0)            


class FCoEAdapterActivationProfile(GenericProfile):
   """A Host Profile that manages FCoE adapter instance configuration
   """

   singleton      = False
   policies       = [ FCoEActivationPolicy ]
   parentProfiles = [ FCoEAdapterProfile ]
   version        = FCoEProfileVersion
  
   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      """Implementation of the GenericProfile.GenerateProfileFromConfig()
         that populates adapter activation profile instances.
      """
      profileList = []

      # Get the list of fcoe adapters
      (fcoeAdapters, macAddrMap, driverMap)  = profileData

      log.info("GenerateProfileFromConfig(): Found %d fcoe adapters" %
               len(fcoeAdapters))

      i = 0

      for adapter in fcoeAdapters:

         # Initialize the default policy option based on mac address
         policyParams = [
            ('macAddr', adapter['Source MAC']),
            ('isActivated', adapter['Active']),
         ]

         i += 1

         # We use the mac address policy option as the default one
         polOpt = FCoEActivationByMACPolicyOption(policyParams)
         actPolicies = [ FCoEActivationPolicy(True, polOpt) ]
         profile = cls(policies=actPolicies)
         profileList.append(profile)

      log.info("Generated profile for %d fcoe adapters" % i)

      return profileList


   @classmethod
   def _GetActivationTask(cls, adapter, isActivated, driverMap):
      """returns the localized message, opaque data tuple for the operation to
         be performed
      """

      needReboot = False
      keyValDict = {
                     'Adapter'   : adapter['FCOE NIC Name'],
                     'Mac'       : adapter['Source MAC'],
                     'Driver'    : driverMap[adapter['FCOE NIC Name']],
                   }

      if adapter['Active']:   # Adapter is in active state already
         if not isActivated:
            # adapter is to be deactivated
            msg = CreateLocalizedMessage(None, FCoE_DEACTIVATE_KEY,
                                         keyValDict)
            dataObj = (FCoE_OP_DEACTIVATE, adapter)
            needReboot = True
            return msg, dataObj, needReboot
      else:                   # Adapter is not active
         if isActivated:
            # adapter is to be activated
            msg = CreateLocalizedMessage(None, FCoE_ACTIVATE_KEY,
                                         keyValDict)
            dataObj = (FCoE_OP_ACTIVATE, adapter)
            return msg, dataObj, needReboot

      # return None if there is no task to be done
      return None


   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      """Performs a diff between the data in the profileInstances and the
         config to determine which sets of parameters are different between
         the two.
      """
      needReboot = False

      # Check for duplicate mac address for this profile
      FCoEAdapterActivationProfile._VerifyDupMac(profileInstances, profileData,
                                                 None, True)
     
      (fcoeAdapters, macAddrMap, driverMap)  = profileData

      for inst in profileInstances:
         policyOpt = inst.FCoEActivationPolicy.policyOption

         if isinstance(policyOpt, FCoEActivationByMACPolicyOption):
            macAddr = policyOpt.macAddr

            tup = SearchStringKey(macAddrMap, macAddr)
            if tup:
               (mac, adapter) = tup

               #get localized message and opaque data
               val = cls._GetActivationTask(adapter, policyOpt.isActivated,
                                            driverMap)
               if (val):
                  (msg, dataObj, needReboot) = val
                  taskList.addTask(msg, dataObj)
            else:
               log.error("GenerateTaskList Failed: Adapter with mac address %s "
                         "not found" % macAddr)
               keyValDict = { 'Mac': macAddr }
               RaiseLocalizedException(
                     None, FCoE_NOADAP_FOR_MAC_FAIL_KEY, keyValDict)

         elif isinstance(policyOpt, FCoEActivationByDriverPolicyOption):
            driver = policyOpt.driverName
            hasOneMatch = False
            # For all these driver adapters create task
            for adapter in fcoeAdapters:
               if driver == driverMap[adapter['FCOE NIC Name']]:
                  hasOneMatch = True

                  val = cls._GetActivationTask(adapter, policyOpt.isActivated,
                                               driverMap)
                  if (val):
                     (msg, dataObj, needRebootForTask) = val
                     taskList.addTask(msg, dataObj)
                     if needRebootForTask:
                        needReboot = True

            if not hasOneMatch:
               log.error("GenerateTaskList Failed: No adapters for driver '%s' "
                         "found" % driver)
               keyValDict = { 'Driver' : driver }
               RaiseLocalizedException(
                     None, FCoE_NOADAP_FOR_DRIVER_EXISTS_KEY, keyValDict)

      if needReboot:
         return TASK_LIST_REQ_REBOOT

      return TASK_LIST_RES_OK


   @classmethod
   def RemediateConfig(cls, taskList, hostServices, profileData):
      """Implementation of remediate config that takes the supplied task list
         and activates/deactivates the fcoe adapter
      """
      mgr = hostServices.hostSystemService

      for taskOp, adapter in taskList:
         if taskOp == FCoE_OP_ACTIVATE:
            ActivateFCoEAdapter(hostServices, adapter['FCOE NIC Name'])
         elif taskOp == FCoE_OP_DEACTIVATE:
            DeactivateFCoEAdapter(hostServices, adapter['FCOE NIC Name'])
         else:
            log.error("Remediate Failed: Invalid operation for FCoE Profile "
                      "update %s: %s" % (taskOp,adapter['FCOE NIC Name']))
            keyValDict = { 'Op' : taskOp,
                           'Mac' : adapter['Source MAC'],
                           'Adapter' : adapter['FCOE NIC Name']
                         }
            RaiseLocalizedException(
                  None, FCoE_REMEDIATE_INVALID_OP_KEY, keyValDict)

      log.info("Remediate task complete")


   @staticmethod
   def _GetAdaptersForDriver(profileData, driverName):
      """
         Gets a list of fcoe adapters for the specific driver name
      """

      foundAdapters = []

      (fcoeAdapters, macAddrMap, driverMap)  = profileData

      for adapter in fcoeAdapters:
         if driverName == driverMap[adapter['FCOE NIC Name']]:
            foundAdapters.append(adapter)

      return foundAdapters


   @staticmethod
   def _GetSuppliedMacAddr(profileInstances, profileData):
      """Utility method to get all the user supplied mac addresses
      """

      macsSupplied = {}
      foundMacs = []

      for inst in profileInstances:
         assert isinstance(inst, FCoEAdapterActivationProfile)

         policyOpt = inst.FCoEActivationPolicy.policyOption

         if isinstance(policyOpt, FCoEActivationByMACPolicyOption):
            if policyOpt.macAddr:
               foundMacs.append(policyOpt.macAddr)
         elif isinstance(policyOpt, FCoEActivationByDriverPolicyOption):
            driverName = policyOpt.driverName

            foundAdapters = FCoEAdapterActivationProfile._GetAdaptersForDriver(
                                                       profileData, driverName)

            for adapter in foundAdapters:
               foundMacs.append(adapter['Source MAC'])

      # Now maintain a count of duplicate macs
      for mac in foundMacs:
         if SearchStringKey(macsSupplied, mac):
            macsSupplied[mac] += 1
         else:
            macsSupplied[mac] = 1
      
      return macsSupplied
 


   @staticmethod
   def _VerifyDupMac(profileInstances, profileData, validationErrors, canRaise):
      """Method to detect duplicate mac address values entered by user
      """

      (fcoeAdapters, macAddrMap, driverMap)  = profileData

      macsSupplied = FCoEAdapterActivationProfile._GetSuppliedMacAddr(
                                        profileInstances, profileData)

      dupMac =  FindDupMac(macsSupplied)
      if dupMac:
         tup = SearchStringKey(macAddrMap, dupMac)
         if tup:
            (mac, adap) = tup
            keyValDict = {
                           'Adapter'   : adap['FCOE NIC Name'],
                           'Mac'       : adap['Source MAC'],
                         }

            msg = CreateLocalizedMessage(
                     None, FCoE_DUP_MAC_ADDR_FOR_ACTIVATION_KEY, keyValDict)

            log.error("_VerifyDupMac: Found DUP mac = '%s'" % dupMac)
            if canRaise:
               RaiseLocalizedException(
                     None, FCoE_DUP_MAC_ADDR_FOR_ACTIVATION_KEY, keyValDict)
            else:
               validationErrors.append(msg)


   @staticmethod
   def _VerifyEmptyMacProfiles(profileInstances, hostServices, profileData,
                               validationErrors):
      """Method to fill in empty mac userinput required fields
      """

      (fcoeAdapters, macAddrMap, driverMap)  = profileData

      macsSupplied = FCoEAdapterActivationProfile._GetSuppliedMacAddr(
                                        profileInstances, profileData)

      for inst in profileInstances:
         assert isinstance(inst, FCoEAdapterActivationProfile)

         policyOpt = inst.FCoEActivationPolicy.policyOption

         # if the profile instance needs to be filled in automatically
         if isinstance(policyOpt, FCoEActivationByMACPolicyOption) and not policyOpt.macAddr:
       
            # Get a fcoe mac that is not added by the user     
            for adapter in fcoeAdapters:
               mac = adapter['Source MAC']
               isActivated =  adapter['Active']

               if not SearchStringKey(macsSupplied, mac):
                  policyOpt.macAddr = mac
                  policyOpt.isActivated = isActivated
                  macsSupplied[mac] = 1
                  log.info("_VerifyEmptyMacProfiles: Filled in mac = '%s' act = %s"
                      % (mac, isActivated))
                  break

      
   @staticmethod
   def VerifyActProfiles(profileInstances, hostServices, profileData,
                          validationErrors):
      """Verify if the FCoE activation profiles are well formed.
         This method does 2 things,
         - Check for any duplicate mac address entered by the user
         - Fill in empty mac userinput required fields with
           system found mac addresses.
      """

      assert profileInstances

      # 1. Check for duplicate mac address across profile instances
      FCoEAdapterActivationProfile._VerifyDupMac(profileInstances, profileData,
                                                 validationErrors, False)

      # 2. Check for any empty mac input required fields to fill up with
      #    default values
      FCoEAdapterActivationProfile._VerifyEmptyMacProfiles(profileInstances,
                                hostServices, profileData, validationErrors)

   
   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData, validationErrors):
      """Implementation of the GenericProfile.VerifyProfile() for verifying per
         activation profile instance.
      """

      # 1. Verify if the driver name is valid
      FCoEAdapterActivationProfile._VerifyValidDriver( profileInstance,
                                   hostServices, profileData, validationErrors)

      # 2. Verify if the mac address is valid
      FCoEAdapterActivationProfile._VerifyValidMac( profileInstance,
                                   hostServices, profileData, validationErrors)

      return (len(validationErrors) == 0)            


   @staticmethod
   def _VerifyValidDriver(profileInstance, hostServices, profileData,
                          validationErrors):
      """Verify if the user supplied driver name in the profile instance is valid
      """
   
      policyOpt = profileInstance.FCoEActivationPolicy.policyOption

      if isinstance(policyOpt, FCoEActivationByDriverPolicyOption):
         foundAdapters = []
         driverName = policyOpt.driverName
         foundAdapters = FCoEAdapterActivationProfile._GetAdaptersForDriver(
                                                       profileData, driverName)

         if len(foundAdapters) == 0: 
            log.error("_VerifyValidDriver: No adapters for driver '%s' found"
                      % driverName)
            keyValDict = { 'Driver' : driverName }
            msg = CreateLocalizedMessage(
                     None, FCoE_NOADAP_FOR_DRIVER_EXISTS_KEY, keyValDict)
            validationErrors.append(msg)


   @staticmethod
   def _VerifyValidMac(profileInstance, hostServices, profileData,
                       validationErrors):
      """Verify if the user supplied mac in the profile instance is valid
      """
      (fcoeAdapters, macAddrMap, driverMap)  = profileData
      policyOpt = profileInstance.FCoEActivationPolicy.policyOption

      if isinstance(policyOpt, FCoEActivationByMACPolicyOption) and policyOpt.macAddr:
         tup = SearchStringKey(macAddrMap, policyOpt.macAddr)
         if not tup:
            log.error("_VerifyValidMac: Adapter with mac address %s not found"
                      % policyOpt.macAddr)
            keyValDict = { 'Mac': policyOpt.macAddr }
            msg = CreateLocalizedMessage(
                     None, FCoE_NOADAP_FOR_MAC_FAIL_KEY, keyValDict)
            validationErrors.append(msg)
         else:
            (mac, adap) = tup
            policyOpt.macAddr = mac


   @classmethod
   def CheckVersion(cls, version):
      """Version verification for this profile
      """

      isCompatible = CmpVersion(version, cls.version)

      if (not isCompatible):
         log.error("Version mismatch for FCoEAdapterActivationProfile %s != %s" % \
                  (version, cls.version))

      return isCompatible
