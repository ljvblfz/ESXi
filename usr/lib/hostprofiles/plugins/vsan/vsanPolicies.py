#!/usr/bin/python
# **********************************************************
# Copyright 2013-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


import re

from pluginApi import Policy, FixedPolicyOption, UserInputRequiredOption, \
                      ParameterMetadata, PolicyOptComplianceChecker, \
                      CreateLocalizedMessage, log, \
                      CreateComplianceFailureValues, \
                      TASK_LIST_REQ_REBOOT, TASK_LIST_REQ_MAINT_MODE, \
                      TASK_LIST_RES_OK, PARAM_NAME
from pyEngine.nodeputil import IsValidIpv4Address
from hpCommon.constants import RELEASE_VERSION_2015

from .vsanConstants import *
from .vsanUtils import *

###
### Autoclaim Storage policy
###

# Ancillary routine to check compliance and generate remediation task list
def VSANAutoclaimStorageComplianceAndTask(policyOpt, profileData, taskList):
   log.debug('in autoclaim complianceandtask')

   complianceErrors = []
   taskResult = TASK_LIST_RES_OK

   actual = profileData['autoclaimStorage']
   desired = policyOpt.autoclaimStorage

   if actual != desired:
      if taskList:
         msg = CreateLocalizedMessage(None, VSAN_AUTOCLAIM_TASK_KEY)
         # The esxcli command is actually case sensitive and only accepts
         # lowercase true and false
         taskList.addTask(msg, (VSAN_AUTOCLAIM_TASK, str(desired).lower()))
      else:
         msg = CreateLocalizedMessage(None,VSAN_AUTOCLAIMSTORAGE_COMPLIANCE_KEY)
         comparisonValues = CreateComplianceFailureValues('autoclaimStorage',
            PARAM_NAME, profileValue=desired, hostValue=actual)
         complianceErrors.append((msg, [comparisonValues]))

   if taskList:
      return taskResult
   else:
      return complianceErrors

#
class VSANAutoclaimStorageComplianceChecker(PolicyOptComplianceChecker):

   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, \
                                                    hostServices, profileData):
      # Called implicitly
      log.debug('in autoclaim compliancechecker')

      complianceErrors = \
             VSANAutoclaimStorageComplianceAndTask(policyOpt, profileData, None)

      return (len(complianceErrors) == 0, complianceErrors)

#
class VSANAutoclaimStorageOption(FixedPolicyOption):
   paramMeta = [
                  ParameterMetadata('autoclaimStorage', 'bool',
                                    False, VSAN_DEFAULT_AUTOCLAIMSTORAGE)
               ]

   complianceChecker = VSANAutoclaimStorageComplianceChecker

   @classmethod
   def CreateOption(cls, profileData):
      optParams = [('autoclaimStorage', profileData['autoclaimStorage'])]
      return cls(optParams)

#
# Main class
#
# !!! All methods must be called explicitly from the profile's corresponding
# methods.
#
class VSANAutoclaimStoragePolicy(Policy):
   possibleOptions = [
                        VSANAutoclaimStorageOption
                     ]

   @classmethod
   def CreatePolicy(cls, profileData):
      policyOpt = cls.possibleOptions[0].CreateOption(profileData)
      return cls(True, policyOpt)

   @classmethod
   def GenerateTaskList(cls, policy, taskList, profileData, parent):
      log.debug('in autoclaim generate tasklist')
      policyOpt = policy.policyOption

      result = \
         VSANAutoclaimStorageComplianceAndTask(policyOpt, profileData, taskList)

      return result

   @classmethod
   def VerifyPolicy(cls, policy, profileData, validationErrors):
      log.debug('in autoclaim verify policy')

      # Nothing to check

      return True


###
### Enablement policy, including cluster UUID and datastore name
###

