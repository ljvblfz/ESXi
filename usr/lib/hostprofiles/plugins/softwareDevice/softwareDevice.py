#!/usr/bin/python
# **********************************************************
# Copyright 2017 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import ParameterMetadata
from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING
from pluginApi import COMPONENT_SOFTWARE_DEVICE_CONFIG
from pluginApi import log
from pluginApi.extensions import SimpleConfigProfile
from pluginApi.extensions import StringNonEmptyValidator

class SoftwareDeviceProfile(SimpleConfigProfile):
   """A Host Profile that manages Software Devices on ESX hosts.
   """
   # Define required class attributes
   singleton = False
   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_SOFTWARE_DEVICE_CONFIG

   # Esxcli and Profile parameter names
   DEVICE_ID  = 'Device ID'      # esxcli parameter name
   DEVICEID   = 'DeviceID'       # profile parameter name (no space)
   INSTANCE   = 'Instance'       # esxcli & profile parameter name
   parameters = [ ParameterMetadata(DEVICEID, 'string', False,
                                    paramChecker=StringNonEmptyValidator),
                  ParameterMetadata(INSTANCE, 'string', False,
                                    paramChecker=StringNonEmptyValidator),
   ]

   @classmethod
   def EsxCli(cls, hostServices, cmdLine):
      """Invoke esxcli with cmdLine.
      """
      status, output = hostServices.ExecuteEsxcli(cmdLine)
      if status != 0:
         log.error('Failed to execute "esxcli"', cmdLine,
            'command. Status = %d, Error = %s' % (status, output))
         output = []
      return output

   @classmethod
   def EsxCliDeviceSoftware(cls, hostServices, cmd, deviceConfig=None):
      """Invoke esxcli with options for software devices in the system.
      """
      options = ''
      if deviceConfig:
         options = ' -d %s -i %s' % (deviceConfig[cls.DEVICEID],
                                     deviceConfig[cls.INSTANCE])
      return cls.EsxCli(hostServices, 'device software ' + cmd + options)

   @classmethod
   def ExtractConfig(cls, hostServices):
      """For the SoftwareDeviceProfile, the extract executes esxcli commands
         to get a list of dicts, where each dict contains the config info
         for one software device.
      """
      config = []

      # There should be no existing software devices at earlyBoot.
      if not hostServices.earlyBoot:
         # Implementation of extract config is pretty easy with ExecuteEsxcli.
         # That already returns output as a list of dicts, where each dict is
         # a software device. We just need to extract the items we need.
         softwareDeviceList = cls.EsxCliDeviceSoftware(hostServices, 'list')
         for deviceInfo in softwareDeviceList:
            deviceConfig = {cls.DEVICEID : deviceInfo[cls.DEVICE_ID],
                            cls.INSTANCE : deviceInfo[cls.INSTANCE]}
            config.append(deviceConfig)
      return config

   @classmethod
   def SetConfig(cls, config, hostServices):
      """For the SoftwareDeviceProfile, config contains a list of dicts, where
         each dict contains the parameters needed to create a softwareDevice.
      """
      # devicesToRemove is initialized with all the existing software devices.
      devicesToRemove = cls.ExtractConfig(hostServices)

      # devicesToAdd is initialized with all the configured software devices.
      devicesToAdd = config[:]

      # Compare the lists of software devices, removing those that are in both.
      # The rest are those that need to be added to or removed from the Host.
      # Note: We iterate through config because devicesToAdd may be modified.
      for deviceConfig in config:
         if deviceConfig in devicesToRemove:
            # Device is in both lists; we don't need to add or remove it.
            devicesToRemove.remove(deviceConfig)
            devicesToAdd.remove(deviceConfig)

      # Now remove and/or add remaining devices.
      for deviceConfig in devicesToRemove:
         cls.EsxCliDeviceSoftware(hostServices, 'remove', deviceConfig)
      for deviceConfig in devicesToAdd:
         cls.EsxCliDeviceSoftware(hostServices, 'add', deviceConfig)

