#!/usr/bin/env python
# Hey Emacs, -*- mode: Python; coding: utf-8 -*-
# **********************************************************
#
'''
For details on Host Profiles plugins see
https://wiki/VmKag/Projects/MNHostProfiles/Extensibility/PluginHowTo
https://wiki/VmKag/Projects/MNHostProfiles/Extensibility#Examples
'''

__author__ = "VMware, Inc."
__copyright__ = "Copyright 2010-2014 VMware, Inc.  All rights reserved."

from pluginApi import ParameterMetadata, CreateLocalizedException
from pluginApi import log
from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING
from pluginApi import COMPONENT_MANAGED_AGENT_CONFIG
from pluginApi.extensions import SimpleConfigProfile
from vmware import runcommand

# localized msgs in profile.vmsg for this module are keyed from:
AGENT_BASE_KEY = 'com.vmware.profile.AgentConfigProfile'
DEFAULT_SNMP_PORT = 161
# Constants for esxcli commands and errors
ESXCLI_SNMP_NS = 'system snmp'
ESXCLI_SNMP_GET = 'get'
ESXCLI_SNMP_SET = 'set'
ESXCLI_BASE_ERR_KEY = '%s.Esxcli' % AGENT_BASE_KEY

# The following 14 xml elements returned by cmd: esxcli system snmp get
# mostly match the xml element names found /etc/vmware/snmp.xml
# for which the mappings to snmp.xml are provided below. Differences
# were due to maintaining --flag-name backward compatiblity
# with RCLI: vicfg-snmp command
AUTH_PROTOCOL = 'authentication' # aka authProtocol
COMMUNITIES = 'communities'
ENABLE = 'enable'
ENGINEID = 'engineid'
EV_FILTER = 'notraps' # aka EventFilter
EV_SOURCE = 'hwsrc' # aka EnvEventSource
LOGLEVEL = 'loglevel'
PORT = 'port'
PRIV_PROTOCOL = 'privacy' # aka privProtocol
SYSCONTACT = 'syscontact'
SYSLOCATION = 'syslocation'
TARGETS = 'targets'
USERS = "users"
REMOTE_USERS = 'remote-users'
V3TARGETS = 'v3targets'
LARGESTORAGE = 'largestorage'

# for info on parameters see:
# wiki.eng.vmware.com/VmKag/Projects/MNHostProfiles/Extensibility#ParameterMetadata_Class