# Ancillary routine to check compliance and generate remediation task list
def VSANClusterUUIDComplianceAndTask(policyOpt, profileData, taskList):
   log.debug('in uuid complianceandtask')

   complianceErrors = []
   taskResult = TASK_LIST_RES_OK

   # Check enablement first, since the rest won't matter if disabled is desired
   enabled = profileData['enabled']
   toEnable = policyOpt.enabled

   if toEnable:
      # Whether it's already enabled or about to be enabled, the datastoreName
      # will have to be the desired one
      actual = profileData['datastoreName']
      desired = policyOpt.datastoreName
      if actual != desired:
         if taskList:
            msg = CreateLocalizedMessage(None, VSAN_DATASTORENAME_TASK_KEY)
            taskList.addTask(msg, (VSAN_DATASTORENAME_TASK, desired))
            taskResult = TASK_LIST_REQ_MAINT_MODE
         else:
            msg = CreateLocalizedMessage(None,VSAN_DATASTORENAME_COMPLIANCE_KEY)
            comparisonValues = CreateComplianceFailureValues('datastoreName',
               PARAM_NAME, profileValue=desired, hostValue=actual)
            complianceErrors.append((msg, [comparisonValues]))

      # If it's already enabled and the UUIDs don't match, we have to leave and
      # rejoin with the desired UUID
      actual = profileData['clusterUUID']
      desired = policyOpt.clusterUUID
      stretchedEnabled = profileData['stretchedEnabled']
      stretchedExpected = policyOpt.stretchedEnabled

      joinTaskArg = {'clusterUUID': policyOpt.clusterUUID,
                     'stretchedEnabled': stretchedExpected}
      if stretchedExpected:
         joinTaskArg['stretchedEnabled'] = True
         joinTaskArg['isWitness'] = policyOpt.isWitness
         if policyOpt.isWitness:
            joinTaskArg['preferredFD'] = policyOpt.preferredFD

      if enabled:
         # Attempting to disable an existing stretched cluster will be ignored
         if (actual != desired) or (stretchedExpected and \
                                    policyOpt.isWitness \
                                    and (not stretchedEnabled)):
            if taskList:
               msg = CreateLocalizedMessage(None, VSAN_UUID_TASK_KEY)
               taskList.addTask(None, (VSAN_CLUSTER_LEAVE_TASK, None))
               taskList.addTask(msg, (VSAN_CLUSTER_JOIN_TASK, joinTaskArg))
               taskResult = TASK_LIST_REQ_MAINT_MODE
            else:
               # Check cluster UUID compliance
               if actual != desired:
                  uuidMsg = CreateLocalizedMessage(
                     None, VSAN_UUID_COMPLIANCE_KEY)
                  comparisonValues = CreateComplianceFailureValues(
                     'clusterUUID', PARAM_NAME, profileValue=desired,
                     hostValue=actual)
                  complianceErrors.append((uuidMsg, [comparisonValues]))

               # Checke stretached cluster compliance
               if stretchedExpected and not stretchedEnabled:
                  stretchedMsg = CreateLocalizedMessage(None,
                                    VSAN_STRETCHED_ENABLE_COMPLIANCE_KEY)

                  comparisonValues = CreateComplianceFailureValues(
                     'stretchedEnabled', PARAM_NAME,
                     profileValue=stretchedExpected,
                     hostValue=stretchedEnabled)
                  complianceErrors.append((stretchedMsg, [comparisonValues]))
      else:
         if taskList:
            msg = CreateLocalizedMessage(None, VSAN_ENABLE_TASK_KEY)
            taskList.addTask(msg, (VSAN_CLUSTER_JOIN_TASK, joinTaskArg))
            taskResult = TASK_LIST_REQ_MAINT_MODE
         else:
            msg = CreateLocalizedMessage(None, VSAN_ENABLE_COMPLIANCE_KEY)
            comparisonValues = CreateComplianceFailureValues('enabled',
               PARAM_NAME, profileValue=toEnable, hostValue=enabled)
            complianceErrors.append((msg, [comparisonValues]))

      if not policyOpt.isWitness and \
         profileData['unicastAgent'] != policyOpt.unicastAgent:
         if taskList:
            msg = CreateLocalizedMessage(None, VSAN_ADD_UNIAGENT_TASK_KEY,
                                         {'desired': policyOpt.unicastAgent})
            taskList.addTask(msg, (VSAN_ADD_UNICAST_AGENT_TASK,
                                   policyOpt.unicastAgent))

            taskResult = VSANUtilComputeTaskListRes(taskResult,
                                                    TASK_LIST_RES_OK)
         else:
            actual = profileData['unicastAgent']
            desired = policyOpt.unicastAgent
            msg = CreateLocalizedMessage(None,
                                         VSAN_UNICAST_AGENT_COMPLIANCE_KEY,
                                         {'actual': actual, 'desired': desired})
            complianceErrors.append(msg)

      # Only the witness can set the preferred fault domain
      if policyOpt.isWitness and \
         profileData['preferredFD'] != policyOpt.preferredFD:
         if taskList:
            msg = CreateLocalizedMessage(None, VSAN_SET_PREFERREDFD_TASK_KEY,
                                         {'desired': policyOpt.preferredFD})
            taskList.addTask(msg, (VSAN_SET_PREFERREDFD_TASK,
                                   policyOpt.preferredFD))

            taskResult = VSANUtilComputeTaskListRes(taskResult,
                                                    TASK_LIST_RES_OK)
         else:
            actual = profileData['preferredFD']
            desired = policyOpt.preferredFD
            msg = CreateLocalizedMessage(None,
                                         VSAN_PREFERRED_FD_COMPLIANCE_KEY,
                                         {'actual': actual, 'desired': desired})
            complianceErrors.append(msg)

   elif enabled:
      # When disabling, we do not proactively change UUID or datastoreName
      if taskList:
         msg = CreateLocalizedMessage(None, VSAN_ENABLE_TASK_KEY)
         taskList.addTask(msg, (VSAN_CLUSTER_LEAVE_TASK, None))
         taskResult = TASK_LIST_REQ_MAINT_MODE
      else:
         msg = CreateLocalizedMessage(None, VSAN_ENABLE_COMPLIANCE_KEY)
         comparisonValues = CreateComplianceFailureValues('enabled',
            PARAM_NAME, profileValue=toEnable, hostValue=enabled)
         complianceErrors.append((msg, [comparisonValues]))

   else:
      # Do not proactively change UUID or datastoreName when disabled
      pass

   if taskList:
      return taskResult
   else:
      return complianceErrors

