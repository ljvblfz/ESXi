#!/usr/bin/python
# **********************************************************
# Copyright 2013-2016 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from vmware import runcommand

from pluginApi import GenericProfile, Policy, FixedPolicyOption, \
                      ParameterMetadata, log, \
                      PolicyOptComplianceChecker, ProfileComplianceChecker, \
                      TASK_LIST_REQ_MAINT_MODE, TASK_LIST_REQ_REBOOT, \
                      TASK_LIST_RES_OK

from pluginApi import CATEGORY_STORAGE, COMPONENT_CORE_STORAGE

from pyEngine.storageprofile import StorageProfile

from pyEngine.nodeputil import RangeValidator

import re
import sys
from psa.common import *

#
# hostd storage refresh command
# The command fails without "-U dcui". The error was something to the effect of
# not able to get the current user.
#
HOSTD_STORAGE_REFRESH_CMD = '/bin/vim-cmd -U dcui hostsvc/storage/refresh'

#
# Declare VVOL specific keys needed for task lists and compliance checking
#
VVOL_BASE = 'com.vmware.profile.plugins.vvol'
VVOL_PROFILE_BASE = 'com.vmware.vim.profile.Profile.vvol.vvolProfile'
VVOL_OP_ADD = 'VvolAdd'
VVOL_OP_DEL = 'VvolDel'
VVOL_ADD_KEY = '%s.%s' % (VVOL_BASE, VVOL_OP_ADD)
VVOL_DEL_KEY = '%s.%s' % (VVOL_BASE, VVOL_OP_DEL)

VVOL_ADD_STORAGE_CONTAINER_KEY = '%s%s' % (VVOL_ADD_KEY, 'StorageContainer')
VVOL_DEL_STORAGE_CONTAINER_KEY = '%s%s' % (VVOL_DEL_KEY, 'StorageContainer')
VVOL_ADD_VASA_CONTEXT_KEY = '%s%s' % (VVOL_ADD_KEY, 'VasaContext')
VVOL_DEL_VASA_CONTEXT_KEY = '%s%s' % (VVOL_DEL_KEY, 'VasaContext')
VVOL_ADD_VASA_PROVIDER_KEY = '%s%s' % (VVOL_ADD_KEY, 'VasaProvider')
VVOL_DEL_VASA_PROVIDER_KEY = '%s%s' % (VVOL_DEL_KEY, 'VasaProvider')

VVOL_PROFILE_NOT_FOUND_KEY = '%s.%s' % (VVOL_BASE, 'VvolProfileNotFound')
VVOL_PROFILE_PARAM_MISMATCH_KEY = '%s.%s' % (VVOL_BASE, 'VvolProfileParamMismatch')
VVOL_PROFILE_POLICY_MISMATCH_KEY = '%s.%s' % (VVOL_BASE, 'VvolProfilePolicyMismatch')

VVOL_LCLI_INT_ARG = '--plugin-dir /usr/lib/vmware/esxcli/int storage internal'

#
# Global compliance checker for VVOL profiles
#
class VvolProfileComplianceChecker(ProfileComplianceChecker):
   """A compliance checker type for VVOL profiles
   """
   def __init__(self, profileClass, esxcliDictParam = None):
      self.profileClass = profileClass
      if esxcliDictParam is None:
         self.esxcliDictParam = None
      else:
         self.esxcliDictParam = esxcliDictParam

   def CheckProfileCompliance(self, profileInsts, hostServices, profileData,
                              parent):
      """Checks whether the VVOL configuration described by the profiles
         and their policies and policy option parameters exists and matches
         what is on the host.
      """
      msgKeyDict = {'ProfNotFound' : VVOL_PROFILE_NOT_FOUND_KEY,
                    'ParamMismatch' : VVOL_PROFILE_PARAM_MISMATCH_KEY,
                    'PolicyMismatch' : VVOL_PROFILE_POLICY_MISMATCH_KEY,
                    'KeyBase' : VVOL_PROFILE_BASE}
      return CheckMyCompliance(self.profileClass, profileInsts, hostServices,
                               profileData, parent, msgKeyDict, self.esxcliDictParam)


