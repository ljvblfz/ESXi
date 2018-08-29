#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import GenericProfile, FixedPolicyOption, Policy, \
                      ParameterMetadata, CreateLocalizedException, \
                      CreateLocalizedMessage, log, IsString, \
                      PolicyOptComplianceChecker, \
                      TASK_LIST_RES_OK, TASK_LIST_REQ_REBOOT

from pluginApi import CATEGORY_ADVANCED_CONFIG_SETTING, \
                      COMPONENT_POWER_SYSTEM_CONFIG, POLICY_NAME, \
                      CreateComplianceFailureValues, \
                      FindClassWithMatchingAttr

#TBD: Should the NoDefaultOption should be in the pluginApi.extension module?
from pyEngine.policy import NoDefaultOption

# TBD: We should get this from the pluginApi module, not directly from pyVmomi
from pyVmomi import Vim

# Define error message keys
BASE_MSG_KEY = 'com.vmware.profile.powerSystem'
MODIFY_MSG_KEY = '%s.ModifyTo' % BASE_MSG_KEY
CHANGED_MSG_KEY = '%s.ChangedFrom' % BASE_MSG_KEY
UNSUPPORTED_CPU_POLICY = '%s.UnsupportedCpuPolicy' % BASE_MSG_KEY

def _Capitalize(inStr):
   """Helper function that capitalizes the first letter of the input string.
   """
   if len(inStr) <= 1:
      return inStr.capitalize()
   return inStr[0].capitalize() + inStr[1:]

