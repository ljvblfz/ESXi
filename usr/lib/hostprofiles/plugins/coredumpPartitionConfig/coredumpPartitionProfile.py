#!/usr/bin/python
# **********************************************************
# Copyright 2017 VMware, Inc.  All rights reserved.
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import CreateComplianceFailureValues, \
                      POLICY_NAME, PARAM_NAME
from pluginApi import CreateLocalizedMessage
from pluginApi import GenericProfile
from pluginApi import FixedPolicyOption
from pluginApi import log
from pluginApi import Policy
from pluginApi import PolicyOptComplianceChecker
from pluginApi import TASK_LIST_RES_OK

from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING, \
                      COMPONENT_COREDUMP_CONFIG

from .coredumpPartition import CoredumpPartitionProfile as cdpOld

ENABLED = 'Enabled'
ENABLE_PARTITION = 'enable partition'

vmsgPrefix = 'com.vmware.vim.profile.CoredumpPartitionProfile'

class CoredumpPartitionPolicyChecker(PolicyOptComplianceChecker):
   ''' Compliance Checker class for CoredumpPartition.
   '''
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices,
                             hostData):
      if isinstance(policyOpt, AutoConfigureOption) and not hostData[ENABLED]:
         msg = CreateLocalizedMessage(None,
            '%s.ComplianceError.Disabled.label' % vmsgPrefix)
         comparisonValues = CreateComplianceFailureValues(
            'CoredumpPartitionPolicy', POLICY_NAME, profileValue='enabled',
            hostValue='disabled')
         return (False, [(msg, [comparisonValues])])
      return (True, [])

class DefaultOption(FixedPolicyOption):
   paramMeta = []
   complianceChecker = CoredumpPartitionPolicyChecker

class AutoConfigureOption(FixedPolicyOption):
   paramMeta = []
   complianceChecker = CoredumpPartitionPolicyChecker

class CoredumpPartitionPolicy(Policy):
   possibleOptions = [DefaultOption, AutoConfigureOption]
   _defaultOption = DefaultOption


class CoredumpPartition(GenericProfile):
   ''' Coredump Partition Profile
   '''
   singleton = True
   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_COREDUMP_CONFIG
   policies = [CoredumpPartitionPolicy]
   complianceChecker = None

   @classmethod
   def GatherData(cls, hostServices):
      return cdpOld.ExtractConfig(hostServices)

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, hostData, parent):
      polOpt = DefaultOption([])
      if hostData[ENABLED]:
         polOpt = AutoConfigureOption([])
      return cls([CoredumpPartitionPolicy(True, polOpt)])

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        hostData, parent):
      profInst = profileInstances[0]
      opt = profInst.policies[0].policyOption
      if isinstance(opt, AutoConfigureOption) and not hostData[ENABLED]:
         msg = CreateLocalizedMessage(None, '%s.TaskList.Enable.label' %
                                      vmsgPrefix)
         taskList.addTask(msg, ENABLE_PARTITION)
      return TASK_LIST_RES_OK

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, hostData):
      for task in taskList:
         if task == ENABLE_PARTITION:
            cdpOld.SetConfig([{'Enabled': True}], hostServices)