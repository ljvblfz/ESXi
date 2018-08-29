#!/usr/bin/python
# **********************************************************
# Copyright 2012-2017 VMware, Inc.  All rights reserved.
# -- VMware Confidential
# **********************************************************

from pluginApi import GenericProfile
from pluginApi import FixedPolicyOption
from pluginApi import Policy
from pluginApi import log
from pluginApi import ParameterMetadata
from pluginApi import CreateLocalizedMessage
from pluginApi import CreateLocalizedException
from pluginApi import ProfileComplianceChecker
from pluginApi import ApplyFailure
from pluginApi import TASK_LIST_RES_OK
from pluginApi import TASK_LIST_REQ_REBOOT
from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING
from pluginApi import COMPONENT_DEVICE_ALIAS_CONFIG
from pluginApi import CreateComplianceFailureValues
from pluginApi import PARAM_NAME
from pluginApi import MESSAGE_KEY

import re

def makeErrorPath(error):
   return '%s.%s' % ('com.vmware.profile.DeviceAlias', error)

DEVICE_ALIAS_DUPLICATE         = makeErrorPath('AliasDuplicate')
DEVICE_ALIAS_INVALID           = makeErrorPath('AliasInvalid')
DEVICE_ALIAS_UNDEFINED_IN_HOST = makeErrorPath('AliasUndefinedInHost')
DEVICE_BUS_ADDRESS_INVALID     = makeErrorPath('BusAddressInvalid')
DEVICE_BUS_TYPE_INVALID        = makeErrorPath('BusTypeInvalid')
DEVICE_COUNT_SHORT_ON_HOST     = makeErrorPath('CountShortOnHost')
DEVICE_DIFFERENT_ALIAS         = makeErrorPath('DifferentAlias')
DEVICE_DO_SET_ALIAS            = makeErrorPath('DoSetAlias')
DEVICE_DUPLICATE               = makeErrorPath('Duplicate')
DEVICE_ESXCLI_RESET_FAIL       = makeErrorPath('EsxcliResetFail')
DEVICE_ESXCLI_LIST_FAIL        = makeErrorPath('EsxcliListFail')
DEVICE_ESXCLI_SET_FAIL         = makeErrorPath('EsxcliSetFail')
DEVICE_MISSING_FROM_HOST       = makeErrorPath('MissingFromHost')
DEVICE_MISSING_FROM_PCI_SLOT   = makeErrorPath('MissingFromPciSLot')
DEVICE_MISSING_FROM_PCI_INTEG  = makeErrorPath('MissingFromHostPciInteg')

DEVICE_ALIAS_MESSAGE_KEY = "com.vmware.vim.profile.Profile.deviceAlias.deviceAlias.DeviceAliasProfile.label"

#
# Some useful constants for this plugin.
#
_BUSTYPE    = 'BusType'
_BUSADDRESS = 'BusAddress'
_ALIAS      = 'Alias'
_PARAMID    = '__paramId__'

#
# Some useful regular expressions for verification.
#
_aliasRoots          = ("vmgfx", "vmhba", "vmnic", "vmrdma")
_joinedAliasRoots    = '|'.join(_aliasRoots)
_validAlias          = r"\A(?P<aliasRoot>(%s))(?P<aliasNum>(0|[1-9][0-9]*))\Z" \
                       % _joinedAliasRoots
_aliasRegex          = re.compile(_validAlias)

_validPciBusAddr     = r"\A[mps][a-f0-9:.]+\Z"
_validPciRegex       = re.compile(_validPciBusAddr)

_logicalBusPrefix    = r"\A(?P<prefix>(logical#|pci#)+)"
_logicalBusSuffix    = r"(?P<suffix>((#([^#]+[0-9]+|0|[1-9][0-9]*))+))\Z"
_validLogicalBusAddr = _logicalBusPrefix + r"[^#\t\r\n /\"']+" \
                       + _logicalBusSuffix
