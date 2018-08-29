#!/usr/bin/python
# **********************************************************
# Copyright 2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import ParameterMetadata, \
                      CreateLocalizedException
from pluginApi import CATEGORY_ADVANCED_CONFIG_SETTING, \
                      COMPONENT_GRAPHICS_CONFIG
from pluginApi.extensions import SimpleConfigProfile, \
                                 ChoiceValidator
from pluginApi import log
from pyVmomi import Vim

#
# Define the localization message catalog keys used by this profile
#
BASE_MSG_KEY = 'com.vmware.profile.Profile.graphicsConfig'
FAILED_TO_READ_CONFIG = '%s.FailedToReadConfig' % BASE_MSG_KEY
FAILED_TO_UPDATE_CONFIG = '%s.FailedToUpdateConfig' % BASE_MSG_KEY

GRAPHICS_TYPE_PARAM = 'defaultGraphicsType'
GRAPHICS_TYPE_VALUES = ['shared', 'sharedDirect']
ASSIGNMENT_POLICY_PARAM = 'sharedPassthruAssignmentPolicy'
ASSIGNMENT_POLICY_VALUES = ['performance', 'consolidation']

class GraphicsConfigProfile(SimpleConfigProfile):
   """A Host Profile that manages the host configuration of graphics devices.
   """
   #
   # Define required class attributes
   #
   parameters = [
      # Parameter for the profile
      ParameterMetadata(GRAPHICS_TYPE_PARAM, 'string', True,
         paramChecker=ChoiceValidator(GRAPHICS_TYPE_VALUES)),
      ParameterMetadata(ASSIGNMENT_POLICY_PARAM, 'string', True,
         paramChecker=ChoiceValidator(ASSIGNMENT_POLICY_VALUES))
   ]

   singleton = True

   component = COMPONENT_GRAPHICS_CONFIG
   category = CATEGORY_ADVANCED_CONFIG_SETTING

   @classmethod
   def ExtractConfig(cls, hostServices):
      """Extracts the current host graphics configuration.
      """
      config = {}
      try:
         graphicsConfig = hostServices.hostConfigInfo.config.graphicsConfig
         config[GRAPHICS_TYPE_PARAM] = graphicsConfig.hostDefaultGraphicsType
         config[ASSIGNMENT_POLICY_PARAM] = \
            graphicsConfig.sharedPassthruAssignmentPolicy
         log.info('GraphicsConfigProfile::ExtractConfig: %s' % config)

      except Exception as exc:
         log.exception('GraphicsConfigProfile failed to read host ' + \
                       'graphics configuration: %s', str(exc))
         fault = CreateLocalizedException(None, FAILED_TO_READ_CONFIG)
         raise fault

      return config

   @classmethod
   def SetConfig(cls, config, hostServices):
      """For the GraphicsConfigProfile, the config parameter should contain
         a list of dicts with a single entry, and that entry should have
         parameters defaultGraphicsType and sharedPassthruAssignmentPolicy.
      """
      log.info('GraphicsConfigProfile::SetConfig: %s' % config)
      config = config[0]
      try:
         graphicsMgr = \
            hostServices.hostSystemService.configManager.graphicsManager
         graphics = Vim.Host.GraphicsConfig(
            hostDefaultGraphicsType=config[GRAPHICS_TYPE_PARAM],
            sharedPassthruAssignmentPolicy=config[ASSIGNMENT_POLICY_PARAM])
         graphicsMgr.UpdateGraphicsConfig(graphics)

      except Exception as exc:
         log.exception('GraphicsConfigProfile failed to update host ' + \
                       'graphics configuration: %s', str(exc))
         fault = CreateLocalizedException(None, FAILED_TO_UPDATE_CONFIG)
         raise fault

      return True
