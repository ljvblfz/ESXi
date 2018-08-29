#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import GenericProfile, Policy, FixedPolicyOption, \
                      ParameterMetadata, PolicyOptComplianceChecker, \
                      ProfileComplianceChecker, CreateLocalizedMessage, log, \
                      TASK_LIST_REQ_MAINT_MODE, TASK_LIST_RES_OK, TASK_LIST_REQ_REBOOT

from pluginApi import CATEGORY_STORAGE, COMPONENT_ISCSI

from pyEngine import storageprofile

import pdb
import os

from .iscsiPolicies import *
from .iscsiPlatformUtils import *
from .iscsiInitiatorConfigProfile import *
from .iscsiSendTargetsDiscoveryConfigProfile import *
from .iscsiTargetConfigProfile import *
from .iscsiPortBindingConfigProfile import *

class IscsiInitiatorProfileChecker(ProfileComplianceChecker):
   def CheckProfileCompliance(self, profileInsts, hostServices, configData, parent):
      complianceFailures = []

      if len(profileInsts) > 0:
         if isinstance(profileInsts[0], IscsiInitiatorProfile):
            cls = IscsiInitiatorProfile()
         elif isinstance(profileInsts[0], DependantHardwareIscsiInitiatorProfile):
            cls = DependantHardwareIscsiInitiatorProfile()
         elif isinstance(profileInsts[0], SoftwareIscsiInitiatorProfile):
            cls = SoftwareIscsiInitiatorProfile()
         elif isinstance(profileInsts[0], IndependentHardwareIscsiInitiatorProfile):
            cls = IndependentHardwareIscsiInitiatorProfile()
         else:
            assert()

         complianceFailures = cls.CheckCompliance(profileInsts, hostServices, configData, parent)

      # Checks the specified profile instances against the current config.
      return (len(complianceFailures) == 0, complianceFailures)

class IscsiConfigData:
   iscsiHbaList = None

   def __init__(self, hostServices):
      self.iscsiHbaList = GetIscsiHbaList(hostServices)

def GetIscsiHbaProfiles(cls, config, hbaType):
   iscsiInitiatorProfileList = []
   iscsiHbaList = config.iscsiHbaList

   for hba in iscsiHbaList:
      if not (hba.type == hbaType and \
         hba.enabled == True):
         continue

      iscsiInitiatorPolicies = [
         IscsiInitiatorIdentityPolicy(True,
            IscsiInitiatorIdentityPolicyOption([('name', hba.name)])),
      ]

      if hbaType == ISCSI_HBA_PROFILE_SOFTWARE:
         iscsiInitiatorPolicies.append(IscsiSoftwareInitiatorSelectionPolicy(True,
               IscsiInitiatorSelectionDisabled([('disabled', not hba.enabled)])))
      else:
         iscsiInitiatorPolicies.append(IscsiHardwareInitiatorSelectionPolicy(True,
               IscsiInitiatorSelectionMatchByPciSlotInfo([('pciSlotInfo', hba.pciSlotInfo)])))

      profile = cls(policies=iscsiInitiatorPolicies)
      profile.selectedHbaInstances = [hba]
      iscsiInitiatorProfileList.append(profile)

   return iscsiInitiatorProfileList