_validLogicalRegex   = re.compile(_validLogicalBusAddr)

_char                = r"[^#]"
_separatorRegex      = re.compile(_char)

_logicalSbdf         = r"(\A|#)pci#p[a-f0-9:.]+(#|\Z)"
_logicalSbdfRegex    = re.compile(_logicalSbdf)

_slotPattern         = r"\As(?P<slot>[0-9a-f]+)[.:]"
_slotRegex           = re.compile(_slotPattern)

#
# Formulate a regex to search for software devices (aka pseudo-hw devices),
# which are under either the vmkernel device root or the swdevroot.
#   Old <phdCoreAddr>:  "logical#vmkernel#<devID>".
#   New <phdCoreAddr>:  "logical#swdevroot#<devID>".
# The search will find either an exact match for <phdCoreAddr> or
# the portion of a derived address, e.g logical#<phdCoreAddr>#<number>.
#
# XXX: PR 1645537
# This pattern is cloned from the Logical Bus plugin to the vmkdevmgr.
# See phdRegex_ in:
#       bora/lib/vmkctl/drivers/plugins/logical/LogicalBus.cpp.
#
_coreAddressPrefix   = r"(\A|#)"
_CorePdAddress       = r"(logical#(vmkernel|swdevroot)#[^#]+[0-9]+)"
_coreAddressSuffix   = r"(#[0-9]|\z)"
_phdRegex            = re.compile(_coreAddressPrefix + _CorePdAddress +
                                  _coreAddressSuffix)

class DeviceAliasPolicyOption(FixedPolicyOption):
   """ Policy Option type containing the rule configuration.
   """
   paramMeta = [ ParameterMetadata(_BUSTYPE, 'string', False),
                 ParameterMetadata(_BUSADDRESS, 'string', False),
                 ParameterMetadata(_ALIAS, 'string', False) ]


class DeviceAliasPolicy(Policy):
   """ Define a policy for the device alias rule.
   """
   possibleOptions = [ DeviceAliasPolicyOption ]


def _GetProfileInst(profInst):
   """ Helper method that returns the info inside a device alias profile
   instance.
   """
   params = profInst.policies[0].policyOption.paramValue
   busType = busAddress = alias = None
   for key, value in params:
      if key == _BUSTYPE:
         busType = value
      elif key == _BUSADDRESS:
         busAddress = value
      elif key == _ALIAS:
         alias = value
   return (busType, busAddress, alias)

def _ParseAlias(alias):
   """ Helper method to return the aliasRoot and aliasNumber from an alias.
   """
   msg = None
   m = _aliasRegex.match(alias)
   if m:
      aliasRoot = m.group('aliasRoot')
      aliasNum = m.group('aliasNum')
   else:
      errDict = { _ALIAS : alias,
                  _PARAMID : _ALIAS }
      msg = _CreateLocalizedMessage(None, DEVICE_ALIAS_INVALID, errDict)
      alias = None
      aliasNum = None
      aliasRoot = None
   return (aliasRoot, aliasNum, msg)

def _ValidateBusAddress(busType, busAddress):
   """ Helper method to determine if a busAddress is valid.
   """
   rslt = True
   msg = None
   errDict = { _BUSTYPE : busType,
               _BUSADDRESS : busAddress }
   if busType == "pci":
      if not _validPciRegex.match(busAddress):
         errDict[_PARAMID] = _BUSADDRESS
         msg = _CreateLocalizedMessage(None, DEVICE_BUS_ADDRESS_INVALID,
                                       errDict)
         rslt = False
   elif busType == "logical":
      validated = False
      m = _validLogicalRegex.match(busAddress)
      if m:
         # prefix and suffix must have the same number of '#' characters
         prefix = _separatorRegex.sub('', m.group('prefix'))
         suffix = _separatorRegex.sub('', m.group('suffix'))
         validated = (prefix == suffix)
      if not validated:
         errDict[_PARAMID] = _BUSADDRESS
         msg = _CreateLocalizedMessage(None, DEVICE_BUS_ADDRESS_INVALID,
                                       errDict)
         rslt = False
   else:
      errDict[_PARAMID] = _BUSTYPE
      msg = _CreateLocalizedMessage(None, DEVICE_BUS_TYPE_INVALID, errDict)
      rslt = False
   return (rslt, msg)

