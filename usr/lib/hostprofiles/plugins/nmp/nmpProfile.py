#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import GenericProfile, Policy, FixedPolicyOption, \
                      UserInputRequiredOption, ParameterMetadata, log, \
                      PolicyOptComplianceChecker, ProfileComplianceChecker, \
                      TASK_LIST_REQ_MAINT_MODE, TASK_LIST_REQ_REBOOT, \
                      TASK_LIST_RES_OK

from pluginApi import CATEGORY_STORAGE, COMPONENT_CORE_STORAGE

from pyEngine.storageprofile import StorageProfile

from pyEngine.nodeputil import RangeValidator

import re

from psa.common import *

from psa.psaProfile import PsaBootDeviceProfile, PsaDeviceSharingProfile

#
# Declare NMP specific keys needed for task lists and compliance checking
#
NMP_BASE = 'com.vmware.profile.plugins.nmp'
NMP_PROFILE_BASE = 'com.vmware.vim.profile.Profile.nmp.nmpProfile'
NMP_OP_ADD = 'NmpAdd'
NMP_OP_DEL = 'NmpDel'
NMP_ADD_KEY = '%s.%s' % (NMP_BASE, NMP_OP_ADD)
NMP_DEL_KEY = '%s.%s' % (NMP_BASE, NMP_OP_DEL)

NMP_ADD_DEFAULT_PSP_KEY = '%s%s' % (NMP_ADD_KEY, 'DefaultPsp')
NMP_DEL_DEFAULT_PSP_KEY = '%s%s' % (NMP_DEL_KEY, 'DefaultPsp')
NMP_ADD_PATH_KEY = '%s%s' % (NMP_ADD_KEY, 'Path')
NMP_DEL_PATH_KEY = '%s%s' % (NMP_DEL_KEY, 'Path')
NMP_ADD_PSP_ASSIGNMENT_KEY = '%s%s' % (NMP_ADD_KEY, 'PspAssignment')
NMP_DEL_PSP_ASSIGNMENT_KEY = '%s%s' % (NMP_DEL_KEY, 'PspAssignment')
NMP_ADD_ROUND_ROBIN_KEY = '%s%s' % (NMP_ADD_KEY, 'RoundRobin')
NMP_DEL_ROUND_ROBIN_KEY = '%s%s' % (NMP_DEL_KEY, 'RoundRobin')
NMP_ADD_SATP_CLAIMRULE_KEY = '%s%s' % (NMP_ADD_KEY, 'SatpClaimrule')
NMP_DEL_SATP_CLAIMRULE_KEY = '%s%s' % (NMP_DEL_KEY, 'SatpClaimrule')
NMP_ADD_DEVICE_CONFIG_KEY = '%s%s' % (NMP_ADD_KEY, 'DeviceConfig')
NMP_DEL_DEVICE_CONFIG_KEY = '%s%s' % (NMP_DEL_KEY, 'DeviceConfig')
NMP_PROFILE_NOT_FOUND_KEY = '%s.%s' % (NMP_BASE, 'NmpProfileNotFound')
NMP_PROFILE_PARAM_MISMATCH_KEY = '%s.%s' % (NMP_BASE, 'NmpProfileParamMismatch')
NMP_PROFILE_POLICY_MISMATCH_KEY = '%s.%s' % (NMP_BASE, 'NmpProfilePolicyMismatch')

#
# Global compliance checker for NMP profiles
#
class NmpProfileComplianceChecker(ProfileComplianceChecker):
   """A compliance checker type for NMP and SATP profiles
   """
   def __init__(self, profileClass, esxcliDictParam = None, translateFunc = None):
      self.profileClass = profileClass
      self.translateFunc = translateFunc
      self.esxcliDictParam = esxcliDictParam

   def CheckProfileCompliance(self, profileInsts, hostServices, profileData,
                              parent):
      """Checks whether the NMP configuration described by the profiles
         and their policies and policy option parameters exists and matches
         what is on the host.
      """
      msgKeyDict = {'ProfNotFound' : NMP_PROFILE_NOT_FOUND_KEY,
                    'ParamMismatch' : NMP_PROFILE_PARAM_MISMATCH_KEY,
                    'PolicyMismatch' : NMP_PROFILE_POLICY_MISMATCH_KEY,
                    'KeyBase' : NMP_PROFILE_BASE}
      return CheckMyCompliance(self.profileClass, profileInsts, hostServices,
                               profileData, parent, msgKeyDict,
                               self.translateFunc, self.esxcliDictParam)


#
# Policy options and compliance checkers (one checker per policy option)
#
# Helper function for Compliance checking (validates satpName against host)
#
def ValidateSatp(cls, hostServices, satpName):
   """Validate SATP name against host.
   """
   cliNs, cliApp, cliCmd = 'storage nmp', 'satp', 'list'
   status, output = hostServices.ExecuteEsxcli(cliNs, cliApp, cliCmd)
   # Raise exception on failure to read host state (should always succeed)
   if status != 0:
      LogAndRaiseException(cls, PSA_ESXCLI_CMD_FAILED_KEY, output)
   status = 1
   for satp in output:
      if satp['Name'] == satpName:
         status = 0
         break
   if status != 0:
      return LogAndReturnError(cls, PSA_PARAM_NOT_FOUND_KEY,
                               {'Param': satpName, 'By': 'esxcli'})
   else:
      return (True, [])