#
# Policy options and compliance checkers (one checker per policy option)
#
# Helper function for Compliance checking (validates vasaprovider against host)
#
# Note: this function is not currently used but could be useful in future.
#       For example, if the decision is taken to associate storage container
#       profiles with VASA provider profiles then this function could be used
#       to validate that the specified VASA provider is known to the host.
#
def ValidateVp(cls, hostServices, vpName):
   """Validate VASA Provider name against host.
   """
   cliNs, cliApp, cliCmd = 'storage', 'vvol vasaprovider', 'list'
   status, output = hostServices.ExecuteEsxcli(cliNs, cliApp, cliCmd)
   # Raise exception on failure to read host state (should always succeed)
   if status != 0:
      LogAndRaiseException(cls, PSA_ESXCLI_CMD_FAILED_KEY, output)
   status = 1
   for vp in output:
      if vp['VP Name'] == vpName:
         status = 0
         break
   if status != 0:
      return LogAndReturnError(policyOpt, PSA_PARAM_NOT_FOUND_KEY,
                               {'Param': vpName, 'By': 'esxcli'})
   else:
      return (True, [])

#
# Policy option for the Storage Container policy
#
class VvolScNameAndUuidPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for the Vvol Storage Container policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the Vvol Storage Container by the policy
         option is valid and matches what's on the host
      """
      #XXX TBD: validate against host state

      return (True, [])

class ScNameAndUuidPolicyOption(FixedPolicyOption):
   """Policy Option type containing the Storage Container for an VVOL device.
   """
   paramMeta = [
      ParameterMetadata('scArray', 'string', False),
      ParameterMetadata('scName', 'string', False),
      ParameterMetadata('scUuid', 'string', False)]

   complianceChecker = VvolScNameAndUuidPolicyOptComplianceChecker

   def GetComparisonKey(self):
      return 'scUuid'

   # esxcli options needed to add or delete this policy option to/from the host
   def GetEsxcliDict(self, notUsed):
      assert notUsed is None, \
             '%s: notUsed param %s expected None' % (str(self), str(notUsed))
      addOptStr = '--container-name="%s" --container-id="%s"' % \
                  (self.scName, self.scUuid)
      if self.scArray is not None and self.scArray != '':
         addOptStr += ' --array="%s"' % self.scArray
      # if self.defaultPolicy is not None and self.defaultPolicy != '':
      #    addOptStr += ' --defaultPolicy="%s"' % self.defaultPolicy
      delOptStr = '--container-id="%s"' % self.scUuid

      addMsgDict = {'Storage Container Name': self.scName, 'UUID': self.scUuid,
                    'Array': self.scArray if self.scArray is not None else ""}
      delMsgDict = {'Storage Container Name': self.scName}
      messageDict = MakeMessageDict(VVOL_ADD_STORAGE_CONTAINER_KEY,
                                    VVOL_DEL_STORAGE_CONTAINER_KEY,
                                    addMsgDict, delMsgDict)

      #
      # As part of CS 4171762, psa/common.py was changed to use
      # ExecuteLocalEsxcli() instead of ExecuteEsxcli(). The former forks the
      # localcli command while the latter uses a python library (cliPy). The
      # latter also # had the advantage of handling internal commands which the
      # former # doesn't. So, we now have to explicitly pass in the plugin-dir
      # where to # find the internal commands.
      # XXX: CS 4171762 was done to handle 32bit libraries in 64bit binaries.
      # If that problem gets fixed, then we may have to consider reverting this
      # and going back to using cliPy.
      #
      return MakeEsxcliDict(VVOL_LCLI_INT_ARG, 'vvol storagecontainer',
                            'add', 'remove',
                            addOptStr, delOptStr, messageDict)

   # Optionally pre-process input dictionaries from GenerateMyProfileFromConfig
   def __init__(self, inputParam):
      if isinstance(inputParam, dict):
         paramList = [ ('scArray', inputParam['Array']),
                       ('scName', inputParam['StorageContainer Name']),
                       ('scUuid', inputParam['UUID']) ]
      elif isinstance(inputParam, list):
         paramList = inputParam
      else:
         assert False,                                                     \
                '%s: __init__ inputParam must be a dictionary or a list' % \
                str(self)

      FixedPolicyOption.__init__(self, paramList)

#
# Policy option for the VASA Provider policy
#
class VvolVpNameAndUrlPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for the Vvol VASA Provider policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the Vvol VASA Provider described by the policy
         option is valid and matches what's on the host
      """
      #XXX TBD: validate against host state

      return (True, [])

