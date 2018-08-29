#!/usr/bin/python
# ***************************************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. VMware Confidential.
# ***************************************************************************

__author__ = "VMware, Inc."

from pluginApi.extensions import XmlConfigProfile
from pluginApi import ParameterMetadata
from pyEngine.nodeputil import ChoiceValidator
from pluginApi import CATEGORY_ADVANCED_CONFIG_SETTING, COMPONENT_HP_LOGGING_CONFIG


PARAM_LOGLEVEL = 'logLevel'
PARAM_TRACE = 'traceEnabled'
LOGLEVEL_CHOICES = ['ERROR', 'WARN', 'INFO', 'DEBUG']


class HPLoggingProfile(XmlConfigProfile):
   """A Host Profile that manages the Host Profile Engine logging configuration.
   """
   # Parameters for the profile.
   parameters = [
      ParameterMetadata(PARAM_LOGLEVEL, 'string', False,
          paramChecker=ChoiceValidator(LOGLEVEL_CHOICES)),
      ParameterMetadata(PARAM_TRACE, 'bool', False),
      ]
   filePath = '/etc/vmware/hostd/hostProfileEngine.xml'
   paramLocation = { PARAM_LOGLEVEL : '/config/logLevel',
                     PARAM_TRACE : '/config/traceEnabled' }
   paramConvs = {
      PARAM_TRACE : {
         "Extract": lambda v: True if v == "true" else False,
         "Set": lambda v: "true" if v else "false",
         }
      }

   category = CATEGORY_ADVANCED_CONFIG_SETTING
   component = COMPONENT_HP_LOGGING_CONFIG

