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

class PortBindingConfigProfileChecker(ProfileComplianceChecker):
   def CheckProfileCompliance(self, profileInsts, hostServices, configData, parent):

      complianceFailures = []

      cls = IscsiPortBindingConfigProfile()
      complianceFailures = cls.CheckCompliance(profileInsts, hostServices, configData, parent)

      # Checks the specified profile instances against the current config.
      return (len(complianceFailures) == 0, complianceFailures)

def GenerateVnicListFromProfileInstance(hostServices,
                                        configData,
                                        parent,
                                        profInst,
                                        vnicsByDevice,
                                        compatibleVnics):

   hba = GetIscsiHbaFromProfile(configData, parent, False)
   if hba is None:
      return

   #PrintProfileInstances([profInst])

   policyInst = profInst.IscsiVnicSelectionPolicy

   if isinstance(policyInst.policyOption, BindVnicByDevice):
      vnicsByDevice.append(policyInst.policyOption.vnicDevice)
   elif isinstance(policyInst.policyOption, BindCompatibleVnics):
      allOrFirst = policyInst.policyOption.all
      portgroups = policyInst.policyOption.portgroups
      compatibleVnics.extend(FindCompatibleVnics(hba, hostServices, allOrFirst, portgroups))
   elif isinstance(policyInst.policyOption, BindVnicByIpv4Subnet):
      allOrFirst = policyInst.policyOption.all
      ipv4Address = policyInst.policyOption.ipv4Address
      ipv4Netmask = policyInst.policyOption.ipv4Netmask
      compatibleVnics.extend(FindVnicsByIpv4Subnet(hba, hostServices, allOrFirst, ipv4Address, ipv4Netmask))
   elif isinstance(policyInst.policyOption, BindVnicByIpv6Subnet):
      allOrFirst = policyInst.policyOption.all
      ipv6Address = policyInst.policyOption.ipv6Address
      ipv6Prefix = policyInst.policyOption.ipv6Prefix
      compatibleVnics.extend(FindVnicsByIpv6Subnet(hba, hostServices, allOrFirst, ipv6Address, ipv6Prefix))
   else:
      assert()

   return

def GeneratePortBindingConfigTaskList(hostServices, configData, profileInstances, parent, taskList):
   hba = GetIscsiHbaFromProfile(configData, parent, False)
   if hba is None:
      return

   if len(profileInstances) != 0:
      tasks = []
      for profInst in profileInstances:
         tasks.append(profInst.IscsiVnicSelectionPolicy.policyOption.toTaskSet())

      if len(tasks) != 0:
         taskSet = [{'task': 'ISCSI_INITIATOR_CONFIG_NP',
                     'taskData': tasks,
                     'taskFunc': 'IscsiDoPortBindingTasks',
                     'hba': hba.name,
                     'failOK': True}]

         PrintTaskData(taskSet)
   else:
      taskSet = CheckPortBindingConfig(hostServices, configData, parent, [], [])

   if len(taskSet) != 0:
      tmpTaskMsg = IscsiCreateLocalizedMessage(taskSet,
                                               '%s.label' % ISCSI_PORT_BINDING_CONFIG_UPDATE,
                                               {'hba': hba.GetName()})
      taskList.addTask(tmpTaskMsg, taskSet)

   return

def CheckPortBindingConfig(hostServices,
                           configData,
                           parent,
                           vnicsByDevice,
                           compatibleVnics):
   hba = GetIscsiHbaFromProfile(configData, parent, False)
   if hba is None:
      return []

   currVnicList = [vnic for vnic, policyClass, policyArg in hba.boundVnicList]

   newVnicList = EliminateIncompatibleVnics(hba, hostServices, vnicsByDevice, compatibleVnics)

   tmpTaskData = CreateBindingConfigTaskFromConfigData(hba, currVnicList, newVnicList, hostServices.earlyBoot)

   PrintTaskData(tmpTaskData)

   return tmpTaskData

def GetIscsiBoundVnicProfileList(cls, config, parent):
   hba = GetIscsiHbaFromProfile(config, parent, True)
   vnicList = hba.boundVnicList

   iscsiBoundVnicProfileList = []

   for vnic, policyClass, policyArg in vnicList:
      iscsiBoundVnicPolicies = []
      if policyClass == 'BindVnicByDevice':
         iscsiBoundVnicPolicies.append(IscsiVnicSelectionPolicy(True,
            BindVnicByDevice([('vnicDevice', vnic)])))
      elif policyClass == 'BindCompatibleVnics':
         iscsiBoundVnicPolicies.append(IscsiVnicSelectionPolicy(True,
            BindCompatibleVnics([('all', policyArg[0]), ('portgroups', policyArg[1])])))
      elif policyClass == 'BindVnicByIpv4Subnet':
         iscsiBoundVnicPolicies.append(IscsiVnicSelectionPolicy(True,
            BindVnicByIpv4Subnet([('all', policyArg[0]), ('ipv4Address', policyArg[1]), ('ipv4Netmask', policyArg[2])])))
      elif policyClass == 'BindVnicByIpv6Subnet':
         iscsiBoundVnicPolicies.append(IscsiVnicSelectionPolicy(True,
            BindVnicByIpv6Subnet([('all', policyArg[0]), ('ipv6Address', policyArg[1]), ('ipv6Prefix', policyArg[2])])))
      else:
         assert()

      profile = cls(policies=iscsiBoundVnicPolicies)
      iscsiBoundVnicProfileList.append(profile)

   return iscsiBoundVnicProfileList

class IscsiPortBindingConfigProfile(GenericProfile):
   policies = [
      IscsiVnicSelectionPolicy
   ]

   complianceChecker = PortBindingConfigProfileChecker()

   singleton = False

   version = ISCSI_PROFILE_VERSION

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

      compatibleVnics = []
      vnicsByDevice = []
      for profInst in profileInstances:
         ret = ProfilesToHba([profInst.parentProfile], configData, parent, None)
         if ret == False:
            continue

         hba = GetIscsiHbaFromProfile(configData, parent, False)
         if hba == None or hba.enabled == False:
            continue

         GenerateVnicListFromProfileInstance(hostServices,
                                             configData,
                                             parent,
                                             profInst,
                                             vnicsByDevice,
                                             compatibleVnics)

      # Generate the tasks for non-existing/compliant (in the system)
      # port-binding records
      taskData = CheckPortBindingConfig(hostServices,
                                        configData,
                                        parent,
                                        vnicsByDevice,
                                        compatibleVnics)

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
      IscsiLog(3, 'VerifyProfileInt(forApply=%s) for %s:%s is returning %d' %\
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
         GeneratePortBindingConfigTaskList(hostServices, configData, profileInstances, parent, taskList)

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
      iscsiBoundVnicProfileList = GetIscsiBoundVnicProfileList(cls, config, parent)

      return iscsiBoundVnicProfileList
