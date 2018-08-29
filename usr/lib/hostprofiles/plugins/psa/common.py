#!/usr/bin/python
# **********************************************************
# Copyright 2010-2016 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import GenericProfile, Policy, FixedPolicyOption, \
                      UserInputRequiredOption, ParameterMetadata, log, \
                      PolicyOptComplianceChecker, ProfileComplianceChecker, \
                      CreateLocalizedException, CreateLocalizedMessage, \
                      TASK_LIST_REQ_MAINT_MODE, TASK_LIST_REQ_REBOOT, \
                      TASK_LIST_RES_OK
from pluginApi import CreateComplianceFailureValues, PARAM_NAME, \
                      MESSAGE_KEY, POLICY_NAME
from hpCommon.utilities import VersionLessThanEqual
from hpCommon.constants import RELEASE_VERSION_2013
import re

#
# Declare command strings for use in task lists
#
PSA_OP_ADD = 'PsaAdd'
PSA_OP_DEL = 'PsaDel'

#
# Declare the keys needed for task lists and compliance checking
#
PSA_BASE = 'com.vmware.profile.plugins.psa'

PSA_ADAPTER_TARGET_BOTH_EMPTY_OR_NON_EMPTY_KEY = \
   '%s.PsaAdapterTargetBothEmptyOrNonEmpty' % PSA_BASE
PSA_ESXCLI_CMD_BADDATA_KEY = '%s.PsaEsxcliCmdBadData' % PSA_BASE
PSA_ESXCLI_CMD_FAILED_KEY = '%s.PsaEsxcliCmdFailed' % PSA_BASE
PSA_INVALID_PARAM_KEY = '%s.PsaInvalidParam' % PSA_BASE
PSA_INVALID_PATH_KEY = '%s.PsaInvalidPath' % PSA_BASE
PSA_INTERNAL_CODE_KEY = '%s.PsaInternalCode' % PSA_BASE
PSA_MISMATCH_PARAM_KEY = '%s.PsaMismatchParam' % PSA_BASE
PSA_PARAM_NOT_FOUND_KEY = '%s.PsaParamNotFound' % PSA_BASE
PSA_PARAM_NOT_PRESENT_KEY = '%s.PsaParamNotPresent' % PSA_BASE
PSA_PARAM_NOT_POSITIVE_INT_KEY = \
   '%s.PsaParamNotPositiveInt' % PSA_BASE
PSA_PSP_OPTION_REQUIRES_PSP_NAME_KEY = \
   '%s.PsaPspOptionRequiresPspName' % PSA_BASE
PSA_REBOOT_REQUIRED_KEY = '%s.PsaRebootRequired' % PSA_BASE
PSA_VENDOR_MODEL_NOT_BOTH_NULL_KEY = \
   '%s.PsaVendorModelNotBothNull' % PSA_BASE

PSA_ADD_KEY = '%s.%s' % (PSA_BASE, PSA_OP_ADD)
PSA_DEL_KEY = '%s.%s' % (PSA_BASE, PSA_OP_DEL)


# global dictionary to map reference profile devices to host devices
mappingDict = {}
#
# Common lists for device sharing
#

hostDeviceList = []
profileSharedClusterwideDeviceList = []
profileNotSharedClusterwideDeviceList = []

#
# Common functions for error and exception handling with logging
#
def MakeLocalizedDict(details):
   if details is None:
      keyValDict = None
   elif isinstance(details, dict):
      keyValDict = details
   else:
      keyValDict = {'Error' : details}
   return keyValDict

def MakeLocalizedMessage(obj, message, details = None):
   keyValDict = MakeLocalizedDict(details)
   failureMsg = CreateLocalizedMessage(obj, message, keyValDict)
   if failureMsg:
      return failureMsg
   else:
      log.warning('Failed to get localized message for key %s with '      \
                  'details %s' % (message if message is not None else "", \
                                  details if details is not None else ""))
      return None

def LogAndReturnError(obj, message, errorDetails = None):
   failureMsg = MakeLocalizedMessage(obj, message, errorDetails)
   if failureMsg is not None:
      log.warning(failureMsg.message)
   return (False, [ failureMsg ])

def MakeLocalizedException(obj, message, details = None):
   keyValDict = MakeLocalizedDict(details)
   exceptionObj = CreateLocalizedException(obj, message, keyValDict)
   if exceptionObj.faultMessage and exceptionObj.faultMessage[0] is not None:
      log.error(exceptionObj.faultMessage[0].message)
   return exceptionObj

def LogAndRaiseException(obj, message, errorDetails = None):
   exceptionObj = MakeLocalizedException(obj, message, errorDetails)
   raise exceptionObj

def MakeTaskMessage(obj, message, messageDict):
   assert messageDict is None or isinstance(messageDict, dict), \
      '%s: task message dictionary not None and not a dictionary' % str(obj)
   taskMsg = MakeLocalizedMessage(obj, message, messageDict)
   if taskMsg is None:
      taskMsg = ''
   return taskMsg