class DependantHardwareIscsiInitiatorProfile(GenericProfile):
   policies = [ IscsiInitiatorIdentityPolicy,
                IscsiHardwareInitiatorSelectionPolicy ]

   version = ISCSI_PROFILE_VERSION

   singleton = False

   subprofiles = [
      DependantHardwareIscsiInitiatorConfigProfile,
      IscsiPortBindingConfigProfile,
      IscsiSendTargetsDiscoveryConfigProfile,
      IscsiDiscoveredTargetConfigProfile,
      IscsiStaticTargetConfigProfile
   ]

   dependents = [
      DependantHardwareIscsiInitiatorConfigProfile,
      IscsiPortBindingConfigProfile,
      IscsiSendTargetsDiscoveryConfigProfile,
      IscsiDiscoveredTargetConfigProfile,
      IscsiStaticTargetConfigProfile
   ]

   selectedHbaInstances = []

   iscsiProfileType = ISCSI_HBA_PROFILE_DEPENDENT

   complianceChecker = IscsiInitiatorProfileChecker()

   def GetInitiatorConfigSubProfile(self):
      for profInst in self.subprofiles:
         if isinstance(profInst, DependantHardwareIscsiInitiatorConfigProfile):
            return profInst
      return None

   def GetParams(self, hba):
      return hba.params

   @classmethod
   def GatherData(cls, hostServices):
      return None

   @classmethod
   def CheckCompliance(cls, profileInstances, hostServices, configData, parent):
      IscsiLog(3, 'CheckCompliance for %s' %(cls.__name__))
      complianceErrors = []

      ProfilesToHba(profileInstances, configData, parent, None)
      return complianceErrors

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, configData, validationErrors):
      return cls.VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, False)

   @classmethod
   def VerifyProfileForApply(cls, profileInstance, hostServices, configData, validationErrors):
      return cls.VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, True)

   @staticmethod
   def VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, forApply):
      #EnterDebugger()
      hba = GetIscsiHbaFromProfile(None, profileInstance, False)

      if hba is None:
         return True

      result = VerifyInitiatorCommonConfigPolicies(cls,
                                                   profileInstance,
                                                   hba,
                                                   hostServices,
                                                   configData,
                                                   forApply,
                                                   validationErrors)
      IscsiLog(3, 'VerifyProfileInt(forApply=%s) for %s:%s is returning %d' % \
            (forApply, profileInstance.__class__.__name__, id(profileInstance), result))
      return result

   # Version verification
   @classmethod
   def CheckVersion(cls, version):
      return VerifyVersionCompatibility(cls, version)

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, configData):
      for taskSet in taskList:
         ExecuteTask(cls, hostServices, configData, taskSet)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, configData, parent):
      IscsiLog(3, 'GenerateTaskList for %s' %(cls.__name__))
      if debuggerEnabled() == 2:
         ret = pdb.runcall(cls.GenerateTaskList_Impl, profileInstances, taskList, hostServices, configData, parent)
      else:
         ret = cls.GenerateTaskList_Impl(profileInstances, taskList, hostServices, configData, parent)
      return ret

   @classmethod
   def GenerateTaskList_Impl(cls, profileInstances, taskList, hostServices, configData, parent):
      for profInst in profileInstances:
            hba = GetIscsiHbaFromProfile(configData, profInst, False)

      return TASK_LIST_RES_OK

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      if debuggerEnabled() == 1:
         ret = pdb.runcall(cls.GenerateProfileFromConfig_Impl, hostServices, config, parent)
      else:
         ret = cls.GenerateProfileFromConfig_Impl(hostServices, config, parent)
      return ret

   @classmethod
   def GenerateProfileFromConfig_Impl(cls, hostServices, config, parent):
      iscsiInitiatorProfileList = GetIscsiHbaProfiles(cls, config, ISCSI_HBA_PROFILE_DEPENDENT)

      return iscsiInitiatorProfileList

def CheckSoftwareInitiatorConfig(profInst, configData, hostServices, taskData):
   msgKey = ''

   hba = GetIscsiHbaFromProfile(configData, profInst, True)
   status, result = RunEsxCli(hostServices, ISCSI_INITIATOR_CONFIG_SWISCSI_ENABLED_GET_CMD)

   policyInst = profInst.IscsiSoftwareInitiatorSelectionPolicy
   disabled = ExtractPolicyOptionValue(profInst,
                     IscsiSoftwareInitiatorSelectionPolicy,
                     [([IscsiInitiatorSelectionDisabled], FROM_ATTRIBUTE,
                     'disabled')],
                     True)
   if disabled is True and result is True:
      msgKey = ISCSI_DISABLE_SOFTWARE_ISCSI
      taskData.append({'task': 'ISCSI_INITIATOR_CONFIG_SWISCSI_DISABLE',
                       'profileInstance':hba.GetName(),
                       'hostValue': result,
                       'profileValue': not disabled,
                       'comparisonIdentifier': 'DisableSoftwareIscsi'})
   elif disabled is False and result is False:
      msgKey = ISCSI_ENABLE_SOFTWARE_ISCSI
      iqn = ExtractPolicyOptionValue(profInst.GetInitiatorConfigSubProfile(),
                                 Hba_InitiatorIqnSelectionPolicy,
                                 [([UserInputIqn], FROM_ATTRIBUTE, 'iqn')],
                                 True)

      taskData.append({'task': 'ISCSI_INITIATOR_CONFIG_SWISCSI_ENABLE',
                       'iqn' : iqn,
                       'profileInstance': hba.GetName(),
                       'hostValue': result,
                       'profileValue': not disabled,
                       'comparisonIdentifier': 'EnableSoftwareIscsi'})

   PrintTaskData(taskData)

   return msgKey, {}