#
# Policy option for the Device PSP Assignment policy
#
class DevicePspAssignmentPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for the Device PSP Assignment policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the PSP assignment described by the policy
         option is valid and matches what's on the host
      """

      return (True, [])

class DevicePspAssignmentPolicyOption(FixedPolicyOption):
   """Policy Option type containing PSP assignment for an NMP device.
   """
   paramMeta = [
      ParameterMetadata('deviceName', 'string', False),
      ParameterMetadata('pspName', 'string', False)]

   complianceChecker = DevicePspAssignmentPolicyOptComplianceChecker

   def GetComparisonKey(self):
      return 'deviceName'

   # esxcli options needed to add or delete this policy option to/from the host
   def GetEsxcliDict(self, _notUsed):
      assert _notUsed is None, \
             '%s: _notUsed param %s expected None' % (str(self), str(_notUsed))
      addOptStr = '--device="%s" --psp="%s"' % (self.deviceName, self.pspName)
      delOptStr = '--device="%s" --default' % self.deviceName

      addMsgDict = {'Device': self.deviceName, 'Psp': self.pspName}
      delMsgDict = {'Device': self.deviceName}
      messageDict = MakeMessageDict(NMP_ADD_PSP_ASSIGNMENT_KEY,
                                    NMP_DEL_PSP_ASSIGNMENT_KEY,
                                    addMsgDict, delMsgDict)

      return MakeEsxcliDict('storage nmp', 'device', 'set', 'set',
                addOptStr, delOptStr, messageDict, dictDevice = self.deviceName)

   # Optionally pre-process input dictionaries from GenerateMyProfileFromConfig
   def __init__(self, inputParam):
      if isinstance(inputParam, dict):
         paramList = [ ('deviceName', inputParam['Device']),
                       ('pspName', inputParam['Path Selection Policy']) ]
      elif isinstance(inputParam, list):
         paramList = inputParam
      else:
         assert False,                                                     \
                '%s: __init__ inputParam must be a dictionary or a list' % \
                str(self)

      FixedPolicyOption.__init__(self, paramList)

#
# Policy option for the Device PSP Configuration policy
#
class DeviceConfigurationPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for the Device Configuration policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the device configuration described by the policy
         option is valid and matches what's on the host
      """

      return (True, [])

class DeviceConfigurationPolicyOption(FixedPolicyOption):
   """Policy Option type containing configuration for an NMP SATP device.
   """
   # XXX todo: Add a custom validator for configInfo parameter?
   paramMeta = [
      ParameterMetadata('deviceName', 'string', False),
      ParameterMetadata('configInfo', 'string', True)]

   complianceChecker = DeviceConfigurationPolicyOptComplianceChecker

   def GetComparisonKey(self):
      return 'deviceName'

   # esxcli options needed to add or delete this policy option to/from the host
   def GetEsxcliDict(self, application):
      assert application == 'psp' or application == 'satp',                \
             '%s: application param is "%s", expected "psp" or "satp"' %   \
             (str(self), type)
      addOptStr = delOptStr = '--device=%s --config' % self.deviceName
      if self.configInfo is not None and self.configInfo != '':
         addOptStr += '="%s"' % self.configInfo
      if application == 'psp':
         addOptStr += "-g"
         delOptStr += "-g"

      addMsgDict = delMsgDict = {'Application': application.upper(),
         'Device': self.deviceName,
         'Config': self.configInfo if self.configInfo is not None else ''}
      messageDict = MakeMessageDict(NMP_ADD_DEVICE_CONFIG_KEY,
                                    NMP_DEL_DEVICE_CONFIG_KEY,
                                    addMsgDict, delMsgDict)

      esxcliApplication = '%s generic deviceconfig' % application
      return MakeEsxcliDict('storage nmp', esxcliApplication, 'set', 'set',
                addOptStr, delOptStr, messageDict, dictDevice = self.deviceName)

   # Removing TPG info from SATP config strings (from profile instances extracted
   # from a 55U2 or earlier host) and appending action_OnRetryErrors config option
   # for ALUA SATPs.
   def adjustPolicyOpt(self):
      configStr = self.configInfo
      tpgPos = configStr.find('TPG')
      configStr = configStr[:tpgPos-1] if tpgPos != -1 else configStr
      if ('on' in configStr or 'off' in configStr) and \
         'action_OnRetryErrors' not in configStr:
         configStr += ' action_OnRetryErrors=off' if configStr[-1] == ';' \
                      else '; action_OnRetryErrors=off'
      self.configInfo = configStr

   # Optionally pre-process input dictionaries from GenerateMyProfileFromConfig
   def __init__(self, inputParam):
      # Both the host config and the profile config strings are adjusted to ensure
      # backward compatibility. SATP_ALUA_CX puts a ',' between some config options,
      # so ',' is also removed. The adjusted strings have config options separated by
      # '; '.
      if isinstance(inputParam, dict):
         configInfo = inputParam['Get']
         configOpts = re.split(';|,|{|}', configInfo)
         configOpts = [item.strip() for item in configOpts if item.strip()]
         configInfo = '; '.join(configOpts)
         paramList = [ ('deviceName', inputParam['Device']),
                       ('configInfo', configInfo) ]
      elif isinstance(inputParam, list):
         paramList = []
         for (name, value) in inputParam:
            if name == 'configInfo' and value is not None:
               configOpts = re.split(';|,|{|}', value)
               configOpts = [item.strip() for item in configOpts if item.strip()]
               value = '; '.join(configOpts)
            paramList.append((name, value))
      else:
         assert False,                                                     \
                '%s: __init__ inputParam must be a dictionary or a list' % \
                str(self)

      FixedPolicyOption.__init__(self, paramList)

#
# Policy option for the Device Preferred Path policy
#
class PathPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for the Path policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):

      return (True, [])