#
# Usage Model for Common Functions:
#
# Each "profile" corresponds to a single set of esxcli add/delete/list commands.
# Each profile has 1+ "policies" which when instantiated consist of a single
# "policy option" from a specified set that presents related data to the
# user. Profiles export several class methods which allow for "apply", "extract"
# and other operations.  We conflate extract and apply and view application as
# consisting of first extracting and deleting the host state and then applying
# the new state.  Each profile instance thus maps one to one to a pair of esxcli
# commands, one for addition and one for deletion.
#
# We implement the notion of an "esxcli dictionary" which is populated by the
# policy option.  The provided common operations expect to receive data in this
# format, enabling profiles to have comparitively little knowledge of esxcli.
# The dictionary also contains localized message codes and format dictionaries
# for these localized message codes so profiles can output properly localized
# messages with no knowledge of the parameters to the localized messages.  Thus
# a typical profile would thus look like this:
#
# class FoobarProfileComplianceChecker(ProfileComplianceChecker):
#    """A compliance checker for the Foobar profiles
#    """
#    @classmethod
#    def CheckProfileCompliance(self, profileInsts, hostServices, profileData,
#                               parent):
#       """Checks whether the Foobar device configuration described by the
#          profiles matches what is on the host.
#       """
#       return CheckMyCompliance(self, profileInsts, hostServices, profileData,
#                                parent)
#
# class Foobar(GenericProfile):
#    """A leaf Host Profile that manages Foobar device configuration on the
#       ESX host.
#    """
#    #
#    # Define required class attributes
#    #
#    policies = [ FoobarConfigurationPolicy ]
#
#    complianceChecker = FoobarProfileComplianceChecker
#
#    singleton = False
#
#    @classmethod
#    def GatherData(cls, hostServices):
#       """Retrieves a list of all Foobar devices on the host
#       """
#       # XXX This could be pushed into the policy options as well
#       return GatherEsxcliData(cls, hostServices, 'storage theModule',
#                               'foobar device', 'list')
#
# Note: here 'theModule' is the name of a top-level namespace which is nested
#       in the overall 'storage' namespace, 'foobar' and 'device' are nested
#       namespaces defined by the esxcli plug-in and 'list' is a command.
#
#    @classmethod
#    def GenerateProfileFromConfig(cls, hostServices, config, parent):
#       """Retrieves one profile instance per Foobar device on the ESX host.
#       """
#       return GenerateMyProfileFromConfig(cls, hostServices, config,
#                                          FoobarConfigurationPolicyOption)
#
#    @classmethod
#    def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
#                         parent):
#       """Generates a list of the data in the profileInstances.
#       """
#       return GenerateMyTaskList(cls, profileInstances, taskList, hostServices,
#                                 config, parent)
#
#    @classmethod
#    def RemediateConfig(cls, taskList, hostServices, config):
#       """Remediates host config based on the supplied task list.
#       """
#       RemediateMyConfig(cls, taskList, hostServices, config)
#
#    @classmethod
#    def VerifyProfile(cls, profileInstance, hostServices, profileData,
#                      validationErrors):
#       """Verifies the profile based on the supplied profile data.
#       """
#       return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
#                                       profileData, validationErrors)
#
# Optionally for profiles with a user input required secondary policy option
#    @classmethod
#    def VerifyProfileForApply(cls, profileInstance, hostServices, profileData,
#                      validationErrors):
#       """Verifies the profile based on the supplied profile data.
#       """
#       return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
#                                       profileData, validationErrors, True)
#
# Helper function for policy options to bundle up an esxcli command
#
# Parameters passed directly to ExecuteEsxcli:
#
#    * cliNs - esxcli (top level) namespace(s) (e.g., 'storage core')
#    * cliApp - esxcli application (low level namespace(s)) (e.g., 'path stats')
#    * cliAddCmd - esxcli command to add policy option (e.g. 'set')
#    * cliDelCmd - esxcli command to delete policy option (e.g. 'set'), can be None
#
# Optional parameters passed directly to ExecuteEsxcli (default to None):
#    * cliAddOpt - esxcli options to add command (e.g. '--device Name')
#    * cliDelOpt - esxcli options to delete command (e.g. '--device Name')
#         Note: if cliDelCmd is None then cliDelOpt must also be None.
#
# Note: there is no 'storage core path stats set' command; this was only an
#       example of how to split namespaces and commands among the parameters.
#       The actual 'storage core path stats get' command would be used in a
#       GatherData implementation if path stats were stored in a host profile.
#
# Optional parameters used to derive parameters for ExecuteEsxcli
#
#    * addPolicyOpt - instance of PolicyOpt exporting GetEsxcliOptionString()
#    * deletePolicyOpt - instance of PolicyOpt exporting GetEsxcliOptionString()
#                        or may be the PolicyOpt itself (i.e., a subclass) in
#                        which case must export GetStaticEsxcliOptionString().
#                        This is useful when a "default" policy option has
#                        no parameters and can be used to delete instances of
#                        other sibling PolicyOpts.
#    * esxcliOptionBool - boolean passed to dependent policy option
#
# Optional parameter used to control taskList stripping for devices not shared
# clusterwide
#
#    * dictDevice - device to which dictionary applies.  For policies which
#                   have dependent policies, the secondary policy option
#                   (addPolicyOpt) may export a GetEsxcliDictDevice() interface.
#
# Parameters used to derive user output
#    * messageDict - a "message dictionary"
#
# The output of this function is referred to as an "esxcli dictionary" and
# is used by RemediateMyConfig and GenerateMyTaskList below.
#
def MakeEsxcliDict(cliNs, cliApp, cliAddCmd, cliDelCmd, cliAddOpt, cliDelOpt,
                   messageDict, addPolicyOpt = None, deletePolicyOpt = None,
                   esxcliOptionBool = False, dictDevice = None):
   """Makes an esxcli dictionary.
   """

   if cliDelCmd is None:
      cliDelCmd = ''
      assert cliDelOpt is None and deletePolicyOpt is None,                  \
          'MakeEsxcliDict: cliDelOpt and deletePolicyOpt must be None when ' \
          'cliDelCmd is None'
      cliDelOpt = None
      deletePolicyOpt = None
   if cliAddOpt is None:
      cliAddOpt = ''
   if cliDelOpt is None:
      cliDelOpt = ''
   assert messageDict is not None, \
          'MakeEsxcliDict: messageDict must not be None'

   if addPolicyOpt is not None:
      assert hasattr(addPolicyOpt, 'GetEsxcliOptionString'), \
             'addPolicyOpt must have GetEsxcliOptionString method'
      cliAddOpt += ' %s' % addPolicyOpt.GetEsxcliOptionString(esxcliOptionBool)

      if dictDevice is None and hasattr(addPolicyOpt, 'GetEsxcliDictDevice'):
         dictDevice = addPolicyOpt.GetEsxcliDictDevice(esxcliOptionBool)

   if deletePolicyOpt is not None:
      if isinstance(deletePolicyOpt, FixedPolicyOption) or \
         isinstance(deletePolicyOpt, UserInputRequiredOption):
         assert hasattr(deletePolicyOpt, 'GetEsxcliOptionString'), \
                'deletePolicyOpt must have GetEsxcliOptionString method'
         cliDelOpt += ' %s' % \
            deletePolicyOpt.GetEsxcliOptionString(esxcliOptionBool)
      elif issubclass(deletePolicyOpt, FixedPolicyOption) or \
         issubclass(deletePolicyOpt, FixedPolicyOption):
         assert hasattr(deletePolicyOpt, 'GetStaticEsxcliOptionString'), \
                'deletePolicyOpt must have GetStaticEsxcliOptionString method'
         cliDelOpt += ' %s' % \
            deletePolicyOpt.GetStaticEsxcliOptionString(esxcliOptionBool)
      else:
         assert False, 'deletePolicyOpt must be an instance or a subclass'

   esxcliDict = { 'Namespace': cliNs, 'App': cliApp,
                  'AddCmd': cliAddCmd, 'AddOpt': cliAddOpt,
                  'DelCmd': cliDelCmd, 'DelOpt': cliDelOpt,
                  'MessageDict': messageDict, 'Device': dictDevice }
   return esxcliDict

# Helper function for policy options to bundle up localized message codes and
# dictionaries matching same
#
# Parameters passed directly to MakeTaskMessage
#
#    * addKey - key to localized message for an add operation
#    * delKey - key to localized message for a delete operation
#    * addDict - dictionary for localized message for an add operation
#    * delDict - dictionary for localized message for a delete operation
#
# The output of this function is part of an "esxcli dictionary" and is used by
# GenerateMyTaskList below.
#
def MakeMessageDict(addKey, delKey, addDict = None, delDict = None):
   """Makes a message dictionary.
   """

   assert addKey is not None and delKey is not None,                        \
          'MakeMessageDict() with addKey %s, delKey %s; must not be None' % \
          (addKey, delKey)

   if addDict is None:
      addDict = {}
   if delDict is None:
      delDict = {}

   messageDict = { 'AddKey': addKey, 'DelKey': delKey,
                   'AddDict': addDict, 'DelDict': delDict }
   return messageDict

#
# Helper function to invoke esxcli command through hostServices interface
# Logs failed cmd and error output in case of command failure.
#
# General Parameters:
#
#   * cls - the calling object class
#   * hostServices - hostServices from the calling profile
#
# Parameters passed directly to ExecuteEsxcli:
#
#    * cliNs - esxcli namespace
#    * cliApp - esxcli application
#    * cliCmd - esxcli command to run on host
#    * cliOpt - esxcli option string
# Optional Parameters
#    * ignoreError - if True logs the error but do not generate exception
#
def RunEsxcli(cls, hostServices, cliNs, cliApp, cliCmd, cliOpt, ignoreError=False):
   status, output = hostServices.ExecuteEsxcli(cliNs, cliApp, cliCmd, cliOpt)
   logStr = 'Esxcli Command "%s" failed' % \
            (' '.join(['esxcli', cliNs, cliApp, cliCmd, cliOpt]))
   if status != 0 and not ignoreError:
      log.error(logStr)
      LogAndRaiseException(cls, PSA_ESXCLI_CMD_FAILED_KEY, output)
   elif status != 0:
      log.warning(logStr)
   else:
      return output