#
class VSANClusterUUIDComplianceChecker(PolicyOptComplianceChecker):

   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, \
                                                    hostServices, profileData):
      # Called implicitly
      log.debug('in uuid compliancechecker')

      complianceErrors = \
                  VSANClusterUUIDComplianceAndTask(policyOpt, profileData, None)

      return (len(complianceErrors) == 0, complianceErrors)

# Ancillary routine to validate special inputs
class VSANClusterUUIDValidator:

   @staticmethod
   def Validate(policyOpt, name, value, errors):
      # Called implicitly
      log.debug('in VSANClusterUUIDValidator for %s' % name)

      validuuid = re.compile(r"\A[0-9a-f]{8,8}-"
                             r"[0-9a-f]{4,4}-[0-9a-f]{4,4}-[0-9a-f]{4,4}-"
                             r"[0-9a-f]{12,12}\Z")
      if not validuuid.match(value):
         log.debug('malformed uuid: <<%s>>' % value)
         msg = CreateLocalizedMessage(None, VSAN_UUID_ERROR_KEY, \
                                                {'name': name, 'value': value})
         errors.append(msg)
         return False

      return True

#
class VSANClusterDatastoreNameValidator:

   @staticmethod
   def Validate(policyOpt, name, value, errors):
      # Called implicitly
      log.debug('in VSANClusterDatastoreNameValidator for %s' % name)

      # Let's just make sure it's not empty and there is no single quote as we
      # will use single quotes to quote it on the command line
      if len(value) == 0 or value.find("'") != -1:
         log.debug('invalid datastore name: <<%s>>' % value)
         msg = CreateLocalizedMessage(None, VSAN_DATASTORENAME_ERROR_KEY, \
                                                {'name': name, 'value': value})
         errors.append(msg)
         return False

      return True

