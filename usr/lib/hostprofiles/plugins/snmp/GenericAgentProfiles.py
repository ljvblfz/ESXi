#!/usr/bin/python
# **********************************************************
# Copyright 2014 VMware, Inc.  All rights reserved.
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import ParameterMetadata, CreateLocalizedException
from pluginApi import CreateLocalizedMessage
from pluginApi import log, ProfileComplianceChecker
from pluginApi import PolicyOptComplianceChecker
from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING
from pluginApi import COMPONENT_MANAGED_AGENT_CONFIG
from pluginApi import GenericProfile
from pluginApi import Policy
from pluginApi import TASK_LIST_RES_OK
from pluginApi import FixedPolicyOption, UserInputRequiredOption
from pluginApi.extensions import SimpleConfigProfile
from vmware import runcommand
from .snmpConstants import *
from .GenericAgentPolicies import SNMPParamChecker, FixedUsersOption
from .GenericAgentPolicies import FixedV3TargetsOption, FixedEngineIdOption
from .GenericAgentPolicies import FixedContactOption, FixedLocationOption
from .GenericAgentPolicies import UsersPolicy, V3TargetsPolicy, EngineIdPolicy
from .GenericAgentPolicies import SystemContactPolicy, SystemLocationPolicy
import xml.dom.minidom
from vmkctl import SnmpAgentConfigImpl
from sys import exc_info

# Common functions for both AgentConfigProfile and AgentConfigProfileOthers

def ExecRealEsxcli(hostServices, namespace, cmd, arglist):
   '''
   Run esxcli in order for hostd to be notified about changes to snmp agent configuration
   state
   '''
   cmdStr = '%s %s %s' % (namespace, cmd, ' '.join(arglist))
   log.info('Running cmd: %s' % cmdStr)
   errCode, output = hostServices.ExecuteRemoteEsxcli(cmdStr)
   return (errCode, output)

def ExecCli(hostServices, cmd, opts=list(), namespace=None):
   '''Helper method that invokes esxcli for sets, localcli for gets
   and performs generic error handling.
   '''
   status = 1
   if namespace is None:
      namespace = ESXCLI_SNMP_NS

   if cmd == ESXCLI_SNMP_SET: # must run esxcli not localcli
      status, output = ExecRealEsxcli(hostServices, namespace, cmd, opts)
      if status != 0:
         log.warning('esxcli failed %s, will retry with localcli %s' % (status, output))

   if status != 0:
      status, output = hostServices.ExecuteEsxcli(namespace, cmd, opts) # calls localcli

   if status != 0:
      errArgs = { 'error' : output }
      errKey = ESXCLI_BASE_ERR_KEY + cmd.capitalize()
      log.error("SNMP plugin failed to run esxcli command '%s': %s" % \
                (cmd, output))
      raise CreateLocalizedException(None, errKey, errArgs)
   return output

def TransformToProfile(paramName, cliOutput, profileConfig):
   '''
   A helper method that will transform the parameter value from the esxcli
   output into the format expected by the host profile config data.
   example:
   esxcli output for v3targets: ['test1 user1 none inform','test2 user2 none inform']
   esxcli input for v3targets: 'test1/user1/none/inform,test2/user2/none/inform'
   '''

   if paramName in cliOutput:
      # cli output for USERS and V3TARGETS is a list
      if paramName == USERS or paramName == V3TARGETS:
         # Convert right here to esxcli input format
         interList = [ values.strip().replace(' ','/') for values in \
                       cliOutput[paramName] ]
         cliOutput[paramName] = ','.join(interList)

      profileConfig[paramName] = cliOutput[paramName]
   else:
      log.info('Skipping param "%s", not seen in cli output' % paramName)


# Function to clear the values in /etc/vmware/snml.xml
# The options to be cleared are passed as a list
# Once the feature in PR 1284714 is completed, we can
# remove this and use the esxcli command instead
def clearText(optionList):
   try:
      dom = xml.dom.minidom.parse(SNMP_CONFIG_FILE)
   except Exception as err:
      log.error('Failed to parse snmp.xml %s' % str(err))
      errArgs = { 'error' : str(err) }
      errKey = SNMP_CONFIG_FILE_ERROR
      raise CreateLocalizedException(None, errKey, errArgs)

   file_handle = open(SNMP_CONFIG_FILE, 'w')
   for option in optionList:
      # In the xml file, 'users' is actually 'v3users'.
      if option == 'users':
         option = 'v3users'
      try:
         currentNode = dom.getElementsByTagName(option)
         if currentNode:
            currentChild = currentNode[0]
            if currentChild.firstChild is not None:
               # Create empty text node to replace current text
               newNode = dom.createTextNode('')
               currentChild.replaceChild(newNode, currentChild.firstChild)
      except Exception as err:
            log.error('Failed to clear value for option %s ' % option)
            errArgs = { 'error' : str(err) }
            errKey = SNMP_CONFIG_FILE_ERROR
            raise CreateLocalizedException(None, errKey, errArgs)

   # Write the xml back to the file
   dom.writexml(file_handle)
   file_handle.close()

