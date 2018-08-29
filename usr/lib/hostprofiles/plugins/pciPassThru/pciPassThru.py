#!/usr/bin/python
# **********************************************************
# Copyright 2011-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

from pluginApi import GenericProfile, FixedPolicyOption, Policy, log, \
                      ParameterMetadata, CreateLocalizedMessage, \
                      CreateLocalizedException, ProfileComplianceChecker, \
                      CreateComplianceFailureValues, PARAM_NAME, MESSAGE_KEY, \
                      TASK_LIST_RES_OK, TASK_LIST_REQ_REBOOT
from pluginApi import CATEGORY_ADVANCED_CONFIG_SETTING, COMPONENT_VMDIRECTPATH_CONFIG
from pyVmomi import Vim

import re

MODULE_MSG_KEY_BASE = 'com.vmware.profile.pciPassThru'
SETTING_PCIPASSTHRU = '%s.%s' % (MODULE_MSG_KEY_BASE, 'settingConfig')
SETTING_PCIPASSTHRU_FAIL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'settingConfigFail')
GETTING_PCIPASSTHRU_FAIL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'gettingConfigFail')
SETTING_PCIPASSTHRU_STRICT_FAIL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'settingConfigStrictFail')
DEPENDENT_DEVICES_CONFIG = '%s.%s' % (MODULE_MSG_KEY_BASE, 'dependentDevicesConfig')
DEVICE_MISSING_IN_HOST = '%s.%s' % (MODULE_MSG_KEY_BASE, 'deviceMissingHost')
DEVICE_MISSING_IN_PROFILE = '%s.%s' % (MODULE_MSG_KEY_BASE, 'deviceMissingProfile')
DEVICE_PASSTHRU_MISMATCH = '%s.%s' % (MODULE_MSG_KEY_BASE, 'configMismatch')


def PciPassthroughFormatSbdf(sbdf):
   """Formats the given PCI seg/bus/dev/func (sbdf) identifier string into the
   form 'ssss:bb:dd.f'. The given sbdf must be in hex but the segment
   identifier may or may not be present (as old host profiles may not have it).
   In addition, the given sbdf string may specify the segment, bus, device, or
   function with a number of digits differing from the format produced by this
   function.
   """
   split = re.split(':|\.', sbdf)
   split.reverse()

   func = int(split[0], 16)
   dev = int(split[1], 16)
   bus = int(split[2], 16)

   if len(split) == 3:
      seg = 0
   else:
      seg = int(split[3], 16)

   newSbdf = '{:04x}:{:02x}:{:02x}.{:1x}'.format(seg, bus, dev, func)
   return newSbdf


class PCIPassThroughIgnoreOption(FixedPolicyOption):
   """Policy Option type to ignore the configuration.
   """
   paramMeta = [ ]


class PCIPassThroughApplyOption(FixedPolicyOption):
   """Policy Option type to apply the configuration.
   """
   paramMeta = [ ParameterMetadata('strictMode', 'boolean', False, True) ]


class PCIPassThroughPolicy(Policy):
   """Define a policy to control the profile behavior.
   """
   possibleOptions = [ PCIPassThroughIgnoreOption, PCIPassThroughApplyOption ]


class PCIPassThroughConfigPolicyOption(FixedPolicyOption):
   """Policy Option type containing the PCI PassThrough configuration.
   """
   paramMeta = [ ParameterMetadata('deviceId', 'string', False,
                    mappingAttributePath={'vim' : 'id'}, mappingIsKey={'vim' : True}),
                 ParameterMetadata('enabled', 'boolean', False,
                    mappingAttributePath={'vim' : 'passthruEnabled'}) ]


class PCIPassThroughConfigPolicy(Policy):
   """Define a policy for the PCI PassThrough configuration.
   """
   possibleOptions = [ PCIPassThroughConfigPolicyOption ]