class VSANStretchedClusterPreferredFDValidator:
   @staticmethod
   def Validate(policyOpt, name, value, errors):
      # Let's just make sure the preferred fd does not exceed the
      # length limit 128.
      if len(value) > 128:
         log.info("The length of the preferred fault domain is too long:[ %s ]"\
                  % value)
         msg = CreateLocalizedMessage(None, VSAN_PREFERREDFD_ERROR_KEY,
                                      {'param': value})
         errors.append(msg)
         return False

      return True

class VSANStretchedClusterUnicastAgentValidator:
   @staticmethod
   def Validate(policyOpt, name, value, errors):
      if value != VSAN_DEFAULT_UNICAST_AGENT \
         and not IsValidIpv4Address(value):
         log.info("Unicast agent[ %s ]is not a valid ipv4 address" % value)
         msg = CreateLocalizedMessage(None, VSAN_UNICAST_AGENT_ERROR_KEY,
                                      {'param': value})
         errors.append(msg)
         return False

      return True

#
class VSANClusterUUIDOption(FixedPolicyOption):
   paramMeta = [
                  ParameterMetadata('enabled', 'bool',
                                    False, VSAN_DEFAULT_ENABLED),
                  ParameterMetadata('clusterUUID', 'string',
                                    True, VSAN_DEFAULT_UUID,
                                    VSANClusterUUIDValidator),
                  ParameterMetadata('datastoreName', 'string',
                                    True, VSAN_DEFAULT_DATASTORENAME,
                                    VSANClusterDatastoreNameValidator),
                  ParameterMetadata('stretchedEnabled', 'bool',
                                    False, VSAN_DEFAULT_STRETCHED_ENABLED),
                  ParameterMetadata('isWitness', 'bool',
                                    False, VSAN_DEFAULT_IS_WITNESS),
                  ParameterMetadata('preferredFD', 'string',
                                    True, VSAN_DEFAULT_PREFERREDFD,
                                    VSANStretchedClusterPreferredFDValidator),
                  ParameterMetadata('unicastAgent', 'string',
                                    True, VSAN_DEFAULT_UNICAST_AGENT,
                                    VSANStretchedClusterUnicastAgentValidator),
               ]

   complianceChecker = VSANClusterUUIDComplianceChecker

   @classmethod
   def CreateOption(cls, profileData):
      optParams = [('enabled', profileData['enabled']),
                   ('clusterUUID', profileData['clusterUUID']),
                   ('datastoreName', profileData['datastoreName']),
                   ('stretchedEnabled', profileData['stretchedEnabled']),
                   ('isWitness', profileData['isWitness']),
                   ('preferredFD', profileData['preferredFD']),
                   ('unicastAgent', profileData['unicastAgent'])]
      return cls(optParams)