class PathPolicyOption(UserInputRequiredOption):
   """Policy Option type containing path configuration for an NMP device.
   """
   paramMeta = [
             ParameterMetadata('device', 'string', True, hidden=True)]
   userInputParamMeta = [
      ParameterMetadata('adapterId', 'string', False, ''),
      ParameterMetadata('targetId', 'string', False, '') ]

   complianceChecker = PathPolicyOptComplianceChecker

   # Validate adapterId and targetId against host
   # If we are called during the "apply workflow" (includes "esxhpcli gaf")
   # and the adapterId and targetId params are '' then typePolicyOpt must
   # not be None.  Otherwise typePolicyOpt is a don't care and thus optional.
   def PolicyOptValidator(self, hostServices, typePolicyOpt = None):
      assert self.adapterId is not None and self.targetId is not None,  \
             '%s: adapterId param %s and/or targetId param %s are None' \
             % (str(self), self.adapterId, self.targetId)

      status, output = AdapterTargetIdValidator.Validate(self, hostServices,
                 None if typePolicyOpt is None else typePolicyOpt.deviceName)
      if status != True:
         return (status, output)

      return (True, [])

   def GetComparisonKey(self):
      return 'device'

   # esxcli options needed to add or delete this policy option to/from the host
   def GetEsxcliDict(self, typePolicyOpt):
      assert isinstance(typePolicyOpt, DevicePolicyOption),             \
             '%s: typePolicyOpt param %s expected DevicePolicyOption' % \
             (str(self), str(typePolicyOpt))
      addOptStr = '-g --path="%s-%s-%s" ' % \
                  (self.adapterId, self.targetId, typePolicyOpt.deviceName)
      delOptStr = '-g --default '

      addMsgDict = {'Adapter': self.adapterId, 'Target': self.targetId,
                    'Device': typePolicyOpt.deviceName}
      delMsgDict = {'Device': typePolicyOpt.deviceName}
      messageDict = MakeMessageDict(NMP_ADD_PATH_KEY,
                                    NMP_DEL_PATH_KEY,
                                    addMsgDict, delMsgDict)
      # overloading GetEsxcliDict for backward compatibility
      if self.device == '':
         self.device = typePolicyOpt.deviceName

      return MakeEsxcliDict('storage nmp', 'psp fixed deviceconfig', 'set',
                            'set', addOptStr, delOptStr, messageDict,
                            typePolicyOpt, typePolicyOpt, True)

   # Optionally pre-process input dictionaries from GenerateMyProfileFromConfig
   def __init__(self, inputParam):
      if isinstance(inputParam, dict):
         configuredPath = inputParam['Configured Preferred Path']
         device  = inputParam['Device']
         split = 0
         if configuredPath == '':
            adapterId = targetId = configuredPath
            split = 1
         elif configuredPath.count('-') == 2:
            adapterId, targetId, deviceName = configuredPath.split('-')
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

               adapterId = configuredPath[:targetIndex-1]
               targetId = configuredPath[targetIndex:deviceIndex-1]
               deviceName = configuredPath[deviceIndex:]
               split = 1

         if split == 0:
            assert False,                                            \
                   '%s: Unrecognized Fixed PSP configured path %s' % \
                   (str(cls), configuredPath)
            adapterId = targetId = configuredPath = ''

         paramList = [ ('adapterId', adapterId),
                       ('targetId', targetId),
                       ('device', device) ]
      elif isinstance(inputParam, list):
         paramList = inputParam
         # for backward compatibility
         paramNames = {name for (name, val) in inputParam}
         if 'device' not in paramNames:
            paramList.append(('device', ''))
      else:
         assert False,                                                     \
                '%s: __init__ inputParam must be a dictionary or a list' % \
                str(self)

      UserInputRequiredOption.__init__(self, paramList)

#
# Policy options for the Round-Robin Configuration policy
#
class RoundRobinDevicePolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for the Round-Robin policy options.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the device configuration described by the policy
         option is valid and matches what's on the host
      """

      return (True, [])

class RoundRobinDevicePolicyOption(FixedPolicyOption):
   """Policy Option type containing configuration parameters for round-robin
      PSP.
   """
   paramMeta = [
      ParameterMetadata('deviceName', 'string', False),
      ParameterMetadata('useActiveUnoptimizedPaths', 'bool', True)]

   complianceChecker = RoundRobinDevicePolicyOptComplianceChecker

   def GetComparisonKey(self):
      return 'deviceName'

   # esxcli options needed to add or delete this policy option to/from the host
   def GetEsxcliDict(self, typePolicyOpt):
      assert typePolicyOpt is not None, \
             '%s: typePolicyOpt param is None expected not None' % str(self)
      addOptStr = '-g --device="%s" --useano="%s"' % \
                  (self.deviceName, str(self.useActiveUnoptimizedPaths).lower())
      delOptStr = '-g --device="%s" --useano=false' % self.deviceName

      addMsgDict = {'Device': self.deviceName,
                    'Policy': str(typePolicyOpt),
                    'Ano': 'on' if self.useActiveUnoptimizedPaths else 'off'}
      delMsgDict = {'Device': self.deviceName,
                    'Default': 'EqualizeLoadDefaultPolicyOption'}
      messageDict = MakeMessageDict(NMP_ADD_ROUND_ROBIN_KEY,
                                    NMP_DEL_ROUND_ROBIN_KEY,
                                    addMsgDict, delMsgDict)

      return MakeEsxcliDict('storage nmp', 'psp roundrobin deviceconfig', 'set',
                            'set', addOptStr, delOptStr, messageDict,
                            typePolicyOpt, EqualizeLoadDefaultPolicyOption,
                            dictDevice = self.deviceName)

   # Optionally pre-process input dictionaries from GenerateMyProfileFromConfig
   def __init__(self, inputParam):
      if isinstance(inputParam, dict):
         paramList = [ ('deviceName', inputParam['Device']),
                       ('useActiveUnoptimizedPaths',
                        inputParam['Use Active Unoptimized Paths']) ]
      elif isinstance(inputParam, list):
         paramList = inputParam
      else:
         assert False,                                                     \
                '%s: __init__ inputParam must be a dictionary or a list' % \
                str(self)

      FixedPolicyOption.__init__(self, paramList)

class EqualizeLoadByNumberOfIOsPolicyOption(FixedPolicyOption):
   """Policy Option type containing load configuration parameters for
      round-robin PSP.
   """
   paramMeta = [
      ParameterMetadata('ioOperationsBeforeSwitchingToNextPath', 'int', False,
         paramChecker=RangeValidator(1)) ]

   complianceChecker = None

   # esxcli options needed to add this policy option to the host
   def GetEsxcliOptionString(self, _notUsed):
      optStr = '--type=iops --iops=%d' % \
               self.ioOperationsBeforeSwitchingToNextPath
      return optStr

class EqualizeLoadBySizeOfIOsPolicyOption(FixedPolicyOption):
   """Policy Option type containing load configuration parameters for
      round-robin PSP.
   """
   paramMeta = [
      ParameterMetadata('bytesBeforeSwitchingToNextPath', 'int', False,
         paramChecker=RangeValidator(1)) ]

   complianceChecker = None

   # esxcli options needed to add this policy option to the host
   def GetEsxcliOptionString(self, _notUsed):
      optStr = '--type=bytes --bytes=%d' % self.bytesBeforeSwitchingToNextPath
      return optStr

class EqualizeLoadDefaultPolicyOption(FixedPolicyOption):
   """Phantom Policy Option type for default round-robin PSP load configuration.
      We don't ever instantiate this policy option but use it to remove the
      other EqualizeLoad policy options.  This works because we implement a
      static GetEsxcliOptionString method.
   """
   paramMeta = [ ]

   complianceChecker = None

   # esxcli options needed to add this policy option to the host
   # static method needed for delete case where we don't have an instance
   @staticmethod
   def GetStaticEsxcliOptionString(_notUsed):
      optStr = '--type=default'
      return optStr

   def GetEsxcliOptionString(self, _notUsed):
      return self.GetStaticEsxcliOptionString(_notUsed)

#
# Policy option for the SATP Claim Information policy (part of a claimrule)
#
class SatpClaimInformationPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for the SATP Claim Information policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the SATP claim information described by the policy
         option is correct
      """

      return (True, [])