class PciPassThroughChecker(ProfileComplianceChecker):
   """Checks whether the host's PCI Passthrough configuration is compliant with the profile.
   """
   def CheckProfileCompliance(self, profiles, hostServices, profileData, parent):
      """Checks for profile compliance.
      """
      option = profiles[0].PCIPassThroughPolicy.policyOption
      if isinstance(option, PCIPassThroughIgnoreOption):
         return (True, [])
      strictMode = option.strictMode

      # get configuration from profile
      profConf = {}
      for profInst in profiles[0].subprofiles:
         deviceId = profInst.PCIPassThroughConfigPolicy.policyOption.deviceId
         deviceId = PciPassthroughFormatSbdf(deviceId)
         enabled = profInst.PCIPassThroughConfigPolicy.policyOption.enabled
         profConf[deviceId] = enabled
      # get configuration from host
      hostConf = {}
      for pciInfo in hostServices.hostConfigInfo.config.pciPassthruInfo:
         if pciInfo.passthruCapable:
            pciInfoId = PciPassthroughFormatSbdf(pciInfo.id)
            hostConf[pciInfoId] = pciInfo.passthruEnabled

      complianceFailures = []
      if strictMode:
         # report missing devices either in profile or host
         for deviceId in profConf:
            if deviceId not in hostConf:
               msgData = { 'deviceId' : deviceId }
               complyFailMsg = CreateLocalizedMessage(None,
                                 DEVICE_MISSING_IN_HOST, msgData)
               msgKey = "com.vmware.vim.profile.Policy.pciPassThru." \
                        "pciPassThru.PCIPassThroughConfigPolicy.label"
               comparisonValues = CreateComplianceFailureValues(msgKey,
                                    MESSAGE_KEY, profileValue = deviceId,
                                    hostValue = '')
               complianceFailures.append((complyFailMsg, [comparisonValues]))
         for deviceId in hostConf:
            if deviceId not in profConf:
               msgData = { 'deviceId' : deviceId }
               complyFailMsg = CreateLocalizedMessage(None,
                                 DEVICE_MISSING_IN_PROFILE, msgData)
               msgKey = "com.vmware.vim.profile.Policy.pciPassThru." \
                        "pciPassThru.PCIPassThroughConfigPolicy.label"
               comparisonValues = CreateComplianceFailureValues(msgKey,
                                    MESSAGE_KEY, profileValue = '',
                                    hostValue = deviceId)
               complianceFailures.append((complyFailMsg, [comparisonValues]))
      # report device configuration mismatches between profile and host
      for deviceId, enabled in profConf.items():
         if deviceId in hostConf and hostConf[deviceId] != enabled:
            msgData = { 'deviceId' : deviceId, 'enabled' : str(enabled) }
            complyFailMsg = CreateLocalizedMessage(None,
                              DEVICE_PASSTHRU_MISMATCH, msgData)
            comparisonValues = CreateComplianceFailureValues('enabled',
                                 PARAM_NAME,
                                 profileValue = profConf[deviceId],
                                 hostValue = hostConf[deviceId],
                                 profileInstance = deviceId)
            complianceFailures.append((complyFailMsg, [comparisonValues]))
      return (len(complianceFailures) == 0, complianceFailures)