#
# Main class
#
# !!! All methods must be called explicitly from the profile's corresponding
# methods.
#
class VSANClusterUUIDPolicy(Policy):
   possibleOptions = [
                       VSANClusterUUIDOption
                     ]

   @classmethod
   def CreatePolicy(cls, profileData):
      policyOpt = cls.possibleOptions[0].CreateOption(profileData)
      return cls(True, policyOpt)

   @classmethod
   def GenerateTaskList(cls, policy, taskList, profileData, parent):
      log.debug('in uuid generate tasklist')
      policyOpt = policy.policyOption

      result = VSANClusterUUIDComplianceAndTask(policyOpt, profileData,taskList)

      return result

   @classmethod
   def VerifyPolicy(cls, policy, profileData, validationErrors):
      log.debug('in uuid verify policy')
      policyOpt = policy.policyOption

      # When enabled, uuid is required and should not be null
      if policyOpt.enabled:
         if not hasattr(policyOpt, 'clusterUUID'):
            log.debug('enabled but no uuid')
            msg = CreateLocalizedMessage(None, VSAN_ENABLEDUUID_ERROR_KEY)
            validationErrors.append(msg)
         if policyOpt.clusterUUID == VSAN_DEFAULT_UUID:
            log.debug('enabled but null uuid')
            msg = CreateLocalizedMessage(None, VSAN_NULL_UUID_ERROR_KEY)
            validationErrors.append(msg)

      if not policyOpt.enabled and policyOpt.stretchedEnabled:
         msg = CreateLocalizedMessage(None, VSAN_STRETCHED_ENABLED_ERROR_KEY)
         validationErrors.append(msg)

      if policyOpt.stretchedEnabled:
         log.debug('Verify streatched parameters %s' % policyOpt)

         # If the host is a witness node, then the preferred FD must not be an
         # empty string.
         if policyOpt.isWitness and \
            (not hasattr(policyOpt, 'preferredFD') or \
             policyOpt.preferredFD == VSAN_DEFAULT_PREFERREDFD):
            msg = CreateLocalizedMessage(None, VSAN_PREFERREDFD_ERROR_KEY,
                                         {'param': policyOpt.preferredFD})
            validationErrors.append(msg)

         if not policyOpt.isWitness and \
            (not hasattr(policyOpt, 'unicastAgent') \
              or policyOpt.unicastAgent == VSAN_DEFAULT_UNICAST_AGENT):
            msg = CreateLocalizedMessage(None, VSAN_UNICAST_AGENT_ERROR_KEY,
                                         {'param': policyOpt.unicastAgent})
            validationErrors.append(msg)

      return len(validationErrors) == 0


###
### Storage policy
###

# Ancillary routine to check compliance and generate remediation task list
def VSANStorageComplianceAndTask(policyOpt, profileData, taskList):
   log.debug('in storage complianceandtask')

   complianceErrors = []
   taskResult = TASK_LIST_RES_OK

   # Straight comparison of all the attributes of the policy
   if policyOpt.paramMeta:
      for paramName, desired in policyOpt.paramValue:
         log.debug('examining %s' % paramName)
         log.debug('desired is %s, actual is %s' % \
                                             (desired, profileData[paramName]))
         if profileData[paramName] != desired:
            log.debug('mismatch for %s' % paramName)
            if taskList:
               msg = CreateLocalizedMessage(None, VSAN_STORAGEPOLICY_TASK_KEY,
                                                      {'paramName': paramName})
               taskList.addTask(msg,
                              (VSAN_STORAGEPOLICY_TASK, (paramName, desired)))
            else:
               msg = CreateLocalizedMessage(None,
                                            VSAN_STORAGEPOLICY_COMPLIANCE_KEY,
                                            {'paramName': paramName})
               comparisonValues = CreateComplianceFailureValues(paramName,
                  PARAM_NAME, profileValue=desired,
                  hostValue=profileData[paramName])
               complianceErrors.append((msg, [comparisonValues]))

   if taskList:
      return taskResult
   else:
      return complianceErrors

#
class VSANStorageComplianceChecker(PolicyOptComplianceChecker):

   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, \
                                                    hostServices, profileData):
      # Called implicitly
      log.debug('in storage compliancechecker')

      complianceErrors =VSANStorageComplianceAndTask(policyOpt,profileData,None)

      return (len(complianceErrors) == 0, complianceErrors)

# Ancillary routine to validate special inputs
class VSANStoragePolicyValidator:

   @staticmethod
   def Validate(policyOpt, name, value, errors):
      # Called implicitly
      log.debug('in VSANStoragePolicyValidator for %s' % name)

      # XXX PR 1014928: Syntax and validation of policies is complex and should
      # not be duplicated here. In the absence of a service to do the job, a
      # minimal validation is done: starts with left parenthesis, ends with
      # right parenthesis, does not contain single quote (as single quotes will
      # be used to quote the policy on the command line)
      if len(value) < 2 or value[0] != '(' or value[-1] != ')':
         log.debug('policy not enclosed in parentheses: <<%s>>' % value)
         msg = CreateLocalizedMessage(None, VSAN_STORAGEPOLICY_ERROR_KEY, \
                                                {'name': name, 'value': value})
         errors.append(msg)
         return False
      if value.find("'") != -1:
         log.debug('policy contains single quote: <<%s>>' % value)
         msg = CreateLocalizedMessage(None, VSAN_STORAGEPOLICY_ERROR_KEY, \
                                                {'name': name, 'value': value})
         errors.append(msg)
         return False

      return True