class VpNameAndUrlPolicyOption(FixedPolicyOption):
   """Policy Option type containing the Vvol VASA Provider for a VVOL device.
   """
   paramMeta = [
      ParameterMetadata('vpName', 'string', False),
      ParameterMetadata('vpUrl', 'string', False)]

   complianceChecker = VvolVpNameAndUrlPolicyOptComplianceChecker

   def GetComparisonKey(self):
      return 'vpName'

   # esxcli options needed to add or delete this policy option to/from the host
   def GetEsxcliDict(self, typePolicyOpt):
      assert typePolicyOpt is not None, \
             '%s: typePolicyOpt param is None expected not None' % str(self)

      addOptStr = '--vp-name="%s" --vp-url="%s"' % (self.vpName, self.vpUrl)
      delOptStr = '--vp-name="%s"' % self.vpName

      addMsgDict = {'VP Name': self.vpName, 'URL': self.vpUrl}
      delMsgDict = {'VP Name': self.vpName}
      messageDict = MakeMessageDict(VVOL_ADD_VASA_PROVIDER_KEY,
                                    VVOL_DEL_VASA_PROVIDER_KEY,
                                    addMsgDict, delMsgDict)

      #
      # If a user is trying to remove all storage containers and VPs on a host
      # (say by applying an empty VVol hostprofile - PR 1568142), the commands
      # that eventually get run has the VP removal command before the storage
      # containers removal.  In some of the QE tests, we saw this causing
      # problems during container removal as removing the last VP results in APD
      # for containers with bound VVols.
      # To get over this, we don't do an explicit VP removal as vvold will
      # automatically remove the VP when the last container from the VP is
      # removed.
      #
      #
      # As part of CS 4171762, psa/common.py was changed to use
      # ExecuteLocalEsxcli() instead of ExecuteEsxcli(). The former forks the
      # localcli command while the latter uses a python library (cliPy). The
      # latter also # had the advantage of handling internal commands which the
      # former # doesn't. So, we now have to explicitly pass in the plugin-dir
      # where to # find the internal commands.
      # XXX: CS 4171762 was done to handle 32bit libraries in 64bit binaries.
      # If that problem gets fixed, then we may have to consider reverting this
      # and going back to using cliPy.
      #
      return MakeEsxcliDict(VVOL_LCLI_INT_ARG, 'vvol vasaprovider',
                            'add', None,
                            addOptStr, None, messageDict,
                            typePolicyOpt, None)

   # Optionally pre-process input dictionaries from GenerateMyProfileFromConfig
   def __init__(self, inputParam):
      if isinstance(inputParam, dict):
         paramList = [ ('vpName', inputParam['VP Name']),
                       ('vpUrl', inputParam['URL']) ]
      elif isinstance(inputParam, list):
         paramList = inputParam
      else:
         assert False,                                                     \
                '%s: __init__ inputParam must be a dictionary or a list' % \
                str(self)

      FixedPolicyOption.__init__(self, paramList)