class SatpClaimInformationPolicyOption(FixedPolicyOption):
   """Policy Option type specifying claim information for an NMP SATP claimrule.
   """
   paramMeta = [
      ParameterMetadata('satpName', 'string', False),
      ParameterMetadata('claimOptions', 'string', True),
      ParameterMetadata('description', 'string', True),
      ParameterMetadata('options', 'string', True),
      ParameterMetadata('pspName', 'string', True),
      ParameterMetadata('pspOptions', 'string', True)]

   complianceChecker = SatpClaimInformationPolicyOptComplianceChecker

   # no unique identifier for the profile instance. We choose satpName as it is
   # the most symbolic
   def GetComparisonKey(self):
      return 'satpName'

   # esxcli options needed to add or delete this policy option to/from the host
   def GetEsxcliDict(self, typePolicyOpt):
      assert typePolicyOpt is not None, \
             '%s: typePolicyOpt param is None expected not None' % str(self)
      optStr = '--satp="%s"' % self.satpName
      wereOptions = False
      if self.description is not None and self.description != '':
         optStr += ' --description="%s"' % self.description
      if self.claimOptions is not None and self.claimOptions != '':
         optStr += ' --claim-option="%s"' % self.claimOptions
         wereOptions = True
      if self.options is not None and self.options != '':
         optStr += ' --option="%s"' % self.options
         wereOptions = True
      if self.pspName is not None and self.pspName != '':
         optStr += ' --psp="%s"' % self.pspName
         if self.pspOptions is not None and self.pspOptions != '':
            optStr += ' --psp-option="%s"' % self.pspOptions

      # DevicePolicyOption is no longer supported but can be present in legacy
      # profiles.  Convert addMsgDict/delMsgDict 'Type' string here to be
      # "UserInputDevicePolicyOption..." to avoid false compliance failures.
      typePolicyOptStr = str(typePolicyOpt)
      if typePolicyOptStr[0:len('DevicePolicyOption:')] == 'DevicePolicyOption:':
         typePolicyOptStr = 'UserInput' + typePolicyOptStr
      addMsgDict = delMsgDict = {'Satp': self.satpName,
         'Type': typePolicyOptStr,
         'Description': self.description if self.description else 'undescribed',
         'Claimopts': self.claimOptions if self.claimOptions else '',
         'Options': self.options if self.options else '',
         'Psp': self.pspName if self.pspName else ''}
      messageDict = MakeMessageDict(NMP_ADD_SATP_CLAIMRULE_KEY,
                                    NMP_DEL_SATP_CLAIMRULE_KEY,
                                    addMsgDict, delMsgDict)

      return MakeEsxcliDict('storage nmp', 'satp rule', 'add', 'remove',
                            optStr, optStr, messageDict,
                            typePolicyOpt, typePolicyOpt)

   # Ensure that at least one optional parameter is specified; checked by
   # VerifyProfile() and CheckPolicyCompliance().
   def PolicyOptValidator(self, hostServices, typePolicyOpt = None):
      if self.pspOptions is not None and self.pspOptions != '' and \
         (self.pspName is None or self.pspName == ''):
         return LogAndReturnError(self, PSA_PSP_OPTION_REQUIRES_PSP_NAME_KEY)
      #Secondly, validate the SATP name against the host
      status, output = ValidateSatp(self, hostServices, self.satpName)
      if status != True:
         return (status, output)

      return (True, [])

   # Optionally pre-process input dictionaries from GenerateMyProfileFromConfig
   def __init__(self, inputParam):
      if isinstance(inputParam, dict):
         paramList = [ ('satpName', inputParam['Name']),
                       ('claimOptions', inputParam['Claim Options']),
                       ('description', inputParam['Description']),
                       ('options', inputParam['Options']),
                       ('pspName', inputParam['Default PSP']),
                       ('pspOptions', inputParam['PSP Options']) ]
      elif isinstance(inputParam, list):
         paramList = inputParam
      else:
         assert False,                                                     \
                '%s: __init__ inputParam must be a dictionary or a list' % \
                str(self)

      FixedPolicyOption.__init__(self, paramList)