#
# Helper function for profiles to gather raw data (list of dictionaries) from
# the host using esxcli.  Returns a list of dictionaries (need not be raw data)
#
# General Parameters:
#
#    * cls - the calling class object
#    * hostServices - hostServices from the calling profile
#
# Parameters passed directly to ExecuteEsxcli:
#
#    * cliNs - esxcli namespace
#    * cliApp - esxcli application
#    * cliCmd - esxcli command to gather data
#    * cliOpt - esxcli option string
#
# Parameters for subsequent invocations of ExecuteEsxcli:
#
#    * itemApp - esxcli application
#    * itemCmd - esxcli command
#    * itemName, itemNameLookup - rendered into an esxcli option string
#                                 also used in dictionary creation if needed
#                                 if itemName is not None then itemNameLookup
#                                 must not be None.
#
#
# Parameter for subsetting the returned dictionary:
#
#    * itemIfFct - (lambda) function for subsetting the list of dictionaries
#
# Note: the output of this function is always of type list of dictionaries but
# the dictionaries are _not_ "esxcli dictionaries".  See MakeEsxcliDict()
# for those.  The output of this fct winds up in "config" via GenerateTaskList.
#
def GatherEsxcliData(cls, hostServices, cliNs, cliApp, cliCmd, cliOpt = None,
                     itemApp = None, itemCmd = None,
                     itemName = None, itemNameLookup = None, itemIfFct = None):
   """Retrieves a list of dictionaries, one per item on the host.  Optionally
      returns the raw list, a subsetted list based on itemIfFct or a list of
      dictionaries based on itemApp, itemCmd and itemName.  For a generated
      list specify itemApp, itemCmd, itemName and itemNameLookup.  For a
      subsetted list specify itemIfFct, typically a lambda such as
      "lambda x: x['Path Selection Policy'] == 'VMW_PSP_FIXED'".  In all cases
      the original list must be a list of dictionaries but if the esxcli
      outputs to the secondary app/cmd (itemApp/itemCmd) is not a dictionary
      then it will be automatically re-rendered into a list of dictionaries.
   """
   # Get the raw list.  This should be a list of dictionaries.
   assert cliNs is not None and cliApp is not None and cliCmd is not None, \
          '%s: cliNs, cliApp, cliCmd must not be None' % str(cls)
   # Workaround for PR 573640
   if cliOpt is None:
      cliOpt = ''

   status, output = hostServices.ExecuteEsxcli(cliNs, cliApp, cliCmd, cliOpt)
   # Raise exception on failure to read host state (should always succeed)
   if status != 0:
      LogAndRaiseException(cls, PSA_ESXCLI_CMD_FAILED_KEY, output)

   # If no itemApp/Cmd and no itemIfFct then return this list
   # If no itemApp/Cmd and itemIfFct then return a filtered list
   # If itemApp/Cmd then return output of itemApp/Cmd, possibly filtered
   if itemApp is None and itemCmd is None and itemIfFct is None:
      if hostServices.earlyBoot == True:
         log.info('%s GatherEsxcliData: found (expected?) early boot state: %s'
                  % (str(cls), output))
      return output

   # Enforce itemApp/Cmd and itemName/itemNameLookup constraints
   if itemApp is None and itemCmd is not None:
      itemApp = cliApp
   elif itemCmd is None and itemApp is not None:
      itemCmd = cliCmd
   # itemName is None ==> no itemOpt but itemNameLookup might still be needed
   assert itemName is None or                                  \
          itemName is not None and itemNameLookup is not None, \
         '%s: itemName, itemNameLookup must agree (None or not None)' % str(cls)

   # Make a list of dictionaries, each being per caller specified item
   itemList = []
   for item in output:
      assert isinstance(item, dict), \
         '%s: initial esxcli output must be a list of dictionaries' % str(cls)
      if itemIfFct is None or itemIfFct(item):
         if itemApp is not None:
            itemOpt = None if itemName is None else \
                      '--%s="%s"' % (itemName, item[itemNameLookup])
            status, itemOutput = hostServices.ExecuteEsxcli(cliNs,
                                       itemApp, itemCmd, itemOpt)
            # Raise exception on failure to read host state (should succeed)
            if status != 0:
               LogAndRaiseException(cls,
                                    PSA_ESXCLI_CMD_FAILED_KEY, itemOutput)
         else:
            itemOutput = item

         if isinstance(itemOutput, dict):
            itemDict = itemOutput
         else:
            assert itemNameLookup is not None,                                 \
               '%s: returned item not a dict requires itemNameLookup not None' \
               % str(cls)
            outputKey = itemCmd if itemCmd is not None else cliCmd
            itemDict = {itemNameLookup : item[itemNameLookup],
                        outputKey.capitalize() : itemOutput}

         itemList.append(itemDict)

   if hostServices.earlyBoot == True:
      log.info('%s GatherEsxcliData: found (expected?) early boot state: %s' %
               (str(cls), str(itemList)))
   return itemList

#
# Helper function for profile generation from local host config information
#
# Assumes config is a dictionary generated by GatherEsxcliData and that
# policyOption implements a constructor to parse this dictionary.  If
# secondaryPolicy is not None then it should supply a GetPolicyOption method
# that will determine the appropriate policy option and instantiate it based
# on the provided entry from the aforementioned dictionary.  If secondaryPolicy
# is not None and the output of GetPolicyOption is None then no profile is
# created and policyOption is not even called.  This can be useful for the
# case where secondaryPolicy inspects the config entry and determines that
# no valid data is present (e.g., a device with no local host config info).
#
# General Parameters:
#
#    * cls - the calling class object
#    * hostServices, config - from the calling profile
#
# Policy Parameters:
#
#   * policyOption - policy option that has an __init__ function which takes
#                    an esxcli dictionary as an input parameter.
#   * secondaryPolicy - policy that implements a GetPolicyOption class method
#                       that takes esxcli output (from config) as an input
#                       param and returns the correct policy option instance.
#
def GenerateMyProfileFromConfig(cls, hostServices, config, policyOption,
                                secondaryPolicy = None):
   """Generates a profile from the host config data.
   """

   assert issubclass(policyOption,FixedPolicyOption) or                  \
          issubclass(policyOption,UserInputRequiredOption),              \
          '%s: policyOption %s must be a subclass of FixedPolicyOption ' \
          'or UserInputRequiredOption' % (str(cls), str(policyOption))

   profileList = []
   for entry in config:
      if secondaryPolicy is not None and \
         hasattr(secondaryPolicy, 'GetPolicyOption'):
         secondaryPolicyOpt = secondaryPolicy.GetPolicyOption(entry)
         if secondaryPolicyOpt is not None:
            policyOpt = policyOption(entry)
            newPolicies = [ cls.policies[0](True, policyOpt),
                            cls.policies[1](True, secondaryPolicyOpt) ]
         else:
            newPolicies = None
      else:
         policyOpt = policyOption(entry)
         newPolicies = [ cls.policies[0](True, policyOpt) ]
      if newPolicies is not None:
         profileInstance = cls(policies=newPolicies)
         profileList.append(profileInstance)

   return profileList

#
# Internal function factored out of GenerateMyTaskList.
# Not intended for users to call directly.
# Note that "taskList" can be either a list or a taskList.
#
def AddInstancesToTaskList(cls, profileInstances, taskList, taskListOp,
                           rebootOnOp, esxcliDictParam):
   """Generates a list of the data in the profileInstances.
   """
   retVal = TASK_LIST_RES_OK

   assert taskListOp == PSA_OP_ADD or taskListOp == PSA_OP_DEL, \
          'unknown taskListOp: %s' % taskListOp

   # Add each profile instance to the taskList for the specified operation
   for inst in profileInstances:
      ver = inst.version
      param = esxcliDictParam
      pIndex = 0
      secondary = False

      if rebootOnOp:
         retVal = TASK_LIST_REQ_REBOOT
      # If the profiles has multiple policies then we must have the following:
      # - esxcliDictParam is None
      # - policy option to primary policy exports GetEsxcliDict() and this
      #   function takes as an optional param a GetEsxcliOptionString() fct.
      # - policy option to primary policy exports GetComparisonKey()
      # - policy option to secondary policy may export GetEsxcliOptionString()
      # We don't require the primary option to be at offset 0 but use pIndex
      if len(inst.policies) > 1:
         secondary = True
         assert len(inst.policies) == 2 and esxcliDictParam is None,         \
                'Dual-policy profile %s incompatible with esxcliDictParam' % \
                str(inst)
         if hasattr(inst.policies[1].policyOption, 'GetEsxcliOptionString'):
            pIndex = 0
            param = inst.policies[1].policyOption
         elif hasattr(inst.policies[0].policyOption, 'GetEsxcliOptionString'):
            pIndex = 1
            param = inst.policies[0].policyOption
      assert hasattr(inst.policies[pIndex].policyOption, 'GetEsxcliDict'),     \
             '(Primary) policy option %s must export GetEsxcliDict() method' % \
             str(inst.policies[pIndex].policyOption)
      policyOpt = inst.policies[pIndex].policyOption
      # For profiles extracted from a 5.5 or older host
      if ver is not None and VersionLessThanEqual(ver, RELEASE_VERSION_2013) and \
         'SatpDeviceProfile' in cls.__name__:
         policyOpt.adjustPolicyOpt()
      esxcliDict = policyOpt.GetEsxcliDict(param)
      if esxcliDict is None:
         continue

      # paramValue is list of tuples convert it to dict
      paramDict = {key: value for (key,value) in policyOpt.paramValue}
      if hasattr(policyOpt, 'GetComparisonKey'):
         # The defining param for an instance of the profile
         paramDict['ComparisonKey'] = policyOpt.GetComparisonKey()

      if hasattr(policyOpt, 'GetComplianceTaskDict'):
         complianceValueDict = policyOpt.GetComplianceTaskDict()
         paramDict['messageCode'] = complianceValueDict.get('messageCode')
         paramDict['messageDict'] = complianceValueDict.get('messageDict')
         paramDict['comparisonIdentifier'] = \
            complianceValueDict.get('comparisonIdentifier')
         paramDict['hostValue'] = complianceValueDict.get('hostValue')
         paramDict['profileValue'] = complianceValueDict.get('profileValue')
         paramDict['profileInstance'] = complianceValueDict.get('profileInstance')

      if secondary:
         # Introduce a special key to identify the policy option for policies with
         # multiple policy opts. As of now in PSA/NMP/VVOL only secondary
         # polices have multiple secondary policy options.
         paramDict['SecPolicy'] = inst.policies[1 - pIndex].__class__.__name__
         paramDict['SecPolicyOptType'] =  inst.policies[1 - pIndex].policyOption.__class__.__name__
         for (key,value) in inst.policies[1].policyOption.paramValue:
            paramDict[key] = value
      esxcliDict['ParamDict'] = paramDict
      log.debug('Params: %s' % str(paramDict))

      # adding empty string for modMsg in taskList, not being used for
      # compliance comparison.
      modMsg = ''
      modData = (taskListOp, esxcliDict)

      # CheckMyCompliance doesn't receive a taskList and we can't create one
      # so we transparently handle the case where taskList is actually a list.
      if isinstance(taskList, list):
         taskList.append( (modMsg, modData) )
      else:
         taskList.addTask(modMsg, modData)

   return retVal

