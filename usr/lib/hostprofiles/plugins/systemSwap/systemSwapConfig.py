#!/usr/bin/python
# **********************************************************
# Copyright 2011-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

import os
from pluginApi import ParameterMetadata, \
                      CreateLocalizedException, \
                      log

from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING, \
                      COMPONENT_SYSTEM_SWAP_CONFIG, \
                      TASK_LIST_REQ_MAINT_MODE

from pluginApi.extensions import SimpleConfigProfile, RangeValidator

from pyEngine import storageprofile
from vFlashHostCache import vFlashHostCacheConfig
from hostCache import hostCacheConfig

from operator import itemgetter
from pyEngine.nodeputil import StringTypeValidator


# Localization message catalog keys used by this profile
BASE_MSG_KEY = 'com.vmware.profile.systemSwapConfig'
ESXCLI_ERROR_MSG_KEY = BASE_MSG_KEY + '.EsxcliError'
MAX_ORDER = 255

class SystemSwapConfigProfile(SimpleConfigProfile):
   """A Host Profile that manages system swap config settings on ESX hosts."""

   # Required class attributes
   parameters = [ParameterMetadata('hostcache-enabled', 'bool', False),
                 ParameterMetadata('hostcache-order', 'int', False,
                                   paramChecker=RangeValidator(-1, MAX_ORDER)),
                 ParameterMetadata('hostlocalswap-enabled', 'bool', False),
                 ParameterMetadata('hostlocalswap-order', 'int', False,
                                   paramChecker=RangeValidator(-1, MAX_ORDER)),
                 ParameterMetadata('datastore-enabled', 'bool', False),
                 ParameterMetadata('datastore-order', 'int', False,
                                   paramChecker=RangeValidator(-1, MAX_ORDER)),
                 ParameterMetadata('datastore-name', 'string', nullPermitted=False,
                                   minLength=0)]

   singleton = True
   setConfigReq = TASK_LIST_REQ_MAINT_MODE

   dependencies = [storageprofile.StorageProfile,
                   vFlashHostCacheConfig.VFlashHostCacheConfigProfile,
                   hostCacheConfig.HostCacheConfigProfile]

   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_SYSTEM_SWAP_CONFIG


   # Functions that read or write data from/to localcli
   @classmethod
   def executeEsxcli(cls, hostservices, command):
      """Execute an esxcli command and handle potential errors"""

      status, ret = hostservices.ExecuteEsxcli(command)
      if status != 0:
         msgData = {'cmd': str(command), 'errMsg': str(ret)}
         raise CreateLocalizedException(None, ESXCLI_ERROR_MSG_KEY, msgData)
      if ret == None:
         ret = []
      return ret

   @classmethod
   def FindDatastore(cls, hostservices, name):
      if hostservices.earlyBoot:
         datastoreList = cls.executeEsxcli(hostservices,
                                           'storage filesystem list')
         for d in datastoreList:
            if d['UUID'] == name or d['Volume Name'] == name:
               return True
      else:
         ds = hostservices.hostSystemService.configManager.datastoreSystem
         for d in ds.datastore:
            # uuid is in url which is of the following format:
            # /vmfs/volumes/aedb61bc-c977e125
            if d.name == name or d.summary.url.split(os.sep)[-1] == name:
               return True
      return False

   # External interface
   @classmethod
   def ExtractConfig(cls, hostservices):
      """Gets the system swap config on the ESX system"""

      rawConfig = cls.executeEsxcli(hostservices, 'sched swap system get')
      config = {}
      for param in cls.parameters:
         config[param.paramName] = \
            rawConfig[param.paramName.title().replace('-', ' ')]
      return [config]

   @classmethod
   def SetConfig(cls, configRaw, hostservices):
      """Sets the system swap configuration settings."""

      if len(configRaw) != 1:
         log.error('SystemSwap config has %d entries. Should have one.' %
                   len(configRaw))
         return

      config = configRaw[0]
      command = 'sched swap system set'

      for param in cls.parameters:
         name = param.paramName
         if name in list(config.keys()):
            # ignore unknown datastore name parameters
            if (name == 'datastore-name' and
                not cls.FindDatastore(hostservices, config[name])):
               continue
            value = str(config[name])
            # Convert python type into something localcli can understand
            if isinstance(config[name], bool):
               value = value.lower()
            command = "%s --%s \"%s\"" % (command, name, value)
      return cls.executeEsxcli(hostservices, command)
