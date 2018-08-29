#!/usr/bin/python
# **********************************************************
# Copyright 2014-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import ParameterMetadata, CreateLocalizedException
from pluginApi import CreateLocalizedMessage
from pluginApi import CreateComplianceFailureValues, PARAM_NAME
from pluginApi import log
from pluginApi import PolicyOptComplianceChecker
from pluginApi import Policy
from pluginApi import TASK_LIST_RES_OK
from pluginApi import FixedPolicyOption, UserInputRequiredOption
from vmkctl import SnmpAgentConfigImpl
from .snmpConstants import *
from sys import exc_info
from pyVmomi import Vim

def NormalizeEngineID(engineID):
   '''
   This function mimics the behavior of NormalizeEngineID() function in
   SnmpAgentSet.cpp
   Converts following string formats as:
   a) 0xhex -> hex
   b) 00:11:22:33 -> 0011233
   c) 0:1:2:3 -> 00010203
   and trims off any whitespace
   '''
   engineID = engineID.strip()
   if engineID.startswith('0x'):
         engineID = engineID[2:]
   if ':' in engineID:
      tokens = engineID.split(':')
      engineID = ''
      for token in tokens:
         if len(token) == 1:
            token = '0' + token
         engineID = engineID + token
   return engineID

class SNMPPoliciesComplianceChecker(PolicyOptComplianceChecker):

   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt,
                             hostServices, profileData):
      assert(policyOpt.paramValue is not None)

      desired = ''
      # Obtain the policy option name
      if 'FixedPolicyOption' in str(policyOpt.__class__.__bases__):
         name = policyOpt.paramMeta[0].paramName
      else:
         assert('UserInputRequiredOption' in str(policyOpt.__class__.__bases__))
         name = policyOpt.userInputParamMeta[0].paramName

      # policOpt.paramValue is a list of parameter-name, value tuples
      for paramName, desiredValue in policyOpt.paramValue:
         if paramName == name:
            desired = desiredValue
            break

      actual = profileData[name] #info from host
      hostValue = actual
      profileValue = desired
      if actual is None:
         actual = ''
      if desired is None:
         desired = ''
      log.debug('Desired  value is %s, current value is %s ' \
               % (str(desired), str(actual)))

      # Special handling for 'users' and 'v3targets' since they can contain
      # multiple values
      if name == USERS or name == V3TARGETS:
         # Convert string to lists and then to sets for unordered comparison
         desired = set(desired.split(','))
         actual = set(actual.split(','))
      elif name == ENGINEID:
         # Normalize the engineID before comparison
         desired = NormalizeEngineID(desired)

      # Compare actual and desired values
      if actual != desired:
         # If EngineID is empty, and the V3 parameters
         # (users and v3targets) haven't been set,
         # then ignore compliance check and return true
         if name == ENGINEID and desired == '' and \
            not profileData[V3TARGETS] and not profileData[USERS]:

            log.warning('Engine ID mismatch. Compliance ignored since ' + \
                        'V3 is not used')
            return (True, [])

         log.warning('GenericAgentConfigProfile: Value mismatch in : %s' \
                     % paramName)
         msg = CreateLocalizedMessage(None, SNMP_COMMON_COMPLIANCE_KEY,
                                      {'paramName': paramName})

         comparisonValues = CreateComplianceFailureValues(
                               paramName, PARAM_NAME,
                               profileValue=profileValue, hostValue=hostValue)

         return (False, [(msg, [comparisonValues])])

      return (True, [])