#
# Helper function for RemoveRedunantEntriesfromList(). A profile on
# the host does not match one in the reference profile (and vice versa)
# if no matching 'AddOpt' string is found. It is extraneous to
# to match other entries of esxcliDict.
# Note: Whether the esxcliDict is for a PSA_OP_ADD or a PSA_OP_DEL,
# it is 'AddOpt' that containas all the info required to match
# profiles.
#
def DictinList(esxcliItem, esxcliDictList):
   itemOpStr = esxcliItem['AddOpt']
   for checkItem in esxcliDictList:
      if itemOpStr == checkItem['AddOpt']:
         return True

   return False

#
# Helper function for RemoveRedundantEntriesFromList() to check if a device
# that has an entry in delList doesn't have an entry in addList. If such is
# the case, it would mean that the profile was extracted from an older host
# and this device setting was not supported at that time.
#
def SupportedInProfile(dictItem, dictList):
   for item in dictList:
      if item['Device'] == dictItem['Device']:
         return True
   return False
 
#
# Helper function for profiles to remove redundant entries from a list
# containing esxcliDict entries.  A "redundant entry" takes several forms:
#
# 1) a pair of entries, one for add and one for delete, with identical content.
# 2) if we do NOT have a legacy profile and if "Device:" value is not None
#    then remove certain single (add or delete only) device entries too.
# 3) for delete operation, a single entry for a host device which is not present
#    in the profile, whether or not the device is marked as shared clusterwide.
# 4) for add operation, a single entry for a device which is not marked as
#    shared clusterwide in the profile IFF the device is not present on the host.
#
# Users can call this function directly from other custom GenerateTaskList
# methods or custom CheckProfileCompliance methods or specify via parameter to
# GenerateMyTaskList that it is to be called.  If Esxcli dictionaries have not
# set a 'Device' value then legacy behavior (rule 1 only) will be maintained.
# If a legacy profile is being processed then profileSharedClusterwideDeviceList and
# profileNotSharedClusterwideDeviceList will be empty and again only rule 1) will run.
#
# General Parameters:
#
#    * cls - the calling class object
#    * oldList - the list to be cleaned of redundant entries
#
def RemoveRedundantEntriesFromList(cls, oldList):
   """Removes redundant pairs of entries in a list
   """

   assert isinstance(oldList, list), \
          '%s: oldList is not a list (probably is a taskList)' % str(cls)

   # PR 1246224 to evaluate the below logic for redundancies that can be
   # removed for RC.  These will NOT be removed for Beta2 due to risk.
   addList = []
   delList = []
   for modMsg, modData in oldList:
      tasklistOp, esxcliDict = modData
      if tasklistOp == PSA_OP_DEL:
         delList.append( esxcliDict )
      elif tasklistOp == PSA_OP_ADD:
         addList.append( esxcliDict )
      else:
         LogAndRaiseException(cls, PSA_INTERNAL_CODE_KEY,
                              'unknown tasklist operation')

   modDataList = []
   for delDict in delList:
      if not DictinList(delDict, addList):
         # 2) if profile{,Not}SharedClusterwideDeviceList are both
         #    empty we have a legacy profile or no reference profile devices and
         #    thus an empty addList. For a legacy SatpDeviceProfile, we check if
         #    the device in delDict is present in addList. If it's not, then we
         #    strip this entry as the SATP claiming this device didn't support
         #    device config till ESX 5.5U2. But addList could also be empty if we have
         #    no host state of this profile type (e.g., no RR rotation setting).
         #    We default to legacy behavior for the case of a new type profile
         #    that lacks any device.  This is documented on PR 1247575 and thus
         #    we can assume that the reference profile always has 1+ devices
         #    across all profile types (not just this type) and thus that here
         #    len(profileNotSharedClusterwideDeviceList) == 0 and
         #    len(profileSharedClusterwideDeviceList) == 0 ==> a legacy profile.
         # 3) if delDict has no Device value or the device is a profile device
         #    then do NOT strip the dictionary.
         if (len(profileSharedClusterwideDeviceList) == 0 and           \
             len(profileNotSharedClusterwideDeviceList) == 0 and
             (cls.__name__ != 'SatpDeviceProfile' or                    \
              SupportedInProfile(delDict, addList))) or                 \
            delDict['Device'] is None or                                \
            delDict['Device'] in profileSharedClusterwideDeviceList or  \
            delDict['Device'] in profileNotSharedClusterwideDeviceList:
            modDataList.append( (PSA_OP_DEL, delDict) )

   for addDict in addList:
      if not DictinList(addDict, delList):
         # 2) if profileSharedClusterwideDeviceList and
         #    profileNotSharedClusterwideDeviceList are both
         #    empty we have a legacy profile or no reference profile devices
         #    and thus an empty addList.  We only get here if addList is not
         #    empty so here len(profileSharedClusterwideDeviceList) == 0 and
         #    len(profileNotSharedClusterwideDeviceList) == 0 implies a legacy
         #    profile.
         # 4) if addDict has no Device value or the device is not marked as not
         #    shared clusterwide on the reference host or the device is present on the
         #    target host, then do NOT strip the dict entry (i.e., append it to
         #    modDataList).
         #    If the device is not shared clusterwide on the reference host, and it is
         #    not present on the target host, then we need to strip it for device
         #    profiles other than device sharing profile, because it should not be
         #    considered for matching device settings and configuration between the
         #    reference host and the target host.
         #
         if (len(profileSharedClusterwideDeviceList) == 0 and                 \
             len(profileNotSharedClusterwideDeviceList) == 0) or              \
            addDict['Device'] is None or                                      \
            addDict['Device'] not in profileNotSharedClusterwideDeviceList or \
            addDict['Device'] in hostDeviceList:
            modDataList.append( (PSA_OP_ADD, addDict) )

   newList = []
   for modMsg, modData in oldList:
      if modData in modDataList:
         newList.append( (modMsg, modData) )

   return newList

