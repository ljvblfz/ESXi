#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

import time

from pluginApi import ParameterMetadata, \
                      CreateLocalizedMessage, \
                      CreateLocalizedException
from pluginApi import log, IsString
from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING, \
                      COMPONENT_RESOURCE_POOL_CONFIG, \
                      TASK_LIST_REQ_MAINT_MODE, \
                      RELEASE_VERSION_CURRENT
from pluginApi.extensions import SimpleConfigProfile

from vmware import runcommand

#
# Define the localization message catalog keys used by this profile
#
BASE_MSG_KEY = 'com.vmware.profile.Profile.RPConfig'
GETCPU_FAILURE_MSG_KEY = '%s.GetcpuFailure' % BASE_MSG_KEY
GETMEM_FAILURE_MSG_KEY = '%s.GetmemFailure' % BASE_MSG_KEY
SETCPU_FAILURE_MSG_KEY = '%s.SetcpuFailure' % BASE_MSG_KEY
SETMEM_FAILURE_MSG_KEY = '%s.SetmemFailure' % BASE_MSG_KEY
LISTGROUPS_FAILURE_MSG_KEY = '%s.ListGroupsFailure' % BASE_MSG_KEY
CREATEGROUP_FAILURE_MSG_KEY = '%s.CreateGroupFailure' % BASE_MSG_KEY
INVALID_MEM_MINIMUM_KEY = '%s.InvalidMemoryMinimum' % BASE_MSG_KEY
INVALID_MEM_MAXIMUM_KEY = '%s.InvalidMemoryMaximum' % BASE_MSG_KEY
INVALID_CPU_MINIMUM_KEY = '%s.InvalidCpuMinimum' % BASE_MSG_KEY
INVALID_CPU_MAXIMUM_KEY = '%s.InvalidCpuMaximum' % BASE_MSG_KEY
INVALID_PARAM_MSG_KEY = '%s.InvalidParamValue' % BASE_MSG_KEY
MISSING_PARENT_POOL_KEY = '%s.MissingParentPool' % BASE_MSG_KEY


def HandleEsxcliError(status, result, errKey, otherArgs=None, logOnly=False):
   """Helper function that checks the status of an ESXCLI command and raises
      an exception if an error occurs.
   """
   if status != 0:
      faultArgs = { 'error' : result }
      if otherArgs:
         faultArgs.update(otherArgs)
      fault = CreateLocalizedException(None, errKey, faultArgs)
      log.warning('Error in esxcli in Resource Pool Config Profile: %s' % \
                  str(fault))
      if not logOnly:
         raise fault

RP_COMMON_SETTINGS = {
                        'Maximum' : 'max',
                        'Minimum' : 'min',
                        'Minlimit' : 'minlimit',
                        'Shares' : 'shares'
                     }

RP_INT_SETTINGS = [ 'Minimum', 'cpuMinimum', 'memMinimum' ]

ESXCLI_UNLIMITED_VAL = -1

ESXCLI_SHARES_MAPPING = { -1 : 'Low',
                          -2 : 'Normal',
                          -3 : 'High' }

HP_SHARES_MAPPING = dict([ (valStr, valInt) for (valInt, valStr) in
                           ESXCLI_SHARES_MAPPING.items() ])

HOSTPROF_UNLIMITED_VAL = 'Unlimited'

class ResGroupSettingChecker:
   """A ParamChecker / Validator that checks whether the supplied values are
      really integers. This is needed because host profiles does not support
      negative integers but resource groups use "-1" as a value to indicate
      "unlimited". Rather than choosing some other arbitrary number, we're going
      to keep the resource settings as strings but make sure that the value is
      either "unlimited" or an integer >= 0.
   """
   @staticmethod
   def Validate(obj, argName, arg, errors):
      assert IsString(arg)
      validParam = True
      checkForInt = True

      if argName.endswith('Shares'):
         if arg in HP_SHARES_MAPPING:
            checkForInt = False
      elif arg == HOSTPROF_UNLIMITED_VAL:
         checkForInt = False

      if checkForInt:
         try:
            realArgVal = int(arg)
            # No negative values. Any negative values should be special values
            # that have word representations in the profile, i.e. Unlimited,
            # Low, Normal, High.
            if realArgVal < 0:
               validParam = False
         except:
            validParam = False

      if not validParam:
         # If it wasn't an integer, then this is an invalid parameter
         errArgs = { 'ParamName' : argName,
                     'ParamVal' : arg }
         err = CreateLocalizedMessage(None, INVALID_PARAM_MSG_KEY, errArgs)
         assert err is not None, \
                'Missing invalid param message key for RPConfigProfile'
         errors.append(err)

      return validParam


