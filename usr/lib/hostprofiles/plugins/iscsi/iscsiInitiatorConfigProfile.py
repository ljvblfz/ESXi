#!/usr/bin/python
# **********************************************************
# Copyright 2014-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import GenericProfile, Policy, FixedPolicyOption, \
                      ParameterMetadata, PolicyOptComplianceChecker, \
                      UserInputRequiredOption, ProfileComplianceChecker, \
                      CreateLocalizedMessage, log, TASK_LIST_REQ_MAINT_MODE, \
                      TASK_LIST_RES_OK

from .iscsiPlatformUtils import *
from .iscsiPolicies import *
from .iscsiPortBindingConfigProfile import IscsiPortBindingConfigProfile
from hpCommon.utilities import VersionLessThan, VersionGreaterThanEqual

import pdb
import os
import pprint

class IscsiInitiatorConfigProfileChecker(ProfileComplianceChecker):
   def CheckProfileCompliance(self, profileInsts, hostServices, configData, parent):

      complianceFailures = []

      if len(profileInsts) > 0:
         #taskList = ProfileTaskList()
         taskList = []

         if isinstance(profileInsts[0], DependantHardwareIscsiInitiatorConfigProfile):
            cls = DependantHardwareIscsiInitiatorConfigProfile()
         elif isinstance(profileInsts[0], IndependentHardwareIscsiInitiatorConfigProfile):
            cls = IndependentHardwareIscsiInitiatorConfigProfile()
         elif isinstance(profileInsts[0], SoftwareIscsiInitiatorConfigProfile):
            cls = SoftwareIscsiInitiatorConfigProfile()
         else:
            assert()

         complianceFailures = cls.CheckCompliance(profileInsts, hostServices, configData, parent)

      # Checks the specified profile instances against the current config.
      return (len(complianceFailures) == 0, complianceFailures)

def GenerateInitiatorConfigTaskList(hbaType, configData, parent, taskList, profInst):
   tmpTaskData = CheckInitiatorConfig(hbaType, configData, parent, profInst, True)
   if len(tmpTaskData) != 0:
      hba = GetIscsiHbaFromProfile(configData, parent, False)
      tmpTaskMsg = IscsiCreateLocalizedMessage(tmpTaskData,
                                               '%s.label' % ISCSI_INITIATOR_CONFIG_UPDATE,
                                               {'hba': hba.GetName()})
      taskList.addTask(tmpTaskMsg, tmpTaskData)

