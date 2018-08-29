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

from pluginApi import CATEGORY_STORAGE, COMPONENT_VSAN

from pyEngine import storageprofile


from .vsanConstants import *
from .vsanUtils import *
from .vsanPolicies import VSANAutoclaimStoragePolicy, \
   VSANClusterUUIDPolicy, \
   VSANStoragePolicy, \
   VSANFaultDomainPolicy, \
   VSANChecksumEnabledPolicy, \
   VSANServicePolicy

from .vsanNicAllProfiles import VSANNicAllProfilesVerify

import base64
import os
import sys

###
### Main VSAN Profile for VSAN-wide policies
###

#
class VSANProfileChecker(ProfileComplianceChecker):

   @classmethod
   def CheckProfileCompliance(self, profileInstances, \
                                         hostServices, profileData, parent):
      # Called implicitly
      log.debug('in main profile checker')
      assert len(profileInstances) == 1

      # Likewise all the policy checkers are called implicitly and
      # there is nothing more to check at the profile level cross-policies.

      return (True, [])


#
# Main class
#
# !!! Only compliance is implicitly invoked on the policies, all other methods
# must explicitly handle the policies.
#
class VSANProfile(GenericProfile):

   # There is only one instance of VSAN
   singleton = True

   version = VSAN_PROFILE_VERSION

   # Neatly fall under storage subtree
   parentProfiles = [ storageprofile.StorageProfile ]
   category = CATEGORY_STORAGE
   component = COMPONENT_VSAN

   policies = [
                VSANAutoclaimStoragePolicy,
                VSANClusterUUIDPolicy,
                VSANStoragePolicy,
                VSANFaultDomainPolicy,
                VSANChecksumEnabledPolicy,
                VSANServicePolicy,
              ]

   complianceChecker = VSANProfileChecker()

   @classmethod
   def GatherData(cls, hostServices):
      log.debug('in main gather data')

      # It's straightforward to gather all the state here rather than
      # implement policy methods and delegate.

      result = {'enabled': VSAN_DEFAULT_ENABLED,
                'stretchedEnabled': VSAN_DEFAULT_STRETCHED_ENABLED,
                'clusterUUID': VSAN_DEFAULT_UUID,
                'autoclaimStorage': VSAN_DEFAULT_AUTOCLAIMSTORAGE,
                'datastoreName': VSAN_DEFAULT_DATASTORENAME,
                'cluster': VSAN_DEFAULT_CLUSTERPOLICY,
                'vdisk': VSAN_DEFAULT_VDISKPOLICY,
                'vmnamespace': VSAN_DEFAULT_VMNAMESPACE,
                'vmswap': VSAN_DEFAULT_VMSWAP,
                'vmem': VSAN_DEFAULT_VMEM,
                'faultDomain': VSAN_DEFAULT_FAULTDOMAIN,
                'isWitness' : VSAN_DEFAULT_IS_WITNESS,
                'preferredFD' : VSAN_DEFAULT_PREFERREDFD,
                'unicastAgent' : VSAN_DEFAULT_UNICAST_AGENT,
                'vsanvpdCastore' : '',
               }

      # First, let's see if the service is enabled
      status, output = hostServices.ExecuteEsxcli('vsan', 'cluster', 'get')
      if status != 0:
         # XXX PR 1002911
         # When the service is not enabled, a failure is returned, so we
         # cannot distinguish between disabled and genuine failure.
         # Assume disabled.
         result['enabled'] = False
      else:
         result['enabled'] = True
         result['clusterUUID'] = output['Sub-Cluster UUID']

      # Get autoclaim mode
      output = VSANUtilEsxcli(hostServices, 'storage', 'automode', 'get', \
                                                   VSAN_GETAUTOCLAIM_FAIL_KEY)
      result['autoclaimStorage'] = output['Enabled']

      # Get datastoreName
      output = VSANUtilEsxcli(hostServices, 'datastore', 'name', 'get', \
                                                 VSAN_GETDATASTORENAME_FAIL_KEY)
      result['datastoreName'] = output['Name']

      # Gather the storage policies
      output = VSANUtilEsxcli(hostServices, 'policy', 'getdefault', '', \
                                                   VSAN_GETDEFAULT_FAIL_KEY)
      for option in output:
         polClass = option['Policy Class']
         polValue = option['Policy Value']
         if polClass not in result:
            log.error('"vsan policy getdefault" returned %s' % polClass)
            raise CreateLocalizedException(None, VSAN_GETDEFAULT_FAIL_KEY)
         else:
            result[polClass] = polValue

      # If vSAN is disabled, skip fetching fault domain as it may print
      # error message "Operation not allowed because the VMKernel is shutting
      # down" on console.
      if result['enabled']:
         # Get vsan host fault domain
         output = VSANUtilEsxcli(hostServices, 'faultdomain', 'get', '', \
                                 VSAN_GETFAULTDOMAIN_FAIL_KEY)
         result['faultDomain'] = output['faultDomainName']

      stretchedInfo = VSANUtilGetStretchedInfo(result['enabled'])
      for k, v in list(stretchedInfo.items()):
         result[k] = v

      # There is a corner case: the unicast agent is set to a wrong ip. In that
      # case, the above VSANUtilGetStretchedInfo function can't retrieve the
      # witness information. But the host is able to get a unicast agent.
      # The unicast agent must be filled so that following actions like
      # compliance check can work as expected.
      if result['enabled']:
         status, output = hostServices.ExecuteEsxcli('vsan', 'cluster',
                                                     'unicastagent', 'list')
         if (status == 0) and (len(output) > 0):
            for agent in output:
               if agent['IsWitness'] == 1:
                  result['unicastAgent'] = agent['IP Address']
                  break
         else:
            # The unicastagent cmd can't be invoked in witness host.
            if stretchedInfo['stretchedEnabled'] \
               and not stretchedInfo['isWitness'] and status != 0:
               log.error('Failed to list unicast agent: %s' % output)
               raise CreateLocalizedException(None,
                                              VSAN_GET_UNICASTAGENT_FAIL_KEY)

      if os.path.exists(VSAN_VPD_CASTORE):
         with open(VSAN_VPD_CASTORE, 'rb') as f:
            s = f.read()
         encodedData = base64.b64encode(s)
         # XXX Python 3 b64encode returns bytes, converting it to str.
         if sys.version_info[0] < 3:
            result['vsanvpdCastore'] = encodedData
         else:
            result['vsanvpdCastore'] = encodedData.decode()
      return result

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      log.debug('in main generate profile')

      thePolicies = [ policy.CreatePolicy(profileData) \
                         for policy in cls.policies ]

      theProfile = cls(policies=thePolicies)
      return theProfile

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                             profileData, parent):
      log.debug('in main generate tasklist')
      assert len(profileInstances) == 1
      profile = profileInstances[0]

      theResult = TASK_LIST_RES_OK

      # Generate the task list for each policy
      for policy in profile.policies:
         result = policy.GenerateTaskList(policy, taskList, profileData, parent)
         theResult = VSANUtilComputeTaskListRes(theResult, result)

      # Nothing more to generate at the profile level

      return theResult

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, profileData):
      log.debug('in main remediate with %s' % taskList)

      # It's straightforward to process all the tasks here rather than
      # implement policy methods and delegate.
      # Sort the VSAN OPs, to make sure tasks are going to be executed
      # in the sequence as we expect.
      taskDict = {op: arg for op, arg in taskList}
      taskOps = sorted(taskDict.keys())
      for taskOp in taskOps:
         taskArg = taskDict[taskOp]
         if taskOp == VSAN_AUTOCLAIM_TASK:
            # taskArg should be a single value containing true or false
            log.debug('trying to set autoclaim %s' % taskArg)
            output = VSANUtilEsxcli(hostServices, 'storage', 'automode', \
                                                'set --enabled=%s' % taskArg, \
                                                VSAN_SETAUTOCLAIM_FAIL_KEY)
         elif taskOp == VSAN_DATASTORENAME_TASK:
            # taskArg should be a string containing the datastore name
            log.debug('trying to set datastore name %s' % taskArg)
            output = VSANUtilEsxcli(hostServices, 'datastore', 'name', \
                                             'set --newname=\'%s\'' % taskArg, \
                                             VSAN_SETDATASTORENAME_FAIL_KEY)
         elif taskOp == VSAN_STORAGEPOLICY_TASK:
            # taskArg should be a tuple containing (class, policy)
            log.debug('trying to set storage policy %s to %s' % taskArg)
            output = VSANUtilEsxcli(hostServices, 'policy', 'setdefault', \
                                    '-c %s -p \'%s\'' % taskArg, \
                                    VSAN_STORAGEPOLICY_FAIL_KEY, \
                                    {"Class": taskArg[0], "Policy": taskArg[1]})
         elif taskOp == VSAN_CLUSTER_JOIN_TASK:
            # taskArg should be a string containing the cluster UUID
            log.debug('trying to join %s' % taskArg)
            # XXX PR 1006049
            # Invoking the esxcli command from here does not perform all needed
            # tasks.

            cliArg = '-u %s' % taskArg['clusterUUID']
            if taskArg['stretchedEnabled'] and taskArg['isWitness']:
               cliArg = '%s -t -p %s' % (cliArg, taskArg['preferredFD'])

            output = VSANUtilEsxcli(hostServices, 'cluster', 'join',
                                    cliArg, VSAN_JOIN_FAIL_KEY, taskArg)

         elif taskOp == VSAN_CLUSTER_LEAVE_TASK:
            log.debug('trying to leave %s' % taskArg)
            output = VSANUtilEsxcli(hostServices, 'cluster', 'leave', '', \
                                                            VSAN_LEAVE_FAIL_KEY)
         elif taskOp == VSAN_FAULTDOMAIN_TASK:
            log.debug('trying to set fault domain to %s' % taskArg)
            output = VSANUtilEsxcli(hostServices, 'faultdomain', 'set', \
                                    '--fdname \'%s\'' % taskArg, \
                                    VSAN_SETFAULTDOMAIN_FAIL_KEY)
         elif taskOp == VSAN_ADD_UNICAST_AGENT_TASK:
            # Since we don't support multiple unicast agents now, we must
            # remove any existing unicast agent
            actualUnicastAgent = profileData['unicastAgent']
            if actualUnicastAgent != VSAN_DEFAULT_UNICAST_AGENT:
               VSANUtilEsxcli(hostServices, 'cluster', 'unicastagent',
                              'remove -a %s' % actualUnicastAgent,
                              VSAN_REMOVE_UNICASTAGENT_FAIL_KEY)

            VSANUtilEsxcli(hostServices, 'cluster', 'unicastagent',
                           'add -a %s' % taskArg,
                           VSAN_ADD_UNICASTAGENT_FAIL_KEY)
         elif taskOp == VSAN_SET_PREFERREDFD_TASK:
            log.info("Set preferred fault domain to: %s" % taskArg)
            VSANUtilRemoteEsxcli(hostServices, 'cluster',
                                 'preferredfaultdomain',
                                 'set -n %s' % taskArg,
                                 VSAN_SET_PREFERREDFD_FAIL_KEY)
         elif taskOp == VSAN_VPD_CASTORE_TASK:
            log.debug("Try to update VSAN VPD CA store.")
            s = base64.b64decode(taskArg)
            if isinstance(s, bytes):
               if sys.version_info[0] < 3:
                  s = s.encode()
               else:
                  s = s.decode()
            with open(VSAN_VPD_CASTORE, 'w+') as f:
               f.write(s)
         else:
            log.error('unknown op %s' % taskOp)
            raise CreateLocalizedException(None, VSAN_UNKNOWNTASK_FAIL_KEY,
                                           {"TaskOp": taskOp})

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData, \
                                                            validationErrors):
      log.debug('in main verify profile')

      theResult = True

      # Check each policy
      for policy in profileInstance.policies:
         good = policy.VerifyPolicy(policy, profileData, validationErrors)
         if not good:
            theResult = False

      # VSAN enables the firewall passIGMP rule, however that rule is not
      # handled by the firewall profile so it can remain implicit and a side
      # effect of joining a cluster.
      #
      # There is nothing more to verify cross-policies but there is something
      # to verify on behalf of the NIC subprofile.
      #
      # !!! VerifyProfile is called for one profile at a time, not for all
      # profiles at once, contrary to GenerateTaskList, so in order to verify
      # something across all profiles, it has to be done from the parent
      # profile.

      # !!! Theoretically we should filter subprofiles per subprofile type,
      # but since we only have one, we just hardcode it.

      # Only do subprofile verification when subprofile is not empty.
      # Because we are using answer file for fault domain, a profile with
      # no nic subprofile will be passed down to this verify method.
      subprofiles = profileInstance.subprofiles
      if subprofiles != None and len(subprofiles) > 0:
         good = VSANNicAllProfilesVerify(profileInstance, subprofiles, \
                                         hostServices, profileData, \
                                         validationErrors)
      if not good:
         theResult = False

      return theResult
