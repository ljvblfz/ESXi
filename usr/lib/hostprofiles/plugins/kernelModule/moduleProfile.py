#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import GenericProfile, FixedPolicyOption, Policy, \
                      ParameterMetadata, CreateLocalizedException, \
                      CreateLocalizedMessage, log, IsString, \
                      PolicyOptComplianceChecker, \
                      TASK_LIST_RES_OK, TASK_LIST_REQ_REBOOT, \
                      UserInputRequiredOption

from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING, COMPONENT_KERNEL_MODULE_CONFIG
from pluginApi import CreateComplianceFailureValues, \
                      PARAM_NAME, MESSAGE_VALUE, MESSAGE_KEY
from pyEngine.i18nmgr import MESSAGE_NS


ESXCLI_NAMESPACE = 'system'
ESXCLI_APP = 'module'

# Common module name option
ESXCLI_MODULE_OPT = '--module'

# Define constants for the list command
ESXCLI_LIST_CMD = 'list'
MODULE_NAME_FIELD = 'Name'

# Define constants for the parameters list command
ESXCLI_PARAMS_LIST_CMD = 'parameters list'
ESXCLI_PARAM_NAME_FIELD = 'Name'
ESXCLI_PARAM_TYPE_FIELD = 'Type'
ESXCLI_PARAM_VALUE_FIELD = 'Value'

# Define constants for the parameters set command
ESXCLI_PARAMS_SET_CMD = 'parameters set'
ESXCLI_PARAMS_SET_OPT = '--parameter-string'


# Define error message keys
MODULE_MSG_KEY_BASE = 'com.vmware.profile.kernelModule'
ESXCLI_ERROR_KEY = '%s.%s' % (MODULE_MSG_KEY_BASE, 'esxcliError')

# Keys for showing compliance failures
POLICY_LABEL = '%sPolicy.kernelModule.moduleProfile.ModuleNamePolicy.label' \
               % MESSAGE_NS
PARAM_PROFILE_LABEL = '%sProfile.kernelModule.moduleProfile.KernelModule' \
                      'ParamProfile.label' % MESSAGE_NS

# Message keys for module parameter validation
MODULE_NOT_PRESENT_KEY = '%s.%s' % (MODULE_MSG_KEY_BASE, 'notPresent')
MODULE_PARAMETER_CHANGED_KEY = '%s.%s' % (MODULE_MSG_KEY_BASE, 'parameterChanged')
MODULE_PARAMETER_NOTPRESENT_KEY = '%s.%s' % (MODULE_MSG_KEY_BASE,
                                          'moduleParamNotPresent')
MODULE_PARAMETER_EXPECTED_INT = '%s.%s' % (MODULE_MSG_KEY_BASE, 'parameterNotInt')
MODULE_PARAMETER_EXPECTED_BOOL = '%s.%s' % (MODULE_MSG_KEY_BASE, 'parameterNotBool')

EXTRA_MODULE_PARAMETER_FOUND_KEY = '%s.%s' % (MODULE_MSG_KEY_BASE,
                                           'extraModuleParamFound')
MODULE_PARAMETER_OK = 'parameterVerified'

DUPLICATE_MODULE_FOUND = '%s.%s' % (MODULE_MSG_KEY_BASE, 'duplicateModule')
DUPLICATE_MODULE_PARAM_FOUND = '%s.%s' % (MODULE_MSG_KEY_BASE,
                                        'duplicateModuleParam')

# Message key for modifying a kernel module's parameters
SETTING_MODULE_PARAMETERS = '%s.%s' % (MODULE_MSG_KEY_BASE, 'settingParameters')
CLEARING_MODULE_PARAMETERS = '%s.%s' % (MODULE_MSG_KEY_BASE, 'clearingParameters')

def InvokeEsxcli(hostServices, command, opts=None):
   """Helper function for invoking esxcli and processing errors.
   """
   if opts is None:
      opts = ''
   log.debug('Kernel Module provider invoking esxcli command %s %s' % \
             (command, opts))
   status, output = hostServices.ExecuteEsxcli(
                          ESXCLI_NAMESPACE, ESXCLI_APP, command, opts)
   if status != 0:
      if not IsString(output):
         log.warning('ESXCLI error output not a string for kernel ' + \
                     'module command %s with options %s' % (command, opts))
      errMsgData = { 'error': output }
      errMsg = 'Kernel Module Provider: Error issuing esxcli ' + \
               'command %s with options %s: %s' % \
               (command, str(opts), str(output))
      log.error(errMsg)
      raise CreateLocalizedException(None, ESXCLI_ERROR_KEY, errMsgData)
   return output


