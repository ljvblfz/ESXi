#!/usr/bin/python
# **********************************************************
# Copyright 2011-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

from pluginApi import GenericProfile, FixedPolicyOption, Policy, log, \
                      ParameterMetadata, CreateLocalizedMessage, \
                      CreateLocalizedException, ProfileComplianceChecker, \
                      TASK_LIST_RES_OK, RELEASE_VERSION_2015
from pluginApi import CATEGORY_SECURITY_SERVICES, COMPONENT_SECURITY_SETTING
from .loginMapManager import LoginMapManager, DEFAULT_USERS

MODULE_MSG_KEY_BASE = 'com.vmware.profile.loginMap'
MULTIPLE_RULES_FOUND = '%s.%s' % (MODULE_MSG_KEY_BASE, 'multipleRule')
NO_DEFAULT_USER_IN_RULE = '%s.%s' % (MODULE_MSG_KEY_BASE, 'noDefaultUserInRule')
SETTING_LOGINMAP = '%s.%s' % (MODULE_MSG_KEY_BASE, 'settingConfig')
READ_LOGINMAP_FAIL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'readConfigFail')
WRITE_LOGINMAP_FAIL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'writeConfigFail')
DEFAULT_PATH_NOT_DEFINED = '%s.%s' % (MODULE_MSG_KEY_BASE, 'defaultPathNotDefined')
USER_UNDEFINED_IN_PROFILE = '%s.%s' % (MODULE_MSG_KEY_BASE, 'userNotFoundInProfile')
USER_UNDEFINED_IN_HOST = '%s.%s' % (MODULE_MSG_KEY_BASE, 'userNotFoundInHost')
PATH_MISMATCH_FOR_USER = '%s.%s' % (MODULE_MSG_KEY_BASE, 'pathMismatchForUser')


class LoginMapRulePolicyOption(FixedPolicyOption):
   """Policy Option type containing the rule configuration.
   """
   paramMeta = [ ParameterMetadata('userName', 'string', False),
                 ParameterMetadata('authPath', 'string', False) ]

   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

class LoginMapRulePolicy(Policy):
   """Define a policy for the login map rule.
   """
   possibleOptions = [ LoginMapRulePolicyOption ]

   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

class DefaultAuthPathPolicyOption(FixedPolicyOption):
   """Policy Option type containing the default authentication path.
   """
   paramMeta = [ ParameterMetadata('authPath', 'string', False) ]

   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

class DefaultAuthPathPolicy(Policy):
   """Define a policy for the default authenticaiton path.
   """
   possibleOptions = [ DefaultAuthPathPolicyOption ]

   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015