#
# Policy option for the Array ID policy
#
class VvolArrayIdPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for VVol VASA Provider Array Id policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks nothing at present
      """
      #Firstly, validate the policy option
      status, output = policyOpt.PolicyOptValidator(hostServices)
      if status != True:
         return (status, output)

      #XXX TBD: validate vendor/model against host state?

      return (True, [])

class ArrayIdPolicyOption(FixedPolicyOption):
   """Policy Option type specifying a VVol VASA Provider Array Id policy
      option.
   """
   paramMeta = [
      ParameterMetadata('arrayId', 'string', False),
      ParameterMetadata('isActive', 'string', False),
      ParameterMetadata('priority', 'string', False)]

   complianceChecker = VvolArrayIdPolicyOptComplianceChecker

   # Ensure that at least one parameter is specified; checked by
   # VerifyProfile() and CheckPolicyCompliance().
   def PolicyOptValidator(self, hostServices, notUsed = None):
      assert notUsed is None, \
             '%s: notUsed param %s expected None' % (str(self), str(notUsed))
      return (True, [])

   # esxcli options needed to add this policy option to the host
   def GetEsxcliOptionString(self, notUsed):
      assert notUsed is False, \
             '%s: notUsed param %s expected False' % (str(self), str(notUsed))

      arrayIds = self.arrayId.split('|')
      isActives = self.isActive.split('|')
      priorities = self.priority.split('|')

      assert len(arrayIds) == len(isActives) and                    \
             len(arrayIds) == len(priorities),                      \
             '%s: parameter arrays must match in length %s %s %s' % \
             (str(self), arrayIds, isActives, priorities)

      optStr = ''
      if (len(arrayIds) > 0):
         for i in range(1, len(arrayIds)):
            if (len(arrayIds[i]) > 0):
               optStr += ' --arrayid="%s"' % arrayIds[i]
               optStr += ' --isactive="%s"' % isActives[i].lower()
               optStr += ' --priority=%d' % int(priorities[i])
            else:
               assert len(arrayIds[i]) == len(isActives[i]) and              \
                      len(arrayIds[i]) == len(priorities[i]),                \
                      '%s: gaps in split param arrays must match %s %s %s' % \
                      (str(self), arrayIds[i], isActives[i], priorities[i])
      else:
         LogAndRaiseException(cls, PSA_INVALID_PARAM_KEY, self.arrayId)

      return optStr

#
# Policy option for the VASA Context policy
#
class VvolVasaContextPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for the Vvol VASA Provider policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the Vvol VASA Provider described by the policy
         option is valid and matches what's on the host
      """
      #XXX TBD: validate against host state

      return (True, [])

class VasaContextPolicyOption(FixedPolicyOption):
   """Policy Option type containing the Vvol VASA Provider for a VVOL device.
   """
   paramMeta = [
      ParameterMetadata('vcUuid', 'string', False)]

   complianceChecker = VvolVasaContextPolicyOptComplianceChecker

   def GetComparisonKey(self):
      return 'vcUuid'

   # esxcli options needed to add or delete this policy option to/from the host
   def GetEsxcliDict(self, notUsed):
      assert notUsed is None, \
             '%s: notUsed param %s expected None' % (str(self), str(notUsed))

      addOptStr = '--uuid="%s"' % self.vcUuid
      delOptStr = '--clear'

      addMsgDict = {'VASA context UUID': self.vcUuid}
      delMsgDict = None
      messageDict = MakeMessageDict(VVOL_ADD_VASA_CONTEXT_KEY,
                                    VVOL_DEL_VASA_CONTEXT_KEY,
                                    addMsgDict, delMsgDict)

      #
      # As part of CS 4171762, psa/common.py was changed to use
      # ExecuteLocalEsxcli() instead of ExecuteEsxcli(). The former forks the
      # localcli command while the latter uses a python library (cliPy). The
      # latter also # had the advantage of handling internal commands which the
      # former # doesn't. So, we now have to explicitly pass in the plugin-dir
      # where to # find the internal commands.
      # XXX: CS 4171762 was done to handle 32bit libraries in 64bit binaries.
      # If that problem gets fixed, then we may have to consider reverting this
      # and going back to using cliPy.
      #
      return MakeEsxcliDict(VVOL_LCLI_INT_ARG, 'vvol vasacontext',
                            'set', 'set',
                            addOptStr, delOptStr, messageDict)

   # Optionally pre-process input dictionaries from GenerateMyProfileFromConfig
   def __init__(self, inputParam):
      if isinstance(inputParam, dict):
         if 'UUID' not in inputParam:
            paramList = [ ('vcUuid', '') ]
         else:
            paramList = [ ('vcUuid', inputParam['UUID']) ]
      elif isinstance(inputParam, list):
         paramList = inputParam
      else:
         assert False,                                                     \
                '%s: __init__ inputParam must be a dictionary or string' % \
                str(self)

      FixedPolicyOption.__init__(self, paramList)