#
# Policy option for the Default PSP policy
#
class DefaultPspPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for the Default PSP policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the default PSP setting described by the policy
         option is valid and matches what's on the host
      """

      return (True, [])

class DefaultPspPolicyOption(FixedPolicyOption):
   """Policy Option type specifying the default PSP for a SATP.
   """
   paramMeta = [
      ParameterMetadata('satpName', 'string', False),
      ParameterMetadata('pspName', 'string', False)]

   complianceChecker = DefaultPspPolicyOptComplianceChecker

   def GetComparisonKey(self):
      return 'satpName'

   # esxcli options needed to add or delete this policy option to/from the host
   def GetEsxcliDict(self, _notUsed):
      assert _notUsed is None, \
             '%s: _notUsed param %s expected None' % (str(self), str(_notUsed))
      addOptStr = '--satp="%s" --default-psp="%s"' % (self.satpName, self.pspName)
      delOptStr = '--satp="%s" --default-psp=VMW_PSP_FIXED' % self.satpName

      addMsgDict = {'Satp': self.satpName, 'Psp': self.pspName}
      delMsgDict = {'Satp': self.satpName, 'Psp': 'VMW_PSP_FIXED'}
      messageDict = MakeMessageDict(NMP_ADD_DEFAULT_PSP_KEY,
                                    NMP_DEL_DEFAULT_PSP_KEY,
                                    addMsgDict, delMsgDict)

      return MakeEsxcliDict('storage nmp', 'satp', 'set',
                            'set', addOptStr, delOptStr, messageDict)

   def PolicyOptValidator(self, hostServices, _notUsed = None):
      #Firstly, validate the SATP name against the host
      status, output = ValidateSatp(self, hostServices, self.satpName)
      if status != 0:
         return (status, output)

      #Secondly, validate the pspName against the host
      if self.pspName is not None and self.pspName != '':
         cliNs, cliApp, cliCmd = 'storage nmp', 'psp', 'list'
         status, output = hostServices.ExecuteEsxcli(cliNs, cliApp, cliCmd)
         # Raise exception on failure to read host state (should always succeed)
         if status != 0:
            LogAndRaiseException(self, PSA_ESXCLI_CMD_FAILED_KEY, output)
         status = 1
         for psp in output:
            if psp['Name'] == self.pspName:
               status = 0
               break
         if status != 0:
            return LogAndReturnError(self, PSA_PARAM_NOT_FOUND_KEY,
                                     {'Param': self.pspName,
                                      'By': 'esxcli'})
      return (True, [])

   # Optionally pre-process input dictionaries from GenerateMyProfileFromConfig
   def __init__(self, inputParam):
      if isinstance(inputParam, dict):
         paramList = [ ('satpName', inputParam['Name']),
                       ('pspName', inputParam['Default PSP']) ]
      elif isinstance(inputParam, list):
         paramList = inputParam
      else:
         assert False,                                                     \
                '%s: __init__ inputParam must be a dictionary or a list' % \
                str(self)

      FixedPolicyOption.__init__(self, paramList)

#
# Policies
#
class DevicePspAssignmentPolicy(Policy):
   """Define the policy for the Device PSP Assignment Profile.
   """
   possibleOptions = [ DevicePspAssignmentPolicyOption ]

class DevicePspConfigurationPolicy(Policy):
   """Define the policy for the PSP Device Configuration Profile.
   """
   possibleOptions = [ DeviceConfigurationPolicyOption ]

class DevicePreferredPathPolicy(Policy):
   """Define the policy for the Fixed PSP Configuration Profile.
   """
   possibleOptions = [ PathPolicyOption ]

class FixedPspPolicy(Policy):
   """Define the policy for the Fixed PSP Configuration Profile.
   """
   possibleOptions = [ DevicePolicyOption ]

   # Instantiate policy option based on esxcli output
   @classmethod
   def GetPolicyOption(cls, esxcliOutput, _notUsed = False):
      fixedConfigurationPolicyOption = None

      assert not _notUsed,                                                     \
             '%s: GetPolicyOption boolean param value of True not supported' % \
             str(cls)
      assert isinstance(esxcliOutput, dict), \
             '%s: esxcliOutput must be a dictionary' % str(cls)

      configuredPath = esxcliOutput['Configured Preferred Path']
      if configuredPath == '':
         fixedConfigurationPolicyOption = None
      elif configuredPath.count('-') >= 2:
         # iscs paths can have more than 2 hyphens
         deviceName = configuredPath.split('-')[-1]
         params = [ ('deviceName', deviceName) ]
         fixedConfigurationPolicyOption = DevicePolicyOption(params)
      else:
         assert False,                                            \
                '%s: Unrecognized Fixed PSP configured path %s' % \
                (str(cls), configuredPath)

      return fixedConfigurationPolicyOption

class RoundRobinLoadConfigurationPolicy(Policy):
   """Define the policy for the Round-robin PSP Configuration Profile.
   """
   possibleOptions = [
      EqualizeLoadByNumberOfIOsPolicyOption,
      EqualizeLoadBySizeOfIOsPolicyOption ]

   # Instantiate policy option based on esxcli output
   @classmethod
   def GetPolicyOption(cls, esxcliOutput, _notUsed = False):
      roundRobinConfigurationPolicyOption = None

      assert not _notUsed,                                                     \
             '%s: GetPolicyOption boolean param value of True not supported' % \
             str(cls)
      assert isinstance(esxcliOutput, dict), \
             '%s: esxcliOutput must be a dictionary' % str(cls)

      limitType = esxcliOutput['Limit Type']
      if limitType == 'Default':
         roundRobinConfigurationPolicyOption = None
      elif limitType == 'Bytes':
         params = [ ('bytesBeforeSwitchingToNextPath', esxcliOutput['Byte Limit']) ]
         roundRobinConfigurationPolicyOption = \
            EqualizeLoadBySizeOfIOsPolicyOption(params)
      elif limitType == 'Iops':
         params = [ ('ioOperationsBeforeSwitchingToNextPath',
                     esxcliOutput['I/O Operation Limit']) ]
         roundRobinConfigurationPolicyOption = \
            EqualizeLoadByNumberOfIOsPolicyOption(params)
      else:
         assert False,                                                \
                '%s: Unrecognized Round Robin PSP configuration %s' % \
                (str(cls), limitType)

      return roundRobinConfigurationPolicyOption

class RoundRobinDevicePolicy(Policy):
   """Define the useAno policy for the Round-robin PSP Configuration Profile.
   """
   possibleOptions = [ RoundRobinDevicePolicyOption ]

class SatpClaimInformationPolicy(Policy):
   """Define the claim information policy for the SATP Claimrules profile.
   """
   possibleOptions = [ SatpClaimInformationPolicyOption ]

class SatpClaimTypePolicy(Policy):
   """Define the claim type policy for SATP NMP Claimrules profile.
   """
   possibleOptions = [
                      DevicePolicyOption, #deprecated but allowable
                      DriverPolicyOption,
                      TransportPolicyOption,
                      VendorModelPolicyOption,
                      UserInputDevicePolicyOption ]

   # Instantiate policy option based on esxcli output containing a claimrule.
   # Overloaded to return UserInputRequiredPolicyOption params if paramsOnly
   # because we don't populate the answer file until VerifyProfileForApply.
   @classmethod
   def GetPolicyOption(cls, esxcliRule, paramsOnly = False):
      satpClaimTypePolicyOpt = None
      dupeSatpClaimType = False
      params = []
      userInputParams = []

      assert isinstance(esxcliRule, dict), \
             '%s: esxcliRule must be a dictionary' % str(cls)

      # 'Device', 'Driver', 'Model', 'Transport' and 'Vendor' fields conflict
      # (except for 'Vendor' + 'Model'), so assert if we encounter a conflict.
      #
      # PR 1014658: Device rules are per-host so use UserInputDevicePolicyOption
      if esxcliRule['Device'] != '':
         satpClaimTypePolicyOpt = UserInputDevicePolicyOption
         userInputParams = [ ('deviceName', esxcliRule['Device']) ]
      if esxcliRule['Driver'] != '':
         if satpClaimTypePolicyOpt is not None:
            dupeSatpClaimType = True
         else:
            satpClaimTypePolicyOpt = DriverPolicyOption
            params.append( ('driverName', esxcliRule['Driver']) )
      if esxcliRule['Transport'] != '':
         if satpClaimTypePolicyOpt is not None:
            dupeSatpClaimType = True
         else:
            satpClaimTypePolicyOpt = TransportPolicyOption
            params.append( ('transportName', esxcliRule['Transport']) )
      if esxcliRule['Vendor'] != '' or esxcliRule['Model'] != '':
         if satpClaimTypePolicyOpt is not None:
            dupeSatpClaimType = True
         else:
            satpClaimTypePolicyOpt = VendorModelPolicyOption
            if esxcliRule['Vendor'] != '':
               params.append( ('vendorName', esxcliRule['Vendor']) )
            if esxcliRule['Model'] != '':
               params.append( ('model', esxcliRule['Model']) )
      if satpClaimTypePolicyOpt is None:
         if esxcliRule['Claim Options'] is None:
            assert False, 'At least one of Device, Driver, Transport, \
               vendor/Model or claim options must be specified'
         return None

      if dupeSatpClaimType:
         assert False,                                                      \
             '%s: Exactly one SATP claim type must be specified, found '    \
             '"%s", "%s", "%s", "%s/%s"' % (str(cls), esxcliRule['Device'], \
             esxcliRule['Driver'], esxcliRule['Transport'],                 \
             esxcliRule['Vendor'], esxcliRule['Model'])
      elif issubclass(satpClaimTypePolicyOpt, UserInputRequiredOption):
         # If we pass "params, userInputParams" we get an __init__ error so
         # enforce here that params is empty ([]).
         assert len(params) == 0,                                             \
                '%s: %s: params cannot be used for UserInputRequiredOption' % \
                (str(cls), str(satpClaimTypePolicyOpt))
         return userInputParams if paramsOnly else \
                satpClaimTypePolicyOpt(userInputParams)

      assert not paramsOnly and len(userInputParams) == 0,                   \
             '%s: %s: paramsOnly only allowed for UserInputRequiredOption' % \
             (str(cls), str(satpClaimTypePolicyOpt))

      return satpClaimTypePolicyOpt(params)

class DefaultPspPolicy(Policy):
   """Define the default PSP policy.
   """
   possibleOptions = [ DefaultPspPolicyOption ]

class SatpDeviceConfigurationPolicy(Policy):
   """Define the device configuration for various NMP profiles.
   """
   possibleOptions = [ DeviceConfigurationPolicyOption ]

#
# Leaf Profiles
#
class NmpDeviceConfigurationProfile(GenericProfile):
   """A leaf Host Profile that manages NMP device configuration on the ESX host.
   """
   #
   # Define required class attributes
   #
   policies = [ DevicePspAssignmentPolicy ]

   complianceChecker = None

   dependencies = [ PsaDeviceSharingProfile ]

   singleton = False

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves a list of dictionaries, one per NMP device on the host.
      """
      # XXX only store configs made via "storage nmp device setpolicy"?
      return GatherEsxcliData(cls, hostServices,
                              'storage nmp', 'device', 'list',
                              itemIfFct = (lambda x: x['Is USB'] != True))

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance per configured NMP device on the host.
      """
      return GenerateMyProfileFromConfig(cls, hostServices, config,
                                         DevicePspAssignmentPolicyOption)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
                        parent):
      """Generates a list of the data in the profileInstances.
      """
      return GenerateMyTaskList(cls, profileInstances, taskList, hostServices,
                                config, parent, GetTranslatedTaskList)

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Implementation of remediate config that takes the supplied task list
         and adds and/or removes the NAS datastores indicated in the task list.
      """
      RemediateMyConfig(cls, taskList, hostServices, config, True)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
                                      profileData, validationErrors)