class SNMPParamChecker():

   @staticmethod
   def Validate(obj, argName, arg, errors):
      # Since all parameters are optional,
      # their values can be blank
      if not arg:
         return True

      snmpObject = SnmpAgentConfigImpl()
      if argName == EV_SOURCE:
         argName = 'EnvEventSource'
      # Need to normalize engineid before validating
      if argName == ENGINEID:
         arg = NormalizeEngineID(arg)
      snmpDict = {argName : arg}
      log.debug('Validating: %s' % str(snmpDict))
      try:
         snmpObject.SetOptions(snmpDict)
      except:
         error = str(exc_info()[1])
         log.error('Parameter value invalid for %s=%s: %s' \
                     % (argName, arg, error))
         msg_key = SNMP_VALIDATE_ERROR + '.' + argName
         msg = CreateLocalizedMessage(None, msg_key)
         errors.append(msg)
         return False
      return True

class SNMPUsersAndTargetsParamChecker():

   @staticmethod
   def Validate(obj, argName, arg, errors):
      # Blank values are valid
      if not arg:
         return True

      # Need to convert to a list for validation
      arg = arg.split(',')
      snmpObject = SnmpAgentConfigImpl()
      try:
         if argName == USERS:
            snmpObject.SetUsers(arg)
         else:
            snmpObject.SetV3Targets(arg)
      except:
         error = str(exc_info()[1])
         log.error('Parameter value invalid for %s=%s: %s' \
                     % (argName, arg, error))
         msg_key = SNMP_VALIDATE_ERROR + '.' + argName
         msg = CreateLocalizedMessage(None, msg_key)
         errors.append(msg)
         return False
      return True

class UserInputUsers(UserInputRequiredOption):
   '''
   Policy option which sets a per-host value
   '''
   userInputParamMeta = [
      ParameterMetadata(USERS, 'string', True,
                        paramChecker=SNMPUsersAndTargetsParamChecker),
   ]
   complianceChecker = SNMPPoliciesComplianceChecker

class FixedUsersOption(FixedPolicyOption):
   '''
   The policy option which sets a fixed value for all applicable hosts
   '''
   paramMeta = [
      ParameterMetadata(USERS, 'string', True,
                        paramChecker=SNMPUsersAndTargetsParamChecker),
   ]
   complianceChecker = SNMPPoliciesComplianceChecker

class UserInputV3Targets(UserInputRequiredOption):
   '''
   Policy option which sets a per-host value
   '''
   userInputParamMeta = [
      ParameterMetadata(V3TARGETS, 'string', True,
                        paramChecker=SNMPUsersAndTargetsParamChecker),
   ]
   complianceChecker = SNMPPoliciesComplianceChecker

class FixedV3TargetsOption(FixedPolicyOption):
   '''
   The policy option which sets a fixed value for all applicable hosts
   '''
   paramMeta = [
      ParameterMetadata(V3TARGETS, 'string', True,
                        paramChecker=SNMPUsersAndTargetsParamChecker),
   ]
   complianceChecker = SNMPPoliciesComplianceChecker

class UserInputEngineId(UserInputRequiredOption):
   '''
   Policy option which sets a per-host value
   '''
   userInputParamMeta = [
      ParameterMetadata(ENGINEID, 'string', True,
                        paramChecker=SNMPParamChecker),
   ]
   complianceChecker = SNMPPoliciesComplianceChecker

class FixedEngineIdOption(FixedPolicyOption):
   '''
   The policy option which sets a fixed value for all applicable hosts
   '''
   paramMeta = [
      ParameterMetadata(ENGINEID, 'string', True,
                        paramChecker=SNMPParamChecker),
   ]
   complianceChecker = SNMPPoliciesComplianceChecker

class UserInputContact(UserInputRequiredOption):
   '''
   Policy option which sets a per-host value
   '''
   userInputParamMeta = [
      ParameterMetadata(SYSCONTACT, 'string', True, '',
                        paramChecker=SNMPParamChecker),
   ]
   complianceChecker = SNMPPoliciesComplianceChecker

class FixedContactOption(FixedPolicyOption):
   '''
   The policy option which sets a fixed value for all applicable hosts
   '''
   paramMeta = [
      ParameterMetadata(SYSCONTACT, 'string', True, '',
                        paramChecker=SNMPParamChecker),
   ]
   complianceChecker = SNMPPoliciesComplianceChecker