#
class VSANStorageOption(FixedPolicyOption):
   paramMeta = [
                   ParameterMetadata('cluster', 'string',
                                     True, VSAN_DEFAULT_CLUSTERPOLICY,
                                     VSANStoragePolicyValidator),
                   ParameterMetadata('vdisk', 'string',
                                     True, VSAN_DEFAULT_VDISKPOLICY,
                                     VSANStoragePolicyValidator),
                   ParameterMetadata('vmnamespace', 'string',
                                     True, VSAN_DEFAULT_VMNAMESPACE,
                                     VSANStoragePolicyValidator),
                   ParameterMetadata('vmswap', 'string',
                                     True, VSAN_DEFAULT_VMSWAP,
                                     VSANStoragePolicyValidator),
                   ParameterMetadata('vmem',   'string',
                                     True, VSAN_DEFAULT_VMEM,
                                     VSANStoragePolicyValidator)
               ]

   complianceChecker = VSANStorageComplianceChecker

   @classmethod
   def CreateOption(cls, profileData):
      optParams = [('cluster', profileData['cluster']), \
                   ('vdisk', profileData['vdisk']), \
                   ('vmnamespace', profileData['vmnamespace']), \
                   ('vmswap', profileData['vmswap']), \
                   ('vmem', profileData['vmem']), \
                  ]
      return cls(optParams)

#
# Main class
#
# !!! All methods must be called explicitly from the profile's corresponding
# methods.
#
class VSANStoragePolicy(Policy):
   possibleOptions = [
                       VSANStorageOption
                     ]

   @classmethod
   def CreatePolicy(cls, profileData):
      policyOpt = cls.possibleOptions[0].CreateOption(profileData)
      return cls(True, policyOpt)

   @classmethod
   def GenerateTaskList(cls, policy, taskList, profileData, parent):
      log.debug('in storage generate tasklist')
      policyOpt = policy.policyOption

      result = VSANStorageComplianceAndTask(policyOpt, profileData, taskList)

      return result

   @classmethod
   def VerifyPolicy(cls, policy, profileData, validationErrors):
      log.debug('in storage verify policy')

      # XXX Is there any cross-parameter consistency checks to perform ?

      return True


###
### VSAN fault domain policy
###

# Ancillary routine to check compliance and generate remediation task list
def VSANFaultDomainComplianceAndTask(policyOpt, profileData, taskList):
   log.debug('in fault domain complianceandtask')

   complianceErrors = []
   taskResult = TASK_LIST_RES_OK

   actual = profileData['faultDomain']
   desired = policyOpt.faultDomain

   if actual != desired:
      if taskList:
         msg = CreateLocalizedMessage(None, VSAN_FAULTDOMAIN_TASK_KEY)
         taskList.addTask(msg, (VSAN_FAULTDOMAIN_TASK, desired))
      else:
         msg = CreateLocalizedMessage(None, VSAN_FAULTDOMAIN_COMPLIANCE_KEY)
         comparisonValues = CreateComplianceFailureValues('faultDomain',
                  PARAM_NAME, profileValue=desired, hostValue=actual)
         complianceErrors.append((msg, [comparisonValues]))

   if taskList:
      return taskResult
   else:
      return complianceErrors

# Validate fault domain and append invalid errors
def ValidateFaultDomain(faultDomain, errors):
   if faultDomain == None \
      or not isinstance(faultDomain, str) \
      or len(faultDomain) > VSAN_FAULTDOMAIN_MAX_LENGTH:
      msg = CreateLocalizedMessage(None, VSAN_FAULTDOMAIN_ERROR_KEY,
                                   {'length': VSAN_FAULTDOMAIN_MAX_LENGTH})
      errors.append(msg)
      return False
   return True