#
# Start class definitions for Kernel Module base profile
#
class ModuleNamePolicyOption(FixedPolicyOption):
   """Policy Option type containing configuration parameters for a NAS
      datastore.
   """
   MODULE_NAME_PARAM = 'moduleName'
   paramMeta = [
      ParameterMetadata(MODULE_NAME_PARAM, 'string', False)]

   # Don't need or want a compliance checker since we want to ignore extra
   # kernel modules that might not be installed on the system.
   #complianceChecker =

class ModuleNamePolicy(Policy):
   """Define a policy for the Kernel Module profile containing the name.
   """
   possibleOptions = [ ModuleNamePolicyOption ]


class ModuleParamData:
   """Helper class that contains data for a kernel module parameter.
   """
   def __init__(self, paramInfo):
      self.name = paramInfo[ESXCLI_PARAM_NAME_FIELD]
      self.type = paramInfo[ESXCLI_PARAM_TYPE_FIELD]
      if paramInfo[ESXCLI_PARAM_VALUE_FIELD] == "":
         self.value = None
      else:
      	self.value = paramInfo[ESXCLI_PARAM_VALUE_FIELD]


class KernelModuleProfile(GenericProfile):
   """A Host Profile that manages Kernel Modules on ESX hosts. This is a
      non-singleton/array profile that returns one instance per kernel module
      on the system.
   """
   #
   # Define required class attributes
   #
   policies = [ ModuleNamePolicy ]
   singleton = False

   # Don't need or want a compliance checker since we want to ignore extra
   # kernel modules that might not be installed on the system.
   #complianceChecker =

   @classmethod
   def _CreateProfileInst(cls, moduleName):
      """Helper method that creates a profile instance for the specified
         module.
      """
      # Create the policy option, policy, and then profile instance
      moduleNameParam = ('moduleName', moduleName)
      policyOpt = ModuleNamePolicyOption([moduleNameParam])
      policies = [ ModuleNamePolicy(True, policyOpt) ]
      return cls(policies=policies)

   @staticmethod
   def FormParamString(paramNameVals):
      """Helper function that forms an parameter string from a list of parameter
         name-value pairs. Specifically, this will return a string of the form:
            "name1=val1, name2=val2,..., nameN=valN"
      """
      paramStrs = []
      for paramName, paramVal in paramNameVals:
         paramString = '%s=%s' % (paramName, paramVal)
         paramStrs.append(paramString)
      return ' '.join(paramStrs)


   @classmethod
   def _GetModuleData(cls, moduleName, hostServices):
      """Helper function that retrieves module parameters for a particular
         module.
      """
      moduleParams = {}
      moduleCliOpt = '%s=%s' % (ESXCLI_MODULE_OPT, moduleName)

      # Get the list of module parameters with current user defined values
      cliRes = InvokeEsxcli(hostServices, ESXCLI_PARAMS_LIST_CMD, moduleCliOpt)
      for paramInfo in cliRes:
         paramData = ModuleParamData(paramInfo)
         moduleParams[paramData.name] = paramData

      return moduleParams


   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves kernel module info.
      """
      modulesData = {}
      cliRes = InvokeEsxcli(hostServices, ESXCLI_LIST_CMD)
      for moduleInfo in cliRes:
         # Do some debug error checking. These conditions shouldn't ever happen
         assert isinstance(moduleInfo, dict), \
             'Unexpected item (%s)in kernel module list command output: %s' \
             % (str(moduleInfo), str(cliRes))
         assert MODULE_NAME_FIELD in moduleInfo, \
             'Did not find module name field in module info: %s' % \
             str(moduleInfo)
         # Save the name as a key for now
         moduleName = moduleInfo[MODULE_NAME_FIELD]
         try:
            modulesData[moduleName] = cls._GetModuleData(moduleName,
                                                         hostServices)
         except Exception as e:
            # Seeing some errors evaluating the output of some of the esxcli
            # commands. For now, log the error and continue processing the
            # rest.
            log.error('Error getting module data for module %s: %s' % \
                      (moduleName, str(e)))

      return modulesData


   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      """Implementation of the GenericProfile.GenerateProfileFromConfig()
         that retrieves one profile instance per NAS datastore on the ESX
         host.
      """
      modules = []
      assert isinstance(profileData, dict)
      for moduleName, moduleParams in profileData.items():
         if len(moduleParams) > 0:
            # Don't create a profile if there are no parameters for the module
            moduleInst = cls._CreateProfileInst(moduleName)
            modules.append(moduleInst)

      return modules


   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      """Generates a task list for kernel module config changes.
      """
      # This is actually a no-op. We're not going to modify the list of kernel
      # modules on the system.
      return TASK_LIST_RES_OK


   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      """Verifies that there are no duplicate kernel module profile parameter
         instances defined for the current module.
      """
      moduleParamsFound = set()
      duplicates = set()

      moduleName = profileInstance.ModuleNamePolicy.policyOption.moduleName
      for moduleParamProf in profileInstance.subprofiles:
         moduleParamName = moduleParamProf.ModuleParamPolicy.policyOption.parameterName
         if moduleParamName in moduleParamsFound:
            duplicates.add((moduleParamName, moduleParamProf))
         else:
            moduleParamsFound.add(moduleParamName)
      for moduleParamName, moduleParamProf in duplicates:
         msgData = { 'ParameterName' : moduleParamName,
                     'ModuleName' : moduleName }
         duplicateModuleParamMsg = CreateLocalizedMessage(None,
                                         DUPLICATE_MODULE_PARAM_FOUND, msgData)
         duplicateModuleParamMsg.SetRelatedPathInfo(paramId='parameterName',
                                                    policy='ModuleParamPolicy',
                                                    profile=moduleParamProf)
         validationErrors.append(duplicateModuleParamMsg)
      return len(duplicates) == 0


   #
   # NOTE: We're not creating a RemediateConfig() method since it should never
   #       be called. If it is, that's a logic error in the infrastructure and
   #       the default implementation will raise an exception.
   #

   def GetProfileKey(self):
      if hasattr(self, 'ModuleNamePolicy'):
         return self.ModuleNamePolicy.policyOption.moduleName
      return ''


#
# Start class definitions for Kernel Module Parameter profile
#
class ModuleParamChecker(PolicyOptComplianceChecker):
   """Checks whether a given module parameter is set on the system with the
      value specified in the host profile.
   """
   @classmethod
   def VerifyModuleParameter(cls, moduleName, modParameterPolOpt, moduleData):
      """Helper function that extracts module parameter data from the given policy
         option and compares it against the moduleData currently on the system.
      """
      paramName = modParameterPolOpt.parameterName
      paramVal = modParameterPolOpt.parameterValue

      if moduleName not in moduleData:
         log.info('Verify Module Parameter skipping profile definition ' + \
                  'for module %s not found in system.' % moduleName)
         comparisonValues = CreateComplianceFailureValues(POLICY_LABEL,
            MESSAGE_KEY, profileValue = moduleName, hostValue = '')
         return MODULE_NOT_PRESENT_KEY, [comparisonValues]

      curModuleData = moduleData[moduleName]
      if paramName not in curModuleData:
         comparisonValues = CreateComplianceFailureValues(PARAM_PROFILE_LABEL,
            MESSAGE_KEY, profileValue = paramName, hostValue = '',
            profileInstance = moduleName)
         return MODULE_PARAMETER_NOTPRESENT_KEY, [comparisonValues]

      paramInfo = curModuleData[paramName]

      if paramVal is not None:
         # If there's a value, test the type of that parameter value
         if paramInfo.type == 'int' or paramInfo.type == 'uint':
            try:
               int(paramVal)
            except:
               log.warning('Parameter %s for module %s set to invalid value %s' \
                           % (paramName, moduleName, paramVal))
               return MODULE_PARAMETER_EXPECTED_INT, []
         #elif paramInfo.type == 'bool':
         #   # TODO: Not sure what values are valid for boolean parameters.
         #   log.warning('Parameter %s for module %s set to invalid value %s' \
         #               % (parameterName, moduleName, paramVal))
         #      return MODULE_PARAMETER_EXPECTED_BOOL
         #else: It's a string type, just like the policy option parameter

      if paramVal != paramInfo.value:
         log.info('Parameter %s for module %s ' % (paramName, moduleName) + \
                  'has value %s in system and %s in host profile' % \
                  (paramInfo.value, paramVal))
         comparisonValues = CreateComplianceFailureValues(paramName,
            MESSAGE_VALUE, profileValue = paramVal, hostValue = paramInfo.value,
            profileInstance = moduleName)
         return MODULE_PARAMETER_CHANGED_KEY, [comparisonValues]

      return MODULE_PARAMETER_OK, []


   @classmethod
   def CreateVerifyFailureMessage(cls, msgKey, moduleName, policyOpt):
      """Helper function to create a localized message for a verification
         failure.
      """
      paramName = policyOpt.parameterName
      paramVal = policyOpt.parameterValue
      if paramVal is None:
         paramVal = '<unset>'

      msgData = {
                  'ModuleName' : moduleName,
                  'ParameterName' : paramName,
                  'ParameterValue' : paramVal
                }
      msg = CreateLocalizedMessage(None, msgKey, msgData)
      if msg is None:
         log.warning('Failed to create localized message for key ' + msgKey)
      return msg


   def CheckPolicyCompliance(self, profile, policyOpt, hostServices,
                             profileData):
      """Checks whether a given module parameter is set on the system with the
         value specified in the host profile.
      """
      moduleName = GetModuleName(profile.parentProfile)

      retVal, complainceFailure = self.VerifyModuleParameter(moduleName,
                                     policyOpt, profileData)
      if retVal != MODULE_PARAMETER_OK:
         # We have to check the parent profile to see if we should fail
         # compliance if the module or module parameter was not found on the
         # system.
         strictCompliance = False
         configProf = profile.parentProfile.parentProfile
         configSettingPol = configProf.ConfigurationSettingPolicy
         if not isinstance(configSettingPol.policyOption, ApplyIfFoundOption):
            strictCompliance = True
         # Do not generate compliance failure if policy option is set to
         # ApplyIfFoundOption and if the failure is due to a missing module
         # or parameter on the host.
         if (retVal != MODULE_PARAMETER_NOTPRESENT_KEY and
               retVal != MODULE_NOT_PRESENT_KEY) or strictCompliance:
            complyFailMsg = self.CreateVerifyFailureMessage(
                                  retVal, moduleName, policyOpt)
            return (False, [(complyFailMsg, complainceFailure)])
      return (True, [])

   def CheckProfileCompliance(self, profileInsts, hostServices, profileData,
                              parent):
      """In addition to the validation done by CheckPolicyCompliance(), this
         method checks if the module has any extra module parameters specified
         that are not in the profile specification.
      """
      moduleName = GetModuleName(parent)

      assert isinstance(profileData, dict)
      if moduleName in profileData:
         # Build up the list of module parameters defined for this profile
         paramsDefined = set()
         for paramProfInst in profileInsts:
            paramsDefined.add(paramProfInst.ModuleParamPolicy.policyOption.parameterName)

         for paramInfo in profileData[moduleName].values():
            if paramInfo.name not in paramsDefined:
               # Found a parameter on the system that's not in the profile
               # This is ok if the value is not set, but a compliance failure
               # if it is.
               if paramInfo.value is not None:
                  msgData = { 'ParameterName' : paramInfo.name,
                              'ModuleName' : moduleName }
                  complyFailMsg = CreateLocalizedMessage(None,
                                        EXTRA_MODULE_PARAMETER_FOUND_KEY,
                                        msgData)
                  comparisonValues = CreateComplianceFailureValues(
                     PARAM_PROFILE_LABEL, MESSAGE_KEY,
                     profileValue = '', hostValue = paramInfo.name,
                     profileInstance = moduleName)
                  return (False, [(complyFailMsg, [comparisonValues])])
      else:
         log.info('Check Profile Compliance skipping profile definition ' + \
                  'for module %s not found in system.' % moduleName)

      return (True, [])

parameterName = 'parameterName'
parameterValue = 'parameterValue'
PARAMETER_NAME = ParameterMetadata(parameterName, 'string', False)
PARAMETER_VALUE = ParameterMetadata(parameterValue, 'string', True)

class ModuleParamPolicyOption(FixedPolicyOption):
   """ Kernel Module Fixed Policy Option.
   """

   paramMeta = [PARAMETER_NAME, PARAMETER_VALUE]

   # Don't need or want a compliance checker since we want to ignore extra
   # kernel modules that might not be installed on the system.
   complianceChecker = ModuleParamChecker()

class ModuleParamUserInputPolicyOption(UserInputRequiredOption):
   """ Kernel Module UserInput Policy Option
   """

   paramMeta = [PARAMETER_NAME]
   userInputParamMeta = [PARAMETER_VALUE]

   complianceChecker = ModuleParamChecker()


class ModuleParamPolicy(Policy):
   """Define a policy containing a module parameter's name and value.
   """
   possibleOptions = [ModuleParamPolicyOption, ModuleParamUserInputPolicyOption]

   _defaultOption = ModuleParamPolicyOption([])


class KernelModuleParamProfile(GenericProfile):
   """Host profile containing the parameter names and values for a kernel module.
   """
   #
   # Define required class attributes
   #
   policies = [ ModuleParamPolicy ]
   singleton = False
   parentProfiles = [ KernelModuleProfile ]

   # Don't need or want a compliance checker since we should ignore extra
   # or missing kernel modules in the host profile document.
   complianceChecker = ModuleParamChecker()

   @classmethod
   def _CreateProfileInst(cls, optInfo):
      """Helper method that creates a profile instance for the specified
         module.
      """
      # Create the policy option, policy, and then profile instance
      nameParam = (parameterName, optInfo.name)
      params = [ nameParam ]

      if optInfo.value is not None:
         valParam = ( parameterValue, optInfo.value)
         params.append(valParam)


      policyOpt = ModuleParamPolicyOption(params)
      policies = [ ModuleParamPolicy(True, policyOpt) ]
      return cls(policies=policies)

   def GetProfileKey(self):
      if hasattr(self, 'ModuleParamPolicy'):
         return self.ModuleParamPolicy.policyOption.parameterName
      return ''


   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      """Implementation of the GenericProfile.GenerateProfileFromConfig()
         that retrieves one profile instance per NAS datastore on the ESX
         host.
      """
      moduleName = parent.ModuleNamePolicy.policyOption.moduleName
      moduleParams = profileData[moduleName]
      assert len(moduleParams) > 0, \
             'Module %s does not have any parameters' % moduleName
      profileInsts = []
      for paramInfo in moduleParams.values():
         profileInsts.append(cls._CreateProfileInst(paramInfo))

      return profileInsts

   @classmethod
   def VerifyProfileForApply(cls, profileInstance, hostServices,
                             profileData, validationErrors):
      """Verifies the type of the value in the module parameter and whether
         the particular policy option is present on the system.
      """
      return cls.VerifyProfileInt(profileInstance, hostServices, profileData,
                                  validationErrors, True)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      """Verifies the type of the value in the module parameter and whether
         the particular policy option is present on the system.
      """
      return cls.VerifyProfileInt(profileInstance, hostServices, profileData,
                                  validationErrors, False)


   @classmethod
   def VerifyProfileInt(cls, profileInstance, hostServices, profileData,
                        validationErrors, preApplyStage):
      """Verifies the type of the value in the module parameter and whether
         the particular policy option is present on the system.
      """
      # Don't bother with verification during early boot, since we're always
      # going to try to apply what's there.
      if hostServices.earlyBoot:
         return True

      policyOption = profileInstance.ModuleParamPolicy.policyOption
      moduleName = GetModuleName(profileInstance.parentProfile)

      verifyRes, compFailure = cls.complianceChecker.VerifyModuleParameter(
                                  moduleName, policyOption, profileData)

      if verifyRes != MODULE_PARAMETER_OK and \
            verifyRes != MODULE_PARAMETER_CHANGED_KEY:
         # If the kernel module config profile indicates strict validation
         # (i.e. AlwaysApply), then fail if the module or one of the
         # module parameters is not present.
         strictValidation = False
         configProf = profileInstance.parentProfile.parentProfile
         configSettingPol = configProf.ConfigurationSettingPolicy
         if isinstance(configSettingPol.policyOption, AlwaysApplyOption):
            strictValidation = True
         if (not strictValidation or not preApplyStage) and \
               (verifyRes == MODULE_PARAMETER_NOTPRESENT_KEY or \
                verifyRes == MODULE_NOT_PRESENT_KEY):
            log.debug('Module %s in host profile not found ' % moduleName + \
                      'on system. Ignoring kernel module.')
         else:
            msg = ModuleParamChecker.CreateVerifyFailureMessage(
                        verifyRes, moduleName, policyOption)
            msg.SetRelatedPathInfo(policy=profileInstance.ModuleParamPolicy,
                                   paramId='parameterName')

            validationErrors.append(msg)
            return False

      return True


   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      """Generates a task if the parameters have changed for a kernel module.
      """
      # This is actually a no-op. We're not going to modify the list of kernel
      # modules on the system.

      # Use the compliance checker to determine if there has been a change
      # to the set of module parameters. First, use the CheckProfileCompliance
      # to determine if the module on the system contains extra parameters.
      # If the system doesn't have extra parameters, then check the existing
      # parameters for changes.
      moduleName = GetModuleName(parent)

      log.info('KernelModuleParamProfile checking %s for modified parameters' % \
               moduleName)

      # For the purposes of generating a task list, treat the "always check
      # compliance" option as the "apply if found" option.
      configSettingPol = parent.parentProfile.ConfigurationSettingPolicy
      if isinstance(configSettingPol.policyOption, AlwaysCheckComplianceOption):
         configSettingPol.policyOption = ApplyIfFoundOption([])

      # Don't bother with the compliance check if we're running at early boot,
      # since we'll always want to apply what's in the profile.
      if not hostServices.earlyBoot:
         compliant, _msg = cls.complianceChecker.CheckProfileCompliance(
                              profileInstances, hostServices, profileData, parent)
         if compliant:
            for modParamInst in profileInstances:
               paramName = modParamInst.ModuleParamPolicy.policyOption.parameterName
               log.debug(
                  'KernelModuleParamProfile checking %s for modified parameter %s' % \
                  (moduleName, paramName))
               policyOpt = modParamInst.ModuleParamPolicy.policyOption
               compliant, _msg = cls.complianceChecker.CheckPolicyCompliance(
                                    modParamInst,
                                    modParamInst.ModuleParamPolicy.policyOption,
                                    hostServices,
                                    profileData)
               if not compliant:
                  break

         if compliant:
            log.info('KernelModuleParamProfile found no changes for module %s' % \
                     moduleName)
            return TASK_LIST_RES_OK

      # Build up the list of module parameters to set
      paramValPairs = []
      for modParamInst in profileInstances:
         paramName = modParamInst.ModuleParamPolicy.policyOption.parameterName
         paramVal = modParamInst.ModuleParamPolicy.policyOption.parameterValue
         if paramVal:
            paramValPair = (paramName, paramVal)
            paramValPairs.append(paramValPair)

      paramStr = KernelModuleProfile.FormParamString(paramValPairs).strip()
      log.info(
         'KernelModuleParamProfile setting parameters to "%s" for module %s' % \
         (paramStr, moduleName))
      taskData = (moduleName, paramStr)
      msgData = { 'ModuleName' : moduleName, 'ParamStr' : paramStr }
      msgKey = SETTING_MODULE_PARAMETERS
      if len(paramStr) == 0:
         if hostServices.earlyBoot:
            # Don't bother clearing the module parameters at early boot
            return TASK_LIST_RES_OK

         # Slightly different message if we're removing all the parameters
         msgKey = CLEARING_MODULE_PARAMETERS

      taskMsg = CreateLocalizedMessage(None, msgKey, msgData)
      taskList.addTask(taskMsg, taskData)

      # TBD: If a module isn't actually loaded at the moment, there's really
      # no need to require a reboot.
      if hostServices.earlyBoot:
         return TASK_LIST_RES_OK
      return TASK_LIST_REQ_REBOOT


   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Applies the tasks in the task list to the host.
      """
      for moduleName, paramsStr in taskList:
         cmdOptions = [ '%s=%s' % (ESXCLI_MODULE_OPT, moduleName) ]
         cmdOptions.append('%s "%s"' % (ESXCLI_PARAMS_SET_OPT, paramsStr))
         log.info('Setting kernel module parameters with %s: %s' % \
                   (ESXCLI_PARAMS_SET_CMD, cmdOptions))
         output = InvokeEsxcli(hostServices, ESXCLI_PARAMS_SET_CMD, cmdOptions)
         log.info('Completed setting kernel module parameters: %s' % cmdOptions)


