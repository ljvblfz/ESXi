#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import GenericProfile, Policy, FixedPolicyOption, \
                      ParameterMetadata, PolicyOptComplianceChecker, \
                      ProfileComplianceChecker, CreateLocalizedMessage, log, \
                      TASK_LIST_REQ_MAINT_MODE, TASK_LIST_RES_OK
import pdb
import os

from .iscsiPlatformUtils import *
from .iscsiPolicies import *

def TargetConfigProfileChecker(cls, profileInsts, hostServices, configData, parent):
      complianceFailures = []

      complianceFailures = cls.CheckCompliance(profileInsts, hostServices, configData, parent)

      # Checks the specified profile instances against the current config.
      return (len(complianceFailures) == 0, complianceFailures)

class StaticTargetConfigProfileChecker(ProfileComplianceChecker):
   def CheckProfileCompliance(self, profileInsts, hostServices, configData, parent):
      return TargetConfigProfileChecker(IscsiStaticTargetConfigProfile(), profileInsts, hostServices, configData, parent)

class DiscoveredTargetConfigProfileChecker(ProfileComplianceChecker):
   # A compliance checker type for the Singleton Middle Profile. It implements
   # both the PolicyOptComplianceChecker and ProfileComplianceChecker interfaces.
   #profileType = None

   def CheckProfileCompliance(self, profileInsts, hostServices, configData, parent):
      return TargetConfigProfileChecker(IscsiDiscoveredTargetConfigProfile(), profileInsts, hostServices, configData, parent)

def GenerateRemoveTargetsConfigTaskList(configData, targetType, parent, taskList, profInstances):
   tmpTaskData = CheckRemoveTargetsConfig(configData, targetType, parent, profInstances, True)
   if len(tmpTaskData) != 0:
      hba = GetIscsiHbaFromProfile(configData, parent, False)
      tmpTaskMsg = IscsiCreateLocalizedMessage(tmpTaskData,
                                               '%s.label' % ISCSI_TARGET_CONFIG_UPDATE,
                                               {'hba': hba.GetName()})
      taskList.addTask(tmpTaskMsg, tmpTaskData)

def CheckRemoveTargetsConfig(configData, targetType, parent, profInstances, genTaskListOK):
   tmpTaskData = CreateRemoveTargetConfigTaskFromConfigData(configData, parent, profInstances)
   PrintTaskData(tmpTaskData)

   return tmpTaskData

def GenerateTargetsConfigTaskList(configData, targetType, parent, taskList, profInst):
   tmpTaskData = CheckTargetsConfig(configData, targetType, parent, profInst, True)

   if len(tmpTaskData) != 0:
      hba = GetIscsiHbaFromProfile(configData, parent, False)
      tmpTaskMsg = IscsiCreateLocalizedMessage(tmpTaskData,
                                               '%s.label' % ISCSI_TARGET_CONFIG_UPDATE,
                                               {'hba': hba.GetName()})
      taskList.addTask(tmpTaskMsg, tmpTaskData)

def CheckTargetsConfig(configData, targetType, parent, profInst, genTaskListOK):
   hba = GetIscsiHbaFromProfile(configData, parent, False)
   if hba is None:
      return []

   #PrintProfileInstances([parent])
   #PrintProfileInstances([profInst])

   policyInst = profInst.IscsiTargetIdentityPolicy
   assert isinstance(policyInst.policyOption, IscsiTargetIdentityPolicyOption), \
      'Target Profile %u does not have IscsiTargetIdentityPolicyOption policy option' % (id(profInst))

   ipAddress = policyInst.policyOption.targetAddress
   portNumber = policyInst.policyOption.targetPort
   iqn = policyInst.policyOption.targetIqn

   params = ExtractTargetParamsFromProfileInstance(profInst)

   currTargetData = FindTarget(targetType, hba, ipAddress, portNumber, iqn, True)

   newTargetData = IscsiTarget(ipAddress,
                               portNumber,
                               iqn,
                               targetType,
                               'false',
                               params['initiatorChapType'],
                               params['initiatorChapName'],
                               params['initiatorChapSecret'],
                               params['targetChapType'],
                               params['targetChapName'],
                               params['targetChapSecret'],
                               (params['headerDigest'], None, None, None),
                               (params['dataDigest'], None, None, None),
                               (params['maxOutstandingR2T'], None, None, None),
                               (params['firstBurstLength'], None, None, None),
                               (params['maxBurstLength'], None, None, None),
                               (params['maxRecvSegLength'], None, None, None),
                               (params['noopOutInterval'], None, None, None),
                               (params['noopOutTimeout'], None, None, None),
                               (params['recoveryTimeout'], None, None, None),
                               (params['loginTimeout'], None, None, None),
                               (params['delayedAck'], None, None, None))

   tmpTaskData = CreateTargetConfigTaskFromConfigData(hba, currTargetData, newTargetData, genTaskListOK)

   PrintTaskData(tmpTaskData)

   return tmpTaskData