# Compliance checker for fault domain
class VSANFaultDomainComplianceChecker(PolicyOptComplianceChecker):
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices,
                             profileData):
      # Called implicitly
      log.debug('in fault domain compliancechecker')

      complianceErrors = \
         VSANFaultDomainComplianceAndTask(policyOpt, profileData, None)

      return (len(complianceErrors) == 0, complianceErrors)

# User input required option in answer file
class UserInputVSANFaultDomainOption(UserInputRequiredOption):
   userInputParamMeta = [ParameterMetadata('faultDomain', 'string', True,
                                           VSAN_DEFAULT_FAULTDOMAIN)]

   complianceChecker = VSANFaultDomainComplianceChecker

   @classmethod
   def CreateOption(cls, profileData):
      optParams = []
      for param in cls.paramMeta:
         # Sanity check for the parameter info in the gathered faultDomain data
         assert param.paramName in profileData \
            or param.defaultValue is not None, \
            'Parameter %s not found in profile data'
         optParam = (param.paramName, param.defaultValue)
         if param.paramName in profileData:
            optParam = (param.paramName, profileData[param.paramName])
         optParams.append(optParam)
      return cls(optParams)

# User provided option in host profile
class FixedVSANFaultDomainOption(FixedPolicyOption):
   paramMeta = [ParameterMetadata('faultDomain', 'string',
                                  True, VSAN_DEFAULT_FAULTDOMAIN)]

   complianceChecker = VSANFaultDomainComplianceChecker

   @classmethod
   def CreateOption(cls, profileData):
      optParams = []
      for param in cls.paramMeta:
         # Sanity check for the parameter info in the gathered faultDomain data
         assert param.paramName in profileData \
            or param.defaultValue is not None, \
            'Parameter %s not found in profile data'
         optParam = (param.paramName, param.defaultValue)
         if param.paramName in profileData:
            optParam = (param.paramName, profileData[param.paramName])
         optParams.append(optParam)

      return cls(optParams)

# Unchanged option indicate nothing will happen
class LeaveUnchangedVSANFaultDomainOption(FixedPolicyOption):
   paramMeta = []

   @classmethod
   def CreateOption(cls, profileData):
      return cls([])
#
# Main class
#
# !!! All methods must be called explicitly from the profile's corresponding
# methods.
#
class VSANFaultDomainPolicy(Policy):
   possibleOptions = [UserInputVSANFaultDomainOption,
                      FixedVSANFaultDomainOption,
                      LeaveUnchangedVSANFaultDomainOption]
   _defaultOption = LeaveUnchangedVSANFaultDomainOption([])

   @classmethod
   def CreatePolicy(cls, profileData):
      policyOpt = LeaveUnchangedVSANFaultDomainOption([])

      # If vsan enabled in profileData, generate option according to
      # whether faultDomain is valid. Return UserInputRequiredOption
      # if faultDomain is not valid.
      # If vsan is not enabled in profileData, return unchanged option.
      if 'faultDomain' in profileData and 'enabled' in profileData \
            and profileData['enabled']:
         if not ValidateFaultDomain(profileData['faultDomain'], []):
            policyOpt = cls.possibleOptions[0].CreateOption(profileData)
         else:
            policyOpt = cls.possibleOptions[1].CreateOption(profileData)
      log.debug('in create policy use fault domain option %s' % policyOpt)

      return cls(True, policyOpt)

   @classmethod
   def GenerateTaskList(cls, policy, taskList, profileData, parent):
      log.debug('in fault domain generate tasklist')
      policyOpt = policy.policyOption
      result = []

      # Generate tasks if  option is not a leave unchanged option
      if not isinstance(policyOpt, LeaveUnchangedVSANFaultDomainOption):
         result = \
            VSANFaultDomainComplianceAndTask(policyOpt, profileData, taskList)

      return result

   @classmethod
   def VerifyPolicy(cls, policy, profileData, validationErrors):
      log.debug('in fault domain verify policy')
      policyOpt = policy.policyOption

      # Check whether parameter is valid if faultDomain is given
      # Skip verify if the option is a leave unchanged option
      if not isinstance(policyOpt, LeaveUnchangedVSANFaultDomainOption):
         if hasattr(policyOpt, 'faultDomain') \
               and policyOpt.faultDomain != None:
            return ValidateFaultDomain(policyOpt.faultDomain, validationErrors)
         return False

      return True

