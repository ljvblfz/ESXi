#!/usr/bin/python
# ***************************************************************************
# Copyright 2015 VMware, Inc.  All rights reserved. VMware Confidential.
# ***************************************************************************

__author__ = "VMware, Inc."

import os

from pluginApi import CATEGORY_ADVANCED_CONFIG_SETTING, COMPONENT_FILE_CONFIG
from pluginApi import ParameterMetadata
from pluginApi.extensions import XmlConfigProfile, ChoiceValidator

PARAM_LOGLEVEL = 'logLevel'
LOGLEVEL_CHOICES = ['none', 'error', 'warning', 'info', 'verbose', 'trivia']

class VpxaConfigProfile(XmlConfigProfile):
   """A host profile that manages the vpxa configurations.
   """
   category = CATEGORY_ADVANCED_CONFIG_SETTING
   component = COMPONENT_FILE_CONFIG

   parameters = [
      ParameterMetadata(PARAM_LOGLEVEL, 'string', isOptional=False,
         paramChecker=ChoiceValidator(LOGLEVEL_CHOICES))
      ]
   filePath = os.path.join('/etc', 'vmware', 'vpxa', 'vpxa.cfg')
   paramLocation = { PARAM_LOGLEVEL : '/config/log/level' }

   @classmethod
   def GetDefaultProfileValues(cls, hs):
      """ Return a dictionary containing default values for all parameters
          in this profile.
      """
      dValues = dict((x.paramName, None) for x in cls.parameters)
      rc, data = hs.ExecuteLocalEsxcli(['system', 'version', 'get'])
      if (rc == 0 and "Build" in data and
          data["Build"].upper().startswith("RELEASE")):
          dValues[PARAM_LOGLEVEL] = "info"
      else:
          dValues[PARAM_LOGLEVEL] = "verbose"
      return dValues