class SoftwareIscsiInitiatorProfile(GenericProfile):
   policies = [ IscsiInitiatorIdentityPolicy,
                IscsiSoftwareInitiatorSelectionPolicy ]

   singleton = False

   version = ISCSI_PROFILE_VERSION

   subprofiles = [
      SoftwareIscsiInitiatorConfigProfile,
      IscsiPortBindingConfigProfile,
      IscsiSendTargetsDiscoveryConfigProfile,
      IscsiDiscoveredTargetConfigProfile,
      IscsiStaticTargetConfigProfile
   ]

   dependents = [
      SoftwareIscsiInitiatorConfigProfile,
      IscsiPortBindingConfigProfile,
      IscsiSendTargetsDiscoveryConfigProfile,
      IscsiDiscoveredTargetConfigProfile,
      IscsiStaticTargetConfigProfile
   ]

   selectedHbaInstances = []

   iscsiProfileType = ISCSI_HBA_PROFILE_SOFTWARE

   complianceChecker = IscsiInitiatorProfileChecker()

   def GetInitiatorConfigSubProfile(self):
      for profInst in self.subprofiles:
         if isinstance(profInst, SoftwareIscsiInitiatorConfigProfile):
            return profInst
      return None

   def GetParams(self, hba):
      return hba.params

   # Version verification
   @classmethod
   def CheckVersion(cls, version):
      return VerifyVersionCompatibility(cls, version)

   @classmethod
   def CheckCompliance(cls, profileInstances, hostServices, configData, parent):
      IscsiLog(3, 'CheckCompliance for %s' %(cls.__name__))
      complianceErrors = []

      ProfilesToHba(profileInstances, configData, parent, None)

      for profInst in profileInstances:
         taskData = []
         CheckSoftwareInitiatorConfig(profInst, configData, hostServices,taskData)

         IscsiGenerateComplianceErrors(cls,
                                       profileInstances,
                                       profInst,
                                       hostServices,
                                       configData,
                                       parent,
                                       taskData,
                                       complianceErrors)

      return complianceErrors

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, configData, validationErrors):
      return cls.VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, False)

   @classmethod
   def VerifyProfileForApply(cls, profileInstance, hostServices, configData, validationErrors):
      return cls.VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, True)

   @staticmethod
   def VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, forApply):
      #EnterDebugger()
      hba = GetIscsiHbaFromProfile(None, profileInstance, True)

      result = VerifyInitiatorCommonConfigPolicies(cls,
                                                   profileInstance,
                                                   hba,
                                                   hostServices,
                                                   configData,
                                                   forApply,
                                                   validationErrors)
      IscsiLog(3, 'VerifyProfileInt(forApply=%s) for %s:%s is returning %d' % \
                  (forApply, profileInstance.__class__.__name__, id(profileInstance), result))
      return result

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, configData):
      for taskSet in taskList:
         ExecuteTask(cls, hostServices, configData, taskSet)

      if len(taskList) != 0:
         UpdateIscsiHbaData(hostServices, configData, 'iscsi_vmk', None, None)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, configData, parent):
      IscsiLog(3, 'GenerateTaskList for %s' %(cls.__name__))
      if debuggerEnabled() == 2:
         ret = pdb.runcall(cls.GenerateTaskList_Impl, profileInstances, taskList, hostServices, configData, parent)
      else:
         ret = cls.GenerateTaskList_Impl(profileInstances, taskList, hostServices, configData, parent)
      return ret

   @classmethod
   def GenerateTaskList_Impl(cls, profileInstances, taskList, hostServices, configData, parent):
      res = TASK_LIST_RES_OK
      tmpTaskData = []
      for profInst in profileInstances:
         msgKey, msgArg = CheckSoftwareInitiatorConfig(profInst, configData, hostServices, tmpTaskData)
         if len(tmpTaskData) != 0:
            if msgKey == ISCSI_DISABLE_SOFTWARE_ISCSI:
               res = TASK_LIST_REQ_REBOOT

            tmpTaskMsg = IscsiCreateLocalizedMessage(tmpTaskData,
                                                     '%s.label' % msgKey, msgArg)
            taskList.addTask(tmpTaskMsg, tmpTaskData)

      return res

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      if debuggerEnabled() == 1:
         ret = pdb.runcall(cls.GenerateProfileFromConfig_Impl, hostServices, config, parent)
      else:
         ret = cls.GenerateProfileFromConfig_Impl(hostServices, config, parent)

      return ret

   @classmethod
   def GenerateProfileFromConfig_Impl(cls, hostServices, config, parent):
      #EnterDebgger()
      iscsiInitiatorProfileList = GetIscsiHbaProfiles(cls, config, ISCSI_HBA_PROFILE_SOFTWARE)
      return iscsiInitiatorProfileList