###
### DEPRECATED!!! Checksum Enabled Storage policy
###
# Deprecated compliance checker util
def VSANChecksumEnabledComplianceAndTask(policyOpt, profileData, taskList):
   if taskList:
      return TASK_LIST_RES_OK
   else:
      return []

# Deprecated compliance checker
class VSANChecksumEnabledComplianceChecker(PolicyOptComplianceChecker):
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, \
                             hostServices, profileData):
      return (True, [])

# Deprecated policy option
class VSANChecksumEnabledOption(FixedPolicyOption):
   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

   paramMeta = [
                  ParameterMetadata('checksumEnabled', 'bool', False, False)
               ]

   complianceChecker = VSANChecksumEnabledComplianceChecker

   @classmethod
   def CreateOption(cls, profileData):
      optParams = [('checksumEnabled', False)]
      return cls(optParams)

# Deprecated policy
class VSANChecksumEnabledPolicy(Policy):
   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

   possibleOptions = [
                        VSANChecksumEnabledOption
                     ]

   @classmethod
   def CreatePolicy(cls, profileData):
      policyOpt = cls.possibleOptions[0].CreateOption(profileData)
      return cls(True, policyOpt)

   @classmethod
   def GenerateTaskList(cls, policy, taskList, profileData, parent):
      return []

   @classmethod
   def VerifyPolicy(cls, policy, profileData, validationErrors):
      return True

def VSANServiceComplianceAndTask(policyOpt, profileData, taskList):
   complianceErrors = []
   taskResult = TASK_LIST_RES_OK

   actual = profileData['vsanvpdCastore']
   desired = policyOpt.vsanvpdCastore

   if actual != desired:
      if taskList:
         msg = CreateLocalizedMessage(None,
                                      VSAN_VPD_CASTORE_TASK_KEY,
                                      {'desired': desired})
         taskList.addTask(msg, (VSAN_VPD_CASTORE_TASK, desired))
      else:
         msg = CreateLocalizedMessage(None,
                                      VSAN_VPD_CASTORE_COMPLIANCE_KEY,
                                      {'actual': actual, 'desired': desired})
         complianceErrors.append(msg)

   if taskList:
      return taskResult
   else:
      return complianceErrors

#
class VSANServiceComplianceChecker(PolicyOptComplianceChecker):

   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt,
                             hostServices, profileData):

      complianceErrors = VSANServiceComplianceAndTask(
         policyOpt,
         profileData,
         None
      )

      return (len(complianceErrors) == 0, complianceErrors)

#
class VSANServiceOption(FixedPolicyOption):
   # As the CA store is security related, we want to make it
   # non-configurable and invisible to end user.
   paramMeta = [
                  ParameterMetadata(
                     'vsanvpdCastore', # paramName
                     'string',         # paramType
                     True,             # isOptional
                     '',               # defaultValue
                     readOnly=True,
                     hidden=True,
                  )
               ]

   complianceChecker = VSANServiceComplianceChecker

   @classmethod
   def CreateOption(cls, profileData):
      optParams = []
      for param in cls.paramMeta:
         optParams.append((param.paramName, profileData[param.paramName]))
      return cls(optParams)

class VSANServicePolicy(Policy):
   possibleOptions = [
                        VSANServiceOption
                     ]

   @classmethod
   def CreatePolicy(cls, profileData):
      policyOpt = cls.possibleOptions[0].CreateOption(profileData)
      return cls(True, policyOpt)

   @classmethod
   def GenerateTaskList(cls, policy, taskList, profileData, parent):
      policyOpt = policy.policyOption

      result = VSANServiceComplianceAndTask(policyOpt, profileData, taskList)

      return result

   @classmethod
   def VerifyPolicy(cls, policy, profileData, validationErrors):
      return True