class ResourceGroup:
   """Class that defines a resource group and can be used to retrieve resource
      pool limits for that group.
   """
   def __init__(self, groupId, groupName, parent=None):
      self.groupId = groupId
      self.groupName = groupName
      self.parent = parent
      self.units = None

   def GetGroupPath(self):
      """Returns a path for this group
      """
      groupPath = self.groupName
      if self.parent:
         groupPath = '%s/%s' % (self.parent.GetGroupPath(), groupPath)
      return groupPath

   @staticmethod
   def _GetStandardizedValue(settingVals, setting):
      """Helper function that standardizes the units used for numeric values.
         In particular, we want to standardize memory values to use MB.
      """
      # Define a dictionary containing a unit label and multiplier to get to
      # the standardized unit desired.
      unitConversion = { 
                         'mb' : 1,
                         'kb' : 1.0/1024,
                         'pages' : 4.0/1024,
                         'mhz' : 1
                       }
      settingsToConvert = set(['Maximum', 'Minimum', 'Minlimit'])
      settingVal = settingVals[setting]
      units = settingVals['Units']
      if setting in settingsToConvert and units in unitConversion and \
            settingVal > 0:
         settingVal = int(settingVal * unitConversion[units])
      return settingVal

   @classmethod
   def _ProcessSchedSettings(cls, groupConfig, settingVals, hpConfigPrefix):
      """Processes the results of the getcpuconfig or getmemconfig esxcli sched
         commands.
      """
      for setting in RP_COMMON_SETTINGS.keys():
         settingVal = cls._GetStandardizedValue(settingVals, setting)
         # Translate the "unlimited" value
         if setting == 'Shares' and settingVal in ESXCLI_SHARES_MAPPING:
            settingVal = ESXCLI_SHARES_MAPPING[settingVal]
         elif settingVal == ESXCLI_UNLIMITED_VAL:
            settingVal = HOSTPROF_UNLIMITED_VAL
            assert setting not in RP_INT_SETTINGS
         elif setting not in RP_INT_SETTINGS:
            # Make sure that it's a string value
            settingVal = str(settingVal)
         hpConfigName = hpConfigPrefix + setting
         groupConfig[hpConfigName] = settingVal


   def GetConfigMap(self, hostServices):
      """Returns a config map object for this resource group.
      """
      groupPath = self.GetGroupPath()
      groupConfig = { 'groupPath' : groupPath }
      pathOption = '--group-path %s' % groupPath
      status, result = hostServices.ExecuteEsxcli('sched', 'group',
                          'getmemconfig', pathOption)
      if isinstance(result, list):
         assert len(result) == 1
         result = result[0]
      errorArgs = groupConfig
      HandleEsxcliError(status, result, GETMEM_FAILURE_MSG_KEY, errorArgs)
      self._ProcessSchedSettings(groupConfig, result, 'mem')

      status, result = hostServices.ExecuteEsxcli('sched', 'group',
                          'getcpuconfig', pathOption)
      if isinstance(result, list):
         assert len(result) == 1
         result = result[0]
      HandleEsxcliError(status, result, GETCPU_FAILURE_MSG_KEY, errorArgs)
      self._ProcessSchedSettings(groupConfig, result, 'cpu')

      return groupConfig


   @classmethod
   def CreatePool(cls, groupPath, resGroups, hostServices):
      """Helper method that determines if a pool exists for the settings in the
         supplied config map, and will attempt to create that pool if it
         does not exist. This method returns a boolean indicating whether the
         pool had to be created or not.
      """
      if groupPath in resGroups:
         # We found the resource pool/group, so no need to create it.
         log.info('Not creating resource group: ' + groupPath)
         return False

      # If we got this far, that means we didn't find the group already, so
      # let's try to create it.
      parentPath, _sep, groupName = groupPath.rpartition('/')
      addOpts = '--group-name %s --parent-path %s' % (groupName, parentPath)
      log.info('Creating new resource group: ' + groupPath)
      status, result = hostServices.ExecuteEsxcli('sched', 'group', 'add',
                                                  addOpts)
      errorArgs = { 'groupPath' : groupPath }
      HandleEsxcliError(status, result, CREATEGROUP_FAILURE_MSG_KEY, errorArgs,
                        False)
      return result


   @classmethod
   def SetConfig(cls, configMap, hostServices):
      """Method that sets the resource group settings for this group based on
         the values in the supplied configMaps.
      """
      groupPath = configMap['groupPath']
      pathOption = '%s=%s' % ('--group-path', groupPath)
      unitsOption = '--units %s'
      cpuOptions = [ pathOption, unitsOption % 'mhz']
      memOptions = [ pathOption, unitsOption % 'mb' ]

      # Get the current settings
      curGroupSettings = ResourceGroup(None, groupPath)
      curConfigMap = curGroupSettings.GetConfigMap(hostServices)
      cpuConfigChanged = False
      memConfigChanged = False

      for setting, value in configMap.items():
         if setting != 'groupPath':
            # Don't set the setting if it hasn't changed
            if value == curConfigMap[setting]:
               continue

            # Translate the special values if necessary
            if setting.endswith('Shares') and value in HP_SHARES_MAPPING:
               value = str(HP_SHARES_MAPPING[value])
            elif value == HOSTPROF_UNLIMITED_VAL:
               value = ESXCLI_UNLIMITED_VAL
            else:
               value = str(value)
            if setting[:3] == 'cpu':
               cpuConfigChanged = True
               settingName = setting[3:]
               cpuOption = '--%s=%s' % (RP_COMMON_SETTINGS[settingName], value)
               cpuOptions.append(cpuOption)
            elif setting[:3] == 'mem':
               memConfigChanged = True
               settingName = setting[3:]
               memOption = '--%s=%s' % (RP_COMMON_SETTINGS[settingName], value)
               memOptions.append(memOption)

      errorArgs = { 'groupPath' : groupPath }
      if cpuConfigChanged:
         status, result = hostServices.ExecuteEsxcli('sched', 'group',
                             'setcpuconfig', ' '.join(cpuOptions))
         HandleEsxcliError(status, result, SETCPU_FAILURE_MSG_KEY, errorArgs,
                           True)

      if memConfigChanged:
         status, result = hostServices.ExecuteEsxcli('sched', 'group',
                             'setmemconfig', ' '.join(memOptions))
         HandleEsxcliError(status, result, SETMEM_FAILURE_MSG_KEY, errorArgs,
                           True)

   @classmethod
   def Remove(cls, configMap, hostServices):
      """ Method to remove a resource group specified by the group path.
          NOTE: On error to remove, this method only logs the error, since
          currently it is being invoked as part of error cleanup
      """
      groupPath = configMap['groupPath']
      status, result = hostServices.ExecuteEsxcli('sched', 'group', 'delete',
                             '--group-path', groupPath)
      if status != 0:
         log.warning('Failed to remove resource group %s : %s' \
                     % (groupPath, str(result)))