class LoginMapRuleProfile(GenericProfile):
   """Host profile containing PAM login map rule.
   """
   singleton = False
   policies = [ LoginMapRulePolicy ]

   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015
   enableDeprecatedVerify = False
   enableDeprecatedApply = False

   @classmethod
   def _CreateProfileInst(cls, user, path):
      """helper method that creates a profile instance of login map rule.
      """
      userParam = [ 'userName', user ]
      pathParam = [ 'authPath', path ]
      params = [ userParam, pathParam ]
      policyOpt = LoginMapRulePolicyOption(params)
      policies = [ LoginMapRulePolicy(True, policyOpt) ]
      return cls(policies = policies)

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      """Implementation that retrieves one profile instance per rule.
      """
      rules = []
      for key, value in profileData.items():
         if key != DEFAULT_USERS:
            ruleInst = cls._CreateProfileInst(key, value)
            rules.append(ruleInst)
      return rules

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      """Generates a task list for login map configuration changes.
      """
      # this is taken care by the parent profile
      return TASK_LIST_RES_OK

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Sets the current login map setting.
      """
      # this is taken care by the parent profile
      return


class PAMLoginMapChecker(ProfileComplianceChecker):
   """Checks whether the login map setting in the system is same with profile.
   """
   @classmethod
   def CheckProfileCompliance(cls, profiles, hostServices, profileData, parent):
      """Checks for profile compliance.
      """
      confHost = profileData
      confProf = {}
      for profInst in profiles[0].subprofiles:
         user = profInst.LoginMapRulePolicy.policyOption.userName
         path = profInst.LoginMapRulePolicy.policyOption.authPath
         confProf[user] = path
      confProf[DEFAULT_USERS] = profiles[0].DefaultAuthPathPolicy.policyOption.authPath

      complianceFailures = []
      for user, path in confHost.items():
         if user not in confProf:
            msgData = { 'userName' : user }
            complyFailMsg = CreateLocalizedMessage(None,
                              USER_UNDEFINED_IN_PROFILE, msgData)
            complianceFailures.append(complyFailMsg)
         else:
            if confProf[user] != path:
               msgData = { 'userName' : user }
               complyFailMsg = CreateLocalizedMessage(None,
                                 PATH_MISMATCH_FOR_USER, msgData)
               complianceFailures.append(complyFailMsg)

      for user in confProf.keys():
         if user not in confHost:
            msgData = { 'userName' : user }
            complyFailMsg = CreateLocalizedMessage(None,
                              USER_UNDEFINED_IN_HOST, msgData)
            complianceFailures.append(complyFailMsg)

      return (len(complianceFailures) == 0, complianceFailures)


class PAMLoginMapProfile(GenericProfile):
   """Host profile containing the PAM login map configuration.
   """
   singleton = True
   policies = [ DefaultAuthPathPolicy ]
   subprofiles  = [ LoginMapRuleProfile ]
   complianceChecker = PAMLoginMapChecker()

   category = CATEGORY_SECURITY_SERVICES
   component = COMPONENT_SECURITY_SETTING

   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015
   enableDeprecatedVerify = False
   enableDeprecatedApply = False

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves login map configuration.
      """
      loginMapMgr = LoginMapManager()
      loginMapMgr.Read()
      return loginMapMgr.GetConfig()

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      """Implementation that returns a single instance profile.
      """
      if len(profileData) == 0:
         log.error("Login map configuration should not be empty")
         fault = CreateLocalizedException(None, READ_LOGINMAP_FAIL)
         raise fault

      if DEFAULT_USERS not in profileData or not profileData[DEFAULT_USERS]:
         log.error("Default authentication path must be defined in login map")
         fault = CreateLocalizedException(None, DEFAULT_PATH_NOT_DEFINED)
         raise fault

      pathParam = [ 'authPath', profileData[DEFAULT_USERS] ]
      params = [ pathParam ]
      policyOpt = DefaultAuthPathPolicyOption(params)
      policies = [ DefaultAuthPathPolicy(True, policyOpt) ]
      return cls(policies = policies)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      """Verify if the login map configuration in the profile is valid or not.
      """
      retVal = True
      conf = {}
      for profInst in profileInstance.subprofiles:
         user = profInst.LoginMapRulePolicy.policyOption.userName
         path = profInst.LoginMapRulePolicy.policyOption.authPath
         # user name should not be default name
         if user == DEFAULT_USERS:
            msgData = { 'defaultUserName' : DEFAULT_USERS }
            invalidUserMsg = CreateLocalizedMessage(
                                 None, NO_DEFAULT_USER_IN_RULE, msgData)
            invalidUserMsg.SetRelatedPathInfo(profile=profInst,
                                              policy=profInst.LoginMapRulePolicy,
                                              paramId='userName')
            validationErrors.append(invalidUserMsg)
            retVal = False
         else:
            # cannot have duplicate user names
            if user in conf:
               msgData = { 'userName' : user }
               multipleRuleMsg = CreateLocalizedMessage(
                                    None, MULTIPLE_RULES_FOUND, msgData)
               multipleRuleMsg.SetRelatedPathInfo(
                     profile=profInst, policy=profInst.LoginMapRulePolicy,
                     paramId='userName')
               validationErrors.append(multipleRuleMsg)
               retVal = False
            else:
               conf[user] = path
      return retVal

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      """Generates a task list for login map configuration changes.
      """
      oldConf = profileData
      newConf = {}
      for profInst in profileInstances[0].subprofiles:
         user = profInst.LoginMapRulePolicy.policyOption.userName
         path = profInst.LoginMapRulePolicy.policyOption.authPath
         newConf[user] = path
      newConf[DEFAULT_USERS] = profileInstances[0].DefaultAuthPathPolicy.policyOption.authPath

      if oldConf != newConf:
         taskMsg = CreateLocalizedMessage(None, SETTING_LOGINMAP)
         taskList.addTask(taskMsg, newConf)
      return TASK_LIST_RES_OK

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Sets the current login map setting.
      """
      assert(len(taskList) == 1)
      loginMapMgr = LoginMapManager()
      loginMapMgr.SetConfig(taskList[0])
      if not loginMapMgr.Commit():
         fault = CreateLocalizedException(None, WRITE_LOGINMAP_FAIL)
         raise fault

