#!/usr/bin/python
# **********************************************************
# Copyright 2011-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

from pluginApi import GenericProfile, FixedPolicyOption, Policy, log, \
                      ParameterMetadata, CreateLocalizedMessage, \
                      CreateLocalizedException, ProfileComplianceChecker, \
                      TASK_LIST_RES_OK
from pluginApi import CATEGORY_SECURITY_SERVICES, COMPONENT_SECURITY_SETTING

from .passwdPAMManager import PasswordPAMManager
import re

MODULE_MSG_KEY_BASE = 'com.vmware.profile.passwdPAM'
SETTING_PASSWDPAM = '%s.%s' % (MODULE_MSG_KEY_BASE, 'settingConfig')
INVALID_PAM_CONTROL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'invalidPAMControl')
PAM_SECTION_MISMATCH = '%s.%s' % (MODULE_MSG_KEY_BASE, 'PAMSectionMismatch')
READ_PASSWD_PAM_FAIL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'readConfigFail')
WRITE_PASSWD_PAM_FAIL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'writeConfigFail')


def _IsEmptyPAMConfig(conf):
   """Determine if the PAM configuration is empty.
   """
   for sec in conf.values():
      if sec:
         return False
   return True


class PAMControlValidator:
   """Validate if it is a valid control in the PAM entry.
   """
   @staticmethod
   def Validate(obj, argName, arg, errors):
      # control can be a predefined word or in the format
      # "[value1=action1 value2=action2 ...]"
      pattern = r'(required|requisite|sufficient|optional|include|substack|\[(\w+=\w+)(\s+\w+=\w+)*\])'
      parser = re.compile(pattern)
      matches = parser.match(arg)
      if matches is None:
         msgData = { 'controlName' : arg }
         errMsg = CreateLocalizedMessage(None, INVALID_PAM_CONTROL, msgData)
         errors.append(errMsg)
         return False
      return True


class PAMEntryPolicyOption(FixedPolicyOption):
   """Policy Option type containing the PAM entry.
   """
   paramMeta = [ ParameterMetadata('control', 'string', False,
                    paramChecker=PAMControlValidator),
                 ParameterMetadata('module', 'string', False),
                 ParameterMetadata('arguments', 'string', True) ]


class PAMEntryPolicy(Policy):
   """Define the policy for a PAM entry.
   """
   possibleOptions = [ PAMEntryPolicyOption ]


class PAMSectionChecker(ProfileComplianceChecker):
   """Checks whether the section of PAM configuration is same with the profile.
   """
   def __init__(self, sectionName):
      self.sectionName = sectionName

   def CheckProfileCompliance(self, profiles, hostServices, profileData, parent):
      """Checks for profile compliance.
      """
      confHost = profileData[self.sectionName]
      confProf = []
      for profInst in profiles:
         entry = profInst.GetPAMEntry()
         confProf.append(entry)

      complianceFailures = []
      if confHost != confProf:
          msgData = { 'sectionName' : self.sectionName }
          complyFailMsg = CreateLocalizedMessage(None,
                              PAM_SECTION_MISMATCH, msgData)
          complianceFailures.append(complyFailMsg)

      return (len(complianceFailures) == 0, complianceFailures)


class PAMSectionProfile(GenericProfile):
   """Host profile containing a section of PAM configuration.
   """
   singleton = False
   policies = [ PAMEntryPolicy ]

   @classmethod
   def _CreateProfileInst(cls, control, module, arguments):
      """helper method that creates a profile instance
      """
      controlParam = [ 'control', control ]
      moduleParam = [ 'module', module ]
      argumentParam = [ 'arguments', arguments ]
      params = [ controlParam, moduleParam, argumentParam]
      policyOpt = PAMEntryPolicyOption(params)
      policies = [ PAMEntryPolicy(True, policyOpt) ]
      return cls(policies = policies)

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      """Implementation that returns profile.
      """
      rules = []
      for control, module, arguments in profileData[cls.PAM_SECTION_NAME]:
         ruleInst = cls._CreateProfileInst(control, module, arguments)
         rules.append(ruleInst)
      return rules

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      """Generates a task list for PAM configuration changes.
      """
      # this is taken care by parent profile
      return TASK_LIST_RES_OK

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Sets the current PAM configuration.
      """
      # this is taken care by parent profile
      return

   def GetPAMEntry(self):
      """Returns a tuple that describes the PAM entry.
      """
      control = self.PAMEntryPolicy.policyOption.control
      module = self.PAMEntryPolicy.policyOption.module
      arguments = self.PAMEntryPolicy.policyOption.arguments
      if arguments is None:
         arguments = ''
      return (control, module, arguments)


class PAMAuthInterfaceProfile(PAMSectionProfile):
   """Host profile containing the authenticaiton interface of PAM configuration.
   """
   PAM_SECTION_NAME = 'auth'
   complianceChecker = PAMSectionChecker(PAM_SECTION_NAME)


class PAMAccountInterfaceProfile(PAMSectionProfile):
   """Host profile containing the account interface of PAM configuration.
   """
   PAM_SECTION_NAME = 'account'
   complianceChecker = PAMSectionChecker(PAM_SECTION_NAME)


class PAMPasswordInterfaceProfile(PAMSectionProfile):
   """Host profile containing the password interface of PAM configuration.
   """
   PAM_SECTION_NAME = 'password'
   complianceChecker = PAMSectionChecker(PAM_SECTION_NAME)


class PAMSessionInterfaceProfile(PAMSectionProfile):
   """Host profile containing the session interface of PAM configuration.
   """
   PAM_SECTION_NAME = 'session'
   complianceChecker = PAMSectionChecker(PAM_SECTION_NAME)


class PasswordPAMProfile(GenericProfile):
   """Host profile containing the PAM configuration for passwd.
   """
   singleton = True
   subprofiles  = [ PAMAuthInterfaceProfile,
                    PAMAccountInterfaceProfile,
                    PAMPasswordInterfaceProfile,
                    PAMSessionInterfaceProfile ]

   category = CATEGORY_SECURITY_SERVICES
   component = COMPONENT_SECURITY_SETTING

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves PAM configuration for passwd.
      """
      passMgr = PasswordPAMManager()
      passMgr.Read()
      return passMgr.GetConfig()

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      """Implementation that returns a single instance profile.
      """
      if _IsEmptyPAMConfig(profileData):
         log.error("passwd PAM configuration should not be empty")
         fault = CreateLocalizedException(None, READ_PASSWD_PAM_FAIL)
         raise fault

      return cls()

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      """Generates a task list for PAM password configuration changes.
      """
      oldConf = profileData
      newConf = {}
      for profClass in cls.subprofiles:
         profiles = getattr(profileInstances[0], profClass.__name__)
         section = profClass.PAM_SECTION_NAME
         newConf[section] = []
         for profInst in profiles:
            entry = profInst.GetPAMEntry()
            newConf[section].append(entry)

      if oldConf != newConf:
         taskMsg = CreateLocalizedMessage(None, SETTING_PASSWDPAM)
         taskList.addTask(taskMsg, newConf)
      return TASK_LIST_RES_OK

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Sets the current PAM password configuration.
      """
      assert(len(taskList) == 1)
      passMgr = PasswordPAMManager()
      passMgr.SetConfig(taskList[0])
      if not passMgr.Commit(hostServices):
         fault = CreateLocalizedException(None, WRITE_PASSWD_PAM_FAIL)
         raise fault