def GetIscsiTargetProfiles(cls, targetType, config, parent):
   hba = GetIscsiHbaFromProfile(config, parent, True)
   if targetType == ISCSI_STATIC_TARGETS:
      targetList = hba.staticTargetList
   else:
      targetList = hba.discoveredTargetList

   iscsiTargetProfiles = []

   for target in targetList:
      targetIdentityPolicyParams = [('targetAddress', target.ipAddress),
                                    ('targetPort', target.portNumber),
                                    ('targetIqn', target.iqn)
      ]

      iscsiTargetPolicies = [
         IscsiTargetIdentityPolicy(True,
            IscsiTargetIdentityPolicyOption(targetIdentityPolicyParams))
      ]

      iscsiTargetPolicies.extend(GetTargetCommonConfigPolicies(target))

      profile = cls(policies=iscsiTargetPolicies)
      iscsiTargetProfiles.append(profile)

   return iscsiTargetProfiles

class IscsiStaticTargetConfigProfile(GenericProfile):
   policies = [
      IscsiTargetIdentityPolicy,
      Target_InitiatorChapTypeSelectionPolicy,
      Target_InitiatorChapNameSelectionPolicy,
      Target_InitiatorChapSecretSelectionPolicy,
      Target_TargetChapTypeSelectionPolicy,
      Target_TargetChapNameSelectionPolicy,
      Target_TargetChapSecretSelectionPolicy,
      Target_HeaderDigestSelectionPolicy,
      Target_DataDigestSelectionPolicy,
      Target_MaxOutstandingR2TSelectionPolicy,
      Target_FirstBurstLengthSelectionPolicy,
      Target_MaxBurstLengthSelectionPolicy,
      Target_MaxReceiveSegmentLengthSelectionPolicy,
      Target_NoopOutIntervalSelectionPolicy,
      Target_NoopOutTimeoutSelectionPolicy,
      Target_RecoveryTimeoutSelectionPolicy,
      Target_LoginTimeoutSelectionPolicy,
      Target_DelayedAckSelectionPolicy
   ]

   complianceChecker = StaticTargetConfigProfileChecker()

   singleton = False

   version = ISCSI_PROFILE_VERSION

   targetType = ISCSI_STATIC_TARGETS

   def GetParams(self, hba):
      params = None

      idPolicy = self.IscsiTargetIdentityPolicy
      ipAddress = idPolicy.policyOption.targetAddress
      portNumber = idPolicy.policyOption.targetPort
      iqn = idPolicy.policyOption.targetIqn

      target = FindTarget(self.targetType, hba, ipAddress, portNumber, iqn, False)
      if target != None:
         params = target.params

      return params

   # Version verification
   @classmethod
   def CheckVersion(cls, version):
      return VerifyVersionCompatibility(cls, version)

   @classmethod
   def CheckCompliance(cls, profileInstances, hostServices, configData, parent):
      IscsiLog(3, 'CheckCompliance for %s' %(cls.__name__))
      complianceErrors = []

      # Generate the tasks for non-existing/compliant (in the system)
      # send target records
      for profInst in profileInstances:
         ret = ProfilesToHba([profInst.parentProfile], configData, parent, None)
         if ret == False:
            continue

         hba = GetIscsiHbaFromProfile(configData, parent, False)
         if hba == None or hba.enabled == False:
            continue

         taskData = CheckTargetsConfig(configData,
                                       cls.targetType,
                                       parent,
                                       profInst,
                                       False)
         # Convert the tasks into non-compliant errors
         IscsiGenerateComplianceErrors(cls,
                                       profileInstances,
                                       profInst,
                                       hostServices,
                                       configData,
                                       parent,
                                       taskData,
                                       complianceErrors)

      # Generate the tasks for non-existing (in profile) target records
      taskData = CheckRemoveTargetsConfig(configData,
                                          cls.targetType,
                                          parent,
                                          profileInstances,
                                          False)

      # Convert the tasks into non-compliant errors
      IscsiGenerateComplianceErrors(cls,
                                    profileInstances,
                                    None,
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
      if isDisabledInitiatorProfile(profileInstance.parentProfile):
         return True

      hba = GetIscsiHbaFromProfile(None, profileInstance.parentProfile, False)
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
      #EnterDebugger()
      return result

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, configData):
      hbaInstances = FindIscsiHbaByDriverName(configData, SOFTWARE_ISCSI_DRIVER_NAME, None)
      assert(len(hbaInstances) == 1)

      for taskSet in taskList:
         ExecuteTask(cls, hostServices, configData, taskSet,
            SOFTWARE_ISCSI_ADAPTER_PLACE_HOLDER, hbaInstances[0].name)

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
      if not isDisabledInitiatorProfile(parent):
         for profInst in profileInstances:
            GenerateTargetsConfigTaskList(configData, cls.targetType, parent, taskList, profInst)

         GenerateRemoveTargetsConfigTaskList(configData, cls.targetType, parent, taskList, profileInstances)

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
      iscsiTargetProfileList = GetIscsiTargetProfiles(cls, cls.targetType, config, parent)
      return iscsiTargetProfileList