class SNMPCommunitiesAndTrapsParamChecker():

   @staticmethod
   def Validate(obj, argName, arg, errors):
      if not arg:
         return True
      try:
         snmpObject = SnmpAgentConfigImpl()
         if argName == COMMUNITIES:
            snmpObject.SetCommunities(arg)
         else:
            snmpObject.SetTrapTargets(arg)
      except:
         error = str(exc_info()[1])
         log.error('Parameter value invalid for %s=%s: %s' \
                     % (argName, arg, error))
         msg_key = SNMP_VALIDATE_ERROR + '.' + argName
         msg = CreateLocalizedMessage(None, msg_key)
         errors.append(msg)
         return False
      return True

class SNMPProfileChecker(ProfileComplianceChecker):

   @classmethod
   def CheckProfileCompliance(self, profileInstances,
                              hostServices, profileData, parent):
      # Called implicitly
      assert len(profileInstances) == 1

      # Likewise all the policy checkers are called implicitly and
      # there is nothing more to check at the profile level cross-policies.

      return (True, [])

class GenericAgentConfigProfile(GenericProfile):
   '''
   Define required class attributes
   '''
   singleton = True
   policies = [ SystemLocationPolicy , SystemContactPolicy , EngineIdPolicy, \
                V3TargetsPolicy, UsersPolicy ]
   isOptional = True

   # set where you need to place it in the UI
   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_MANAGED_AGENT_CONFIG

   parameters = [ SYSLOCATION, SYSCONTACT, ENGINEID, V3TARGETS, USERS ]
   complianceChecker = SNMPProfileChecker()

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):

      assert len(profileInstances) == 1
      profile = profileInstances[0]

      result = TASK_LIST_RES_OK

      # Generate the task list for each policy
      try:
         for policy in profile.policies:
            result = policy.GenerateTaskList(policy, taskList, profileData, parent)
      except Exception as err:
         log.error('GenerateTaskList failed %s ' % str(err))

      # Nothing more to generate at the profile level

      return result

   @classmethod
   def GatherData(cls, hostServices):
      '''
      Retrieve SNMP agent configuration from cmd: localcli system snmp get.
      '''
      try:
         cfg = dict()
         output = ExecCli(hostServices, ESXCLI_SNMP_GET)
         log.debug('GenericAgentProfiles: Output is %s ' % str(output))

         try:
            for paramName in cls.parameters:
               # Process generic profile parameters
               TransformToProfile(paramName, output, cfg)
         except Exception as err:
            log.error('Error in transforming esxcli output to profile %s' % \
                     str(err))

      except Exception as err:
         log.error('localcli system snmp get failed %s' % str(err))

      log.info('GenericAgentConfigProfiles::GatherData: returning {%s}' % cfg)
      return cfg

   @classmethod
   def _CreateProfileInst(cls, profileDataItems):
      '''
      Helper method that creates a profile instance.
      '''
      policies = []
      PolicyOptionMap = { SYSLOCATION : FixedLocationOption,
                          SYSCONTACT  : FixedContactOption,
                          ENGINEID    : FixedEngineIdOption,
                          V3TARGETS   : FixedV3TargetsOption,
                          USERS       : FixedUsersOption }

      PolicyMap = { SYSLOCATION : SystemLocationPolicy,
                    SYSCONTACT  : SystemContactPolicy,
                    ENGINEID    : EngineIdPolicy,
                    V3TARGETS   : V3TargetsPolicy,
                    USERS       : UsersPolicy }

      for moduleName, moduleParams in profileDataItems:
         log.debug('Creating profile instance for %s' % str(moduleName))
         try:
            param = [moduleName, moduleParams]
            params = [param]
            policyOpt = PolicyOptionMap[moduleName](params)
            policies.append(PolicyMap[moduleName](True, policyOpt))
         except Exception as err:
            log.error('Creating profile instance failed for %s : %s' \
                     % (moduleName, str(err)))

      return cls(policies = policies)

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      '''
      Implementation of GenericAgentConfigProfile.GenerateProfileFromConfig
      '''
      modules = []
      modules = cls._CreateProfileInst(profileData.items())
      return modules

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, profileData):
      '''
      The function which sets the values given in the taskList
      '''
      log.debug('In GenericAgentProfile remediate config')

      # Parameters which cannot be set with an empty value using esxcli.
      optionsList = [ 'users', 'v3targets', 'engineid' ]

      clearList = []
      opts = []
      for taskOp, taskArg in taskList:
         try:
            # If desired value is empty, and param in optionsList, we need
            # to clear the text in snmp.xml.
            if not taskArg and TASK_MAP[taskOp] in optionsList:
               clearList.append(TASK_MAP[taskOp])
               continue

            if taskOp in[ SNMP_ENGINEID_TASK, SNMP_SYSLOCATION_TASK,
                          SNMP_SYSCONTACT_TASK ]:
               taskArg = "\"%s\"" % taskArg

            opt = '--%s=%s' % (TASK_MAP[taskOp], taskArg)
            opts.append(opt)
         except Exception as err:
            log.warning('Transforming parameter failed for item %s=%s: %s' % \
               (taskOp, taskArg, str(err)))
            log.error('GenericAgentProfiles: RemediateConfig failed')
            return

      try:
         # Clear the ones which cannot be cleared using esxcli.
         if clearList:
            log.info('Clearing values for %s' % clearList)
            clearText(clearList)
         # Set the rest (if any) using esxcli.
         if opts:
               ExecCli(hostServices, ESXCLI_SNMP_SET, opts)
      except Exception as err:
         log.error('GenericAgentProfiles: Failed to set snmp ' \
                   'configuration %s' % str(err))

      return