class EsxcliResgrpParser:
   """Class that executes and processes the output of the esxcli sched group
      commands to get the list of resource pools and create necessary Resource
      Group objects.
   """
   MAX_LIST_RETRIES = 5

   def __init__(self, hostServices):
      self.resourceGroups = {}
      self.hostServices = hostServices

   def ProcessResourceGroups(self):
      """Method that will process the esxcli sched group list command and create
         ResourceGroup objects for them.
      """
      status = 1
      output = []
      for i in range(1, self.MAX_LIST_RETRIES+1):
         status, output = self.hostServices.ExecuteEsxcli(
                                   'sched', 'group', 'list')
         logOnly = (i != self.MAX_LIST_RETRIES)
         HandleEsxcliError(status, output, LISTGROUPS_FAILURE_MSG_KEY,
                           logOnly=logOnly)
         if status == 0:
            break
         time.sleep(i*i)

      for resGroup in output:
         try:
            groupPath = resGroup['Group']
         except:
            log.error('Failed to get resource group from resGroup: ' + str(resGroup))
         # Create a new group if the group name doesn't look like it's for a
         # dynamic cartel
         _groupPath, sep, groupSuffix = groupPath.rpartition('.')
         if sep and groupSuffix:
            try:
               # If the suffix is an integer then this isn't a group
               # that we really want to report (i.e. it's a cartel).
               groupCartel = int(groupSuffix)
               log.debug('Skipping cartel group %s' % groupPath)
               continue
            except:
               # If the suffix wasn't an integer, then it's a valid
               # resource group for this plug-in to report.
               pass

         parentPath, _sep, groupName = groupPath.rpartition('/')
         parentGroup = None
         if parentPath:
            parentGroup = self.resourceGroups.get(parentPath)

         newGroup = ResourceGroup(groupPath, groupName, parentGroup)
         self.resourceGroups[groupPath] = newGroup