def _GetSlot(busAddress):
   """ Helper method to return the slot number form a PCI bus address.
   """
   slot = None
   m = _slotRegex.match(busAddress)
   if m:
      slotNo = m.group('slot')
      slot = "%d" % (int(slotNo, 16))
   return slot

def _EvaluateCompliance(profiles, hostGatheredData):
   """ Helper method that evaluates the compliance of this host with respect to
   the profiles.
   
   Returns a pair of lists: (complianceFailures, faultList)

      complianceFailures -- a list of localized messages and/or pairs
                            (localized message, [compliance objects, ...])
      faultList          -- a list of localized exceptions representing PCI
                            hardware differences that cannot be remediated in
                            software
   """

   #
   # Gather this hosts's alias information into tables
   #
   #   We record the SBDF based pci busAddress by aliasRoot
   #   in sbdfAliasesHost to verify per-aliasRoot SBDF ordering.
   #
   pciAliases = set()
   logicalAliases = set()
   pciMappingHost = {}
   logicalMappingHost = {}
   sbdfAliasesHost = {}
   sbdfAliasesProfile = {}
   for aliasRoot in _aliasRoots:
      pciMappingHost[aliasRoot] = {}
      logicalMappingHost[aliasRoot] = {}
      sbdfAliasesHost[aliasRoot] = {}
      sbdfAliasesProfile[aliasRoot] = {}

   for entry in hostGatheredData:
      busType, busAddress, alias = entry
      aliasRoot, aliasNum, msg = _ParseAlias(alias)
      if not aliasRoot:
         log.error("invalid alias %s found on host" % alias)
         continue
      rslt, msg = _ValidateBusAddress(busType, busAddress)
      if not rslt:
         log.error("invalid (busType, busAddress) (%s, %s) found on host" %
                   (busType, busAddress))
         continue
      if busType == "pci":
         pciAliases.add(alias)
         if busAddress[0] == 'p':
            sbdfAliasesHost[aliasRoot][busAddress] = alias
         else:
            pciMappingHost[aliasRoot][busAddress] = alias
      elif busType == "logical":
         logicalAliases.add(alias)
         logicalMappingHost[aliasRoot][busAddress] = alias

   #
   # Now check the profile
   #
   complianceFailures = []
   faultList = []
   for profInst in profiles:
      busType, busAddress, alias =  _GetProfileInst(profInst)
      profileInstance = "%s:%s:%s" % (busType, busAddress, alias)
      msgData = { _BUSTYPE : busType,
                  _BUSADDRESS : busAddress,
                  _ALIAS : alias}
      aliasRoot, aliasNum, msg = _ParseAlias(alias)
      if not aliasRoot:
         invalidName = CreateComplianceFailureValues(
                          DEVICE_ALIAS_MESSAGE_KEY,
                          MESSAGE_KEY,
                          profileValue = aliasRoot,
                          hostValue = '')
         complianceFailures.append((msg, [invalidName]))
         fault = CreateLocalizedException(None, DEVICE_ALIAS_INVALID, msgData)
         faultList.append(fault)
         continue

      msgData['AliasRoot'] = aliasRoot
      rslt, msg = _ValidateBusAddress(busType, busAddress)
      if not rslt:
         invalidName = CreateComplianceFailureValues(
                          DEVICE_ALIAS_MESSAGE_KEY,
                          MESSAGE_KEY,
                          profileValue = busAddress,
                          hostValue = '')
         complianceFailures.append((msg, [invalidName]))
         fault = CreateLocalizedException(None, DEVICE_BUS_ADDRESS_INVALID,
                                          msgData)
         faultList.append(fault)
         continue

      if busType == "pci":
         # alias missing from host?
         if not alias in pciAliases:
            msgData[_PARAMID] = _ALIAS
            msg = _CreateLocalizedMessage(None, DEVICE_ALIAS_UNDEFINED_IN_HOST,
                                          msgData)
            aliasUndefined = CreateComplianceFailureValues(
                                DEVICE_ALIAS_MESSAGE_KEY,
                                MESSAGE_KEY,
                                profileValue = alias,
                                hostValue = '')
            complianceFailures.append((msg, [aliasUndefined]))
         if busAddress[0] == 'p':
            sbdfAliasesProfile[aliasRoot][busAddress] = alias
         else:
            # device missing?
            if busAddress not in pciMappingHost[aliasRoot]:
               slot = _GetSlot(busAddress)
               if slot:
                  msgData['Slot'] = slot
                  key = DEVICE_MISSING_FROM_PCI_SLOT
               else:
                  key = DEVICE_MISSING_FROM_PCI_INTEG
               msgData[_PARAMID] = _BUSADDRESS
               msg = _CreateLocalizedMessage(None, key, msgData)
               missingDevice = CreateComplianceFailureValues(
                                  DEVICE_ALIAS_MESSAGE_KEY,
                                  MESSAGE_KEY,
                                  profileValue = busAddress,
                                  hostValue = '')
               complianceFailures.append((msg, [missingDevice]))
               fault = CreateLocalizedException(None, key, msgData)
               faultList.append(fault)
               continue

            # wrong alias for this device?
            hostAlias = pciMappingHost[aliasRoot][busAddress]
            if hostAlias != alias:
               msgData['ProfileAlias'] = alias
               msgData['Alias'] = hostAlias
               msgData[_PARAMID] = _ALIAS
               msg = _CreateLocalizedMessage(None, DEVICE_DIFFERENT_ALIAS,
                                             msgData)
               wrongAlias = CreateComplianceFailureValues(
                               _ALIAS,
                               PARAM_NAME,
                               profileValue = alias,
                               hostValue = hostAlias,
                               profileInstance = profileInstance)
               complianceFailures.append((msg, [wrongAlias]))

      elif busType == "logical":
         if not alias in logicalAliases:
            msgData[_PARAMID] = _ALIAS
            msg = _CreateLocalizedMessage(None, DEVICE_ALIAS_UNDEFINED_IN_HOST,
                                          msgData)
            aliasUndefined = CreateComplianceFailureValues(
                                DEVICE_ALIAS_MESSAGE_KEY,
                                MESSAGE_KEY,
                                profileValue = alias,
                                hostValue = '')
            complianceFailures.append((msg, [aliasUndefined]))

         # device missing?
         if not _logicalSbdfRegex.match(busAddress):
            #
            # logical device missing?
            #
            #   Don't raise a fault for this during task list generation
            #   because logical devices are software constructs which might
            #   come into existence due to other changes in the system
            #   (possibly due to changes in the host profile document).  If a
            #   missing logical device does not appear after the reboot, then
            #   the system will stay out of compliance.
            #
            if busAddress not in logicalMappingHost[aliasRoot]:
               msgData[_PARAMID] = _BUSADDRESS
               msg = _CreateLocalizedMessage(None, DEVICE_MISSING_FROM_HOST,
                                             msgData)
               missingDevice = CreateComplianceFailureValues(
                                  DEVICE_ALIAS_MESSAGE_KEY,
                                  MESSAGE_KEY,
                                  profileValue = busAddress,
                                  hostValue = '')
               complianceFailures.append((msg, [missingDevice]))
               continue

            # wrong alias for this device?
            hostAlias = logicalMappingHost[aliasRoot][busAddress]
            if hostAlias != alias:
               msgData['ProfileAlias'] = alias
               msgData['Alias'] = hostAlias
               msgData[_PARAMID] = _ALIAS
               msg = _CreateLocalizedMessage(None, DEVICE_DIFFERENT_ALIAS,
                                             msgData)
               wrongAlias = CreateComplianceFailureValues(
                               _ALIAS,
                               PARAM_NAME,
                               profileValue = alias,
                               hostValue = hostAlias,
                               profileInstance = profileInstance)
               complianceFailures.append((msg, [wrongAlias]))

   #
   # For each aliasRoot type, sort the list of pci sbdf busAddress.
   # Then compare the aliases from each of the lists to find any possible
   # mistmatching aliases.
   #
   for aliasRoot in _aliasRoots:
      fromHost = sbdfAliasesHost[aliasRoot]
      fromProf = sbdfAliasesProfile[aliasRoot]
      fromHostBusAddrs = sorted(fromHost.keys())
      fromProfBusAddrs = sorted(fromProf.keys())
      for i in range(min(len(fromHostBusAddrs), len(fromProfBusAddrs))):
         hostAlias = fromHost[fromHostBusAddrs[i]]
         profAlias = fromProf[fromProfBusAddrs[i]]
         if hostAlias != profAlias:
            msgData = { _BUSTYPE : 'pci',
                        _BUSADDRESS : fromHostBusAddrs[i],
                        _ALIAS : hostAlias,
                        'ProfileAlias' : profAlias }
            msg = _CreateLocalizedMessage(None, DEVICE_DIFFERENT_ALIAS, msgData)
            wrongAlias = CreateComplianceFailureValues(
                            _ALIAS,
                            PARAM_NAME,
                            profileValue = profAlias,
                            hostValue = hostAlias,
                            profileInstance = fromProfBusAddrs[i])
            complianceFailures.append((msg, [wrongAlias]))
      if len(fromProfBusAddrs) > len(fromHostBusAddrs):
         short = len(fromProfBusAddrs) - len(fromHostBusAddrs)
         msgData = { 'AliasRoot' : aliasRoot,
                     'Short' : '%d' % short,
                     _PARAMID : 'AliasRoot' }
         msg = _CreateLocalizedMessage(None, DEVICE_COUNT_SHORT_ON_HOST,
                                       msgData)
         complianceFailures.append(msg)
         fault = CreateLocalizedException(None, DEVICE_COUNT_SHORT_ON_HOST,
                                          msgData)
         faultList.append(fault)

   return (complianceFailures, faultList)