class AgentConfigProfileOthers(SimpleConfigProfile):
   '''
   Extract and Install ESX SNMPv1/2c/3 AGENT configuration
   '''
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
                        mappingAttributePath = { 'vim' : 'readOnlyCommunities'},
                        paramChecker=SNMPCommunitiesAndTrapsParamChecker),
      ParameterMetadata(TARGETS, 'string[]', isOptional,
                        paramChecker=SNMPCommunitiesAndTrapsParamChecker),
      ParameterMetadata(LOGLEVEL, 'string', isOptional,
                        paramChecker=SNMPParamChecker),
      ParameterMetadata(AUTH_PROTOCOL, 'string', isOptional, '',
                        paramChecker=SNMPParamChecker),
      ParameterMetadata(PRIV_PROTOCOL, 'string', isOptional, '',
                        paramChecker=SNMPParamChecker),
      ParameterMetadata(REMOTE_USERS, 'string[]', isOptional),
      ParameterMetadata(EV_SOURCE, 'string', isOptional,
                        paramChecker=SNMPParamChecker),
      ParameterMetadata(EV_FILTER, 'string[]', isOptional),
      ParameterMetadata(LARGESTORAGE, 'bool', isOptional, defaultValue=True,
                        mappingAttributePath = { 'vim' : 'enabled' }),
      ]

   singleton = True
   parentProfiles = [ GenericAgentConfigProfile ]

   @classmethod
   def ExtractConfig(cls, hostServices):
      '''
      Retrieve SNMP agent configuration from cmd: localcli system snmp get.
      '''
      try:
         cfg = dict()
         output = ExecCli(hostServices, ESXCLI_SNMP_GET)
         for paramMeta in cls.parameters:
            TransformToProfile(paramMeta.paramName, output, cfg)
      except Exception as err:
         log.error('localcli system snmp get failed %s' % str(err))
         return

      log.info('AgentProfiles::ExtractConfig: returning {%s}' % cfg)
      return cfg

   @classmethod
   def SetConfig(cls, config, hostServices):
      '''
      Load snmp agent configuration into ESX via cmd: esxcli system snmp set
      '''
      ok = True
      # Reset values for parameters which do not take in an
      # empty value
      optionsList = ['communities', 'authProtocol', 'EventFilter',
                     'privProtocol', 'RemoteUsers', 'targets' ]
      clearText(optionsList)
      # Check if config is a list, if so get first config
      if isinstance(config, list):
         config = config[0]
      try:
         log.info('AgentProfiles::SetConfig config {%s}' % str(config))

         opts = []
         for flag, paramVal in config.items():
            if paramVal is not None:
               try:
                  used, value = cls._TransformToEsxcli(flag, paramVal)
                  if used:
                     opt = '--%s=%s' % (flag, value)
                     opts.append(opt)
               except Exception as err:
                  log.warning('Transform param failed for item %s=%s, msg=%s' % (flag, paramVal, str(err)))
                  ok = False
                  break
         if ok:
            log.info('AgentProfiles::SetConfig options {%s}' % str(opts))
            ExecCli(hostServices, ESXCLI_SNMP_SET, opts)
            log.info('AgentProfiles:SetConfig completed ok')
         else:
            log.error('AgentProfiles:SetConfig failed, see prior messages.')
      except Exception as err:
         log.warning('esxcli system snmp set command failed: %s' % str(err))

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

      # covers all string[] type Parameters: REMOTE_USERS, TARGETS, EV_FILTER
      if isinstance(paramVal, list):
         if paramVal:
            return (True, ','.join([ cls._TransformListItem(paramItem) for paramItem in paramVal]))
         else:
            return noParam
      elif paramKey == TARGETS or paramKey == REMOTE_USERS \
               or paramKey == EV_FILTER or paramKey == COMMUNITIES:
         return (True, paramVal.replace(' ', '/'))
      elif paramKey == ENABLE:
         return (True, paramVal and 'true' or 'false')
      elif paramKey == PORT:
         return (True, paramVal)
      elif paramKey == EV_SOURCE or paramKey == PRIV_PROTOCOL or paramKey == AUTH_PROTOCOL :
         if len(paramVal) == 0:
            return noParam
         else:
            return (True, "\"%s\"" % paramVal)
      elif paramKey == LOGLEVEL:
         return (True, paramVal)
      elif paramKey == LARGESTORAGE:
         return (True, paramVal and 'true' or 'false')
      return (True, "\''%s'\'" % str(paramVal))

GenericAgentConfigProfile.subprofiles = [ AgentConfigProfileOthers ]