def CheckInitiatorConfig(hbaType, configData, parent, profInst, genTaskList):
   params = dict([
      ('iqn', None),
      ('alias', None),
      ('ipv4Config', None),
      ('ipv6Config', None),
      ('linklocalConfig', None),
      ('ipv4Address', None),
      ('ipv4Netmask', None),
      ('ipv4Gateway', None),
      ('arpRedirection', None),
      ('jumboFrame', None),
      ('initiatorChapType', None),
      ('initiatorChapName', None),
      ('initiatorChapSecret', None),
      ('targetChapType', None),
      ('targetChapName', None),
      ('targetChapSecret', None),
      ('headerDigest', None),
      ('dataDigest', None),
      ('maxOutstandingR2T', None),
      ('firstBurstLength', None),
      ('maxBurstLength', None),
      ('maxRecvSegLength', None),
      ('noopOutInterval', None),
      ('noopOutTimeout', None),
      ('recoveryTimeout', None),
      ('loginTimeout', None),
      ('delayedAck', None),
   ])

   hba = GetIscsiHbaFromProfile(configData, parent, False)
   if hba is None:
      return []

   #PrintProfileInstances([parent])
   #PrintProfileInstances([profInst])

   profileVer = profInst.version

   # Initiator IQN
   params['iqn'] = ExtractPolicyOptionValue(profInst,
                                 Hba_InitiatorIqnSelectionPolicy,
                                 [([UserInputIqn], FROM_ATTRIBUTE,
                                 'iqn')],
                                 True)

   # Initiator Alias
   params['alias'] = ExtractPolicyOptionValue(profInst,
                                 Hba_InitiatorAliasSelectionPolicy,
                                 [([UserInputAlias], FROM_ATTRIBUTE,
                                 'alias')],
                                 True)

   if hbaType == ISCSI_HBA_PROFILE_INDEPENDENT:

      # Hba_InitiatorIpv4ConfigSelectionPolicy, Hba_InitiatorIpv6ConfigSelectionPolicy
      # are new policies added in iSCSI profile version 5.1.0
      params['ipv4Config'] = ExtractPolicyOptionValue(profInst,
                                 Hba_InitiatorIpv4ConfigSelectionPolicy,
                                 [([FixedDhcpv4Config, UserInputIpv4Config, NoIpv4Config, IgnoreIpv4Config], FROM_FUNCTION_CALL,
                                 ExtractIpv4Config)],
                                 False)

      # Initiator IPv6Config
      params['ipv6Config'] = ExtractPolicyOptionValue(profInst,
                                 Hba_InitiatorIpv6ConfigSelectionPolicy,
                                 [([UserInputIpv6Config, AutoConfigureIpv6, NoIpv6Config, IgnoreIpv6Config], FROM_FUNCTION_CALL,
                                 ExtractIpv6Config)],
                                 False)

      # Initiator linklocal Address Config
      params['linklocalConfig'] = ExtractPolicyOptionValue(profInst,
                                      Hba_InitiatorLinkLocalConfigSelectionPolicy,
                                      [([UserInputLinkLocalAddr, AutoConfigureLinkLocal, IgnoreLinkLocalConfig], FROM_FUNCTION_CALL,
                                      ExtractLinklocalConfig)],
                                      False)

      if VersionLessThan(profileVer, '5.1.0'):
         assert(params['ipv4Config'] == None)
         assert(params['ipv6Config'] == None)
         assert(params['linklocalConfig'] == None)

      # Hba_InitiatorIpv4AddressSelectionPolicy, Hba_InitiatorIpv4NetmaskSelectionPolicy
      # and Hba_InitiatorIpv4GatewaySelectionPolicy have been deprecated in
      # iSCSI profile version 5.1.0

      # Initiator IPv4Address
      params['ipv4Address'] = ExtractPolicyOptionValue(profInst,
                                 Hba_InitiatorIpv4AddressSelectionPolicy,
                                 [([UserInputIpv4Address], FROM_ATTRIBUTE,
                                 'ipv4Address')],
                                 False)

      # Initiator IPv4Netmask
      params['ipv4Netmask'] = ExtractPolicyOptionValue(profInst,
                                 Hba_InitiatorIpv4NetmaskSelectionPolicy,
                                 [([UserInputIpv4Netmask], FROM_ATTRIBUTE,
                                 'ipv4Netmask')],
                                 False)

      # Initiator IPv4Gateway
      params['ipv4Gateway'] = ExtractPolicyOptionValue(profInst,
                                 Hba_InitiatorIpv4GatewaySelectionPolicy,
                                 [([UserInputIpv4Gateway], FROM_ATTRIBUTE,
                                 'ipv4Gateway')],
                                 False)

      if VersionLessThan(profileVer, '5.1.0'):
         assert(params['ipv4Address'] != None)
         assert(params['ipv4Netmask'] != None)
         assert(params['ipv4Gateway'] != None)

      # ARP Redirection
      params['arpRedirection'] = ExtractPolicyOptionValue(profInst,
                                 Hba_ArpRedirectionSelectionPolicy,
                                 [
                                  ([UseFixedArpRedirection, UserInputArpRedirection],
                                    FROM_ATTRIBUTE, 'arpRedirection'),
                                 ],
                                 True)

      # MTU
      params['jumboFrame'] = ExtractPolicyOptionValue(profInst,
                                 Hba_JumboFrameSelectionPolicy,
                                 [
                                  ([UseFixedMTU, UserInputJumboFrame],
                                    FROM_ATTRIBUTE, 'jumboFrame'),
                                 ],
                                 True)

   # Initiator Chap
   params['initiatorChapType'] = ExtractPolicyOptionValue(profInst,
                                    Hba_InitiatorChapTypeSelectionPolicy,
                                    [([SettingNotSupported,
                                    DoNotUseChap,
                                    DoNotUseChapUnlessRequiredByTarget,
                                    UseChapUnlessProhibitedByTarget,
                                    UseChap], FROM_CLASS_NAME,
                                    '')],
                                    True)

   params['initiatorChapName'] = ExtractPolicyOptionValue(profInst,
                                    Hba_InitiatorChapNameSelectionPolicy,
                                    [([UseFixedChapName,
                                    UserInputChapName], FROM_ATTRIBUTE,
                                    'chapName'),
                                     ([UseInitiatorIqnAsChapName],
                                      FROM_CONSTANT,
                                      params['iqn'])],
                                    True)

   params['initiatorChapSecret'] = ExtractPolicyOptionValue(profInst,
                                    Hba_InitiatorChapSecretSelectionPolicy,
                                    [([UseFixedChapSecret,
                                    UserInputChapSecret], FROM_FUNCTION_CALL,
                                    VimPasswordToIscsiChapSecret)],
                                    True)

   # Target Chap
   params['targetChapType'] = ExtractPolicyOptionValue(profInst,
                                    Hba_TargetChapTypeSelectionPolicy,
                                    [([SettingNotSupported,
                                    DoNotUseChap,
                                    DoNotUseChapUnlessRequiredByTarget,
                                    UseChapUnlessProhibitedByTarget,
                                    UseChap], FROM_CLASS_NAME,
                                    '')],
                                    True)

   params['targetChapName'] = ExtractPolicyOptionValue(profInst,
                                    Hba_TargetChapNameSelectionPolicy,
                                    [
                                     ([UseFixedChapName,
                                       UserInputChapName],
                                      FROM_ATTRIBUTE,
                                      'chapName'),
                                     ([UseInitiatorIqnAsChapName],
                                      FROM_CONSTANT,
                                      params['iqn']),
                                    ],
                                    True)

   params['targetChapSecret'] = ExtractPolicyOptionValue(profInst,
                                    Hba_TargetChapSecretSelectionPolicy,
                                    [
                                     ([UseFixedChapSecret,
                                       UserInputChapSecret],
                                      FROM_FUNCTION_CALL,
                                      VimPasswordToIscsiChapSecret),
                                    ],
                                    True)

   params['headerDigest'] = ExtractPolicyOptionValue(profInst,
                                    Hba_HeaderDigestSelectionPolicy,
                                    [
                                     ([SettingNotSupported,
                                      DigestProhibited,
                                      DigestDiscouraged,
                                      DigestPreferred,
                                      DigestRequired],
                                      FROM_CLASS_NAME,
                                      ''),
                                    ],
                                    True)

   params['dataDigest'] = ExtractPolicyOptionValue(profInst,
                                    Hba_DataDigestSelectionPolicy,
                                    [
                                     ([SettingNotSupported,
                                       DigestProhibited,
                                       DigestDiscouraged,
                                       DigestPreferred,
                                       DigestRequired],
                                      FROM_CLASS_NAME,
                                      ''),
                                    ],
                                    True)

   params['maxOutstandingR2T'] = ExtractPolicyOptionValue(profInst,
                                    Hba_MaxOutstandingR2TSelectionPolicy,
                                    [
                                     ([SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedMaxOutstandingR2T, UserInputMaxOutstandingR2T],
                                       FROM_ATTRIBUTE, 'maxOutstandingR2T'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    True)

   params['firstBurstLength'] = ExtractPolicyOptionValue(profInst,
                                    Hba_FirstBurstLengthSelectionPolicy,
                                    [
                                     ([SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedFirstBurstLength, UserInputFirstBurstLength],
                                       FROM_ATTRIBUTE, 'firstBurstLength'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    True)

   params['maxBurstLength'] = ExtractPolicyOptionValue(profInst,
                                    Hba_MaxBurstLengthSelectionPolicy,
                                    [
                                     ([SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedMaxBurstLength, UserInputMaxBurstLength],
                                       FROM_ATTRIBUTE, 'maxBurstLength'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    True)

   params['maxReceiveSegmentLength'] = ExtractPolicyOptionValue(profInst,
                                    Hba_MaxReceiveSegmentLengthSelectionPolicy,
                                    [
                                     ([SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedMaxReceiveSegmentLength, UserInputMaxReceiveSegmentLength],
                                       FROM_ATTRIBUTE, 'maxReceiveSegmentLength'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    True)

   params['noopOutInterval'] = ExtractPolicyOptionValue(profInst,
                                    Hba_NoopOutIntervalSelectionPolicy,
                                    [
                                     ([SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedNoopOutInterval, UserInputNoopOutInterval],
                                       FROM_ATTRIBUTE, 'noopOutInterval'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    True)

   params['noopOutTimeout'] = ExtractPolicyOptionValue(profInst,
                                    Hba_NoopOutTimeoutSelectionPolicy,
                                    [
                                     ([SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedNoopOutTimeout, UserInputNoopOutTimeout],
                                       FROM_ATTRIBUTE, 'noopOutTimeout'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    True)

   params['recoveryTimeout'] = ExtractPolicyOptionValue(profInst,
                                    Hba_RecoveryTimeoutSelectionPolicy,
                                    [
                                     ([SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedRecoveryTimeout, UserInputRecoveryTimeout],
                                       FROM_ATTRIBUTE, 'recoveryTimeout'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    True)
   params['loginTimeout'] = ExtractPolicyOptionValue(profInst,
                                    Hba_LoginTimeoutSelectionPolicy,
                                    [
                                     ([SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedLoginTimeout, UserInputLoginTimeout],
                                       FROM_ATTRIBUTE, 'loginTimeout'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    False)
   if params['loginTimeout'] is None:
      params['loginTimeout'] = ISCSI_DEFAULT_LOGINTIMEOUT

   params['delayedAck'] = ExtractPolicyOptionValue(profInst,
                                    Hba_DelayedAckSelectionPolicy,
                                    [
                                     ([SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedDelayedAck, UserInputDelayedAck],
                                       FROM_ATTRIBUTE, 'delayedAckEnabled'),
                                    ],
                                    True)

   newHbaData = IscsiHba(hba.name,
                         hbaType,
                         True,
                         None,
                         hba.pciSlotInfo,
                         hba.macAddress,
                         hba.driverName,
                         hba.vendorId,
                         params['iqn'],
                         params['alias'],
                         params['ipv4Address'],
                         params['ipv4Netmask'],
                         params['ipv4Gateway'],
                         params['arpRedirection'],
                         params['jumboFrame'],
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
                         (params['maxReceiveSegmentLength'], None, None, None),
                         (params['noopOutInterval'], None, None, None),
                         (params['noopOutTimeout'], None, None, None),
                         (params['recoveryTimeout'], None, None, None),
                         (params['loginTimeout'], None, None, None),
                         (params['delayedAck'], None, None, None),
                         params['ipv4Config'],
                         params['ipv6Config'],
                         params['linklocalConfig'],
                         None)

   tmpTaskData = CreateInitiatorConfigTaskFromConfigData(profileVer, hbaType, hba, newHbaData, genTaskList)

   PrintTaskData(tmpTaskData)
   return tmpTaskData

class IndependentHardwareIscsiInitiatorConfigProfile(GenericProfile):

   policies = [
      Hba_InitiatorIqnSelectionPolicy,
      Hba_InitiatorAliasSelectionPolicy,
      Hba_InitiatorIpv4ConfigSelectionPolicy,
      Hba_InitiatorIpv6ConfigSelectionPolicy,
      Hba_InitiatorLinkLocalConfigSelectionPolicy,
      Hba_InitiatorIpv4AddressSelectionPolicy, # deprecated in RELEASE_VERSION_2015
      Hba_InitiatorIpv4NetmaskSelectionPolicy, # deprecated in RELEASE_VERSION_2015
      Hba_InitiatorIpv4GatewaySelectionPolicy, # deprecated in RELEASE_VERSION_2015
      Hba_InitiatorIpv6AddressSelectionPolicy, # deprecated in RELEASE_VERSION_2015
      Hba_InitiatorIpv6PrefixSelectionPolicy,  # deprecated in RELEASE_VERSION_2015
      Hba_ArpRedirectionSelectionPolicy,
      Hba_JumboFrameSelectionPolicy,
      Hba_InitiatorChapTypeSelectionPolicy,
      Hba_InitiatorChapNameSelectionPolicy,
      Hba_InitiatorChapSecretSelectionPolicy,
      Hba_TargetChapTypeSelectionPolicy,
      Hba_TargetChapNameSelectionPolicy,
      Hba_TargetChapSecretSelectionPolicy,
      Hba_HeaderDigestSelectionPolicy,
      Hba_DataDigestSelectionPolicy,
      Hba_MaxOutstandingR2TSelectionPolicy,
      Hba_FirstBurstLengthSelectionPolicy,
      Hba_MaxBurstLengthSelectionPolicy,
      Hba_MaxReceiveSegmentLengthSelectionPolicy,
      Hba_NoopOutIntervalSelectionPolicy,
      Hba_NoopOutTimeoutSelectionPolicy,
      Hba_RecoveryTimeoutSelectionPolicy,
      Hba_LoginTimeoutSelectionPolicy,
      Hba_DelayedAckSelectionPolicy
   ]

   version = ISCSI_PROFILE_VERSION

   complianceChecker = IscsiInitiatorConfigProfileChecker()

   # Version verification
   @classmethod
   def CheckVersion(cls, version):
      return VerifyVersionCompatibility(cls, version)

   @classmethod
   def CheckCompliance(cls, profileInstances, hostServices, configData, parent):
      IscsiLog(3, 'CheckCompliance for %s' %(cls.__name__))
      complianceErrors = []
      for profInst in profileInstances:
         ret = ProfilesToHba([profInst.parentProfile], configData, parent, None)
         if ret == False:
            continue

         taskData = CheckInitiatorConfig(ISCSI_HBA_PROFILE_INDEPENDENT,
                                            configData, parent, profInst, False)
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

   def GetParams(self, hba):
      return hba.params

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, configData, validationErrors):
      return cls.VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, False)

   @classmethod
   def VerifyProfileForApply(cls, profileInstance, hostServices, configData, validationErrors):
      return cls.VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, True)

   @staticmethod
   def VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, forApply):
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
                  (forApply,
                   profileInstance.__class__.__name__,
                   id(profileInstance),
                   result))

      #EnterDebugger()
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
         GenerateInitiatorConfigTaskList(ISCSI_HBA_PROFILE_INDEPENDENT, configData, parent, taskList, profInst)

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
      # Get the hba from parent profile
      hba = GetIscsiHbaFromProfile(config, parent, True)

      # Determine default ipv4 configuration policy option based on current ipv4 configuration
      if hba.ipv4Config.ignore == True:
         ipv4Policy = Hba_InitiatorIpv4ConfigSelectionPolicy(True,
            IgnoreIpv4Config([]))
      elif hba.ipv4Config.enabled == False:
         ipv4Policy = Hba_InitiatorIpv4ConfigSelectionPolicy(True,
            NoIpv4Config([]))
      elif hba.ipv4Config.useDhcp == True:
         ipv4Policy = Hba_InitiatorIpv4ConfigSelectionPolicy(True,
            FixedDhcpv4Config([]))
      else:
         ipv4Policy = Hba_InitiatorIpv4ConfigSelectionPolicy(True,
            UserInputIpv4Config([]))

      # Determine default ipv6 configuration policy option based on current ipv6 configuration
      if hba.ipv6Config.ignore == True:
         ipv6Policy = Hba_InitiatorIpv6ConfigSelectionPolicy(True,
            IgnoreIpv6Config([]))
      elif hba.ipv6Config.enabled == False:
         ipv6Policy = Hba_InitiatorIpv6ConfigSelectionPolicy(True,
            NoIpv6Config([]))
      elif hba.ipv6Config.useRouterAdv == True or hba.ipv6Config.useDhcp6 == True:
         ipv6Policy = Hba_InitiatorIpv6ConfigSelectionPolicy(True,
            AutoConfigureIpv6([('useRouterAdvertisement', hba.ipv6Config.useRouterAdv),
                               ('useDhcpv6', hba.ipv6Config.useDhcp6)]))
      else:
         ipv6Policy  = Hba_InitiatorIpv6ConfigSelectionPolicy(True,
            UserInputIpv6Config([]))

      # Determine default linklocal configuration policy option
      if hba.linklocalConfig.ignore == True:
         linklocalPolicy = Hba_InitiatorLinkLocalConfigSelectionPolicy(True,
            IgnoreLinkLocalConfig([]))
      elif hba.linklocalConfig.useLinklocalAutoConf == True:
         linklocalPolicy = Hba_InitiatorLinkLocalConfigSelectionPolicy(True,
            AutoConfigureLinkLocal([]))
      else:
         linklocalPolicy = Hba_InitiatorLinkLocalConfigSelectionPolicy(True,
            UserInputLinkLocalAddr([]))

      # Independent Hardware Specific Policies
      iscsiInitiatorConfigPolicies = [
         ipv4Policy,

         ipv6Policy,

         linklocalPolicy,

         # deprecated policies Hba_InitiatorIpv4AddressSelectionPolicy,
         # Hba_InitiatorIpv4NetmaskSelectionPolicy, Hba_InitiatorIpv4GatewaySelectionPolicy,
         # Hba_InitiatorIpv6AddressSelectionPolicy, Hba_InitiatorIpv6PrefixSelectionPolicy
         # have been removed.
         # This is done to prevent newly extracted host profiles from containing
         # deprecated elements in the new hostprofile engine.

         Hba_ArpRedirectionSelectionPolicy(True,
            UserInputArpRedirection([])),

         Hba_JumboFrameSelectionPolicy(True,
            UserInputJumboFrame([]))
      ]

      iscsiInitiatorCommonConfigPolicies = GetInitiatorCommonConfigPolicies(hba)

      iscsiInitiatorConfigPolicies.extend(iscsiInitiatorCommonConfigPolicies)

      return cls(policies=iscsiInitiatorConfigPolicies)

class DependantHardwareIscsiInitiatorConfigProfile(GenericProfile):

   policies = [
      Hba_InitiatorIqnSelectionPolicy,
      Hba_InitiatorAliasSelectionPolicy,
      Hba_InitiatorChapTypeSelectionPolicy,
      Hba_InitiatorChapNameSelectionPolicy,
      Hba_InitiatorChapSecretSelectionPolicy,
      Hba_TargetChapTypeSelectionPolicy,
      Hba_TargetChapNameSelectionPolicy,
      Hba_TargetChapSecretSelectionPolicy,
      Hba_HeaderDigestSelectionPolicy,
      Hba_DataDigestSelectionPolicy,
      Hba_MaxOutstandingR2TSelectionPolicy,
      Hba_FirstBurstLengthSelectionPolicy,
      Hba_MaxBurstLengthSelectionPolicy,
      Hba_MaxReceiveSegmentLengthSelectionPolicy,
      Hba_NoopOutIntervalSelectionPolicy,
      Hba_NoopOutTimeoutSelectionPolicy,
      Hba_RecoveryTimeoutSelectionPolicy,
      Hba_LoginTimeoutSelectionPolicy,
      Hba_DelayedAckSelectionPolicy
   ]

   dependents = [
      IscsiPortBindingConfigProfile
   ]

   version = ISCSI_PROFILE_VERSION

   complianceChecker = IscsiInitiatorConfigProfileChecker()

   # Version verification
   @classmethod
   def CheckVersion(cls, version):
      return VerifyVersionCompatibility(cls, version)

   @classmethod
   def CheckCompliance(cls, profileInstances, hostServices, configData, parent):
      IscsiLog(3, 'CheckCompliance for %s' %(cls.__name__))
      complianceErrors = []
      for profInst in profileInstances:
         ret = ProfilesToHba([profInst.parentProfile], configData, parent, None)
         if ret == False:
            continue

         taskData = CheckInitiatorConfig(ISCSI_HBA_PROFILE_DEPENDENT, configData, parent, profInst, False)
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

   def GetParams(self, hba):
      return hba.params

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, configData, validationErrors):
      return cls.VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, False)

   @classmethod
   def VerifyProfileForApply(cls, profileInstance, hostServices, configData, validationErrors):
      return cls.VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, True)

   @staticmethod
   def VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, forApply):
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

      IscsiLog(3, 'VerifyProfileInt(forApply=%s) for %s:%s is returning %d' %\
               (forApply, profileInstance.__class__.__name__, id(profileInstance), result))
      #EnterDebugger()
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
         GenerateInitiatorConfigTaskList(ISCSI_HBA_PROFILE_DEPENDENT, configData, parent, taskList, profInst)

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
      hba = GetIscsiHbaFromProfile(config, parent, True)
      iscsiInitiatorConfigPolicies = GetInitiatorCommonConfigPolicies(hba)
      return cls(policies=iscsiInitiatorConfigPolicies)

class SoftwareIscsiInitiatorConfigProfile(GenericProfile):

   policies = [
      Hba_InitiatorIqnSelectionPolicy,
      Hba_InitiatorAliasSelectionPolicy,
      Hba_InitiatorChapTypeSelectionPolicy,
      Hba_InitiatorChapNameSelectionPolicy,
      Hba_InitiatorChapSecretSelectionPolicy,
      Hba_TargetChapTypeSelectionPolicy,
      Hba_TargetChapNameSelectionPolicy,
      Hba_TargetChapSecretSelectionPolicy,
      Hba_HeaderDigestSelectionPolicy,
      Hba_DataDigestSelectionPolicy,
      Hba_MaxOutstandingR2TSelectionPolicy,
      Hba_FirstBurstLengthSelectionPolicy,
      Hba_MaxBurstLengthSelectionPolicy,
      Hba_MaxReceiveSegmentLengthSelectionPolicy,
      Hba_NoopOutIntervalSelectionPolicy,
      Hba_NoopOutTimeoutSelectionPolicy,
      Hba_RecoveryTimeoutSelectionPolicy,
      Hba_LoginTimeoutSelectionPolicy,
      Hba_DelayedAckSelectionPolicy
   ]

   dependents = [
      IscsiPortBindingConfigProfile
   ]

   version = ISCSI_PROFILE_VERSION

   complianceChecker = IscsiInitiatorConfigProfileChecker()

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

      for profInst in profileInstances:
         ret = ProfilesToHba([profInst.parentProfile], configData, parent, None)
         if ret == False:
            continue

         hba = GetIscsiHbaFromProfile(configData, parent, False)
         if hba == None or hba.enabled == False:
            continue

         taskData = CheckInitiatorConfig(ISCSI_HBA_PROFILE_SOFTWARE,
                                         configData,
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

      return complianceErrors

   def GetParams(self, hba):
      return hba.params

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, configData, validationErrors):
      return cls.VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, False)

   @classmethod
   def VerifyProfileForApply(cls, profileInstance, hostServices, configData, validationErrors):
      return cls.VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, True)

   @staticmethod
   def VerifyProfileInt(cls, profileInstance, hostServices, configData, validationErrors, forApply):
      #EnterDebugger()

      hba = GetIscsiHbaFromProfile(None, profileInstance.parentProfile, False)
      if hba is None:
         return True

      GenericVerifyPolicy(profileInstance.Hba_InitiatorIqnSelectionPolicy,
                        profileInstance,
                        hba,
                        forApply,
                        None)

      if hba.enabled == False or \
         isDisabledInitiatorProfile(profileInstance.parentProfile):
         return True

      result = VerifyInitiatorCommonConfigPolicies(cls,
                                                   profileInstance,
                                                   hba,
                                                   hostServices,
                                                   configData,
                                                   forApply,
                                                   validationErrors)
      IscsiLog(3, 'VerifyProfileInt(forApply=%s) for %s:%s is returning %d' %\
                  (forApply, profileInstance.__class__.__name__, id(profileInstance), result))
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
            GenerateInitiatorConfigTaskList(ISCSI_HBA_PROFILE_SOFTWARE, configData, parent, taskList, profInst)

      return TASK_LIST_RES_OK

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      if debuggerEnabled() == 1:
         ret = pdb.runcall(cls.GenerateProfileFromConfig_Impl, hostServices, config, parent)
      else:
         ret = cls.GenerateProfileFromConfig_Impl(hostServices, config, parent)
         #EnterDebugger()
      return ret

   @classmethod
   def GenerateProfileFromConfig_Impl(cls, hostServices, config, parent):
      hba = GetIscsiHbaFromProfile(config, parent, True)
      iscsiInitiatorConfigPolicies = GetInitiatorCommonConfigPolicies(hba)
      return cls(policies=iscsiInitiatorConfigPolicies)