NmpDeviceConfigurationProfile.complianceChecker = \
   NmpProfileComplianceChecker(NmpDeviceConfigurationProfile, None, GetTranslatedTaskList)

class PspDeviceConfigurationProfile(GenericProfile):
   """A leaf Host Profile that manages PSP device configuration on the ESX host.
   """
   #
   # Define required class attributes
   #
   policies = [ DevicePspConfigurationPolicy ]

   complianceChecker = None

   dependencies = [ PsaDeviceSharingProfile ]

   singleton = False

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves a list of dictionaries, one per NMP device on the host.
         Creates and returns a list of dictionaries of per-device PSP
         configuration, one per NMP device on the host.
      """
      # XXX PR 591715: all PSPs excluded; getconfig/setconfig are not symmetric.
      return GatherEsxcliData(cls, hostServices, 'storage nmp', 'device',
         'list', None, 'psp generic deviceconfig', 'get', 'device', 'Device',
         (lambda x: x['Path Selection Policy'] != 'VMW_PSP_FIXED' and \
                    x['Path Selection Policy'] != 'VMW_PSP_MRU' and \
                    x['Path Selection Policy'] != 'VMW_PSP_RR')
         )

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance per NMP device on the ESX host.
      """
      return GenerateMyProfileFromConfig(cls, hostServices, config,
                                         DeviceConfigurationPolicyOption)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
                        parent):
      """Generates a list of the data in the profileInstances.
      """
      return GenerateMyTaskList(cls, profileInstances, taskList, hostServices,
                                config, parent, GetTranslatedTaskList, 'psp')

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Implementation of remediate config that takes the supplied task list
         and adds and/or removes the NAS datastores indicated in the task list.
      """
      RemediateMyConfig(cls, taskList, hostServices, config, True)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
                                      profileData, validationErrors)

PspDeviceConfigurationProfile.complianceChecker = \
      NmpProfileComplianceChecker(PspDeviceConfigurationProfile, 'psp', GetTranslatedTaskList)

class FixedPspConfigurationProfile(GenericProfile):
   """A leaf Host Profile that manages Fixed PSP configuration on the ESX host.
   """
   #
   # Define required class attributes
   #
   policies = [ DevicePreferredPathPolicy, FixedPspPolicy ]

   complianceChecker = None

   dependencies = [ PsaDeviceSharingProfile ]

   singleton = False

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves a list of dictionaries, one per NMP device on the host
         Creates and returns a list of dictionaries of per-device fixed PSP
         configuration, one per fixed PSP device on the host.
      """
      return GatherEsxcliData(cls, hostServices, 'storage nmp', 'device',
             'list', None, 'psp fixed deviceconfig', 'get', 'device', 'Device',
             (lambda x: x['Path Selection Policy'] == 'VMW_PSP_FIXED' and
                        x['Is USB'] != True)
             )

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance per configured fixed PSP device on
         the ESX host.
      """
      return GenerateMyProfileFromConfig(cls, hostServices, config,
                                         PathPolicyOption,
                                         FixedPspPolicy)

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
         and adds and/or removes the NAS datastores indicated in the task list.
      """
      RemediateMyConfig(cls, taskList, hostServices, config, True)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
                                      profileData, validationErrors)