# Helper function for profiles to translate a 'task' with
# the reference profile's device name with that on the host.
# This is for profiles which have a 'Device' key as part
# of their messageDict and '--device' str as part of the
# op string
def GetTranslatedTaskList(task):
   """Translate reference profile's devices to host devices
   """
   msg, data = task
   taskOp, esxcliDict = data
   if taskOp == PSA_OP_ADD:
      messageDict = esxcliDict['MessageDict']
      if ('Device' in messageDict['AddDict']) == False:
         return task
      deviceInProfile = messageDict['AddDict']['Device']
      # Check if this device has a mapping
      if deviceInProfile in mappingDict:
         # NOTE: this touches only the esxcliDict part so error messages to
         # the user will be flagged with the profile's device name and not
         # the host device
         log.debug('add op: %s' % str(task))
         hostDevice = mappingDict[deviceInProfile]

         # translate the name in the message dict
         messageDict['AddDict']['Device'] = hostDevice
         messageDict['DelDict']['Device'] = hostDevice
         esxcliDict['MessageDict'] = messageDict

         # Op str. We choose to replace only the first occurence
         assert esxcliDict['AddOpt'].count(deviceInProfile) == 1, \
               '> 1 occurance of device name in addOpt'
         esxcliDict['AddOpt'] = esxcliDict['AddOpt'].replace(deviceInProfile,
                                                             hostDevice, 1)
         assert esxcliDict['DelOpt'].count(deviceInProfile) == 1, \
              '> 1 occurance of device name in delOpt %s'
         esxcliDict['DelOpt'] = esxcliDict['DelOpt'].replace(deviceInProfile,
                                                             hostDevice, 1)
         if 'Device' in esxcliDict:
            esxcliDict['Device'] = hostDevice

         assert deviceInProfile not in esxcliDict['AddOpt'] and   \
                deviceInProfile not in esxcliDict['DelOpt'],      \
            'Profile device %s found even after translation' % deviceInProfile
         newTask = (msg, (taskOp, esxcliDict))
         log.debug('new dict %s' % str(newTask))
         return newTask
   # nothing to do otherwise
   return task

#
# Helper function for profiles to generate a simple or stripped tasklist.
# A simple tasklist assumes that any state change requires all to be reapplied
# A stripped tasklist is one which has removed deletes and adds of same state.
# Also automatically returns an empty taskList if zero state changes occurred.
#
# Each profile instance is expected to consist of a primary policy which
# has a policy option which exports a GetEsxcliDict instance method which
# returns an "esxcli dictionary" that can be used to drive ExecuteEsxcli.
# If the returned "esxcli dictionary" in None then no esxcli operation is
# required due to a device which is not shared clusterwide (this mechanism
# should only be used by policies of profiles which set the policy for sharing).
# An optional secondary policy is expected to consist of a secondary policy
# option which exports a GetEsxcliOptionString instance method.
#
# General Parameters:
#
#    * cls - the calling class object
#    * profileInstances, taskList - from the calling profile
#    * hostServices, config, parent - from the calling profile
#
# List optimization parameters:
#
#    * strip - unconditionally remove pairs that add and delete identical state
#    * addsOnly - only store add changes (skip deleting old state)
#                 (currently only valid if strip is true)
#
# Other Parameters:
#
#    * rebootOnDelete, rebootOnAdd - reboot needed if something is deleted/added
#    * esxcliDictParam - parameter to be passed to GetEsxcliDict
#    * translateFunc - function to translate the reference profile to host's device name
#                      using the mappingDict
#
def GenerateMyTaskList(cls, profileInstances, taskList, hostServices, config,
                       parent, translateFunc = None, esxcliDictParam = None,
                       rebootOnDelete = False, rebootOnAdd = False,
                       strip = True, addsOnly = False):
   """Generates lists for addition and deletion of the old and new profile
      instances respectively.
   """

   # Construct a provisional list and then strip to remove redundant entries
   tmpTaskList = []
   delRetVal = AddInstancesToTaskList(cls,
                  cls.GenerateProfileFromConfig(hostServices, config, parent),
                  tmpTaskList, PSA_OP_DEL, rebootOnDelete, esxcliDictParam)
   addRetVal = AddInstancesToTaskList(cls, profileInstances, tmpTaskList,
                  PSA_OP_ADD, rebootOnAdd, esxcliDictParam)

   mappedList = tmpTaskList
   # Check if we need to translate the reference host devices
   if len(mappingDict) != 0 and translateFunc != None:
      mappedList = [translateFunc(x) for x in tmpTaskList]

   # If the stripped list is empty then we're done (no state change)
   strippedList = RemoveRedundantEntriesFromList(cls, mappedList)
   if len(strippedList) == 0:
      return TASK_LIST_RES_OK
   else:
      log.debug('%s GenerateMyTaskList: stripped length %d, full length %d' %
                (str(cls), len(strippedList), len(mappedList)))

   # Avoid requiring a reboot at early boot
   if hostServices.earlyBoot == True:
      addRetVal = TASK_LIST_RES_OK
      if delRetVal != TASK_LIST_RES_OK:
         delRetVal = TASK_LIST_RES_OK
         log.info('%s GenerateMyTaskList: found early boot state to delete ' %
                   str(cls))
         # XXX PR 1247076; comment in this loop for debugging earlyboot issues
         #for modMsg, modData in tmpTaskList:
         #   tasklistOp, esxcliDict = modData
         #   if tasklistOp == PSA_OP_DEL:
         #      log.debug('%s GenerateMyTaskList: found early boot state: %s ' %
         #                (str(cls), str(esxcliDict)))
         #   else:
         #      break

   # Non-empty stripped list, so return stripped list if caller so requested
   if strip:
      retVal = TASK_LIST_RES_OK
      for modMsg, modData in strippedList:
         tasklistOp, esxcliDict = modData
         if tasklistOp == PSA_OP_DEL and rebootOnDelete and not addsOnly:
            retVal = delRetVal
         elif tasklistOp == PSA_OP_ADD and rebootOnAdd and \
              retVal == TASK_LIST_RES_OK:
            retVal = addRetVal
         if tasklistOp == PSA_OP_ADD or not addsOnly:
            if isinstance(taskList, list):
               taskList.append( (modMsg, modData) )
            else:
               taskList.addTask(modMsg, modData)
      return retVal
   else:
      assert not addsOnly, '%s: addsOnly is True but strip is False' % str(cls)
      for modMsg, modData in mappedList:
         if isinstance(taskList, list):
            taskList.append( (modMsg, modData) )
         else:
            taskList.addTask(modMsg, modData)
      if delRetVal == addRetVal:
         return delRetVal
      else:
         return delRetVal if (delRetVal != TASK_LIST_RES_OK) else addRetVal

#
# Helper function for profiles to remediate an arbitrary host configuration
# Each tasklist entry is expected to be an "esxcli dictionary".  See
# GenerateMyTaskList.
#
# General Parameters:
#
#    * cls - the calling class object
#    * taskList, hostServices, config - from the calling profile
#    * deviceProfile - used to downgrade warnings at early boot when not all
#                      devices might be present during profile application
#
def RemediateMyConfig(cls, taskList, hostServices, config, deviceProfile = False):
   """Remediates a config based on a taskList generated by GenerateMyTaskList
   """
   delOk = True
   rebootReqd = False
   for tasklistOp, esxcliDict in taskList:
      if tasklistOp == PSA_OP_DEL:
         if not delOk:
            LogAndRaiseException(cls, PSA_INTERNAL_CODE_KEY,
                                 'tasklist improperly sorted')
         if esxcliDict['DelCmd'] != '':
            status, output = hostServices.ExecuteEsxcli(esxcliDict['Namespace'],
                                                             esxcliDict['App'],
                                                             esxcliDict['DelCmd'],
                                                             esxcliDict['DelOpt'])
         else:
            status = 0
      elif tasklistOp == PSA_OP_ADD:
         delOk = False
         status, output = hostServices.ExecuteEsxcli(esxcliDict['Namespace'],
                                                          esxcliDict['App'],
                                                          esxcliDict['AddCmd'],
                                                          esxcliDict['AddOpt'])
      else:
         LogAndRaiseException(cls, PSA_INTERNAL_CODE_KEY,
                              'unknown tasklist operation')

      # Warn on failure to write host state so we continue past failures.
      # Exception: info on device profile failures at early as we might
      # not yet have discovered the device.  This opens a hole in that
      # we won't warn on the _last_ early boot remediatation when we should
      # but since we'll ware on the postBoot remediation it's OK.
      if status != 0 and \
         (deviceProfile == False or hostServices.earlyBoot == False):
            log.warning('esxcli command %s %s %s %s failed' %               \
                     (esxcliDict['Namespace'], esxcliDict['App'],           \
                      esxcliDict['DelCmd'] if tasklistOp == PSA_OP_DEL else \
                      esxcliDict['AddCmd'],                                 \
                      esxcliDict['DelOpt'] if tasklistOp == PSA_OP_DEL else \
                      esxcliDict['AddOpt']))
      elif esxcliDict['DelCmd'] != '':
         log.info('esxcli command %s %s %s %s %s (%s)' % \
                     (esxcliDict['Namespace'], esxcliDict['App'],              \
                      esxcliDict['DelCmd'] if tasklistOp == PSA_OP_DEL else    \
                      esxcliDict['AddCmd'],                                    \
                      esxcliDict['DelOpt'] if tasklistOp == PSA_OP_DEL else    \
                      esxcliDict['AddOpt'],                                    \
                      'failed' if status != 0 else 'used to remediate config', \
                      'delete operation' if tasklistOp == PSA_OP_DEL else      \
                      'add operation'))
      if hostServices.earlyBoot == False and not deviceProfile:
         # tasklistOp is either PSA_OP_ADD or PSA_OP_DEL.  Don't set reboot
         # required if we have an empty ('') DelCmd.  Note that it will get set
         # for the add operation, if there is one.
         if tasklistOp == PSA_OP_ADD or esxcliDict['DelCmd'] != '':
            rebootReqd = True
   if rebootReqd:
      log.warning('%s: reboot will be required due to remediation' % str(cls))

