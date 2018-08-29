#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

import re

from .fcoeCatalogKeys import *
from .fcoeUtils import ListFCoEAdapters, AdapterNameToDriverMap

from pluginApi import Policy, UserInputRequiredOption, FixedPolicyOption, \
                      ParameterMetadata, PolicyOptComplianceChecker, \
                      CreateLocalizedMessage, log
from pluginApi import CreateComplianceFailureValues, PARAM_NAME, MESSAGE_KEY

BoolToActiveMap = {
                     True : 'Active',
                     False : 'Disabled'
                  }

class FCoEActivationByMacPolOptChecker(PolicyOptComplianceChecker):
   """A compliance checker type for FCoE "ActivationByMac" policy option.
   """

   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the FCoE adapter activation described by the policy option's
         parameters are valid.
      """

      msgList = []

      # Mac address whose compliance needs to be verified
      keyValDict = {}
      keyValDict['Mac'] = mac = policyOpt.macAddr

      fcoeAdapters = ListFCoEAdapters(hostServices)

      # If mac address is found then compare if the adapter active/deactivated
      # state matches with what is present in the system
      for adapter in fcoeAdapters:
         nicName      = adapter['FCOE NIC Name']
         activeStatus = adapter['Active']

         if adapter['Source MAC'].lower() != mac.lower():
            continue

         keyValDict['Adapter'] = nicName

         # Check for compliance, then return with the result
         if not policyOpt.isActivated == activeStatus:
            keyValDict['CurrActiveStatus'] = BoolToActiveMap[activeStatus]
            keyValDict['ProfActiveStatus'] = BoolToActiveMap[policyOpt.isActivated]
            msg = CreateLocalizedMessage(None, FCoE_ADAPFAIL_KEY,
                                         keyValDict)
            comparisonValues = CreateComplianceFailureValues('isActivated',
               PARAM_NAME, profileValue = policyOpt.isActivated,
               hostValue = activeStatus, profileInstance = nicName)
            msgList.append((msg, [comparisonValues]))
            log.error("ActivateByMacPolicy Compliance failed for "
                      "[adapter:%s mac:%s] -> curr=%s req=%s" % \
                      (nicName, mac, BoolToActiveMap[activeStatus], \
                       BoolToActiveMap[policyOpt.isActivated]) \
                     )
         isCompliant = (len(msgList) == 0)
         # returns (True, []) if there was no compliance failure
         return (isCompliant, msgList)

      # end for adapter

      # If code is reached here then it implies no adapter with such mac
      # address exists
      keyValDict = { 'Mac': mac }

      log.error("ActivateByMacPolicy Compliance failed: No adapter with "
                "mac address: %s found" % mac)
      msg = CreateLocalizedMessage(None,
              FCoE_NOADAP_FOR_MAC_FAIL_KEY,
              keyValDict)
      msgKey = "com.vmware.vim.profile.Profile.fcoe.fcoeProfiles.FCoEAdapterActivationProfile.label"
      comparisonValues = CreateComplianceFailureValues(msgKey,
         MESSAGE_KEY, profileValue = policyOpt.macAddr, hostValue = '')
      msgList.append((msg, [comparisonValues]))

      isCompliant = (len(msgList) == 0)

      return (isCompliant, msgList)


class FCoEActivationByDriverPolOptChecker(PolicyOptComplianceChecker):
   """A compliance checker type for FCoE "ActivationByDriver" policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the FCoE adapter activation described by the policy option's
         parameters are valid.
      """

      fcoeAdapters = ListFCoEAdapters(hostServices)
      driverMap = AdapterNameToDriverMap(hostServices)

      msgList = []

      keyValDict = {}
      keyValDict['Driver'] = driver = policyOpt.driverName

      found = False

      # Loop through fcoe adapters for matching MAC
      for adapter in fcoeAdapters:
         nicName = adapter['FCOE NIC Name']
         mac = adapter['Source MAC']

         keyValDict['Adapter'] = nicName
         keyValDict['Mac']     = mac

         if driver == driverMap[nicName]:
            activeStatus = adapter['Active']
            found = True

            if not policyOpt.isActivated == activeStatus:
               keyValDict['CurrActiveStatus'] = BoolToActiveMap[activeStatus]
               keyValDict['ProfActiveStatus'] =  BoolToActiveMap[policyOpt.isActivated]
               msg = CreateLocalizedMessage(None, FCoE_ADAPFAIL_KEY,
                                            keyValDict)
               comparisonValues = CreateComplianceFailureValues('isActivated',
                 PARAM_NAME, profileValue = policyOpt.isActivated,
                 hostValue = activeStatus, profileInstance = nicName)
               msgList.append((msg, [comparisonValues]))
               log.error("ActivateByDriver Policy Compliance failed for "
                         "[adapter:%s driver:%s mac:%s] -> curr=%s req=%s" % \
                        (nicName, driver, mac, BoolToActiveMap[activeStatus], \
                         BoolToActiveMap[policyOpt.isActivated]) \
                        )

      # end for adapter

      # If no adapter exists for that driver
      if (not found):
         keyValDict = { 'Driver' : driver }
         log.error("ActivateByDriver Policy Compliance failed as no adapter "
                   "exists for driver:%s" % driver)

         msg = CreateLocalizedMessage(None,
                  FCoE_NOADAP_FOR_DRIVER_EXISTS_KEY,
                  keyValDict)
         msgKey = "com.vmware.vim.profile.Profile.fcoe.fcoeProfiles.FCoEAdapterActivationProfile.label"
         comparisonValues = CreateComplianceFailureValues(msgKey,
            MESSAGE_KEY, profileValue = policyOpt.driverName, hostValue = '')
         msgList.append((msg, [comparisonValues]))


      isCompliant = (len(msgList) == 0)

      # returns (True, []) if there was no compliance failure
      return (isCompliant, msgList)


class FCoEActivationByDriverPolicyOption(FixedPolicyOption):
   """Policy Option type for configuring fcoe activation using driver name
   """
   paramMeta = [
                  ParameterMetadata('driverName', 'string', False, ''),
                  ParameterMetadata('isActivated', 'bool', False, False)
               ]

   complianceChecker = FCoEActivationByDriverPolOptChecker



class FCoEMacValidator():
   """Mac parameter validator
   """

   @classmethod
   def Validate(cls, policyOpt, name, value, errors):
      """Implements the Validate method for Validator for verifying the MAC
         address
      """

      # regex to validate mac address
      if value and re.match("([0-9a-f]{2}:){5}([0-9a-f]{2})", value.lower()):
         return True
      else:
         keyValDict = { 'Mac': value }
         msg = CreateLocalizedMessage(None, FCoE_INVALID_MAC_ADDRESS_KEY,
                                      keyValDict)
         errors.append(msg)
         return False



class FCoEActivationByMACPolicyOption(UserInputRequiredOption):
   """Policy Option type for configuring fcoe activation using mac address
   """

   paramMeta = []
   userInputParamMeta = [
                          ParameterMetadata('macAddr', 'string', False, '',
                                            FCoEMacValidator()),
                          ParameterMetadata('isActivated', 'bool', False, False)
                        ]

   complianceChecker = FCoEActivationByMacPolOptChecker



class FCoEActivationPolicy(Policy):
   """Define a policy for the FCoE adapter activation.
   """

   possibleOptions = [
                       FCoEActivationByMACPolicyOption,
                       FCoEActivationByDriverPolicyOption
                     ]