class CpuPolicyChecker(PolicyOptComplianceChecker):
   """Compliance checker that determines if the currently CPU power policy
      in the host profile matches the setting on the system.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices,
                             profileData):
      """Checks if the current policy option matches the CPU power policy
         on the system.
      """
      cpuPolicy = profileData[0]
      profCpuPolicy = policyOpt.__class__.cpuPolicy
      if cpuPolicy != profCpuPolicy:
         msgKey = CHANGED_MSG_KEY + _Capitalize(profCpuPolicy)
         hostPolicyOption = FindClassWithMatchingAttr(
            profile.policies[0].possibleOptions, 'cpuPolicy', cpuPolicy)
         assert hostPolicyOption is not None
         comparisonValues = CreateComplianceFailureValues(
            'CpuPolicy', POLICY_NAME,
            profileValue=policyOpt.__class__.__name__,
            hostValue=hostPolicyOption)
         complyFailure = CreateLocalizedMessage(None, msgKey)
         return (False, [(complyFailure, [comparisonValues])])
      return True, []


class DynamicCpuPolicyOption(FixedPolicyOption):
   """Policy Option to select the "dynamic" CPU policy.
   """
   paramMeta = []
   cpuPolicy = 'dynamic'
   complianceChecker = CpuPolicyChecker

   # vCM Mapping for policy option
   mappingAttributePath = { 'vim' : 'shortName' }
   mappingCondition = {
      'vim' : Vim.Profile.AttributeCondition(
                 operator=Vim.Profile.NumericComparator.equal,
                 compareValue='dynamic')
   }


class StaticCpuPolicyOption(FixedPolicyOption):
   """Policy Option to select the "static" CPU policy.
   """
   paramMeta = []
   cpuPolicy = 'static'
   complianceChecker = CpuPolicyChecker

   # vCM Mapping for policy option
   mappingAttributePath = { 'vim' : 'shortName' }
   mappingCondition = {
      'vim' : Vim.Profile.AttributeCondition(
                 operator=Vim.Profile.NumericComparator.equal,
                 compareValue='static')
   }


class LowCpuPolicyOption(FixedPolicyOption):
   """Policy Option to select the "low" CPU policy.
   """
   paramMeta = []
   cpuPolicy = 'low'
   complianceChecker = CpuPolicyChecker

   # vCM Mapping for policy option
   mappingAttributePath = { 'vim' : 'shortName' }
   mappingCondition = {
      'vim' : Vim.Profile.AttributeCondition(
                 operator=Vim.Profile.NumericComparator.equal,
                 compareValue='low')
   }


class CustomCpuPolicyOption(FixedPolicyOption):
   """Policy Option to select the "custom" CPU policy
   """
   paramMeta = []
   cpuPolicy = 'custom'
   complianceChecker = CpuPolicyChecker

   # vCM Mapping for policy option
   mappingAttributePath = { 'vim' : 'shortName' }
   mappingCondition = {
      'vim' : Vim.Profile.AttributeCondition(
                 operator=Vim.Profile.NumericComparator.equal,
                 compareValue='custom')
   }


class CpuPolicy(Policy):
   """Define a policy for the power system's CPU policy setting.
   """
   possibleOptions = [ NoDefaultOption,
                       DynamicCpuPolicyOption,
                       StaticCpuPolicyOption,
                       LowCpuPolicyOption,
                       CustomCpuPolicyOption ]


class PowerSystemProfile(GenericProfile):
   """A Host Profile that manages the CPU Power Policy on an ESX host. In the
      future, this profile could be enhanced to accomodate additional power
      settings for the system.
   """
   #
   # Define required class attributes
   #
   policies = [ CpuPolicy ]
   singleton = True

   category = CATEGORY_ADVANCED_CONFIG_SETTING
   component = COMPONENT_POWER_SYSTEM_CONFIG

   # Having the policy opt compliance checker is sufficient
   #complianceChecker =

   # vCM Mapping base
   mappingBasePath = { 'vim': 'configManager.powerSystem.info.currentPolicy' }


   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves the current power system CPU policy
      """
      powerSystem = hostServices.hostSystemService.configManager.powerSystem
      cpuPolicy = powerSystem.info.currentPolicy.shortName
      availablePolicies = powerSystem.capability.availablePolicy
      cpuPolicyKeys = dict([ (policy.shortName, policy.key) \
                              for policy in availablePolicies ])
      return ( cpuPolicy, cpuPolicyKeys )

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      """Returns a profile containing the currently configured CPU power
         policy.
      """
      currentCpuPolicy = profileData[0]
      policyOpt = None
      for optType in CpuPolicy.possibleOptions:
         if hasattr(optType, 'cpuPolicy') and \
               optType.cpuPolicy == currentCpuPolicy:
            policyOpt = optType([])
      if policyOpt is None:
         policyOpt = NoDefaultOption([])

      policy = CpuPolicy(True, policyOpt)
      profile = cls([policy])

      return profile

   @classmethod
   def VerifyProfileForApply(cls, profileInstance, hostServices, profileData,
                             validationErrors):
      """Using the VerifyProfileForApply to raise an error during the Execute
         phase of an "Apply" operation if a profile contains a CPU power policy
         not available on the system.
      """
      if isinstance(profileInstance.CpuPolicy.policyOption,
                    NoDefaultOption):
         return True

      cpuPolicy = profileInstance.CpuPolicy.policyOption.__class__.cpuPolicy
      cpuPolicyKeys = profileData[1]
      if cpuPolicy not in cpuPolicyKeys:
         unsupportedMsgKey = UNSUPPORTED_CPU_POLICY + _Capitalize(cpuPolicy)
         errMsg = CreateLocalizedMessage(None, unsupportedMsgKey)
         validationErrors.append(errMsg)
         return False
      return True

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      """Determines if the CPU Policy setting needs to be modified.
      """
      assert len(profileInstances) == 1
      currentCpuPolicy = profileData[0]
      policyOpt = profileInstances[0].CpuPolicy.policyOption
      if not isinstance(policyOpt, NoDefaultOption):
         cpuPolicyInProfile = policyOpt.__class__.cpuPolicy
         if currentCpuPolicy != cpuPolicyInProfile:
            msgKey = MODIFY_MSG_KEY + _Capitalize(cpuPolicyInProfile)
            taskMsg = CreateLocalizedMessage(None, msgKey)
            taskList.addTask(taskMsg, cpuPolicyInProfile)
      return TASK_LIST_RES_OK

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, profileData):
      """Sets the power system CPU Policy setting.
      """
      assert len(taskList) == 1 and IsString(taskList[0])
      newCpuPolicy = taskList[0]
      cpuPolicyKeys = profileData[1]
      powerSystem = hostServices.hostSystemService.configManager.powerSystem
      powerSystem.ConfigurePolicy(cpuPolicyKeys[newCpuPolicy])