#
# Helper function for profiles to verify an arbitrary profile
#
# Populating the answerfile for UserInputRequiredOption secondary policies:
# For user input required secondary policy options this populates the answer
# file when the forApply parameter is True (calls from VerifyProfileForApply).
# As noted above, secondaryPolicy supplies a GetPolicyOption method which
# previously instantiated the policy option.  For secondary policies which
# support a UserInputRequiredOption this function is overloaded to optionally
# pull the policy option parameters from the profileDate (aka config in other
# contexts).  We use this during the VerifyProfileForApply() workflow.
#
# General Parameters:
#
#    * cls - the calling class object
#    * profileInstance, hostServices, profileData, - from the calling profile
#    * validationErrors - possibly non-empty list to which we append new errors
#    * forApply - boolean that distinguishes calls from VerifyProfileForApply()
#
def VerifyMyProfilesPolicies(cls, profileInstance, hostServices, profileData,
                             validationErrors, forApply = False):
   """A verifier for the policies of arbitrary profiles
   """
   retStatus = True
   status = True

   # Get the policy options
   policyOpt = profileInstance.policies[0].policyOption
   if len(profileInstance.policies) > 1:
      assert len(profileInstance.policies) == 2, \
             'Max 2 policies supported by VerifyMyProfilesPolicies'
      secondaryPolicyOpt = profileInstance.policies[1].policyOption
   else:
      secondaryPolicyOpt = None

   # Validate the policy options; bail at first error
   if hasattr(policyOpt, 'PolicyOptValidator'):
      status, output = policyOpt.PolicyOptValidator(hostServices,
                                                    secondaryPolicyOpt)
   if status == True and secondaryPolicyOpt is not None:
      if hasattr(secondaryPolicyOpt, 'PolicyOptValidator'):
         if forApply and \
            isinstance(secondaryPolicyOpt, UserInputRequiredOption):
            secondaryPolicy = profileInstance.policies[1]
            assert hasattr(secondaryPolicy, 'GetPolicyOption'),           \
                   'SecondaryPolicy %s lacks required GetPolicyOption ' % \
                   'attribute' % str(secondaryPolicy)
            # there are cases when more than 1 profileData is passed -
            # eg: when there are 2 'device' type SATP claimrules
            for data in profileData:
               secondaryPolicyOptParams = \
                      secondaryPolicy.GetPolicyOption(data, True)
               log.info('SecondaryPolicyOptParam found %s',
                         str(secondaryPolicyOptParams))
               status, output = secondaryPolicyOpt.PolicyOptValidator(hostServices,
                                                   secondaryPolicyOptParams)
               # Report any validation errors
               if status is not True:
                  retStatus = False
                  assert output is not None,                                                 \
                      'Policy opt validation failed for policy %s, policy option %s%s%s, '\
                      'but no failure message returned. Make sure that the policy opt '   \
                      'validator passes the correct error key while logging the error' %  \
                      (profileInstance.policies[0], policyOpt,
                      " and " if secondaryPolicyOpt is not None else "",
                      secondaryPolicyOpt if secondaryPolicyOpt is not None else "")
                  if isinstance(output, list):
                     validationErrors.append(output[0])
                  else:
                     validationErrors.append(output)
            return retStatus
         else:
            secondaryPolicyOptParams = None
            # secondaryPolicyOptParams always None for FixedPolicyOption policy opt
            status, output = secondaryPolicyOpt.PolicyOptValidator(hostServices,
                                                   secondaryPolicyOptParams)
      else:
         assert not isinstance(secondaryPolicyOpt, UserInputRequiredOption),   \
                    'UserInputRequiredOption policy option %s lacks required ' \
                    'PolicyOptValidator attribute' % str(secondaryPolicyOpt)

   # Report any validation errors
   if status is not True:
      retStatus = False
      assert output is not None,                                                 \
             'Policy opt validation failed for policy %s, policy option %s%s%s, '\
             'but no failure message returned. Make sure that the policy opt '   \
             'validator passes the correct error key while logging the error' %  \
             (profileInstance.policies[0], policyOpt,
             " and " if secondaryPolicyOpt is not None else "",
             secondaryPolicyOpt if secondaryPolicyOpt is not None else "")
      if isinstance(output, list):
         validationErrors.append(output[0])
      else:
         validationErrors.append(output)

   return retStatus

#
# Helper function for CheckMyCompliance
#
# searchMeList - esxcliDict to search
# key, value - the key:value that are to be matched
#
# Returns a list of entries from searchMeList
# that match key:value
#
def FindMatchingTaskDict(key, value, searchMeList):
   # Typically, 0 or 1 match will be found.
   # >1 matches possible for SatpClaimrulesProfile
   find = [x for x in searchMeList if x[key] == value]
   return find