class PciPassThroughConfigProfile(GenericProfile):
   """Host profile containing passthrough configuration for each PCI device.
   """
   singleton = False
   policies = [ PCIPassThroughConfigPolicy ]

   # vCM Mapping data
   mappingBasePath = { 'vim': 'config.pciPassthruInfo' }

   @classmethod
   def _CreateProfileInst(cls, deviceId, enabled):
      """helper method that creates a profile instance of PCI PassThrough configuration.
      """
      deviceIdParam = [ 'deviceId', deviceId ]
      enabledParam = [ 'enabled', enabled ]
      params = [ deviceIdParam, enabledParam ]
      policyOpt = PCIPassThroughConfigPolicyOption(params)
      policies = [ PCIPassThroughConfigPolicy(True, policyOpt) ]
      return cls(policies = policies)

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      """Implementation that retrieves one profile instance per device.
      """
      rules = []
      for pciInfo in hostServices.hostConfigInfo.config.pciPassthruInfo:
         if pciInfo.passthruCapable:
            ruleInst = cls._CreateProfileInst(pciInfo.id, pciInfo.passthruEnabled)
            rules.append(ruleInst)
      return rules

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      """Generates a task list for PCI passthrough configuration changes.
      """
      # this is taken care by the parent profile
      return TASK_LIST_RES_OK

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Sets the current PCI passthrough setting.
      """
      # this is taken care by the parent profile
      return


class PciPassThroughProfile(GenericProfile):
   """Host profile containing the PCI PassThrough configuration.
   """
   singleton = True
   policies = [ PCIPassThroughPolicy ]
   subprofiles  = [ PciPassThroughConfigProfile ]
   complianceChecker = PciPassThroughChecker()

   category = CATEGORY_ADVANCED_CONFIG_SETTING
   component = COMPONENT_VMDIRECTPATH_CONFIG

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      """Implementation that returns a single instance profile.
      """
      hasEnabledDevice = False
      for pciInfo in hostServices.hostConfigInfo.config.pciPassthruInfo:
         if pciInfo.passthruCapable and pciInfo.passthruEnabled:
            hasEnabledDevice = True
            break
      if hasEnabledDevice:
         strictModeParam = [ 'strictMode', True ]
         policyOpt = PCIPassThroughApplyOption([strictModeParam])
         policies = [ PCIPassThroughPolicy(True, policyOpt) ]
      else:
         policyOpt = PCIPassThroughIgnoreOption([])
         policies = [ PCIPassThroughPolicy(True, policyOpt) ]
      return cls(policies = policies)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      """Verify if the configuration in the profile is valid.
      """
      option = profileInstance.PCIPassThroughPolicy.policyOption
      if isinstance(option, PCIPassThroughIgnoreOption):
         return True

      if not hostServices.hostConfigInfo:
         return True

      # get dependency map based on the information from host
      dependency = {}
      for pciInfo in hostServices.hostConfigInfo.config.pciPassthruInfo:
         if pciInfo.passthruCapable:
            dependency[pciInfo.id] = pciInfo.dependentDevice

      # check each device for dependency based on the information from host
      retVal = True
      profInstList = profileInstance.subprofiles
      for i in range(len(profInstList)):
         id1 = profInstList[i].PCIPassThroughConfigPolicy.policyOption.deviceId
         enabled1 = profInstList[i].PCIPassThroughConfigPolicy.policyOption.enabled
         for j in range(i):
            id2 = profInstList[j].PCIPassThroughConfigPolicy.policyOption.deviceId
            enabled2 = profInstList[j].PCIPassThroughConfigPolicy.policyOption.enabled
            if id1 in dependency and id2 in dependency:
               # if dependency[id] is empty, it means there is no dependent device
               if dependency[id1] and dependency[id1] == dependency[id2]:
                  # the two devices must have the same configuration
                  if enabled1 != enabled2:
                     msgData = { 'deviceId1' : id1, 'deviceId2' : id2 }
                     dependentDeviceMsg = CreateLocalizedMessage(
                                             None, DEPENDENT_DEVICES_CONFIG, msgData)
                     dependentDeviceMsg.SetRelatedPathInfo(profile=profInstList[i],
                                          policy=profInstList[i].PCIPassThroughConfigPolicy,
                                          paramId='enabled')
                     validationErrors.append(dependentDeviceMsg)
                     retVal = False
                     break
      return retVal

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      """Generates a task list for PCI PassThrough configuration changes.
      """
      option = profileInstances[0].PCIPassThroughPolicy.policyOption
      if isinstance(option, PCIPassThroughIgnoreOption):
         return TASK_LIST_RES_OK
      strictMode = option.strictMode

      # get configuration from profile
      profConf = {}
      for profInst in profileInstances[0].subprofiles:
         deviceId = profInst.PCIPassThroughConfigPolicy.policyOption.deviceId
         deviceId = PciPassthroughFormatSbdf(deviceId)
         enabled = profInst.PCIPassThroughConfigPolicy.policyOption.enabled
         profConf[deviceId] = enabled

      # get configuration from hostd
      hostConf = {}
      if not hostServices.earlyBoot:
         for pciInfo in hostServices.hostConfigInfo.config.pciPassthruInfo:
            if pciInfo.passthruCapable:
               pciInfoId = PciPassthroughFormatSbdf(pciInfo.id)
               hostConf[pciInfoId] = pciInfo.passthruEnabled
      else:
         status, output = hostServices.ExecuteEsxcli('hardwareinternal',
                              'pci', 'listpassthru', None)
         if status != 0:
            fault = CreateLocalizedException(None, GETTING_PCIPASSTHRU_FAIL,
                                             {'errMsg': output})
            raise fault
         for item in output:
            # truncate the device id to match the format in profile and hostinfo
            deviceId = item['Device ID']
            deviceId = PciPassthroughFormatSbdf(deviceId)
            enabled = item['Enabled']
            hostConf[deviceId] = enabled

      needReboot = False
      if strictMode:
         # strict mode, profile and host must have same set of devices
         if set(profConf.keys()) != set(hostConf.keys()):
            fault = CreateLocalizedException(None, SETTING_PCIPASSTHRU_STRICT_FAIL)
            raise fault
         for deviceId, enabled in profConf.items():
            if hostConf[deviceId] != enabled:
               msgData = { 'deviceId' : deviceId, 'enabled' : enabled }
               taskMsg = CreateLocalizedMessage(None, SETTING_PCIPASSTHRU, msgData)
               taskList.addTask(taskMsg, (deviceId, enabled))
               needReboot = True
      else:
         # non-strict mode, use best effort approach to remediate configuration
         for deviceId, enabled in profConf.items():
            if deviceId in hostConf and hostConf[deviceId] != enabled:
               msgData = { 'deviceId' : deviceId, 'enabled' : enabled }
               taskMsg = CreateLocalizedMessage(None, SETTING_PCIPASSTHRU, msgData)
               taskList.addTask(taskMsg, (deviceId, enabled))
               needReboot = True

      if hostServices.earlyBoot:
         return TASK_LIST_RES_OK
      else:
         if needReboot:
            return TASK_LIST_REQ_REBOOT
         else:
            return TASK_LIST_RES_OK

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Sets the current PCI PassThrough setting.
      """
      if hostServices.earlyBoot:
         # early boot uses esxcli to configure device
         for task in taskList:
            optStr = '--device-id=%s --enable=%s' % \
                        (task[0], task[1] and 'true' or 'false')
            status, output = hostServices.ExecuteEsxcli('hardwareinternal',
                                 'pci', 'setpassthru', optStr)
            if status != 0:
               log.error("Failed to set PCI passthrough via esxcli: %d, %s" % (status, output))
               msgData = { 'errMsg' : output }
               fault = CreateLocalizedException(None, SETTING_PCIPASSTHRU_FAIL, msgData)
               raise fault
      else:
         # use hostd API to configure device
         configList = []
         for task in taskList:
            config = Vim.Host.PciPassthruConfig(
                        id = task[0],
                        passthruEnabled = task[1])
            configList.append(config)
         try:
            pciPassthruMgr = hostServices.hostSystemService.configManager.pciPassthruSystem
            pciPassthruMgr.UpdatePassthruConfig(configList)
         except Exception as exc:
            log.error("Failed to set PCI passthrough via hostd: %s" % str(exc))
            msgData = { 'errMsg' : str(exc) }
            fault = CreateLocalizedException(None, SETTING_PCIPASSTHRU_FAIL, msgData)
            raise fault

