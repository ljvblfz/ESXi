#!/usr/bin/python
# **********************************************************
# Copyright 2013-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import GenericProfile,  \
                      ProfileComplianceChecker, \
                      CreateLocalizedMessage, CreateLocalizedException, log, \
                      TASK_LIST_REQ_REBOOT, TASK_LIST_REQ_MAINT_MODE, \
                      TASK_LIST_RES_OK

from pluginApi.extensions import NetworkProfile, WillDVSReApply


from .vsanConstants import *
from .vsanUtils import *
from .vsanProfiles import VSANProfile
from .vsanNicPolicies import VSANNicPolicy



###
### VSAN Nic Profile for vmknic-specific policies
###

# Ancillary routine to build param attributes for the "esxcli vsan network ipv4
# add" command.
def VSANNicProfileBuildParams(nicName, nics):
   for nic in nics:
      policyOpt = nic.VSANNicPolicy.policyOption
      if policyOpt.VmkNicName == nicName:
         return policyOpt.BuildParams(policyOpt)
   return ''

# Ancillary routine to check compliance and generate remediation task list
def VSANNicProfileComplianceAndTask(profileInstances, profileData, taskList):
   log.debug('in nic profile complianceandtask')

   complianceErrors = []
   taskResult = TASK_LIST_RES_OK

   # Individual desired nics will be implicitly checked by the policy
   # compliance checker. At the profile level, we check that the set of
   # desired nics matches the set of actual nics.
   #
   # !!! It is assumed that the actual config data is valid (that should
   # have been ensured by GatherData and the system) and that the profile
   # is valid (that should be ensured by the engine ???). Validity here
   # means no duplicates and VSAN nic set being a subset of system nic set
   # so we don't have to explicitly check the networking side for vsan tagging,
   # it will be done automatically by the networking profile.

   # Construct the needed sets of nics
   desiredNics = set([desiredNic.VSANNicPolicy.policyOption.VmkNicName \
                                            for desiredNic in profileInstances])
   actualNics = set([actualNic['VmkNicName'] for actualNic in profileData])
   log.debug('desiredNics is %s, actualNics is %s' % (desiredNics, actualNics))

   for nic in actualNics - desiredNics:
      log.debug('extra actual nic %s' % nic)
      if taskList:
         msg = CreateLocalizedMessage(None, VSAN_NIC_EXTRA_TASK_KEY, \
                                                            {'VmkNicName': nic})
         taskList.addTask(msg, (VSAN_NIC_EXTRA_TASK, nic))
      else:
         msg = CreateLocalizedMessage(None, VSAN_NIC_EXTRA_COMPLIANCE_KEY, \
                                                            {'VmkNicName': nic})
         complianceErrors.append(msg)

   for nic in desiredNics - actualNics:
      log.debug('missing actual nic %s' % nic)
      if taskList:
         msg = CreateLocalizedMessage(None, VSAN_NIC_MISSING_TASK_KEY, \
                                                            {'VmkNicName': nic})
         params = VSANNicProfileBuildParams(nic, profileInstances)
         taskList.addTask(msg, (VSAN_NIC_MISSING_TASK, (nic, params)))
      else:
         msg = CreateLocalizedMessage(None, VSAN_NIC_MISSING_COMPLIANCE_KEY, \
                                                            {'VmkNicName': nic})
         complianceErrors.append(msg)

   if taskList:
      return taskResult
   else:
      return complianceErrors

#
class VSANNicProfileChecker(ProfileComplianceChecker):

   @classmethod
   def CheckProfileCompliance(self, profileInstances, \
                                         hostServices, profileData, parent):
      # Called implicitly
      log.debug('in nic profile checker')

      # Likewise all the policy checkers are called implicitly but we still
      # have something to check at the profile level.
      complianceErrors = \
            VSANNicProfileComplianceAndTask(profileInstances, profileData, None)

      return (len(complianceErrors) == 0, complianceErrors)