class RPConfigProfile(SimpleConfigProfile):
   """A Host Profile that manages system resource pool settings on ESX hosts.
   """
   #
   # Define required class attributes
   #
   parameters = [ ParameterMetadata('groupPath', 'string', False),
                  ParameterMetadata('cpuMaximum', 'string', False,
                                    paramChecker=ResGroupSettingChecker),
                  ParameterMetadata('cpuMinimum', 'int', False),
                  ParameterMetadata('cpuMinlimit', 'string', False,
                                    paramChecker=ResGroupSettingChecker),
                  ParameterMetadata('cpuShares', 'string', False,
                                    paramChecker=ResGroupSettingChecker),
                  ParameterMetadata('memMaximum', 'string', False,
                                    paramChecker=ResGroupSettingChecker),
                  ParameterMetadata('memMinimum', 'int', False),
                  ParameterMetadata('memMinlimit', 'string', False,
                                    paramChecker=ResGroupSettingChecker),
                  ParameterMetadata('memShares', 'string', False,
                                    paramChecker=ResGroupSettingChecker) ]

   singleton = False
   ignoreExtraOnSystem = True
   ignoreExtraInProfile = True

   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_RESOURCE_POOL_CONFIG

   # Need to define some common parent for random system config stuff?
   #parentProfiles = [ ]
   idConfigKeys = [ 'groupPath' ]

   @staticmethod
   def IsGroupConfigurable(groupPath):
      """Helper method that determines if a resource group is configurable or
         not.
      """
      # Only the group in host/vim/vmvisor/plugins are really configurable.
      # The others either can't be set and/or can be dynamically modified
      # by the kernel. Until there is a programtic way that's reasonable
      # to access (i.e. not via vsish) to determine which groups are
      # configurable, just stick with a couple of hard-and-fast rules.
      return groupPath.startswith('host/vim/vmvisor/plugins')


   @classmethod
   def ExtractConfig(cls, hostServices):
      """Gets the resource groups on the ESX system
      """
      groupConfigMaps = []
      resGroupParser = EsxcliResgrpParser(hostServices)
      resGroupParser.ProcessResourceGroups()
      for group in resGroupParser.resourceGroups.values():
         if cls.IsGroupConfigurable(group.GetGroupPath()):
            configMap = group.GetConfigMap(hostServices)
            groupConfigMaps.append(configMap)

      return groupConfigMaps


   @classmethod
   def CompareConfig(cls, hostServices, profConfig, hostConfig, **kwargs):
      """Implementation of comparison method that special-cases the max memory
         limit to ensure that we don't fail compliance or remediate because
         the host has a higher memory limit than what is specified in the
         profile for the relevant resource group.
      """
      # We can leverage the existing comparison method, but first we need to
      # compensate for the use case where the host max memory is greater than
      # the profile max memory. We can do that by simply setting the profile
      # config to the host value.
      if profConfig['groupPath'] != hostConfig['groupPath']:
         return False

      profileVersion = kwargs['version']

      if profileVersion != RELEASE_VERSION_CURRENT:
         hostMemMax = hostConfig['memMaximum']
         profMemMax = profConfig['memMaximum']
         if hostMemMax == HOSTPROF_UNLIMITED_VAL or int(profMemMax) < int(hostMemMax):
            profConfig['memMaximum'] = hostMemMax

      return SimpleConfigProfile.CompareConfig(hostServices, profConfig,
                                               hostConfig, version=profileVersion)


   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      """Implementation of verify that ensures Min values are not set higher
         than Max or Minlimit values.
      """
      policy = profileInstance.policies[0]
      policyOpt = policy.policyOption
      verifyErrors = []
      try:
         if (policyOpt.memMaximum == '0' and
             not cls.IsGroupConfigurable(policyOpt.groupPath) and
             policyOpt.groupPath.startswith('host/vim/vmvisor')):
            # We don't want to allow resource starving the init or mgmt stack
            errMsg = CreateLocalizedMessage(policyOpt, INVALID_MEM_MAXIMUM_KEY)
            errMsg.SetRelatedPathInfo(paramId='memMaximum', policy=policy)
            verifyErrors.append(errMsg)
         elif (policyOpt.memMaximum != HOSTPROF_UNLIMITED_VAL and \
                  int(policyOpt.memMaximum) < int(policyOpt.memMinimum)) or \
               (policyOpt.memMinlimit != HOSTPROF_UNLIMITED_VAL and \
                  int(policyOpt.memMinlimit) < int(policyOpt.memMinimum)):
            log.warn('Found invalid mem minimum value for resource group %s' % \
                     policyOpt.groupPath)
            errMsg = CreateLocalizedMessage(policyOpt, INVALID_MEM_MINIMUM_KEY)
            errMsg.SetRelatedPathInfo(paramId='memMinimum', policy=policy)
            verifyErrors.append(errMsg)
      except ValueError:
         # Either memMaximum or memMinLimit wasn't Unlimited and was not an
         # integer value. Note that we need to catch this, but the parameter
         # validator will actually flag this error for us, so we'll log it but
         # not return a verification error right here.
         log.warn('Found an invalid value for memMaximum or memMinLimit')

      try:
         if policyOpt.cpuMaximum == '0' and \
               policyOpt.groupPath.startswith('host/vim/vmvisor'):
            # We don't want to allow resource starving the init or mgmt stack
            errMsg = CreateLocalizedMessage(policyOpt, INVALID_CPU_MAXIMUM_KEY)
            errMsg.SetRelatedPathInfo(paramId='cpuMaximum', policy=policy)
            verifyErrors.append(errMsg)
         elif (policyOpt.cpuMaximum != HOSTPROF_UNLIMITED_VAL and \
                  int(policyOpt.cpuMaximum) < int(policyOpt.cpuMinimum)) or \
               (policyOpt.cpuMinlimit != HOSTPROF_UNLIMITED_VAL and \
                  int(policyOpt.cpuMinlimit) < int(policyOpt.cpuMinimum)):
            log.warn('Found invalid cpu minimum value for resource group %s' % \
                     policyOpt.groupPath)
            errMsg = CreateLocalizedMessage(policyOpt, INVALID_CPU_MINIMUM_KEY)
            errMsg.SetRelatedPathInfo(paramId='cpuMinimum', policy=policy)
            verifyErrors.append(errMsg)
      except ValueError:
         # Either cpuMaximum or cpuMinLimit wasn't Unlimited and was not an
         # integer value. Note that we need to catch this, but the parameter
         # validator will actually flag this error for us, so we'll log it but
         # not return a verification error right here.
         log.warn('Found an invalid value for cpuMaximum or cpuMinLimit')

      # Check to make sure that, if there was a parent resource pool, there is
      # a subprofile instance for that resource pool as well.
      # NOTE: We only need to check one level up since if there is a subprofile
      #       instance for one level up, we'll check for the parent's parent
      #       during the VerifyProfile() call for that subprofile instance.
      groupPath = policyOpt.groupPath
      parentPoolPath, _sep, _groupSubpool = groupPath.rpartition('/')
      parentFound = False
      if parentPoolPath and cls.IsGroupConfigurable(parentPoolPath):
         rpConfigProfiles = profileInstance.parentProfile.RPConfigProfile
         for rpConfigProf in rpConfigProfiles:
            curPath = rpConfigProf.RPConfigProfilePolicy.policyOption.groupPath
            if curPath == parentPoolPath:
               parentFound = True
               break
         if not parentFound:
            errMsg = CreateLocalizedMessage(policyOpt, MISSING_PARENT_POOL_KEY)
            errMsg.SetRelatedPathInfo(paramId='groupPath', policy=policy)
            verifyErrors.append(errMsg)

      validationErrors.extend(verifyErrors)
      return len(verifyErrors) == 0


   @classmethod
   def CreatePool(cls, groupData, hostServices):
      """Helper method that determines if a pool exists for the settings in the
         supplied config map, and will attempt to create that pool if it
         does not exist. This method returns a boolean indicating whether the
         pool had to be created or not.
      """
      groupPath = groupData['groupPath']
      resGroupData = hostServices.GetProfileData(cls)
      resGroups = set([group['groupPath'] for group in resGroupData])
      return ResourceGroup.CreatePool(groupPath, resGroups, hostServices)

   @classmethod
   def SetConfig(cls, config, hostServices):
      """Sets the resource pool configuration settings.
      """
      # Let's create/set resource groups in order of the path length. This
      # ensures that the parent resource groups are created before children, if
      # required.
      for configMap in sorted(config, key=lambda resgrp:len(resgrp['groupPath'])):
         createdPool = False
         try:
            createdPool = cls.CreatePool(configMap, hostServices)
            ResourceGroup.SetConfig(configMap, hostServices)
         except:
            if createdPool:
               # If there was an error when setting resource group properties
               # for a resource pool we just created, let's remove it
               ResourceGroup.Remove(configMap, hostServices)
            raise

      # End of SetConfig()