#
# Helper function for profiles to check their compliance
#
# General Parameters:
#
#    * cls - the calling class object
#    * profileInstance, hostServices, profileData, translateFunc - from the calling profile
#    * validationErrors - possibly non-empty list to which we append new errors
#
def CheckMyCompliance(cls, profileInstances, hostServices, profileData, parent,
                      msgKeyDict, translateFunc = None, esxcliDictParam = None):
   """A compliance checker for arbitrary profiles
   """
   # store the profile name for use later
   msgDict = {}
   msgDict['Profile'] = cls.__name__

   strippedList = []
   retVal = GenerateMyTaskList(cls, profileInstances, strippedList,
                               hostServices, profileData, parent,
                               translateFunc, esxcliDictParam)

   # If the strippedList is empty then we are compliant, otherwise not
   ccFailures = []
   if not strippedList:
      return (True, ccFailures)

   # Every caller must pass a valid msgKeyDict
   msgKeyProfNotFound = msgKeyDict['ProfNotFound']
   msgKeyParamMismatch = msgKeyDict['ParamMismatch']
   msgKeyPolicyMismatch = msgKeyDict['PolicyMismatch']
   msgKeyBase = msgKeyDict['KeyBase']

   addList = []
   delList = []
   for modMsg, modData in strippedList:
      taskop, esxcliDict = modData
      if taskop == PSA_OP_ADD:
         addList.append(esxcliDict['ParamDict'])
      else:
         delList.append(esxcliDict['ParamDict'])

   for addDict in addList:
      ccValues = []
      if 'ComparisonKey' in addDict:
         keyToCheck =  addDict['ComparisonKey']
         assert keyToCheck in addDict, \
                'Could not find key %s in addDict' % keyToCheck

         matchingDel = FindMatchingTaskDict(keyToCheck, addDict[keyToCheck], delList)

         # no matching delete - missing profile instance on host
         if not matchingDel:
            mesgCode = addDict.get('messageCode', msgKeyProfNotFound)
            mesgDict = addDict.get('messageDict', msgDict)
            comparisonIdentifier = addDict.get('comparisonIdentifier', keyToCheck)
            profileValue = addDict.get('profileValue', addDict[keyToCheck])
            profileInstance = addDict.get('profileInstance', cls.__name__)
            ccfailMsg = MakeLocalizedMessage(cls, mesgCode, mesgDict)
            cc = CreateComplianceFailureValues(comparisonIdentifier, PARAM_NAME,
                    profileValue = profileValue,
                    hostValue = '',
                    profileInstance = profileInstance)
            ccValues.append(cc)
         else:
            mDelDict = matchingDel[0]

            # first check if they are of the same secondary policy option type
            if ((('SecPolicyOptType' in addDict) ^
                   ('SecPolicyOptType' in mDelDict)) or
                   ('SecPolicyOptType' in addDict and
                    addDict['SecPolicyOptType'] != mDelDict['SecPolicyOptType'])):
               ccfailMsg = MakeLocalizedMessage(cls, msgKeyPolicyMismatch, msgDict)
               cc =  CreateComplianceFailureValues(addDict['SecPolicy'], POLICY_NAME,
                                                   profileValue = addDict['SecPolicyOptType'],
                                                   hostValue = mDelDict['SecPolicyOptType'],
                                                   profileInstance = str(addDict[keyToCheck]))
               ccValues.append(cc)
            else:
               # All policies same, now match all param values
               for k, v in list(mDelDict.items()):
                  if v != addDict[k]:
                     log.info('Parameter %s does not match host:%s profile:%s' % (k, v, addDict[k]))
                     cc = CreateComplianceFailureValues(k, PARAM_NAME,
                                    profileValue = addDict[k], hostValue = v,
                                    profileInstance = str(addDict[keyToCheck]))
                     ccValues.append(cc)
               ccfailMsg = MakeLocalizedMessage(cls, msgKeyParamMismatch, msgDict)

            #remove this entry from delList so we don't hit it in the next loop
            delList.remove(mDelDict)
         # add to the list of failures
         ccFailures.append((ccfailMsg, ccValues))
      else:
         # In a profile that doesn't support Compliance FailureValue obj
         assert False, 'Profile does not support ComplianceFailureValue obj'

   # Loop through any left over instances from the host
   for delDict in delList:
      if 'ComparisonKey' in delDict:
         keyToCheck =  delDict['ComparisonKey']
         assert keyToCheck in delDict, \
                'Could not find key %s in addDict' % keyToCheck
         log.info('Did not find %s: %s in profile' % (keyToCheck, delDict[keyToCheck]))

         mesgCode = delDict.get('messageCode', msgKeyProfNotFound)
         mesgDict = delDict.get('messageDict', msgDict)
         comparisonIdentifier = delDict.get('comparisonIdentifier', keyToCheck)
         hostValue = delDict.get('hostValue', delDict[keyToCheck])
         profileInstance = delDict.get('profileInstance', cls.__name__)

         cc = CreateComplianceFailureValues(comparisonIdentifier, PARAM_NAME,
                 profileValue = '',
                 hostValue = hostValue,
                 profileInstance = profileInstance)
         ccfailMsg = CreateLocalizedMessage(cls, mesgCode, mesgDict)

         ccFailures.append((ccfailMsg, [cc]))
      else:
         # in a profile that doesn't support Compliance FailureValue obj
         assert False, 'Profile %s does not support ComplianceFailureValue obj' % \
                        msgDict['Profile']


   if hostServices.earlyBoot == True:
      log.warning('%s CheckMyCompliance: found %s early boot state: %s ' %
               (str(cls), 'no ' if not len(ccFailures) else '', str(ccFailures)))

   return (len(ccFailures) == 0, ccFailures)

#
# Helper function for user input required profiles to update a param from the
# the answer file
#
# Update the policy param with the new value if current value is None or empty
#
# Returns:
#  True if set
#  False if not
#
def PsaUpdatePolicyOptParam(policyOptObj, name, value):
   assert hasattr(policyOptObj, name), 'policyOptObj must have %s attribute' % name

   oldValue = getattr(policyOptObj, name)
   if oldValue == None or \
      (isinstance(oldValue, str) and len(oldValue) == 0):

      # Set the value in the attribute and return True
      setattr(policyOptObj, name, value)
      return True

   # Nothing to update so return False
   return False

#
# Common Validation Functions
#
class AdapterTargetIdValidator():
   """A validator for PSA adapter Ids
   """
   @classmethod
   def Validate(cls, policyOpt, hostServices, deviceName):
      """For existing profiles validates that the provided PSA adapter and
         target IDs are valid and present on the host.  For extracted profiles
         (indicated by empty strings) populates them from the host iff the
         device uses VMW_PSP_FIXED with a configured preferred path.  The
         deviceName param is a don't care for existing profiles.
      """
      if (policyOpt.adapterId == '' and policyOpt.targetId != '') or \
         (policyOpt.adapterId != '' and policyOpt.targetId == ''):
         return LogAndReturnError(cls,
                   PSA_ADAPTER_TARGET_BOTH_EMPTY_OR_NON_EMPTY_KEY)

      #if adapterId, targetId are not '' then validate them against host paths
      if policyOpt.adapterId != '':
         #Get all the paths on the host
         cliNs, cliApp, cliCmd = 'storage core', 'path', 'list'
         status, output = hostServices.ExecuteEsxcli(cliNs, cliApp, cliCmd)
         if status != 0:
            LogAndRaiseException(cls, PSA_ESXCLI_CMD_FAILED_KEY, output)

         #Find first match (don't care about multiple matches, just validity)
         foundAdapter = False
         foundTarget = False
         for path in output:
            if path['Adapter Identifier'] == policyOpt.adapterId:
               foundAdapter = True
               if foundTarget:
                  break
            if path['Target Identifier'] == policyOpt.targetId:
               foundTarget = True
               if foundAdapter:
                  break

         #status, failure = (False, [ '' ])
         if not foundAdapter:
            #defer returning this failure in case we also didn't find the target
            status, failure = LogAndReturnError(cls,
                                                PSA_PARAM_NOT_FOUND_KEY,
                                                {'Param': policyOpt.adapterId,
                                                 'By': 'esxcli'})
         if not foundTarget:
            return LogAndReturnError(cls, PSA_PARAM_NOT_FOUND_KEY,
                                     {'Param': policyOpt.targetId,
                                      'By': 'esxcli'})
         if not foundAdapter:
            return (status, failure)

      else:
         if deviceName is None:
            return LogAndReturnError(cls, PSA_INVALID_PARAM_KEY,
                      'bad host profiles workflow: deviceName is None')
         #Get the fixed PSP device configuration for this device
         cliNs, cliApp, cliCmd = 'storage nmp', 'psp fixed deviceconfig', 'get'
         cliOpt = '--device=%s' % deviceName
         status, output = hostServices.ExecuteEsxcli(cliNs, cliApp,
                                                     cliCmd, cliOpt)
         if status != 0:
            LogAndRaiseException(cls, PSA_ESXCLI_CMD_FAILED_KEY, output)
         assert isinstance(output, dict),                                 \
            '%s: esxcli %s %s %s %s did not return a dict, returned %s' % \
            (str(cls), cliNs, cliApp, cliCmd, cliOpt, output)

         configuredPath = output['Configured Preferred Path']
         # Only perform the check if a preferred path is specified.
         if configuredPath:
            split = 0
            if configuredPath.count('-') == 2:
               policyOpt.adapterId, policyOpt.targetId, device = configuredPath.split('-')
               split = 1
            elif configuredPath.count('-') > 2:
               # iscsi paths can have more than 2 hyphens as hyphens may be
               # included in iscsi initiator and target iqn's
               # Below assumptions are made for splitting iscsi path:
               #  [adapter id] = [adapter iqn]
               #  [target id] = [isid],[target iqn],t,[target portal group]
               #  isid(iscsi session id) is 6 char long printed in hex
               #  [target portal group] is unsigned 32 bit
               #  No hyphens in device uid.
               #
               # adapterId = string before the match of "-" + 12 hex + ","
               # targetId = string after adapterId before last "-"
   
               match = re.search('-[0-9a-fA-F]{12},',configuredPath)
               if match:
                  targetIndex = match.start()+1
                  deviceIndex = configuredPath.rindex("-")+1
   
                  policyOpt.adapterId = configuredPath[:targetIndex-1]
                  policyOpt.targetId = configuredPath[targetIndex:deviceIndex-1]
                  device = configuredPath[deviceIndex:]
                  split = 1
   
            if split == 0 or device != deviceName:
               return LogAndReturnError(cls, PSA_INVALID_PATH_KEY,
                        {'Path': configuredPath})

      return (True, [])