FixedPspConfigurationProfile.complianceChecker = \
      NmpProfileComplianceChecker(FixedPspConfigurationProfile)

class RoundRobinPspConfigurationProfile(GenericProfile):
   """A leaf Host Profile that manages Round-Robin PSP configuration on the ESX host.
   """
   #
   # Define required class attributes
   #
   policies = [ RoundRobinDevicePolicy, RoundRobinLoadConfigurationPolicy ]

   complianceChecker = None

   dependencies = [ PsaDeviceSharingProfile ]

   singleton = False

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves a list of dictionaries, one per NMP device on the host
         Creates and returns a list of dictionaries of per-device round-robin
         PSP configuration, one per round-robin PSP device on the host.
      """
      return GatherEsxcliData(cls, hostServices, 'storage nmp', 'device',
         'list', None, 'psp roundrobin deviceconfig', 'get', 'device', 'Device',
         (lambda x: x['Path Selection Policy'] == 'VMW_PSP_RR' and
                    x['Is USB'] != True)
         )

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance per roundrobin PSP device on the host.
      """
      return GenerateMyProfileFromConfig(cls, hostServices, config,
                                         RoundRobinDevicePolicyOption,
                                         RoundRobinLoadConfigurationPolicy)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
                        parent):
      """Generates a list of the data in the profileInstances.
      """
      return GenerateMyTaskList(cls, profileInstances, taskList, hostServices,
                                config, parent, GetTranslatedTaskList)

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Implementation of remediate config that takes the supplied task list
         and adds and/or removes the NAS datastores indicated in the task list.
      """
      RemediateMyConfig(cls, taskList, hostServices, config, True)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
                                      profileData, validationErrors)

RoundRobinPspConfigurationProfile.complianceChecker = \
      NmpProfileComplianceChecker(RoundRobinPspConfigurationProfile, None, GetTranslatedTaskList)

class SatpClaimrulesProfile(GenericProfile):
   """A leaf Host Profile that manages NMP SATP claimrules on the ESX host.
   """
   #
   # Define required class attributes
   #
   policies = [ SatpClaimInformationPolicy, SatpClaimTypePolicy ]

   complianceChecker = None

   dependencies = [ PsaDeviceSharingProfile ]

   singleton = False

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves a list of dictionaries, one per SATP claimrule on the host.
         Returns a subset of this list containing all dictionaries containing
         a SATP user claimrule.
      """
      return GatherEsxcliData(cls, hostServices, 'storage nmp', 'satp rule',
                              'list', None, None, None, None, None,
                              (lambda x: x['Rule Group'] == 'user')
                             )

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance per SATP use claimrule on the ESX host.
      """
      return GenerateMyProfileFromConfig(cls, hostServices, config,
                                         SatpClaimInformationPolicyOption,
                                         SatpClaimTypePolicy)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
                        parent):
      """Generates a tasklist for the claimrules in the profileInstances.
         We don't compare anything: all rules in the host config are marked
         for deletion while all rules in the profile instances are added.
      """
      return GenerateMyTaskList(cls, profileInstances, taskList, hostServices,
                                config, parent, None, None)

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Implementation of remediate config that takes the supplied task list
         and adds and/or removes the NAS datastores indicated in the task list.
      """
      RemediateMyConfig(cls, taskList, hostServices, config)
      # If some satp rules are added, reboot is required to take effect.
      # But for stateless host, new rules will be added each time during
      # reboot and it will fall into cycle of reboot required.
      # Satp rules needs to be reclaimed to avoid REQ_REBOOT in stateless
      # host.
      cls._ReclaimSatpClaimrules(cls, hostServices, taskList)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
                                      profileData, validationErrors)

   @classmethod
   def VerifyProfileForApply(cls, profileInstance, hostServices, profileData,
                             validationErrors):
      return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
                                      profileData, validationErrors, True)

   def _ReclaimSatpClaimrules(cls, hostServices, taskList):
      '''Parse taskList and claim satp rules'''
      def GetDevicesInTasklist(taskList):
         '''Return a list of devices for which satp claimrules
         were added or removed.
         '''
         deviceList = []
         for task in taskList:
            try:
               addOpt = (task[1]['AddOpt'] or task[1]['DelOpt']).split(' ')
               # Now addOpt will be like :
               # ['--satp="VMW_SATP_ALUA"', '--type=device', '--device="naa.60.."']
               # Search in addOpt to find '--device'
               for token in addOpt:
                  if '--device' in token:
                     deviceList.append(token.split('=')[1])
                     break
            except KeyError as keyError:
               log.error('%s _ReclaimSatpClaimrules: Failed to find devices in taskList %s' %
                         (str(cls), keyError))
         return deviceList

      log.debug('%s RemediateMyConfig: Reclaiming Satp claimrules' %
                (str(cls)))
      deviceList = GetDevicesInTasklist(taskList)
      # Reclaim all satp rules added/deleted for device in deviceList
      for device in deviceList:
         RunEsxcli(cls, hostServices, 'storage core', 'claiming', 'reclaim', '--device=%s'%device)

