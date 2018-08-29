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
from pluginApi import ParameterMetadata
from pluginApi import Policy
from pluginApi import PolicyOptComplianceChecker
from pluginApi import TASK_LIST_RES_OK

from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING, \
                      COMPONENT_COREDUMP_CONFIG
from .coredumpFile import CoredumpFileSizeValidator
from .coredumpFile import CF_MIN_SIZE, CF_ACTIVE_FIELD, CF_CONFIGURED_FIELD
from .coredumpFile import CoredumpFileProfile as cdfOld

DS = 'Datastore'
SIZE = 'Size'
ENABLED = 'Enabled'

PREFIX = 'com.vmware.vim.profile.CoredumpProfile.'
COMPLY_PREFIX = '%sComplianceError.' % PREFIX
TASK_PREFIX = '%sTaskList.' % PREFIX

AUTOENABLE_TASK = 'auto enable'
ENABLE_TASK = 'enable'
UPDATE_TASK = 'update'

def CreateDisabledComplianceError():
   ''' Create cc error when the coredump file is disabled on the host, but
       enabled in the profile.
   '''
   complyFailure = CreateLocalizedMessage(None, '%sDisabled.label' % \
                                          COMPLY_PREFIX)
   comparisonValues = CreateComplianceFailureValues('CoredumpFilePolicy',
                                                    POLICY_NAME,
                                                    profileValue='enabled',
                                                    hostValue='disabled')
   return (complyFailure, [comparisonValues])

def CreateParamComplianceError(param, pd, hd):
   ''' Create a compliance failure for a mismatch in the Datastore or Size
       parameters.
   '''
   complyFailure = CreateLocalizedMessage(None,
                                          '%s%s' % (COMPLY_PREFIX,
                                                   ('%s.label' % param)))
   comparisonValues = CreateComplianceFailureValues(param,
                                                    PARAM_NAME,
                                                    profileValue=pd,
                                                    hostValue=hd)
   return (complyFailure, [comparisonValues])

class CoredumpFilePolicyChecker(PolicyOptComplianceChecker):
   ''' Compliance Checker class for CoredumpFile.
   '''
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices,
                             hostData):
      failures = []
      if isinstance(policyOpt, AutoConfigureOption) and not hostData[ENABLED]:
         failures.append(CreateDisabledComplianceError())
      elif isinstance(policyOpt, ExplicitOption):
         if not hostData[ENABLED]:
            failures.append(CreateDisabledComplianceError())
         else:
            curDS, size = GetDSAndSize(hostServices)
            if policyOpt.Datastore and curDS != policyOpt.Datastore:
               failures.append(CreateParamComplianceError(DS,
                                                          policyOpt.Datastore,
                                                          curDS))
            if policyOpt.Size and size != policyOpt.Size:
               failures.append(CreateParamComplianceError(SIZE,
                                                          policyOpt.Size,
                                                          size))
      return not bool(failures), failures

class DefaultOption(FixedPolicyOption):
   paramMeta = []
   complianceChecker = CoredumpFilePolicyChecker

class AutoConfigureOption(FixedPolicyOption):
   paramMeta = []
   complianceChecker = CoredumpFilePolicyChecker

class ExplicitOption(FixedPolicyOption):
   paramMeta = [ParameterMetadata(DS, 'string', True),
                ParameterMetadata(SIZE, 'int', True,
                  paramChecker=CoredumpFileSizeValidator(CF_MIN_SIZE))]
   complianceChecker = CoredumpFilePolicyChecker

class CoredumpFilePolicy(Policy):
   possibleOptions = [DefaultOption, AutoConfigureOption, ExplicitOption]
   _defaultOption = DefaultOption

def GetDSAndSize(hostServices):
   ''' Get the datastore and size of the current configured coredump file.
   '''
   filePath = cdfOld._GetFilePath(hostServices, CF_CONFIGURED_FIELD)
   return cdfOld._GetFileEntry(hostServices, filePath)

def UpdateFile(hostServices, ds, size):
   ''' Update the coredump file given a datastore and size.
   '''
   curDatastore, curSize = GetDSAndSize(hostServices)
   return cdfOld._CheckAndUpdateFile(hostServices, ds, size, curDatastore,
                                     curSize)

class CoredumpFile(GenericProfile):
   ''' Coredump file profile.
   '''
   singleton = True
   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_COREDUMP_CONFIG
   policies = [CoredumpFilePolicy]

   complianceChecker = None

   @classmethod
   def GatherData(cls, hostServices):
      data = cdfOld.ExtractConfig(hostServices)
      return data

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, hostData, parent):
      polOpt = DefaultOption([])
      if hostData[ENABLED]:
         if hostData[SIZE]:
            polOpt = ExplicitOption([(SIZE, hostData[SIZE])])
         else:
            polOpt = AutoConfigureOption([])
      return cls([CoredumpFilePolicy(True, polOpt)])

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        hostData, parent):
      profInst = profileInstances[0]
      opt = profInst.policies[0].policyOption

      if isinstance(opt, AutoConfigureOption) and not hostData[ENABLED]:
         msg = CreateLocalizedMessage(None, '%sEnable.label' % TASK_PREFIX)
         taskList.addTask(msg, AUTOENABLE_TASK)
      elif isinstance(opt, ExplicitOption):
         if not hostData[ENABLED]:
            msg = CreateLocalizedMessage(None, '%sEnable.label' % TASK_PREFIX)
            taskList.addTask(msg, (ENABLE_TASK, (opt.Datastore, opt.Size)))
         else:
            curDatastore, curSize = GetDSAndSize(hostServices)
            if (opt.Datastore and curDatastore != opt.Datastore) or \
              (opt.Size and curSize != opt.Size):
               msg = CreateLocalizedMessage(None, '%sUpdate.label' %
                                            TASK_PREFIX)
               taskList.addTask(msg, (UPDATE_TASK, (opt.Datastore, opt.Size)))

      return TASK_LIST_RES_OK

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, hostData):
      for task in taskList:
         if task == AUTOENABLE_TASK:
            if cdfOld._IsFileValid(hostServices, CF_CONFIGURED_FIELD):
               cdfOld._ActivateFile(hostServices)
            else:
               cdfOld._AddEnableFile(hostServices, '', 0)
         else:
            taskType, taskData = task
            ds, size = taskData
            if taskType == UPDATE_TASK:
               UpdateFile(hostServices, ds, size)
            elif cdfOld._IsFileValid(hostServices, CF_CONFIGURED_FIELD):
               if not UpdateFile(hostServices, ds, size):
                  cdfOld._ActivateFile(hostServices)
            else:
               cdfOld._AddEnableFile(hostServices, ds, size)