#
# Main class
#
# !!! Only compliance is implicitly invoked on the policies, all other methods
# must explicitly handle the policies.
#
class VSANNicProfile(GenericProfile):

   # There can be several NICs
   singleton = False

   version = VSAN_PROFILE_VERSION

   # XXX Cannot hang off legacy networking, so hang off main VSAN profile
   parentProfiles = [ VSANProfile ]

   # legacy networking must be dealt with before vsan networking
   dependencies = [ NetworkProfile ]

   policies = [ VSANNicPolicy ]

   complianceChecker = VSANNicProfileChecker()

   @classmethod
   def _CreateTaggingTask(cls, nicList, nsanNicProf, taskList):
      for nic in nicList:
         msg = CreateLocalizedMessage(None, VSAN_NIC_MISSING_TASK_KEY,
                                      {'VmkNicName': nic})
         params = VSANNicProfileBuildParams(nic, nsanNicProf)
         taskList.addTask(msg, (VSAN_NIC_MISSING_TASK, (nic, params)))

   @classmethod
   def GatherData(cls, hostServices):
      log.debug('in nic gather data')

      # It's straightforward to gather all the state here rather than
      # implement policy methods and delegate.

      # Get a list of all the nics configured for VSAN
      nics = VSANUtilEsxcli(hostServices, 'network', 'list', '', \
                                                      VSAN_NETWORKLIST_FAIL_KEY)

      # Sanitize the key fields to have no space so that they can be used
      # directly as attributes for the class.
      vsanNics = []
      vsanNicsList = set()
      for nic in nics:
         vsanNic = dict([(key.replace(' ', ''),val) \
                           for key,val in list(nic.items())])
         log.debug('found actual nic %s' % vsanNic['VmkNicName'])
         vsanNics.append(vsanNic)
         vsanNicsList.add(vsanNic['VmkNicName'])

      # XXX PR 1002094
      # vsan nic info may not be in sync with system nic info.
      # Enforce consistency here. Basically we throw our hands up and user
      # has to remediate manually if there is inconsistency.

      # Get a list of all the nics configured for system
      sysNics = VSANUtilEsxcliGeneric(hostServices, 'network', 'ip', \
                              'interface', 'list', VSAN_SYSNETWORKLIST_FAIL_KEY)
      sysNicsList = set([sysNic['Name'] for sysNic in sysNics])
      log.debug('vsanNics is %s, sysNics is %s' % (vsanNicsList, sysNicsList))
      spuriousNicsList = vsanNicsList - sysNicsList
      if len(spuriousNicsList) > 0:
         log.error('Some vsan nic is not a sys nic: %s' % spuriousNicsList)
         raise CreateLocalizedException(vsanNic, \
                                       VSAN_INCONSISTENTNETWORKLIST_FAIL_KEY,
                                       {'VmkNicName': vsanNic['VmkNicName']})

      # XXX Check also vsan tagging

      # XXX should we check ip protocol on system nic is compatible with the
      # XXX one specified on vsan nic too ?

      return vsanNics

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      log.debug('in nic generate profile')

      profileList = []

      nics = profileData
      for nic in nics:
         thePolicies = [ policy.CreatePolicy(nic) for policy in cls.policies ]
         theProfile = cls(policies=thePolicies)
         profileList.append(theProfile)

      return profileList

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, \
                                          profileData, parent):
      log.debug('in nic generate tasklist')

      theResult = TASK_LIST_RES_OK

      # Generate task lists for each policy for all profiles
      for profile in profileInstances:
         for policy in profile.policies:
            result = policy.GenerateTaskList(policy,taskList,profileData,parent)
            theResult = VSANUtilComputeTaskListRes(theResult, result)

      # Generate task lists at the profile level
      result = \
         VSANNicProfileComplianceAndTask(profileInstances,
                                         profileData,
                                         taskList)
      theResult = VSANUtilComputeTaskListRes(theResult, result)

      return theResult

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, profileData):
      log.debug('in nic remediate with %s' % taskList)

      if WillDVSReApply(hostServices):
         log.info('DVS reapply is pending. Ignore remediate vsan nic config.')
         return

      # It's straightforward to process all the tasks here rather than
      # implement policy methods and delegate.

      for taskOp, taskArg in taskList:
         if taskOp == VSAN_NIC_TASK:
            # taskArg should be a tuple containing (nic, param, value)
            log.debug('trying to set nic %s parameter %s to %s' % taskArg)
            # XXX IPv4 only, enforced on valid profile
            output = VSANUtilEsxcli(hostServices, 'network', 'ipv4', \
                  'set -i %s --%s=%s' % taskArg, \
                  VSAN_NIC_FAIL_KEY, \
                  {"Nic": taskArg[0], "Param": taskArg[1], "Value": taskArg[2]})
         elif taskOp == VSAN_NIC_MISSING_TASK:
            # taskArg should be a tuple containing (nic, params string)
            log.debug('trying to add nic %s with %s' % taskArg)
            # XXX IPv4 only, enforced on valid profile

            # XXX Temporarily ignore add vsan nic exception to unblock stateless
            # testing, PR#1600728
            try:
               output = VSANUtilRemoteEsxcli(hostServices, 'network', 'ipv4', \
                     'add -i %s %s' % taskArg, \
                     VSAN_NIC_MISSING_FAIL_KEY, \
                     {"Nic": taskArg[0], "Params": taskArg[1]})
            except CreateLocalizedException as ex:
               log.error('Temporarily ignore add vsan nic exception: %s' % ex)
         elif taskOp == VSAN_NIC_EXTRA_TASK:
            # taskArg should be a single value containing nic
            log.debug('trying to remove nic %s' % taskArg)
            # XXX IPv4 only, enforced on valid profile
            output = VSANUtilEsxcli(hostServices, 'network', 'ipv4', \
                  'remove -i %s' % taskArg, \
                  VSAN_NIC_EXTRA_FAIL_KEY, \
                  {"Nic": taskArg})
         else:
            log.error('unknown op %s' % taskOp)
            raise CreateLocalizedException(None, \
                                 VSAN_UNKNOWNTASK_FAIL_KEY, {"TaskOp": taskOp})

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData, \
                                                            validationErrors):
      log.debug('in nic verify profile')

      theResult = True

      # Check each policy
      for policy in profileInstance.policies:
         good = policy.VerifyPolicy(policy, profileData, validationErrors)
         if not good:
            theResult = False

      # No cross-policy check to make

      # Across nics check is made from the parent level as we do not have
      # access to all the profiles here.

      return theResult