SatpClaimrulesProfile.complianceChecker = \
      NmpProfileComplianceChecker(SatpClaimrulesProfile)

class DefaultPspProfile(GenericProfile):
   """A leaf Host Profile that manages default PSP configuration on the ESX host.
   """
   #
   # Define required class attributes
   #
   policies = [ DefaultPspPolicy ]

   complianceChecker = None

   dependencies = [ PsaDeviceSharingProfile ]

   singleton = False

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves a list of dictionaries, one per SATP on the host.
         Creates and returns a list of dictionaries, one per SATP user
         claimrule.
      """
      return GatherEsxcliData(cls, hostServices, 'storage nmp', 'satp', 'list')

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance per SATP on the ESX host.
      """
      return GenerateMyProfileFromConfig(cls, hostServices, config,
                                         DefaultPspPolicyOption)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
                        parent):
      """Generates a list of the data in the profileInstances.
      """
      return GenerateMyTaskList(cls, profileInstances, taskList, hostServices,
                                config, parent, None, None, True, True)

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Implementation of remediate config that takes the supplied task list
         and adds and/or removes the NAS datastores indicated in the task list.
      """
      RemediateMyConfig(cls, taskList, hostServices, config)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
                                      profileData, validationErrors)

DefaultPspProfile.complianceChecker = \
      NmpProfileComplianceChecker(DefaultPspProfile)

class SatpDeviceProfile(GenericProfile):
   """A leaf Host Profile that manages NMP SATP device configuration on the ESX host.
   """
   #
   # Define required class attributes
   #
   policies = [ SatpDeviceConfigurationPolicy ]

   complianceChecker = None

   dependencies = [ PsaDeviceSharingProfile ]

   singleton = False

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves a list of all SATP devices on the host and creates and
         returns a dictionary of all SATP device configurations on the host
      """
      list = GatherEsxcliData(cls, hostServices, 'storage nmp', 'device',
         'list', None, 'satp generic deviceconfig', 'get',
         'exclude-tpg-info --device', 'Device', (lambda x: x['Is USB'] != True)
         )

      itemList = []
      for item in list:
         assert 'Get' in item, \
                '%s: esxcli output expected to have key "Get"' % str(cls)
         if 'does not support device configuration' not in item['Get']:
            itemList.append(item)

      return itemList

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance per SATP device on the ESX host.
      """
      return GenerateMyProfileFromConfig(cls, hostServices, config,
                                         DeviceConfigurationPolicyOption)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
                        parent):
      """Generates a list of the data in the profileInstances.
      """
      return GenerateMyTaskList(cls, profileInstances, taskList, hostServices,
                                config, parent, GetTranslatedTaskList, 'satp',
                                addsOnly = True)

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Implementation of remediate config that takes the supplied task list
         and adds and/or removes the NAS datastores indicated in the task list.
      """
      RemediateMyConfig(cls, taskList, hostServices, config, True)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
                                      profileData, validationErrors)

SatpDeviceProfile.complianceChecker = \
   NmpProfileComplianceChecker(SatpDeviceProfile, 'satp', GetTranslatedTaskList)

#
# Parent Profiles
#
class StorageArrayTypePluginProfile(GenericProfile):
   """A Host Profile that manages Storage Array Type Plug-ins (SATPs) on the ESX host.
   """
   # For stateless boot must wait until satps and psps are loaded
   #
   # Define required class attributes
   #
   subprofiles = [
                   SatpClaimrulesProfile,
                   DefaultPspProfile ]

   singleton = True

class NmpDeviceProfile(GenericProfile):
   """A Host Profile that manages NMP Device Configurration on the ESX host.
   """
   # For stateless boot must wait until devices are discovered
   #
   # Define required class attributes
   #
   subprofiles = [
                   NmpDeviceConfigurationProfile,
                   SatpDeviceProfile ]

   dependencies = [ PsaBootDeviceProfile, ]
   singleton = True

class PathSelectionPolicyProfile(GenericProfile):
   """A Host Profile that manages Path Selection Policy (PSP) on the ESX host.
   """
   # For stateless boot must wait until devices are discovered
   #
   # Define required class attributes
   #
   subprofiles = [
                   PspDeviceConfigurationProfile,
                   FixedPspConfigurationProfile,
                   RoundRobinPspConfigurationProfile ]

   dependencies = [ DefaultPspProfile,
                    NmpDeviceConfigurationProfile ]

   singleton = True

class NativeMultiPathingProfile(GenericProfile):
   """A Host Profile that manages Native Multi-Pathing (NMP) on the ESX host.
   """
   #
   # Define required class attributes
   #
   subprofiles = [
                   StorageArrayTypePluginProfile,
                   NmpDeviceProfile,
                   PathSelectionPolicyProfile ]

   parentProfiles = [ StorageProfile ]

   singleton = True

   category = CATEGORY_STORAGE
   component = COMPONENT_CORE_STORAGE