class AgentConfigProfile(SimpleConfigProfile):
   '''
   Extract and Install ESX SNMPv1/2c/3 AGENT configuration
   '''
   deprecatedFlag = True
   enableDeprecatedVerify = True
   enableDeprecatedApply = True
   # def __init(self)__ not needed
   # base class bits
   isOptional = True

   # vCM Mapping base. The VIM API for SNMP is deprecated in 5.1 in favor of
   # esxcli, and the host profile doesn't map well to the VIM API, hence a
   # limited amount of mapping data.
   mappingBasePath = { 'vim': 'configManager.snmpSystem.configuration' }

   parameters = [
      ParameterMetadata(ENABLE, 'bool', isOptional, defaultValue=False,
                        mappingAttributePath = { 'vim' : 'enabled' }),
      ParameterMetadata(PORT, 'int', isOptional,
                        defaultValue=DEFAULT_SNMP_PORT,
                        mappingAttributePath = { 'vim' : 'port' }),
      ParameterMetadata(COMMUNITIES, 'string[]', isOptional,
                        mappingAttributePath = { 'vim' : 'readOnlyCommunities' }),
      ParameterMetadata(TARGETS, 'string[]', isOptional),
      ParameterMetadata(ENGINEID, 'string', isOptional),
      ParameterMetadata(SYSLOCATION, 'string', isOptional),
      ParameterMetadata(SYSCONTACT, 'string', isOptional),
      ParameterMetadata(LOGLEVEL, 'string', isOptional),
      ParameterMetadata(AUTH_PROTOCOL, 'string', isOptional),
      ParameterMetadata(PRIV_PROTOCOL, 'string', isOptional),
      ParameterMetadata(V3TARGETS, 'string[]', isOptional),
      ParameterMetadata(USERS, 'string[]', isOptional),
      ParameterMetadata(REMOTE_USERS, 'string[]', isOptional),
      ParameterMetadata(EV_SOURCE, 'string', isOptional),
      ParameterMetadata(EV_FILTER, 'string[]', isOptional),
      ParameterMetadata(LARGESTORAGE, 'bool', isOptional, defaultValue=True,
                        mappingAttributePath = { 'vim' : 'enabled' }),
      ]

   singleton = True
   # parentProfiles not needed

   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_MANAGED_AGENT_CONFIG

   # ESX 5.0 Vim.KeyValue type array name containing EV_* options
   OPTIONS = 'option'

   @classmethod
   def ExtractConfig(cls, hostServices):
      '''
      Retrieve SNMP agent configuration from cmd: localcli system snmp get.
      '''
      try:
         cfg = dict()
         output = cls.ExecCli(hostServices, ESXCLI_SNMP_GET)
         for paramMeta in cls.parameters:
            cls._TransformToProfile(paramMeta.paramName, output, cfg)
      except Exception as err:
         log.error("localcli system snmp get failed %s" % str(err))
         return
      if cls._GetProfileOperationVersion() == "5.0.0":
         log.info('AgentProfiles::ExtractConfig: system reporting 5.0, matching profile {%s}' % cfg)
         cfg = cls._ConvertToVersion50(cfg)
      else:
         log.info('AgentProfiles::ExtractConfig: profile, version > 5.0')
      log.info('AgentProfiles::ExtractConfig: returning {%s}' % cfg)
      return cfg


   @classmethod
   def _ConvertToVersion50(cls, new_cfg):
      '''Extract from new_cfg only those options that were in the 5.0 snmp agent profile '''
      OPTIONS = cls.OPTIONS
      cfg50 = dict()
      keys = [ ENABLE, PORT, COMMUNITIES, TARGETS ]
      for item in keys:
         cfg50[item] = new_cfg[item]

      opts50 = []
      keys = sorted([ EV_FILTER, EV_SOURCE, SYSCONTACT, SYSLOCATION ])
      revisions = {EV_SOURCE : 'EnvEventSource', EV_FILTER : 'EventFilter' }
      for item in keys:
         if item in new_cfg:
            if item in revisions:
               elem = revisions[item]
            else:
               elem = item
            if hasattr(new_cfg[item], '__iter__'):
               val = ",".join(new_cfg[item])
            else:
               val = new_cfg[item]
            if len(val) > 0:
               opts50.append("%s=%s" % (elem, val))

      if opts50:
         cfg50[OPTIONS] = opts50
      return cfg50

   @classmethod
   def _ConvertToVersion51(cls, config):
    ''' convert 5.0 config to 5.1+ '''
    try:
       OPTIONS = cls.OPTIONS
       if OPTIONS in config:
          opts = config[OPTIONS]
          revisions = {'EnvEventSource' : EV_SOURCE, 'EventFilter' : EV_FILTER }
          for item in opts:
             (key, value) = item.split('=')
             if key in revisions:
                key = revisions[key]
             config[key] = value
          del config[OPTIONS]
    except Exception as err:
       log.warning("convert config %s  to 5.1 failed %s" % (config, err))
    return config


   @classmethod
   def _TransformToProfile(cls, paramName, cliOutput, profileConfig):
      '''
      A helper method that will transform the parameter value from the esxcli
      output into the format expected by the host profile config data.
      '''

      if paramName in cliOutput:
         profileConfig[paramName] = cliOutput[paramName]
      else:
         log.info('skipping param "%s", not seen in cli output' % paramName)

   @classmethod
   def SetConfig(cls, config, hostServices):
      '''
      Load snmp agent configuration into ESX via cmd: esxcli system snmp set
      '''
      ok = True
      try: # check if config is a list, if so get first config
         if config[ENABLE]:
            pass
      except TypeError:
         config = config[0]
      try:
         log.info('AgentProfiles::SetConfig config {%s}' % str(config))

         if cls._GetProfileOperationVersion() == "5.0.0":
            config = cls._ConvertToVersion51(config)
            log.info('AgentProfiles::SetConfig 5.0 config {%s}' % str(config))

         opts = ['--reset']  # first step to take is to clear out any config
         for flag, paramVal in config.items():
            if paramVal is not None:
               try:
                  used, value = cls._TransformToEsxcli(flag, paramVal)
                  if used:
                     opt = '--%s=%s' % (flag, value)
                     opts.append(opt)
               except Exception as err:
                  log.warning("Transform param failed for item %s=%s, msg=%s" % (flag, paramVal, str(err)))
                  ok = False
                  break
         if ok:
            log.info('AgentProfiles::SetConfig options {%s}' % str(opts))
            cls.ExecCli(hostServices, ESXCLI_SNMP_SET, opts)
            log.info('AgentProfiles:SetConfig completed ok')
         else:
            log.error("AgentProfiles:SetConfig failed, see prior messages.")
      except Exception as err:
         log.warning("esxcli system snmp set command failed: %s" % str(err))

      return

   @classmethod
   def _TransformListItem(cls, paramVal):
      '''
      Modify paramVal to the format used in esxcli system snmp set.
      '''
      return paramVal.replace(' ', '/')

   @classmethod
   def _TransformToEsxcli(cls, paramKey, paramVal):
      '''
      Helper method that transforms a parameter value from host profile into
      a string format acceptable to the "esxcli system snmp set" command.
      return tuple of boolean,value where boolean means to add the flag
      else ignore value
      '''
      noParam = (False, None)

      # covers all string[] type Parameters: USERS, REMOTE_USERS, TARGETS, V3TARGETS, EV_FILTER
      if isinstance(paramVal, list):
         if paramVal:
            return (True, ','.join([ cls._TransformListItem(paramItem) for paramItem in paramVal]))
         else:
            return noParam
      elif paramKey == TARGETS or paramKey == V3TARGETS or paramKey == USERS or paramKey == REMOTE_USERS \
               or paramKey == EV_FILTER or paramKey == COMMUNITIES:
         return (True, paramVal.replace(' ', '/'))
      elif paramKey == ENABLE:
         return (True, paramVal and 'true' or 'false')
      elif paramKey == PORT:
         return (True, paramVal)
      elif paramKey == EV_SOURCE or paramKey == PRIV_PROTOCOL or paramKey == AUTH_PROTOCOL \
               or paramKey == SYSLOCATION or paramKey == SYSCONTACT:
         if len(paramVal) == 0:
            return noParam
         else:
            return (True, "\"%s\"" % paramVal)
      elif paramKey == LOGLEVEL:
         return (True, paramVal)
      elif paramKey == ENGINEID:
         if len(paramVal) > 0:
            return (True, "\"%s\"" % paramVal)
         else:
            return noParam
      elif paramKey == LARGESTORAGE:
         return (True, paramVal and 'true' or 'false')
      return (True, "\''%s'\'" % str(paramVal))

   @staticmethod
   def ExecRealEsxcli(namespace, cmd, arglist):
      '''
      Run esxcli in order for hostd to be notified about changes to snmp agent configuration
      state, Like hostServices.ExecuteEsxcli, it returns tuple of (exit-code, error msg string)
      '''
      cmdStr = "/sbin/esxcli %s %s %s" % (namespace, cmd, " ".join(arglist))
      log.info("Running cmd: %s" % cmdStr)
      errCode, output = runcommand.runcommand(cmdStr)
      return (errCode, output)

   @staticmethod
   def ExecCli(hostServices, cmd, opts=list(), namespace=None):
      '''Helper method that invokes esxcli for sets, localcli for gets
      and performs generic error handling.
      '''
      again = True
      if namespace is None:
         namespace = ESXCLI_SNMP_NS

      if cmd == ESXCLI_SNMP_SET: # must run esxcli not localcli
         status, output = AgentConfigProfile.ExecRealEsxcli(namespace, cmd, opts)
         if status == 0:
            again = False
         else:
            log.warning("esxcli failed %s, will retry with localcli %s" % (status, output))

      if again:
         status, output = hostServices.ExecuteEsxcli(namespace, cmd, opts) # calls localcli

      if status != 0:
         errArgs = { 'error' : output }
         errKey = ESXCLI_BASE_ERR_KEY + cmd.capitalize()
         log.error('SNMP plugin failed to run esxcli command "%s": %s' % \
                   (cmd, output))
         raise CreateLocalizedException(None, errKey, errArgs)

      return output