#
# Policies
#
class ScNameAndUuidPolicy(Policy):
   """Define the storage container name and Uuid
   """
   possibleOptions = [ ScNameAndUuidPolicyOption ]

class VpNameAndUrlPolicy(Policy):
   """Define the VASA provider name and URL
   """
   possibleOptions = [ VpNameAndUrlPolicyOption ]

class VpArrayIdPolicy(Policy):
   """Define the 1+ arrays associated with the VASA provider
   """
   possibleOptions = [ ArrayIdPolicyOption ]

   # Instantiate policy option based on esxcli output containing a non-empty
   # array of storage arrays associated with a VASA provider (presented as
   # the "Arrays" dictionary within the dictionary of esxcli output for the
   # "storage vvol vasaprovider list" command).
   #
   # In contrast to other secondary policies this one has only a single possible
   # policy option but a varying number of "records".  Thus we overload the
   # GetPolicyOption method to unroll the dictionary of array ID entries into
   # the parameter list which is a fixed set rather than a varying record/array.
   # Since Host Profiles framework (NOT common.py, rather all of Host Profiles)
   # lasks any concept of a varying length array stored in a policy or policy
   # option so we store the values in strings as concatenated csv lists.  This
   # is acceptable because the contents of this policy are not user-editable.
   @classmethod
   def GetPolicyOption(cls, esxcliRule, paramsOnly = False):
      arrayIdsString = "Sorted, do not edit |"
      isActivesString = "Sorted, do not edit |"
      prioritiesString = "Sorted, do not edit |"

      assert not paramsOnly, "%s: paramsOnly not allowed" % str(cls)
      assert isinstance(esxcliRule, dict) and           \
             isinstance(esxcliRule['Arrays'], list),    \
             '%s: esxcliRule must be a dictionary and ' \
             'esxcliRule["Arrays"] must be a list' % str(cls)

      # sort list whenever we extract from esxcli for simpler tasklist compares
      for array in sorted(esxcliRule['Arrays'], key=lambda k: k['ArrayId']):
         assert isinstance(array, dict), \
                'esxcliRule["Arrays"] must be a list of dictionaries' % str(cls)
         if array['ArrayId'].count('|') != 0:
            LogAndRaiseException(cls, PSA_INVALID_PARAM_KEY, array['ArrayId'])
         arrayIdsString += array['ArrayId'] + "|"
         isActivesString += str(array['Is Active']) + "|"
         prioritiesString += str(array['Priority']) + "|"

      params = [ ('arrayId', arrayIdsString),
                 ('isActive', isActivesString),
                 ('priority', prioritiesString) ]

      return ArrayIdPolicyOption(params)

class VasaContextPolicy(Policy):
   """Define the VASA provider name and URL
   """
   possibleOptions = [ VasaContextPolicyOption ]

