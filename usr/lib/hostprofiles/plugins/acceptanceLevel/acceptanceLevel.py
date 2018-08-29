#!/usr/bin/python
# **********************************************************
# Copyright 2012-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

from pluginApi import GenericProfile, FixedPolicyOption, Policy, log, \
                      ParameterMetadata, CreateLocalizedMessage, \
                      CreateLocalizedException, ProfileComplianceChecker, \
                      TASK_LIST_RES_OK
from pyEngine.policy import NoDefaultOption
from pyEngine.nodeputil import ChoiceValidator
from pluginApi import CATEGORY_SECURITY_SERVICES, COMPONENT_SECURITY_SETTING
from pyEngine.comply import CreateComplianceFailureValues, PARAM_NAME

MODULE_MSG_KEY_BASE = 'com.vmware.profile.acceptanceLevel'
GETTING_ACCEPTANCE_LEVEL_FAIL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'gettingAcceptanceFail')
SETTING_ACCEPTANCE_LEVEL_FAIL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'settingAcceptanceFail')
GETTING_VIBLIST_FAIL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'gettingVibListFail')
INVALID_ACCEPTANCE_LEVEL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'invalidAcceptanceLevel')
SETTING_ACCEPTANCE_LEVEL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'settingAcceptance')
ACCEPTANCE_LEVEL_MISMATCH = '%s.%s' % (MODULE_MSG_KEY_BASE, 'acceptanceMismatch')
CONFLICTING_VIBS_FOR_ACCEPTANCE = '%s.%s' % (MODULE_MSG_KEY_BASE, 'conflictingVibs')

HOST_ACCEPTANCE_LEVELS = {
   'VMwareCertified' : 4,
   'VMwareAccepted' : 3,
   'PartnerSupported' : 2,
   'CommunitySupported' : 1 }


class HostAcceptanceLevelChecker(ProfileComplianceChecker):
   """Checks whether the host acceptance level setting in the system is same with profile.
   """
   @classmethod
   def CheckProfileCompliance(cls, profiles, hostServices, profileData, parent):
      """Checks for profile compliance.
      """
      option = profiles[0].HostAcceptanceLevelPolicy.policyOption
      if isinstance(option, NoDefaultOption):
         return (True, [])
      confProf = option.acceptanceLevel
      confHost = profileData['acceptanceLevel']

      complianceFailures = []
      if confHost != confProf:
         msgData = { 'levelHost' : confHost, 'levelProf': confProf }
         complyFailMsg = CreateLocalizedMessage(None, ACCEPTANCE_LEVEL_MISMATCH, msgData)
         comparisonValues = CreateComplianceFailureValues('acceptanceLevel',
            PARAM_NAME, profileValue = confProf, hostValue = confHost)
         complianceFailures.append((complyFailMsg, [comparisonValues]))

         # checking for conflicting VIBs
         status, output = hostServices.ExecuteEsxcli('software', 'vib', 'list', None)
         if status != 0:
            msgData = { 'errMsg' : output }
            fault = CreateLocalizedException(None, GETTING_VIBLIST_FAIL, msgData)
            raise fault
         for item in output:
            vibName = item['Name']
            vibVersion = item['Version']
            vibLevel = item['Acceptance Level']
            if HOST_ACCEPTANCE_LEVELS[vibLevel] < HOST_ACCEPTANCE_LEVELS[confProf]:
               msgData = { 'vibName' : vibName, 'vibVersion': vibVersion,
                           'vibLevel': vibLevel, 'levelProf': confProf }
               complyFailMsg = CreateLocalizedMessage(None, CONFLICTING_VIBS_FOR_ACCEPTANCE, msgData)
               # To keep it consistent, let's return a None for
               # comparison values.
               complianceFailures.append((complyFailMsg, None))

      return (len(complianceFailures) == 0, complianceFailures)


class HostAcceptanceLevelPolicyOption(FixedPolicyOption):
   """Policy Option type containing the host acceptance level configuration.
   """
   paramMeta = [ ParameterMetadata('acceptanceLevel', 'string', False,
                   paramChecker=ChoiceValidator(
                     list(HOST_ACCEPTANCE_LEVELS.keys()))) ]


class HostAcceptanceLevelPolicy(Policy):
   """Define a policy for the host acceptance level configuration.
   """
   possibleOptions = [ HostAcceptanceLevelPolicyOption, NoDefaultOption ]


class HostAcceptanceLevelProfile(GenericProfile):
   """Host profile containing the host acceptance level configuration.
   """
   singleton = True
   policies = [ HostAcceptanceLevelPolicy ]
   complianceChecker = HostAcceptanceLevelChecker()

   category = CATEGORY_SECURITY_SERVICES
   component = COMPONENT_SECURITY_SETTING

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves host acceptance level configuration.
      """
      status, output = hostServices.ExecuteEsxcli('software', 'acceptance', 'get')
      if status != 0:
         log.error("Failed to get host acceptance level: %s" % output)
         msgData = { 'errMsg' : output }
         fault = CreateLocalizedException(None, GETTING_ACCEPTANCE_LEVEL_FAIL, msgData)
         raise fault
      return {'acceptanceLevel': output}

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      """Implementation that returns a single instance profile.
      """
      if profileData['acceptanceLevel'] not in HOST_ACCEPTANCE_LEVELS.keys():
         log.error("Invalid host acceptance level configured on the host: %s" % profileData['acceptanceLevel'])
         msgData = { 'acceptanceLevel' : profileData['acceptanceLevel'] }
         fault = CreateLocalizedException(None, INVALID_ACCEPTANCE_LEVEL, msgData)
         raise fault
      pathParam = [ 'acceptanceLevel', profileData['acceptanceLevel'] ]
      params = [ pathParam ]
      policyOpt = HostAcceptanceLevelPolicyOption(params)
      policies = [ HostAcceptanceLevelPolicy(True, policyOpt) ]
      return cls(policies = policies)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      """Generates a task list for host acceptance level configuration changes.
      """
      # get acceptance level from profile
      option = profileInstances[0].HostAcceptanceLevelPolicy.policyOption
      if isinstance(option, NoDefaultOption):
         return TASK_LIST_RES_OK
      level = option.acceptanceLevel

      # generate task if the acceptance level doesn't match
      if profileData['acceptanceLevel'] != level:
         msgData = { 'acceptanceLevel' : level }
         taskMsg = CreateLocalizedMessage(None, SETTING_ACCEPTANCE_LEVEL, msgData)
         taskList.addTask(taskMsg, level)
      return TASK_LIST_RES_OK

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Sets the current host acceptance level setting.
      """
      assert len(taskList) == 1
      level = taskList[0]
      optStr = '--level=%s' % level
      status, output = hostServices.ExecuteEsxcli('software',
                           'acceptance', 'set', optStr)
      if status != 0:
         log.error("Failed to set host acceptance level: %s" % output)
         msgData = { 'errMsg' : output }
         fault = CreateLocalizedException(None, SETTING_ACCEPTANCE_LEVEL_FAIL, msgData)
         raise fault

