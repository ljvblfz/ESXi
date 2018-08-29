#!/usr/bin/python
# **********************************************************
# Copyright 2013-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import ParameterMetadata, \
                      CreateLocalizedException, \
                      log, \
                      PolicyOptComplianceChecker, \
                      CreateComplianceFailureValues,\
                      CreateLocalizedMessage

from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING, \
                      COMPONENT_VFLASH_HOST_CACHE_CONFIG, \
                      TASK_LIST_REQ_MAINT_MODE

from pluginApi.extensions import SimpleConfigProfile, RangeValidator,\
                                 GenerateDiff, MapDiff, GetProfileLabelKey, \
                                 GetMsgKeyName

from pyEngine import storageprofile
from pyEngine.i18nmgr import MESSAGE_NS
from pluginApi import MESSAGE_KEY


# Localization message catalog keys used by this profile
BASE_MSG_KEY = 'com.vmware.profile.vFlashHostCacheConfig'
ESXCLI_ERROR_MSG_KEY = BASE_MSG_KEY + '.EsxcliError'
INVALID_SYS_CONFIG_MSG_KEY = BASE_MSG_KEY + '.InvalidSystemConfig'
INVALID_CONFIG_MSG_KEY = BASE_MSG_KEY + '.InvalidConfig'

VFLASH_DIFFERENT_KEY = MESSAGE_NS + 'Profile.%s.Different'
VFLASH_MISSING_HARDWARE_KEY = MESSAGE_NS + 'Profile.%s.MissingHardware'

# 1 << 30 * PAGE_SIZE in MB for 30 bits of swap blocks
MAX_SIZE = 4194304
SIZE_NAME = 'SizeMB'

def vFlashVolumeUUID(h):
   """Find the UUID of the vFlash volume"""
   volumes = []
   if h.earlyBoot:
      volumes = c.executeEsxcli(h, 'storage filesystem list')
   else:
      fs = h.hostSystemService.configManager.storageSystem.fileSystemVolumeInfo
      for d in fs.mountInfo:
         if d.volume.type == "VFFS":
            volumes.append({'Type': d.volume.type, 'UUID': d.volume.uuid})

   uuid = None
   for volume in volumes:
      if volume['Type'] == 'VFFS':
         # There can only be a single VFFS volume
         if uuid != None:
            log.error('Mutiple vFlash volumes found')
            raise CreateLocalizedException(None, INVALID_SYS_CONFIG_MSG_KEY)
         uuid = volume['UUID']
   return uuid

class VFlashPolicyOptChecker(PolicyOptComplianceChecker):
   """ The Compliance checker class differentiates between two scenarios.
       1. If the VFLASH hardware is not found, it generates a hardware
          specific error to indicate that the host does not have the
          compatible hardware to remediate the profile.
       2. If the VFLASH hardware is found, then it checks if the parameter
          values in the profile same as the one on the host.
   """
   def CheckPolicyCompliance(self, profile, policyOpt, hostServices, profileData):
      profClass = profile.__class__
      profClass._SetProfileOperationVersion(profile.version)
      log.info("Checking compliance for %s" % profClass)
      _, _, modProfData = GenerateDiff([profile], hostServices, profileData,
                                        profClass)
      if modProfData:
          failureValues = []
          uuid = vFlashVolumeUUID(hostServices)
          if uuid == None:
             log.info("No VFlash Volume found on the host")
             failureKey = VFLASH_MISSING_HARDWARE_KEY
          else:
             log.info("VFlash volume host configuration differs from profile.")
             failureKey = VFLASH_DIFFERENT_KEY
             diffList = MapDiff(modProfData[0])
             # As of now this plugin only has one parameter.
             hostVal, profVal, param = diffList[0]
             comparisonValues = CreateComplianceFailureValues(
                GetProfileLabelKey(profClass), MESSAGE_KEY,
                profileValue = profVal, hostValue = hostVal)
             failureValues.append(comparisonValues)

          msgKey = GetMsgKeyName(profClass, failureKey)
          failureMsg = CreateLocalizedMessage(None, msgKey, None)
          return False, [(failureMsg, failureValues)]
      return True, []

class VFlashHostCacheConfigProfile(SimpleConfigProfile):
   """A Host Profile that manages system vFlash Host cache config settings on
      ESX hosts."""

   # Required class attributes
   parameters = [ParameterMetadata(SIZE_NAME, 'int', False,
                                   paramChecker = RangeValidator(0, MAX_SIZE))]
   singleton = True
   setConfigReq = TASK_LIST_REQ_MAINT_MODE

   dependencies = [storageprofile.StorageProfile]

   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_VFLASH_HOST_CACHE_CONFIG
   policyOptionComplianceChecker = VFlashPolicyOptChecker

   # Functions that read or write data from/to localcli
   @classmethod
   def executeEsxcli(c, h, command):
      """Execute an esxcli command and handle potential errors"""
      status, ret = h.ExecuteEsxcli(command)
      if status != 0:
         msgData = {'cmd': str(command), 'errMsg' : str(ret)}
         raise CreateLocalizedException(None, ESXCLI_ERROR_MSG_KEY, msgData)
      if ret == None:
         ret = []
      return ret


   # External interface
   @classmethod
   def ExtractConfig(c, h):
      """Gets the host cache configuration"""

      config = [{SIZE_NAME: 0}]
      hostCaches = c.executeEsxcli(h, 'sched hostcache list')
      if len(hostCaches) == 0:
         return config
      uuid = vFlashVolumeUUID(h)
      if uuid:
         for hostCache in hostCaches:
            if hostCache['Volume'] == uuid:
               config[0][SIZE_NAME] = int(hostCache['SizeMB'])
               break
      return config

   @classmethod
   def SetConfig(c, config, h):
      """Sets the host cache configuration settings."""

      if len(config) != 1:
         log.error('%s config has %u entries instead of one entry'
                   % (COMPONENT_VFLASH_HOST_CACHE_CONFIG, len(config)))
         raise CreateLocalizedException(None, INVALID_CONFIG_MSG_KEY)

      uuid = vFlashVolumeUUID(h)
      if uuid == None:
         log.error('No vFlash volumes found, not creating host cache')
         return False
      size = config[0][SIZE_NAME]
      return c.executeEsxcli(h, 'sched hostcache set -v ' + uuid + ' -s '
                             + str(size))