class IndependentHardwareIscsiInitiatorProfile(GenericProfile):
   #
   # Define required class attributes
   #
   policies = [ IscsiInitiatorIdentityPolicy,
                IscsiHardwareInitiatorSelectionPolicy ]

   singleton = False

   version = ISCSI_PROFILE_VERSION

   subprofiles = [
      IndependentHardwareIscsiInitiatorConfigProfile,
      IscsiSendTargetsDiscoveryConfigProfile,
      IscsiDiscoveredTargetConfigProfile,
      IscsiStaticTargetConfigProfile
   ]

   dependents = [
      IndependentHardwareIscsiInitiatorConfigProfile,
      IscsiSendTargetsDiscoveryConfigProfile,
      IscsiDiscoveredTargetConfigProfile,
      IscsiStaticTargetConfigProfile
   ]

   selectedHbaInstances = []

   iscsiProfileType = ISCSI_HBA_PROFILE_INDEPENDENT

   complianceChecker = IscsiInitiatorProfileChecker()

   def GetInitiatorConfigSubProfile(self):
      for profInst in self.subprofiles:
         if isinstance(profInst, IndependentHardwareIscsiInitiatorConfigProfile):
            return profInst

      return None

   def GetParams(self, hba):
      return hba.params

   # Version verification
   @classmethod
   def CheckVersion(cls, version):
      return VerifyVersionCompatibility(cls, version)

   @classmethod
   def GatherData(cls, hostServices):
      return None

   @classmethod
   def CheckCompliance(cls, profileInstances, hostServices, configData, parent):
      IscsiLog(3, 'CheckCompliance for %s' %(cls.__name__))
      complianceErrors = []

      ProfilesToHba(profileInstances, configData, parent, None)

      return complianceErrors

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, configData, validationErrors):
      return cls.VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, False)

   @classmethod
   def VerifyProfileForApply(cls, profileInstance, hostServices, configData, validationErrors):
      return cls.VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, True)

   @staticmethod
   def VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, forApply):
      #EnterDebugger()
      hba = GetIscsiHbaFromProfile(None, profileInstance, False)

      if hba is None:
         return True

      result = VerifyInitiatorCommonConfigPolicies(cls,
                                                   profileInstance,
                                                   hba,
                                                   hostServices,
                                                   configData,
                                                   forApply,
                                                   validationErrors)
      IscsiLog(3, 'VerifyProfileInt(forApply=%s) for %s:%s is returning %d' % \
                     (forApply, profileInstance.__class__.__name__, id(profileInstance), result))
      return result

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, configData):
      for taskSet in taskList:
         ExecuteTask(cls, hostServices, configData, taskSet)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, configData, parent):
      IscsiLog(3, 'GenerateTaskList for %s' %(cls.__name__))
      if debuggerEnabled() == 2:
         ret = pdb.runcall(cls.GenerateTaskList_Impl, profileInstances, taskList, hostServices, configData, parent)
      else:
         ret = cls.GenerateTaskList_Impl(profileInstances, taskList, hostServices, configData, parent)
      return ret

   @classmethod
   def GenerateTaskList_Impl(cls, profileInstances, taskList, hostServices, configData, parent):
      for profInst in profileInstances:
         hba = GetIscsiHbaFromProfile(configData, profInst, False)

      return TASK_LIST_RES_OK

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      if debuggerEnabled() == 1:
         ret = pdb.runcall(cls.GenerateProfileFromConfig_Impl, hostServices, config, parent)
      else:
         ret = cls.GenerateProfileFromConfig_Impl(hostServices, config, parent)
      return ret

   @classmethod
   def GenerateProfileFromConfig_Impl(cls, hostServices, config, parent):
      iscsiInitiatorProfileList = GetIscsiHbaProfiles(cls, config, ISCSI_HBA_PROFILE_INDEPENDENT)

      return iscsiInitiatorProfileList