def _CreateLocalizedMessage(obj, catalogKey, keyValDict):
   """ Helper method to add our policy and profile to localized messages.
   """
   paramId = keyValDict[_PARAMID] if _PARAMID in keyValDict else None
   return CreateLocalizedMessage(obj,
                                 catalogKey,
                                 keyValDict=keyValDict,
                                 paramId=paramId,
                                 policy=DeviceAliasPolicy)

class DeviceAliasChecker(ProfileComplianceChecker):
   """ Checks whether the device alias setting in the host is a superset of the
   profile.

   We ignore extract devices in the host.

   We don't require busAddress to match exactly for
   those busAddress that are sbdf based.
   """
   @classmethod
   def CheckProfileCompliance(cls, profiles, hostServices, hostGatheredData,
                              parent):
      """Checks for profile compliance.
      """
      complianceFailures, faultList = _EvaluateCompliance(profiles,
                                                          hostGatheredData)

      return (len(complianceFailures) == 0, complianceFailures)


class DeviceAliasProfile(GenericProfile):
   """ Host profile containing device alias rule.
   """
   singleton = False
   policies = [ DeviceAliasPolicy ]
   complianceChecker = DeviceAliasChecker
   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_DEVICE_ALIAS_CONFIG

   @classmethod
   def _CreateProfileInst(cls, busType, busAddress, alias):
      """ Helper method that creates a single profile instance.
      """
      busTypeParam = (_BUSTYPE, busType)
      busAddressParam = (_BUSADDRESS, busAddress)
      aliasParam = (_ALIAS, alias)
      params = [ busTypeParam, busAddressParam, aliasParam ]
      policyOpt = DeviceAliasPolicyOption(params)
      policies = [ DeviceAliasPolicy(True, policyOpt) ]
      return cls(policies = policies)

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, hostGatheredData, parent):
      """ Generate our profile as a set of rules, with one rule per item in the
      hostGatheredData.
      """
      rules = []
      for entry in hostGatheredData:
         busType, busAddress, alias = entry
         ruleInst = cls._CreateProfileInst(busType, busAddress, alias)
         rules.append(ruleInst)
      return rules

   @classmethod
   def GatherData(cls, hostServices):
      """Gathers the aliases datastores on the host system for use in other
      operations.
      
      Subprofiles of the DeviceAlias Configuration profile will inherit this
      data if they do not provide their own GatherData implementation.
      """
      # Implementation of GatherData is pretty easy with ExecuteEsxcli.
      # That already returns output as a list of dicts, where each dict is
      # a device w/alias.

      status, aliasMap = hostServices.ExecuteEsxcli('deviceInternal',
                                                    'alias', 'list')
      if status != 0:
         log.error("Failed to fetch aliases via esxcli (%d): %s" %
                   (status, aliasMap))
         errDict = { 'Status' : '%d' % status }
         fault = CreateLocalizedException(None, DEVICE_ESXCLI_LIST_FAIL,
                                          errDict)
         raise fault

      aliasConf = []
      for entry in aliasMap:
         alias = entry[_ALIAS]
         busAddress = entry['Bus address']
         busType = entry['Bus type']
         if busType == "logical" and _phdRegex.search(busAddress):
            log.info("GatherData skipping alias %s for addr %s" %
                      (alias, busAddress))
         else:
            aliasConf.append((busType, busAddress, alias))
      return aliasConf

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, hostGatheredData,
                     validationErrors):
      """ Verify if a single profile instance is valid.

      This is generally called by the host profiles infrastructure
      before a compliance check or task list generation.
      """
      busValid = True
      aliasValid = True
      noDuplicates = True
      busType, busAddress, alias =  _GetProfileInst(profileInstance)
      aliasRoot, aliasNum, msg = _ParseAlias(alias)
      if aliasRoot == None:
         validationErrors.append(msg)
         aliasValid = False
      rslt, msg = _ValidateBusAddress(busType, busAddress)
      if not rslt:
         validationErrors.append(msg)
         busValid = False
      else:
         # search for duplicates
         for searchInst in profileInstance.parentProfile.DeviceAliasProfile:
            oBusType, oBusAddress, oAlias =  _GetProfileInst(searchInst)
            if searchInst != profileInstance:
               if oBusType == busType and oBusAddress == busAddress:
                  errDict = { _BUSTYPE : busType,
                              _BUSADDRESS : busAddress,
                              _ALIAS : alias,
                              _PARAMID : _BUSADDRESS }
                  msg = _CreateLocalizedMessage(None, DEVICE_DUPLICATE, errDict)
                  validationErrors.append(msg)
                  noDuplicates = False
               if aliasValid and oBusType == busType and oAlias == alias:
                  errDict = { _BUSTYPE : busType,
                              _BUSADDRESS : busAddress,
                              _ALIAS : alias,
                              _PARAMID : _ALIAS }
                  msg = _CreateLocalizedMessage(None, DEVICE_ALIAS_DUPLICATE,
                                                errDict)
                  validationErrors.append(msg)
                  noDuplicates = False

      return aliasValid and busValid and noDuplicates

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        hostGatheredData, parent):
      """ Generates a task list for device alias configuration changes.

      The tasklist, if generated,  will always contain the complete set
      of aliases in the profile.  There are two reasons for this:

      1. The sbdf remediation algorithm in the vmkdevmgr requires a
         complete set of sbdf busAddress(es).

      2. The mere presense of aliases in the alternate (pending)
         branch of esx.conf triggers the vmkdevmgr to use busAddress
         enumeration order (instead of the old sbdf order).

      This method is generally called either in early boot
      (stateless case) or while doing stateful remediation on
      administrative direction from the VC.

      We will not generate a task list if doing stateful remediation
      (i.e. if not in early boot) and the host is already compliant.
      """

      #
      # Check for profile validity if doing stateful remediation
      # (detrmined by checking the earlyBoot flag).
      #
      # Raise an exception for the administrator to see if this host
      # cannot be made compliant with this profile.
      #
      if not hostServices.earlyBoot:
         complianceFailures, faultList = \
                  _EvaluateCompliance(profileInstances, hostGatheredData)
         if faultList:
            raise faultList[0]
         if not complianceFailures:
            # Host is compliant.  Don't generate tasks.
            profileInstances = []

      haveData = False
      for profInst in profileInstances:
         busType, busAddress, alias =  _GetProfileInst(profInst)
         msgData = { _BUSTYPE : busType,
                     _BUSADDRESS : busAddress,
                     _ALIAS : alias,
                     _PARAMID : _ALIAS }
         taskMsg = _CreateLocalizedMessage(None, DEVICE_DO_SET_ALIAS, msgData)
         taskList.addTask(taskMsg, (busType, busAddress, alias))
         haveData = True

      if haveData and not hostServices.earlyBoot:
         rslt = TASK_LIST_REQ_REBOOT
      else:
         rslt = TASK_LIST_RES_OK

      return rslt

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """ Writes the alias settings from the profile into an alternate branch
      of esx.conf.
      """
      status, output = hostServices.ExecuteEsxcli('deviceInternal',
                                                  'alias',
                                                  'reset')
      if status != 0:
         log.error("Failed to reset pending alias state esxcli: %d, %s" %
                   (status, output))
         errDict = { 'Status' : '%d' % status }
         fault = CreateLocalizedException(None, DEVICE_ESXCLI_RESET_FAIL,
                 errDict)
         raise fault

      for task in taskList:
         busType, busAddress, alias = task
         params = '--bus-type %s --bus-address %s --alias %s' % \
                  (busType, busAddress, alias)
         status, output = hostServices.ExecuteEsxcli('deviceInternal',
                                                     'alias',
                                                     'store',
                                                     params)
         if status != 0:
            log.error("Failed to write alias via esxcli: %d, %s" %
                      (status, output))
            errDict = { 'Status' : '%d' % status }
            fault = CreateLocalizedException(None, DEVICE_ESXCLI_SET_FAIL,
                                             errDict)
            raise fault

   @staticmethod
   def EarlybootFallback(failureStage, exception, hostServices):
      """ Receive notification of early boot errors.

      The profileDisabled error occurs if the host profile document contains a
      device alias profile, but it has been disabled.

      In this case, we need to make sure the the Pci bus plugin to the
      vmkdevmgr sees  a "disabled" pending alias,  so that it will use
      busAddress ordering for alias assignment.
      """
      if failureStage == ApplyFailure.profileDisabled:
         busType = "pci"
         busAddress = "..DISABLED..DEVICE..ALIAS..PROFILE.."
         alias = "vmnic0" # arbitrary legal alias
         params = '--bus-type %s --bus-address %s --alias %s' % \
                  (busType, busAddress, alias)
         status, output = hostServices.ExecuteEsxcli('deviceInternal',
                                                     'alias',
                                                     'store',
                                                     params)
         if status != 0:
            log.error("Failed to write alias via esxcli: %d, %s" %
                      (status, output))