#
# Define top-level kernel module config profile to contain all of the
# kernel module profile instances and to provide a policy that determines
# whether we will always try to apply kernel module configuration, or whether
# the profile/plug-in will allow differences on systems that don't have a
# particular kernel module.
#
class AlwaysApplyOption(FixedPolicyOption):
   """Policy option indicating that all kernel module parameters must be applied
      on a system. If a system is missing a kernel module or a parameter that
      is present in the profile, then both "Apply" operations and compliance
      checks will fail.
   """
   paramMeta = []


class AlwaysCheckComplianceOption(FixedPolicyOption):
   """Policy option indicating that the profile will only apply parameters for
      modules that are found on the system, but will return a compliance
      failure if a host profile contains kernel modules or kernel module
      parameters that are not present on a system.
   """
   paramMeta = []


class ApplyIfFoundOption(FixedPolicyOption):
   """Policy option indicating that the profile will apply parameters for modules
      that are found on the system, but will ignore parameters not found on
      the system. Compliance checks will also pass even if a profile contains
      a kernel module or kernel module parameter not on a system.
   """
   paramMeta = []


class ConfigurationSettingPolicy(Policy):
   """A policy that determines how/when kernel module parameters will be applied
      to an ESX host. This is useful to create profiles where kernel module
      parameters must always be applied and would result in a failure if a kernel
      module were missing on a host. The alternative is having a profile that
      is lenient of differences in the set of kernel modules on a particular
      host vs the kernel modules and parameters defined in a host profile.
   """
   possibleOptions = [ ApplyIfFoundOption, AlwaysCheckComplianceOption,
                       AlwaysApplyOption ]