#
# Common Policy Options
#
# Note that these are not primary policy options and thus do not have a
# GetEsxcliDict instance method, but instead they have a GetEsxcliOptionString
# instance method used by several of the above common functions.
#
# Device
#
class DevicePolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for the Device policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the PSA device described by the policy option exists.
      """
      #Validate deviceName
      cliNs, cliApp, cliCmd, cliOpt = 'storage core', 'device', 'list', '--exclude-offline'
      status, output = hostServices.ExecuteEsxcli(cliNs, cliApp, cliCmd, cliOpt)
      # Raise exception on failure to read host state (should always succeed)
      if status != 0:
         LogAndRaiseException(cls, PSA_ESXCLI_CMD_FAILED_KEY, output)
      status = 1
      for device in output:
         if device['Device'] == policyOpt.deviceName:
            status = 0
            break
      if status != 0:
         return LogAndReturnError(policyOpt, PSA_PARAM_NOT_FOUND_KEY,
                                  {'Param': policyOpt.deviceName,
                                   'By': 'esxcli'})
      return (True, [])

class DevicePolicyOption(FixedPolicyOption):
   """Policy Option type specifying a device for a PSA or NMP SATP claimrule.
   """
   paramMeta = [
      ParameterMetadata('deviceName', 'string', False)]

   complianceChecker = DevicePolicyOptComplianceChecker

   # esxcli options needed to add this policy option to the host
   # set noTypeParam to True to suppress "--type=device"
   def GetEsxcliOptionString(self, noTypeParam):
      if noTypeParam:
         optStr = ''
      else:
         optStr = '--type=device '
      optStr += '--device="%s"' % self.deviceName
      return optStr

   # device name
   def GetEsxcliDictDevice(self, _notUsed):
      return self.deviceName

#
# Driver
#
class DriverPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for Driver policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the PSA driver described by the policy option exists.
      """
      #XXX PR 1246241: validate driverName against host state?

      return (True, [])

class DriverPolicyOption(FixedPolicyOption):
   """Policy Option type specifying a driver for a PSA or NMP SATP claimrule.
   """
   paramMeta = [
      ParameterMetadata('driverName', 'string', False)]

   complianceChecker = DriverPolicyOptComplianceChecker

   # esxcli options needed to add this policy option to the host
   def GetEsxcliOptionString(self, _notUsed):
      optStr = '--type=driver --driver="%s"' % self.driverName
      return optStr

#
# Transport
#
class TransportPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for PSA Transport policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the PSA transport described by the policy option exists.
      """
      #XXX PR 1246241: validate transport against host state?

      return (True, [])

class TransportPolicyOption(FixedPolicyOption):
   """Policy Option type specifying a transport type for a PSA or NMP SATP
      claimrule.
   """
   paramMeta = [
      ParameterMetadata('transportName', 'string', False)]

   complianceChecker = TransportPolicyOptComplianceChecker

   # esxcli options needed to add this policy option to the host
   def GetEsxcliOptionString(self, _notUsed):
      optStr = '--type=transport --transport="%s"' % self.transportName
      return optStr

#
# Vendor-Model
#
class VendorModelPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for PSA VendorModel policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the PSA vendor and model parameters of the policy
         option are not both empty
      """
      #Firstly, validate the policy option
      status, output = policyOpt.PolicyOptValidator(hostServices)
      if status != True:
         return (status, output)

      #XXX PR 1246241: validate vendor/model against host state?

      return (True, [])

class VendorModelPolicyOption(FixedPolicyOption):
   """Policy Option type specifying a vendor and model for a PSA or NMP SATP
      claimrule.
   """
   paramMeta = [
      ParameterMetadata('vendorName', 'string', True),
      ParameterMetadata('model', 'string', True)]

   complianceChecker = VendorModelPolicyOptComplianceChecker

   # Ensure that at least one parameter is specified; checked by
   # VerifyProfile() and CheckPolicyCompliance().
   def PolicyOptValidator(self, hostServices, _notUsed = None):
      assert _notUsed is None, \
             '%s: _notUsed param %s expected None' % (str(self), str(_notUsed))
      if (self.vendorName is None or self.vendorName == '') and \
         (self.model is None or self.model == ''):
         return LogAndReturnError(self, PSA_VENDOR_MODEL_NOT_BOTH_NULL_KEY)
      else:
         return (True, [])

   # esxcli options needed to add this policy option to the host
   def GetEsxcliOptionString(self, vmStar):
      optStr = '--type=vendor'
      # PR 610145: For PSA claimrules esxcli turns optional params into *,
      # so do so also to avoid spurious compliance failures
      if self.vendorName is not None and self.vendorName != '':
         optStr += ' --vendor="%s"' % self.vendorName
      elif vmStar:
         optStr += ' --vendor="%s"' % '*'
      if self.model is not None and self.model != '':
         optStr += ' --model="%s"' % self.model
      elif vmStar:
         optStr += ' --model="%s"' % '*'
      return optStr

#
# User Input Device
#
class UserInputDevicePolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for the Device policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the PSA device described by the policy option exists.
      """
      #Firstly, validate the policy option
      status, output = policyOpt.PolicyOptValidator(hostServices)
      if status != True:
         return (status, output)

      #Validate deviceName
      cliNs, cliApp, cliCmd, cliOpt = 'storage core', 'device', 'list', '--exclude-offline'
      status, output = hostServices.ExecuteEsxcli(cliNs, cliApp, cliCmd, cliOpt)
      # Raise exception on failure to read host state (should always succeed)
      if status != 0:
         LogAndRaiseException(cls, PSA_ESXCLI_CMD_FAILED_KEY, output)
      status = 1
      for device in output:
         if device['Device'] == policyOpt.deviceName:
            status = 0
            break
      if status != 0:
         return LogAndReturnError(policyOpt, PSA_PARAM_NOT_FOUND_KEY,
                                  {'Param': policyOpt.deviceName,
                                   'By': 'esxcli'})
      return (True, [])

class UserInputDevicePolicyOption(UserInputRequiredOption):
   """Policy Option type specifying a user input required device for an NMP SATP claimrule.
   """
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('deviceName', 'string', False, '') ]

   complianceChecker = UserInputDevicePolicyOptComplianceChecker

   # esxcli options needed to add this policy option to the host
   # set noTypeParam to True to suppress "--type=device"
   def GetEsxcliOptionString(self, noTypeParam):
      if noTypeParam:
         optStr = ''
      else:
         optStr = '--type=device '
      optStr += '--device="%s"' % self.deviceName
      return optStr

   # device name XXX
   def GetEsxcliDictDevice(self, _notUsed):
      return self.deviceName

   def PolicyOptValidator(self, hostServices, params = None):

      # If the deviceName is not in answer file, during VerifyProfileForApply
      # operation we propagate the deviceName from the profileData back to the
      # answer file.  We don't know the esxcli syntax to get the data from the
      # host because we don't know what the containing profile is, so this is
      # passed in to us via params as a list of tuples in "params", but only if
      # we are called from VerifyProfileForApply.  In contrast during
      # VerifyProfile operation we won't have answer file data and the "params"
      # tuple will be None so we can only unconditionally succeed in that case
      # because without the answer file there's nothing to validate.

      if params is not None:
         assert len(params) == 1 and params[0][0] == 'deviceName',            \
            '%s: user input param name must be "deviceName", received "%s"' % \
            (str(self), params[0][0])

         status = PsaUpdatePolicyOptParam(self, 'deviceName', params[0][1])

         log.info('Data for field %s %s in answer file' %
                  ('deviceName', 'populated' if status else 'found'))

         # Fail if the field is not populated
         if (self.deviceName is None or self.deviceName == ''):
            return LogAndReturnError(self, PSA_PARAM_NOT_PRESENT_KEY,
                      {'ParamName': 'deviceName',
                       'Where': 'in answer file' if params is None else 'on host'})
      return (True, [])
