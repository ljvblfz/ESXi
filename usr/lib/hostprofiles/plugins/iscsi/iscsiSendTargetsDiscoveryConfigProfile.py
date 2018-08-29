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
import pprint

from .iscsiPlatformUtils import *
from .iscsiPolicies import *
from .iscsiTargetConfigProfile import *

class SendTargetsConfigProfileChecker(ProfileComplianceChecker):
   def CheckProfileCompliance(self, profileInsts, hostServices, configData, parent):

      complianceFailures = []

      cls = IscsiSendTargetsDiscoveryConfigProfile()
      complianceFailures = cls.CheckCompliance(profileInsts, hostServices, configData, parent)

      # Checks the specified profile instances against the current config.
      return (len(complianceFailures) == 0, complianceFailures)

def GenerateRemoveSendTargetsDiscoveryConfigTaskList(configData, parent, taskList, profInstances):
   taskListData = CheckRemoveSendTargetsDiscoveryConfig(configData, parent, profInstances)

   if len(taskListData) != 0:
      hba = GetIscsiHbaFromProfile(configData, parent, False)
      taskListMsg = IscsiCreateLocalizedMessage(taskListData,
                                                '%s.label' % ISCSI_SENDTARGET_DISCOVERY_CONFIG_UPDATE,
                                                {'hba': hba.GetName()})
      taskList.addTask(taskListMsg, taskListData)

def CheckRemoveSendTargetsDiscoveryConfig(configData, parent, profInstances):
   taskListData = CreateRemoveSendTargetsDiscoveryFromConfigData(configData, parent, profInstances)
   PrintTaskData(taskListData)

   return taskListData

def GenerateSendTargetsDiscoveryConfigTaskList(configData, parent, taskList, profInst):
   taskListData = CheckSendTargetsDiscoveryConfig(configData, parent, profInst, True)

   if len(taskListData) != 0:
      hba = GetIscsiHbaFromProfile(configData, parent, False)
      taskListMsg = IscsiCreateLocalizedMessage(taskListData,
                                                '%s.label' % ISCSI_SENDTARGET_DISCOVERY_CONFIG_UPDATE,
                                                {'hba': hba.GetName()})
      taskList.addTask(taskListMsg, taskListData)

def CheckSendTargetsDiscoveryConfig(configData, parent, profInst, genTaskListOK):
   hba = GetIscsiHbaFromProfile(configData, parent, False)
   if hba is None:
      return []

   #PrintProfileInstances([parent])
   #PrintProfileInstances([profInst])

   ipAddress = ExtractPolicyOptionValue(profInst,
                                       IscsiSendTargetsDiscoveryIdentityPolicy,
                                       [
                                        ([IscsiSendTargetsDiscoveryIdentityPolicyOption],
                                         FROM_ATTRIBUTE, 'discoveryAddress'),
                                       ],
                                       True)
   portNumber = ExtractPolicyOptionValue(profInst,
                                       IscsiSendTargetsDiscoveryIdentityPolicy,
                                       [
                                        ([IscsiSendTargetsDiscoveryIdentityPolicyOption],
                                         FROM_ATTRIBUTE, 'discoveryPort'),
                                       ],
                                       True)

   params = ExtractTargetParamsFromProfileInstance(profInst)

   currStdData = FindSendTargetDiscovery(hba, ipAddress, portNumber, True)

   newStdData = IscsiSendTarget(ipAddress,
                                portNumber,
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

   taskListData = CreateSendTargetDiscoveryTaskFromConfigData(hba, currStdData, newStdData, genTaskListOK)
   PrintTaskData(taskListData)

   return taskListData

def GetIscsiSendTargetsDiscoveryProfiles(cls, config, parent):
   hba = GetIscsiHbaFromProfile(config, parent, True)
   sendTargets = hba.sendTargetDiscoveryList
   iscsiSendTargetsDiscoveryProfiles = []

   for discovery in sendTargets:
      sendTargetsDiscoveryIdentityPolicyParams = [('discoveryAddress', discovery.ipAddress),
                                                  ('discoveryPort', discovery.portNumber)]
      iscsiSendTargetsDiscoveryPolicies = [
         IscsiSendTargetsDiscoveryIdentityPolicy(True,
            IscsiSendTargetsDiscoveryIdentityPolicyOption(sendTargetsDiscoveryIdentityPolicyParams))
      ]

      iscsiSendTargetsDiscoveryPolicies.extend(GetTargetCommonConfigPolicies(discovery))

      profile = cls(policies=iscsiSendTargetsDiscoveryPolicies)
      iscsiSendTargetsDiscoveryProfiles.append(profile)

   return iscsiSendTargetsDiscoveryProfiles

class IscsiSendTargetsDiscoveryConfigProfile(GenericProfile):
   policies = [
      IscsiSendTargetsDiscoveryIdentityPolicy,
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

   complianceChecker = SendTargetsConfigProfileChecker()

   dependents = [
      IscsiDiscoveredTargetConfigProfile,
      IscsiStaticTargetConfigProfile
   ]

   singleton = False

   version = ISCSI_PROFILE_VERSION

   def GetParams(self, hba):
      params = None

      idPolicy = self.IscsiSendTargetsDiscoveryIdentityPolicy
      ipAddress = idPolicy.policyOption.discoveryAddress
      portNumber = idPolicy.policyOption.discoveryPort
      sendTarget = FindSendTargetDiscovery(hba, ipAddress, portNumber, False)
      if sendTarget != None:
         params = sendTarget.params

      return params

   # Version verification
   @classmethod
   def CheckVersion(cls, version):
      return VerifyVersionCompatibility(cls, version)

   @classmethod
   def CheckCompliance(cls, profileInstances, hostServices, configData, parent):
      IscsiLog(3, 'CheckCompliance for %s' %(cls.__name__))
      complianceErrors = []

      if isDisabledInitiatorProfile(parent):
         return complianceErrors

      # Generate the tasks for non-existing/compliant (in the system)
      # send target records
      for profInst in profileInstances:
         ret = ProfilesToHba([profInst.parentProfile], configData, parent, None)
         if ret == False:
            continue

         hba = GetIscsiHbaFromProfile(configData, parent, False)
         if hba == None or hba.enabled == False:
            continue

         taskData = CheckSendTargetsDiscoveryConfig(configData,
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

      # Generate the tasks for non-existing (in profile) send target records
      taskData = CheckRemoveSendTargetsDiscoveryConfig(configData,
                                                       parent,
                                                       profileInstances)
      # Convert the tasks into non-compliant errors
      IscsiGenerateComplianceErrors(cls,
                                    profileInstances,
                                    profileInstances,
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
      for profInst in profileInstances:
         if isDisabledInitiatorProfile(parent):
            continue

         GenerateSendTargetsDiscoveryConfigTaskList(configData, parent, taskList, profInst)

      GenerateRemoveSendTargetsDiscoveryConfigTaskList(configData, parent, taskList, profileInstances)

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
      iscsiSendTargetsProfileList = GetIscsiSendTargetsDiscoveryProfiles(cls,config, parent)
      return iscsiSendTargetsProfileList
