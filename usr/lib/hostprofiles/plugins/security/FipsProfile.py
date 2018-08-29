#!/usr/bin/python
# **********************************************************
# Copyright 2017 VMware, Inc.  All rights reserved.
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi.extensions import SimpleConfigProfile, ChoiceValidator
from pluginApi import log, ParameterMetadata, CreateLocalizedException
from pluginApi import CATEGORY_SECURITY_SERVICES, COMPONENT_SERVICE_SETTING, \
                      TASK_LIST_REQ_REBOOT

# Error message keys
FP_MSG_KEY_BASE = 'com.vmware.profile.FipsProfile'
FP_CLI_ERROR_KEY = '%s.cliError' % FP_MSG_KEY_BASE

# Command strings
FP_CLI_GET_CMD = 'system security fips140 %s get'
FP_CLI_SET_CMD = 'system security fips140 %s set --enable %s'

# List of supported services.
SERVICE_LIST = [ 'rhttpproxy', 'ssh' ]

def InvokeLocalcli(hostServices, *args):
   ''' Helper function for invoking localcli and processing errors. '''
   if args is None:
      return None
   log.debug('FIPS profile invoking localcli command %r' % args)
   status, output = hostServices.ExecuteLocalEsxcli(*args)
   if status != 0:
      if not isinstance(output, str):
         log.warning('LOCALCLI error output not a string for '
                     'arguments %r' % args)
      errMsgData = { 'error': output }
      errMsg = 'FIPS Profile: Error issuing localcli ' + \
               'with arguments %r: %r' % (args, output)
      log.error(errMsg)
      raise CreateLocalizedException(None, FP_CLI_ERROR_KEY, errMsgData)
   return output


class FipsProfile(SimpleConfigProfile):
   ''' A simple profile to set the FIPS mode for particular services.'''

   # Allow multiple instances of this profile.
   singleton = False
   # Request reboot if config is changed.
   setConfigReq = TASK_LIST_REQ_REBOOT
   # Config ID -- This field cannot have duplicates.
   idConfigKeys = ['service']
   parameters = [
      ParameterMetadata('service', 'string', False,
                        paramChecker=ChoiceValidator(SERVICE_LIST)),
      ParameterMetadata('enabled', 'bool', False)
   ]
   category = CATEGORY_SECURITY_SERVICES
   component = COMPONENT_SERVICE_SETTING

   @classmethod
   def _GetFipsMode(cls, hostServices, serviceName):
      ''' '''
      # Get current status of service
      cmd = FP_CLI_GET_CMD % serviceName
      output = InvokeLocalcli(hostServices, cmd.split())
      return output['Enabled']

   @classmethod
   def _SetFipsMode(cls, hostServices, serviceName, enabled):
      ''' '''
      # Set FIPS mode for given service
      cmd = FP_CLI_SET_CMD % (serviceName, str(enabled).lower())
      InvokeLocalcli(hostServices, cmd.split())

   @classmethod
   def ExtractConfig(cls, hostServices):
      ''' Return the list of services and if FIPS mode is enabled for them. '''
      cfgList = []
      for s in SERVICE_LIST:
         cfg = { 'service' : s,
                 'enabled' : cls._GetFipsMode(hostServices, s) }
         cfgList.append(cfg)

      return cfgList

   @classmethod
   def SetConfig(cls, configList, hostServices):
      ''' Set the FIPS mode to given configuration. '''
      for c in configList:
         cls._SetFipsMode(hostServices, c['service'], c['enabled'])