class KernelModuleConfigProfile(GenericProfile):
   """Top-level profile that contains all the kernel module profile instances
      and contains policies that indicate how those profiles will be applied
      to a host. We'll also use this top-level class to check for duplicate
      kernel module instances during verification.
   """
   policies = [ ConfigurationSettingPolicy ]
   singleton = True
   subprofiles = [ KernelModuleProfile ]

   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_KERNEL_MODULE_CONFIG

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      """Implementation that always returns a single instance containing the
         default selection for the ConfigurationSettingPolicy.
      """
      configPolicyOpt = ApplyIfFoundOption([])
      configPolicy = ConfigurationSettingPolicy(True, configPolicyOpt)
      return cls([configPolicy])

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      """Verifies that there are no duplicate kernel module profile instances
         defined.
      """
      modulesFound = set()
      duplicates = set()

      for moduleProf in profileInstance.subprofiles:
         moduleName = moduleProf.ModuleNamePolicy.policyOption.moduleName
         if moduleName in modulesFound:
            duplicates.add((moduleName, moduleProf))
         else:
            modulesFound.add(moduleName)
      for moduleName, moduleProf in duplicates:
         msgData = { 'ModuleName' : moduleName }
         duplicateModuleMsg = CreateLocalizedMessage(
                                    None, DUPLICATE_MODULE_FOUND, msgData)
         duplicateModuleMsg.SetRelatedPathInfo(profile=moduleProf,
                                               policy='ModuleNamePolicy',
                                               paramId='moduleName')
         validationErrors.append(duplicateModuleMsg)
      return len(duplicates) == 0

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                        profileData, parent):
      """Generates a task list for kernel module config changes.
      """
      # This is actually a no-op. We're not going to modify anything on the
      # system based solely on the policies, parameters, etc in this profile
      # (real changes to kernel module parameters happen in lower-level profile
      # classes).
      return TASK_LIST_RES_OK


def GetModuleName(moduleProf):
   """Helper function that retrieves the module name from a kernel module
      subprofile. It also deals with any backwards compatibility issues, e.g.
      5.x->6.0 conversion from tcpip3 to tcpip4.
   """
   moduleName = moduleProf.ModuleNamePolicy.policyOption.moduleName
   # If this is a 5.x host profile, treat tcpip3 as tcpip4
   if moduleProf.version[0] == '5':
      # NOTE: If we find more cases like this, then we'll want a more general
      # purpose conversion mechanism in here. We don't want to fill up
      # this method with special cases, but for now this is ok if we just
      # have 1 or 2 special cases.
      if moduleName == 'tcpip3':
         log.info('Converting tcpip3 module parameters to tcpip4 module parameters')
         moduleName = 'tcpip4'

   return moduleName