class UserInputLocation(UserInputRequiredOption):
   '''
   Policy option which sets a per-host value
   '''
   userInputParamMeta = [
      ParameterMetadata(SYSLOCATION, 'string', True, '',
                        paramChecker=SNMPParamChecker),
   ]
   complianceChecker = SNMPPoliciesComplianceChecker

class FixedLocationOption(FixedPolicyOption):
   '''
   The policy option which sets a fixed value for all applicable hosts
   '''
   paramMeta = [
      ParameterMetadata(SYSLOCATION, 'string', True, '',
                        paramChecker=SNMPParamChecker),
   ]
   complianceChecker = SNMPPoliciesComplianceChecker

def GenerateTaskListCommon(taskList, policyOpt, hostVal,
                           optionName, taskId):
   '''
   A common generate task list function for all policies
   '''
   desired = getattr(policyOpt, optionName)
   # Convert None to empty string for consistency.
   if desired is None:
      desired = ''
   log.debug('Desired value for policy %s is %s' % (optionName, desired))

   if optionName == USERS or optionName == V3TARGETS:
      # Users, V3targets are comma separated strings, so compare their sets.
      equal = set(desired.split(',')) == set(hostVal.split(','))
   else:
      equal = desired == hostVal

   if not equal:
      log.info('Adding task list with value %s for %s.' % (desired, optionName))
      task_msg = SNMP_TASK_BASE + '.' + optionName
      msg = CreateLocalizedMessage(None, task_msg)
      taskList.addTask(msg, (taskId, desired))

   return TASK_LIST_RES_OK

class UsersPolicy(Policy):
   '''
   Define a policy for users
   '''
   possibleOptions = [ FixedUsersOption , UserInputUsers ]

   @classmethod
   def GenerateTaskList(cls, policy, taskList, profileData, parent):
      taskResult = GenerateTaskListCommon(taskList, policy.policyOption,
         profileData[USERS], USERS, SNMP_USERS_TASK)
      return taskResult

class V3TargetsPolicy(Policy):
   '''
   Define a policy for v3targets
   '''
   possibleOptions = [ FixedV3TargetsOption , UserInputV3Targets ]

   @classmethod
   def GenerateTaskList(cls, policy, taskList, profileData, parent):
      taskResult = GenerateTaskListCommon(taskList, policy.policyOption,
         profileData[V3TARGETS], V3TARGETS, SNMP_V3TARGETS_TASK)
      return taskResult

class EngineIdPolicy(Policy):
   '''
   Define a policy for the engineid
   '''
   possibleOptions = [ FixedEngineIdOption , UserInputEngineId ]

   @classmethod
   def GenerateTaskList(cls, policy, taskList, profileData, parent):
      taskResult = GenerateTaskListCommon(taskList, policy.policyOption,
         profileData[ENGINEID], ENGINEID, SNMP_ENGINEID_TASK)
      return taskResult

class SystemContactPolicy(Policy):
   '''
   Define a policy for the system contact
   '''
   possibleOptions = [ FixedContactOption , UserInputContact ]

   @classmethod
   def GenerateTaskList(cls, policy, taskList, profileData, parent):
      taskResult = GenerateTaskListCommon(taskList, policy.policyOption,
         profileData[SYSCONTACT], SYSCONTACT, SNMP_SYSCONTACT_TASK)
      return taskResult

class SystemLocationPolicy(Policy):
   '''
   Define a policy for the system location
   '''
   possibleOptions = [ FixedLocationOption, UserInputLocation ]

   @classmethod
   def GenerateTaskList(cls, policy, taskList, profileData, parent):
      taskResult = GenerateTaskListCommon(taskList, policy.policyOption,
         profileData[SYSLOCATION], SYSLOCATION, SNMP_SYSLOCATION_TASK)
      return taskResult