class IscsiDiscoveredTargetConfigProfile(GenericProfile):
   policies = [
      IscsiTargetIdentityPolicy,
      Target_InitiatorChapTypeSelectionPolicy,
      Target_InitiatorChapNameSelectionPolicy,
      Target_InitiatorChapSecretSelectionPolicy,
      Target_TargetChapTypeSelectionPolicy,
      Target_TargetChapNameSelectionPolicy,
      Target_TargetChapSecretSelectionPolicy,
      Target_HeaderDigestSelectionPolicy,
      Target_DataDigestSelectionPolicy,
      Target_MaxOutstandingR2TSelectionPolicy,
      Target_FirstBurstLengthSelectionPolicy,
      Target_MaxBurstLengthSelectionPolicy,
      Target_MaxReceiveSegmentLengthSelectionPolicy,
      Target_NoopOutIntervalSelectionPolicy,
      Target_NoopOutTimeoutSelectionPolicy,
      Target_RecoveryTimeoutSelectionPolicy,
      Target_LoginTimeoutSelectionPolicy,
      Target_DelayedAckSelectionPolicy
   ]

   complianceChecker = DiscoveredTargetConfigProfileChecker()

   targetType = ISCSI_SEND_TARGETS

   singleton = False

   version = ISCSI_PROFILE_VERSION

   def GetParams(self, hba):
      idPolicy = self.IscsiTargetIdentityPolicy
      ipAddress = idPolicy.policyOption.targetAddress
      portNumber = idPolicy.policyOption.targetPort
      iqn = idPolicy.policyOption.targetIqn

      target = FindTarget(self.targetType, hba, ipAddress, portNumber, iqn, False)
      if target is not None:
         return target.params
      else:
         return None

   # Version verification
   @classmethod
   def CheckVersion(cls, version):
      return VerifyVersionCompatibility(cls, version)

   @classmethod
   def CheckCompliance(cls, profileInstances, hostServices, configData, parent):
      IscsiLog(3, 'CheckCompliance for %s' %(cls.__name__))
      complianceErrors = []

      if not isDisabledInitiatorProfile(parent):
         for profInst in profileInstances:
            ret = ProfilesToHba([profInst.parentProfile], configData, parent, None)
            if ret == False:
               continue

            hba = GetIscsiHbaFromProfile(configData, parent, False)
            if hba == None or hba.enabled == False:
               continue

            taskData = CheckTargetsConfig(configData, cls.targetType, parent, profInst, False)

            # Convert the tasks into non-compliant errors
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
      result = True

      if not isDisabledInitiatorProfile(profileInstance.parentProfile):
         hba = GetIscsiHbaFromProfile(None, profileInstance.parentProfile, False)
         if hba:
            result = VerifyInitiatorCommonConfigPolicies(cls,
                                                         profileInstance,
                                                         hba,
                                                         hostServices,
                                                         configData,
                                                         forApply,
                                                         validationErrors)
            IscsiLog(3, 'VerifyProfileInt(forApply=%s) for %s:%s is returning %d' % \
                        (forApply, profileInstance.__class__.__name__, id(profileInstance), result))

      #EnterDebugger()
      return result

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, configData):
      hbaInstances = FindIscsiHbaByDriverName(configData, SOFTWARE_ISCSI_DRIVER_NAME, None)
      assert(len(hbaInstances) == 1)

      for taskSet in taskList:
         ExecuteTask(cls, hostServices, configData, taskSet,
            SOFTWARE_ISCSI_ADAPTER_PLACE_HOLDER, hbaInstances[0].name)

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
      if not isDisabledInitiatorProfile(parent):
         for profInst in profileInstances:
            GenerateTargetsConfigTaskList(configData, cls.targetType, parent, taskList, profInst)

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
      iscsiTargetProfileList = GetIscsiTargetProfiles(cls, cls.targetType, config, parent)
      return iscsiTargetProfileList