#
# Leaf Profiles
#
class VvolStorageContainerConfigurationProfile(GenericProfile):
   """A leaf Host Profile that manages VVOL VASA provider configuration on the ESX host.
   """
   #
   # Define required class attributes
   #
   # XXX Use this if/when a Storage Container can have more than one array ID
   #policies = [ ScNameAndUuidPolicy, ScArrayIdPolicy ]
   # where ScArrayIdPolicy marshalls the embedded array as VpArrayIdPolicy does
   #
   policies = [ ScNameAndUuidPolicy ]

   complianceChecker = None

   singleton = False

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves a list of dictionaries, one per VVOL device on the host.
      """
      return GatherEsxcliData(cls, hostServices, 'storage',
                              'vvol storagecontainer', 'list')

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance per configured VVOL device on the host.
      """
      return GenerateMyProfileFromConfig(cls, hostServices, config,
                                         ScNameAndUuidPolicyOption)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
                        parent):
      """Generates a list of the data in the profileInstances.
      """
      #profileData = hostServices.GetProfileData(profileCls)
      return GenerateMyTaskList(cls, profileInstances, taskList, hostServices,
                                config, parent)

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Implementation of remediate config that takes the supplied task list
         and adds and/or removes the VVol datastores indicated in the task list.
      """
      RemediateMyConfig(cls, taskList, hostServices, config, True)

      if len(taskList) == 0:
         return

      #
      # If we ran some commands (ie len(taskList) != 0), refresh hostd
      # as we found that VC was not getting updated otherwise.
      #
      status, output = runcommand.runcommand(HOSTD_STORAGE_REFRESH_CMD)
      if status:
         # Python 2to3 compatibility Bug #1639716
         if sys.version_info[0] >= 3:
            output = str(output, "utf-8")
         log.warning('Failed to run hostd storage refresh: %s' % output)
      else:
         log.info('Successfully ran hostd storage refresh')

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
                                      profileData, validationErrors)

VvolStorageContainerConfigurationProfile.complianceChecker = \
   VvolProfileComplianceChecker(VvolStorageContainerConfigurationProfile)

class VvolVasaProviderConfigurationProfile(GenericProfile):
   """A leaf Host Profile that manages VVOL VASA provider configuration on the ESX host.
   """
   #
   # Define required class attributes
   #
   policies = [ VpNameAndUrlPolicy, VpArrayIdPolicy ]

   dependents = [ VvolStorageContainerConfigurationProfile ]

   complianceChecker = None

   singleton = False

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves a list of dictionaries, one per VVOL device on the host.
      """
      return GatherEsxcliData(cls, hostServices, 'storage',
                              'vvol vasaprovider', 'list')

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance per configured VVOL device on the host.
      """
      return GenerateMyProfileFromConfig(cls, hostServices, config,
                                         VpNameAndUrlPolicyOption,
                                         VpArrayIdPolicy)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
                        parent):
      """Generates a list of the data in the profileInstances.
      """
      return GenerateMyTaskList(cls, profileInstances, taskList, hostServices,
                                config, parent)

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Implementation of remediate config that takes the supplied task list
         and adds and/or removes the VVol datastores indicated in the task list.
      """
      RemediateMyConfig(cls, taskList, hostServices, config, True)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
                                      profileData, validationErrors)

VvolVasaProviderConfigurationProfile.complianceChecker = \
   VvolProfileComplianceChecker(VvolVasaProviderConfigurationProfile)

class VvolVasaContextConfigurationProfile(GenericProfile):
   """A leaf Host Profile that manages VVOL VASA provider configuration on the ESX host.
   """
   #
   # Define required class attributes
   #
   policies = [ VasaContextPolicy ]

   complianceChecker = None

   # XXX: this is per host so it could be a singleton but that will throw an
   # exception if we ever have multiple VASA contexts defined.  The esxcli code
   # doesn't enforce singleness.  Ilia, does the vmkctl code enforce singleness?
   singleton = False

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves a list with 0 or 1 dictionary entries (i.e., max 1 per host).
      """
      hostData =  GatherEsxcliData(cls, hostServices, 'storage',
                                   'vvol vasacontext', 'get')
      if isinstance(hostData, str) and len(hostData):
         return [ { 'UUID': hostData } ]
      else:
         return []

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance per host.
      """
      return GenerateMyProfileFromConfig(cls, hostServices, config,
                                         VasaContextPolicyOption)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
                        parent):
      """Generates a list of the data in the profileInstances.
      """
      return GenerateMyTaskList(cls, profileInstances, taskList, hostServices,
                                config, parent)

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Implementation of remediate config that takes the supplied task list
         and adds and/or removes the host VVol VASA configuration as indicated
         in the task list.
      """
      RemediateMyConfig(cls, taskList, hostServices, config, True)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
                                      profileData, validationErrors)

VvolVasaContextConfigurationProfile.complianceChecker = \
   VvolProfileComplianceChecker(VvolVasaContextConfigurationProfile)

#
# VVol parent profile
#
class VirtualVolumesProfile(GenericProfile):
   """A Host Profile that manages Virtual Volumes (VVOL) on the ESX host.
   """
   #
   # Define required class attributes
   #
   subprofiles = [
                   VvolStorageContainerConfigurationProfile,
                   VvolVasaProviderConfigurationProfile,
                   VvolVasaContextConfigurationProfile ]

   parentProfiles = [ StorageProfile ]

   singleton = True

   category = CATEGORY_STORAGE
   component = COMPONENT_CORE_STORAGE