class IscsiInitiatorProfile(GenericProfile):
   subprofiles = [
                   IndependentHardwareIscsiInitiatorProfile,
                   SoftwareIscsiInitiatorProfile,
                   DependantHardwareIscsiInitiatorProfile
                 ]

   parentProfiles = [ storageprofile.StorageProfile ]

   version = ISCSI_PROFILE_VERSION

   complianceChecker = IscsiInitiatorProfileChecker()

   category = CATEGORY_STORAGE
   component = COMPONENT_ISCSI

   # called upon completion of RemediateConfig
   @classmethod
   def OnRemediateComplete(cls, hostServices, configData, parent):
      IscsiRescanAllAdapters(cls, parent, hostServices, configData, False)

   # Version verification
   @classmethod
   def CheckVersion(cls, version):
      return VerifyVersionCompatibility(cls, version)

   @classmethod
   def CheckCompliance(cls, profileInstances, hostServices, configData, parent):
      IscsiLog(3, 'CheckCompliance for %s' %(cls.__name__))
      complianceErrors = []

      SubProfilesToHba(profileInstances, configData, parent, complianceErrors)

      tasks = []
      CheckIscsiFirewall(profileInstances, hostServices, tasks)
      IscsiGenerateComplianceErrors(cls,
                                    profileInstances,
                                    profileInstances,
                                    hostServices,
                                    configData,
                                    parent,
                                    tasks,
                                    complianceErrors)
      return complianceErrors

   @classmethod
   def GatherData(cls, hostServices):
      return IscsiConfigData(hostServices)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, configData, validationErrors):
      #EnterDebugger()
      result = AssignIscsiHbaSelection(cls,
                                       profileInstance,
                                       hostServices,
                                       configData,
                                       validationErrors)
      IscsiLog(3, 'VerifyProfile for %s:%s is returning %d' % \
         (profileInstance.__class__.__name__, id(profileInstance), result))
      return result

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, configData):
      for taskSet in taskList:
         ExecuteTask(cls, hostServices, configData, taskSet)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, configData, parent):
      IscsiLog(3, 'GenerateTaskList for %s' %(cls.__name__))
      if debuggerEnabled() == 2:
         ret = pdb.runcall(cls.GenerateTaskList_Impl,
                           profileInstances,
                           taskList,
                           hostServices,
                           configData,
                           parent)
      else:
         ret = cls.GenerateTaskList_Impl(profileInstances, taskList, hostServices, configData, parent)
      return ret

   @classmethod
   def GenerateTaskList_Impl(cls, profileInstances, taskList, hostServices, configData, parent):
      TraverseProfiles(profileInstances)
      SubProfilesToHba(profileInstances, configData, parent)
      tmpTaskData = []
      CheckIscsiFirewall(profileInstances, hostServices, tmpTaskData)
      if len(tmpTaskData) != 0:
         tmpTaskMsg = IscsiCreateLocalizedMessage(tmpTaskData, ISCSI_ISCSI_FIREWALL_CONFIG, {})
         taskList.addTask(tmpTaskMsg, tmpTaskData)
      return TASK_LIST_RES_OK

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      if debuggerEnabled() == 1:
         ret = pdb.runcall(cls.GenerateProfileFromConfig_Impl, hostServices, config, parent)
      else:
         ret = cls.GenerateProfileFromConfig_Impl(hostServices, config, parent)
      return ret

   @classmethod
   def GenerateProfileFromConfig_Impl(cls, hostServices, config, parent):
      return cls()
