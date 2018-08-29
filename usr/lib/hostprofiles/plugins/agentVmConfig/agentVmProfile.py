#!/usr/bin/python
# **********************************************************
# Copyright 2012-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import ParameterMetadata, \
                      CreateLocalizedMessage, \
                      CreateLocalizedException
from pluginApi import log
from pluginApi import CATEGORY_ADVANCED_CONFIG_SETTING, COMPONENT_AGENT_VM_CONFIG
from pluginApi.extensions import SimpleConfigProfile
import inspect
import traceback


#
# Define some constants first
#
BASE_MSG_KEY = 'com.vmware.profile.Profile.agentVm'

#
# Define the localization message catalog keys used by this profile
FAILED_TO_READ_CONFIG = '%s.FailedToReadConfig' % BASE_MSG_KEY
FAILED_TO_UPDATE_CONFIG = '%s.FailedToUpdateConfig' % BASE_MSG_KEY
DATASTORE_PARAM = 'datastore'
NETWORK_PARAM = 'network'

class AgentVmProfile(SimpleConfigProfile):
   """A Host Profile that manages the host configuration, related to agent VMs.
   """
   #
   # Define required class attributes
   #
   parameters = [
      # Parameter for the profile
      ParameterMetadata(DATASTORE_PARAM, 'string', True),
      ParameterMetadata(NETWORK_PARAM, 'string', True) ]

   singleton = True

   component = COMPONENT_AGENT_VM_CONFIG
   category = CATEGORY_ADVANCED_CONFIG_SETTING

   @classmethod
   def ExtractConfig(cls, hostServices):
      """Extracts the current Agent VM datastore and network
      """
      config = {}
      try:
         config[NETWORK_PARAM] = hostServices.hostConfigInfo.agentVmNetworkName
         config[DATASTORE_PARAM] = hostServices.hostConfigInfo.agentVmDatastoreName
      except Exception as exc:
         log.exception('Failed to read agent VM configuration from hostSystem: %s', str(exc))
         fault = CreateLocalizedException(
                    None, FAILED_TO_READ_CONFIG)
         raise fault

      return config

   @classmethod
   def SetConfig(cls, config, hostServices):
      """For the AgentVmProfile, the config parameter should contain a list of
         dicts with a single entry, and that entry should have two parameters - 
         for network and datastore
      """
      return True
