#!/usr/bin/python
# **********************************************************
# Copyright 2010-2016 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import GenericProfile, Policy, FixedPolicyOption, \
                      ParameterMetadata, log, \
                      PolicyOptComplianceChecker, ProfileComplianceChecker, \
                      TASK_LIST_REQ_MAINT_MODE, TASK_LIST_REQ_REBOOT, \
                      TASK_LIST_RES_OK

from pluginApi import CATEGORY_STORAGE, COMPONENT_CORE_STORAGE

from pyEngine.storageprofile import StorageProfile

from pyEngine.nodeputil import RangeValidator

from psa.common import *

import vmkctl

#
# Declare PSA specific keys needed for task lists and compliance checking
#
PSA_ADD_CLAIMRULE_KEY = '%s%s' % (PSA_ADD_KEY, 'Claimrule')
PSA_DEL_CLAIMRULE_KEY = '%s%s' % (PSA_DEL_KEY, 'Claimrule')
PSA_DUPLICATE_CLAIM_RULE_NUMBER_KEY = \
   '%s.PsaDuplicateClaimRuleNumber' % PSA_BASE
PSA_ADD_DEVICE_CONFIG_KEY = '%s%s' % (PSA_ADD_KEY, 'DeviceConfig')
PSA_DEL_DEVICE_CONFIG_KEY = '%s%s' % (PSA_DEL_KEY, 'DeviceConfig')
PSA_ADD_DEVICE_SHARING_KEY = '%s%s' % (PSA_ADD_KEY, 'DeviceSharing')
PSA_DEL_DEVICE_SHARING_KEY = '%s%s' % (PSA_DEL_KEY, 'DeviceSharing')
PSA_LOCATION_PARAMETERS_NOT_DIGITS_OR_ASTERIX = \
   '%s.PsaLocationParametersNotDigistOrAsterix' % PSA_BASE
PSA_LUN_PARAMETER_IS_NOT_DIGITS_OR_ASTERIX = \
   '%s.PsaLunParameterIsNotDigistOrAsterix' % PSA_BASE
PSA_XCOPY_VENDOR_MODEL_INCORRECT = \
   '%s.PsaXcopyVendorModelIncorrect' % PSA_BASE
PSA_XCOPY_MAX_TRANSFER_SIZE_INCORRECT = \
   '%s.PsaXcopyMaxTransferSizeIncorrect' % PSA_BASE
PSA_XCOPY_CLAIMRULE_CLASS_NOT_VAAI = \
   '%s.PsaXcopyClaimruleClassNotVaai' % PSA_BASE

PSA_PROFILE_BASE = 'com.vmware.vim.profile.Profile.psa.psaProfile'
PSA_PROFILE_NOT_FOUND_KEY = '%s.PsaProfileNotFound' % PSA_BASE
PSA_PROFILE_MISMATCH_PARAM_KEY = '%s.PsaProfileMismatchParam' % PSA_BASE
PSA_PROFILE_POLICY_MISMATCH_KEY = '%s.PsaProfilePolicyMismatch' % PSA_BASE

PSA_MISMATCH_SHARED_CLUSTERWIDE = \
   "%s.SharedClusterwideMismatch" % PSA_BASE
PSA_MISMATCH_CLAIMRULE = "%s.ClaimRuleMismatch" % PSA_BASE


#
# Declare global constants that match various PSA constraints
#
# Keep in sync with bora/lib/vmkctl/storage/PSAClaimRuleImpl.cpp
#
# Auto-populate these when PR 575695 is fixed
#
MIN_RULEID = 0
MIN_PUBLIC_RULEID = 101
MAX_PUBLIC_RULEID = 65435
MAX_RULEID = 65535
DEVICE_MAX_OUTSTANDING_REQ = 256
DEVICE_MIN_OUTSTANDING_REQ = 1
DEVICE_MAX_QFULL_THRESHOLD = 16
PSA_XCOPY_MIN_MAX_TRANSFER_SIZE = 4
PSA_XCOPY_MAX_MAX_TRANSFER_SIZE = 240

#
# Common compliance checker for PSA profiles
#
class PsaProfileComplianceChecker(ProfileComplianceChecker):
   """A compliance checker type for PSA profiles
   """
   def __init__(self, profileClass, translateFunc = None):
      self.profileClass = profileClass
      self.translateFunc = translateFunc

   def CheckProfileCompliance(self, profileInsts, hostServices, profileData,
                              parent):
      """Checks whether the PSA configuration described by the profiles
         and their policies and policy option parameters exists and matches
         what is on the host.
      """
      msgKeyDict = {'ProfNotFound' : PSA_PROFILE_NOT_FOUND_KEY,
                    'ParamMismatch' : PSA_PROFILE_MISMATCH_PARAM_KEY,
                    'PolicyMismatch' : PSA_PROFILE_POLICY_MISMATCH_KEY,
                    'KeyBase' : PSA_PROFILE_BASE}

      return CheckMyCompliance(self.profileClass, profileInsts, hostServices,
                         profileData, parent, msgKeyDict, self.translateFunc)


#
# Policy options and compliance checkers (one checker per policy option)
#
# Policy option for the PSA Claim Information policy (part of a claimrule)
#
# XXX This policy option only specifies part of a claimrule so we can't
#     check for a full rule independent of other policy options.  For now
#     we punt and just check individual parameters for host system validity.
#     Need to investigate how to get from PolicyOpt to containing Policy.
#
class PsaClaimInformationPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for PSA Claim Information policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):

      return (True, [])

class PsaClaimInformationPolicyOption(FixedPolicyOption):
   """Policy Option type specifying claim information for a PSA claimrule.
   """
   paramMeta = [
      ParameterMetadata('ruleNumber', 'int', False,
         paramChecker=RangeValidator(MIN_RULEID, MAX_RULEID)),
      ParameterMetadata('pluginName', 'string', False),
      ParameterMetadata('claimruleClass', 'string', True),
      ParameterMetadata('xcopyUseArrayReportedValues', 'bool', True),
      ParameterMetadata('xcopyUseMultipleSegments', 'bool', True),
      ParameterMetadata('xcopyMaxTransferSize', 'int', True)]

   complianceChecker = PsaClaimInformationPolicyOptComplianceChecker

   def GetComparisonKey(self):
      return 'ruleNumber'

   def GetComplianceTaskDict(self):
      complianceTask = {}
      complianceTask['messageCode'] = PSA_MISMATCH_CLAIMRULE
      complianceTask['messageDict'] = {'RuleNumber': self.ruleNumber}
      complianceTask['comparisonIdentifier'] = 'ClaimRule'
      complianceTask['hostValue'] = self.ruleNumber
      complianceTask['profileValue'] = self.ruleNumber
      complianceTask['profileInstance'] = str(self.ruleNumber)
      return complianceTask

   # esxcli options needed to add or delete this policy option to/from the host
   def GetEsxcliDict(self, typePolicyOpt):
      assert typePolicyOpt is not None, \
             '%s: typePolicyOpt param is None expected not None' % str(self)
      addOptStr = '--plugin="%s" --rule=%d' % (self.pluginName, self.ruleNumber)
      delOptStr = '--rule=%d' % self.ruleNumber

      if self.ruleNumber < MIN_PUBLIC_RULEID or self.ruleNumber > MAX_PUBLIC_RULEID:
         addOptStr += ' --force-reserved'

      # If claimruleClass in profile is left empty, but captured by host as MP
      if self.claimruleClass is None or self.claimruleClass == '':
         self.claimruleClass = 'MP'

      addMsgDict = None
      if self.claimruleClass is not None and self.claimruleClass != '':
         addOptStr += ' --claimrule-class="%s"' % self.claimruleClass
         delOptStr += ' --claimrule-class="%s"' % self.claimruleClass
         claimruleClass = self.claimruleClass
         if self.claimruleClass == 'VAAI' and self.xcopyUseArrayReportedValues:
            addOptStr += ' --xcopy-use-array-values'
            if self.xcopyUseMultipleSegments:
               addOptStr += ' --xcopy-use-multi-segs'
            if self.xcopyMaxTransferSize:
               addOptStr += ' --xcopy-max-transfer-size=%d' % \
                            self.xcopyMaxTransferSize
            addMsgDict = {'RuleNumber': self.ruleNumber,
               'RuleClass': claimruleClass,
               'XcopyUseArrayReportedValues': self.xcopyUseArrayReportedValues,
               'XcopyUseMultipleSegments': self.xcopyUseMultipleSegments,
               'XcopyMaxTransferSize': self.xcopyMaxTransferSize}
      else:
         claimruleClass = 'MP'

      delMsgDict = {'RuleNumber': self.ruleNumber,
                    'RuleClass': claimruleClass}
      if addMsgDict is None:
         addMsgDict = delMsgDict

      messageDict = MakeMessageDict(PSA_ADD_CLAIMRULE_KEY,
                                    PSA_DEL_CLAIMRULE_KEY,
                                    addMsgDict, delMsgDict)

      return MakeEsxcliDict('storage core', 'claimrule', 'add', 'remove',
                addOptStr, delOptStr, messageDict, typePolicyOpt, None,
                True if isinstance(typePolicyOpt, VendorModelPolicyOption) else False)

   def PolicyOptValidator(self, hostServices, typePolicyOpt = None):
      """Checks whether the PSA claim information described by the policy
         option is correct
      """
      assert typePolicyOpt is not None, 'Expected non None secondary Policy Opt'

      #Validate pluginName
      cliNs, cliApp, cliCmd = 'storage core', 'plugin registration', 'list'
      status, output = hostServices.ExecuteEsxcli(cliNs, cliApp, cliCmd)
      # Raise exception on failure to read host state (should always succeed)
      if status != 0:
         LogAndRaiseException(self, PSA_ESXCLI_CMD_FAILED_KEY, output)
      status = 1
      for plugin in output:
         if plugin['Plugin Name'] == self.pluginName:
            status = 0
            break
      if status != 0:
         return LogAndReturnError(self, PSA_PARAM_NOT_FOUND_KEY,
                                  {'Param': self.pluginName,
                                   'By': 'esxcli'})

      #Validate optional parameter claimruleClass (none needed for description)
      if self.claimruleClass is not None and self.claimruleClass != '':
         cliOpt = '--claimrule-class="%s"' % self.claimruleClass
         cliNs, cliApp, cliCmd = 'storage core', 'claimrule', 'list'
         status, output = hostServices.ExecuteEsxcli(cliNs, cliApp, cliCmd, cliOpt)
         if status != 0:
            return LogAndReturnError(self, PSA_MISMATCH_PARAM_KEY,
                                     output)

      # Keep checks insync with ClaimRuleAdd.cpp: IsXcopy_array_reported_supported()
      if self.claimruleClass == 'VAAI' and \
           self.xcopyUseArrayReportedValues:
         # 4 <= max transfer size <= 240
         if self.xcopyMaxTransferSize < PSA_XCOPY_MIN_MAX_TRANSFER_SIZE or \
             self.xcopyMaxTransferSize > PSA_XCOPY_MAX_MAX_TRANSFER_SIZE:
            msg = CreateLocalizedMessage(self, PSA_XCOPY_MAX_TRANSFER_SIZE_INCORRECT,
                                         paramId = 'xcopyMaxTransferSize')
            return(False, msg)
         # Supported currently only for EMC/SYMMETRIX
         if isinstance(typePolicyOpt, VendorModelPolicyOption):
            if typePolicyOpt.vendorName.upper() != 'EMC' or \
                 typePolicyOpt.model.upper() != 'SYMMETRIX':
               msg = CreateLocalizedMessage(self, PSA_XCOPY_VENDOR_MODEL_INCORRECT,
                                            paramId = 'xcopyUseArrayReportedValues')
               return(False, msg)
      # XCOPY set for Non-VAAI claimrule class
      elif self.xcopyUseArrayReportedValues:
         msg = CreateLocalizedMessage(self, PSA_XCOPY_CLAIMRULE_CLASS_NOT_VAAI,
                                      paramId = 'xcopyUseArrayReportedValues')
         return(False, msg)

      return (True,[])

   # Optionally pre-process input dictionaries from GenerateMyProfileFromConfig
   def __init__(self, inputParam):
      if isinstance(inputParam, dict):
         paramList = [ ('ruleNumber', inputParam['Rule']),
                       ('pluginName', inputParam['Plugin']),
                       ('claimruleClass', inputParam['Rule Class']) ]
         # If 'XCOPY Use Array Reported Values' is FALSE then XCOPY values are don't cares
         xcopyPresent = 'XCOPY Use Array Reported Values' in inputParam
         mulSegPresent = 'XCOPY Use Multiple Segments' in inputParam
         maxXferPresent = 'XCOPY Max Transfer Size' in inputParam
         assert mulSegPresent == xcopyPresent and maxXferPresent == xcopyPresent, \
                '%s: __init__ inputParam has inconsistent XCOPY members; ' +      \
                'use array reported values is %s, use multiple segments is ' +    \
                '%s, and max transfer size is %s' %                               \
                (str(self), 'present' if xcopyPresent else 'absent',              \
                 'present' if mulSegPresent else 'absent', \
                 'present' if maxXferPresent else 'absent')
         if inputParam['Rule Class'] == "VAAI":
            if xcopyPresent and inputParam['XCOPY Use Array Reported Values']:
               paramList.append( ('xcopyUseArrayReportedValues',
                                 inputParam['XCOPY Use Array Reported Values']) )
               paramList.append( ('xcopyUseMultipleSegments',
                                  inputParam['XCOPY Use Multiple Segments']) )
               paramList.append( ('xcopyMaxTransferSize',
                                  inputParam['XCOPY Max Transfer Size']) )
            else:
               paramList.append( ('xcopyUseArrayReportedValues', False) )
               paramList.append( ('xcopyUseMultipleSegments', False) )
               paramList.append( ('xcopyMaxTransferSize', 0) )
         else:
            assert not xcopyPresent or                                          \
                   not inputParam['XCOPY Use Array Reported Values'],           \
                   '%s: XCOPY members incorrectly present for non VAAI rule ' + \
                   'type %s' % (str(self), inputParam['Rule Class'])
      elif isinstance(inputParam, list):
         paramList = inputParam
      else:
         assert False,                                                     \
                '%s: __init__ inputParam must be a dictionary or a list' % \
                str(self)

      FixedPolicyOption.__init__(self, paramList)

#
# Policy options unique to the PSA Claim Type policy
#
# Fiberchannel Targets
#
class FcTargetPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for a PSA Fiberchannel Target policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):

      return (True, [])

class FcTargetPolicyOption(FixedPolicyOption):
   """Policy Option type specifying a fiberchannel target for a PSA claimrule.
   """
   paramMeta = [
      ParameterMetadata('wwnn', 'string', False),
      ParameterMetadata('wwpn', 'string', False),
      ParameterMetadata('lun', 'string', False)]

   complianceChecker = FcTargetPolicyOptComplianceChecker

   # Ensure that the LUN number parameter is numeric or "*"; checked
   # by VerifyProfile() and CheckPolicyCompliance().
   def PolicyOptValidator(self, hostServices, _notUsed = None):
      assert _notUsed is None, \
             '%s: _notUsed param %s expected None' % (str(self), str(_notUsed))
      if self.lun != '*' and not self.lun.isdigit():
         return LogAndReturnError(self,
                                  PSA_LUN_PARAMETER_IS_NOT_DIGITS_OR_ASTERIX)
      else:
         return (True, [])

   # esxcli options needed to add this policy option to the host
   def GetEsxcliOptionString(self, _notUsed):
      optStr = '--type=target --transport=fc --wwnn="%s" --wwpn="%s"' % \
               (self.wwnn, self.wwpn)
      if self.lun.isdigit():
         #Don't wrap LUN number in quotes because it's numeric
         optStr += ' --lun=%s' % self.lun
      return optStr

#
# Iscsi Targets
#
class IscsiTargetPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for a PSA Iscsi Target policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):

      return (True, [])

class IscsiTargetPolicyOption(FixedPolicyOption):
   """Policy Option type specifying an ISCSI target for a PSA claimrule.
   """
   paramMeta = [
      ParameterMetadata('iqn', 'string', False),
      ParameterMetadata('lun', 'string', False)]

   complianceChecker = IscsiTargetPolicyOptComplianceChecker

   # Ensure that the LUN number parameter is numeric or "*"; checked
   # by VerifyProfile() and CheckPolicyCompliance().
   def PolicyOptValidator(self, hostServices, _notUsed = None):
      assert _notUsed is None, \
             '%s: _notUsed param %s expected None' % (str(self), str(_notUsed))
      if self.lun != '*' and not self.lun.isdigit():
         return LogAndReturnError(self,
                                  PSA_LUN_PARAMETER_IS_NOT_DIGITS_OR_ASTERIX)
      else:
         return (True, [])

   # esxcli options needed to add this policy option to the host
   def GetEsxcliOptionString(self, _notUsed):
      optStr = '--type=target --transport=iscsi --iqn="%s"' % self.iqn
      if self.lun.isdigit():
         #Don't wrap LUN number in quotes because it's numeric
         optStr += ' --lun=%s' % self.lun
      return optStr

#
# Location
#
class LocationPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for PSA Location policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):

      return (True, [])

class LocationPolicyOption(FixedPolicyOption):
   """Policy Option type specifying a location for a PSA claimrule.
   """
   paramMeta = [
      ParameterMetadata('adapterName', 'string', False),
      ParameterMetadata('channel', 'string', False),
      ParameterMetadata('target', 'string', False),
      ParameterMetadata('lun', 'string', False)]

   complianceChecker = LocationPolicyOptComplianceChecker

   # Ensure that parameters other than adapterName are numeric or "*"; checked
   # by VerifyProfile() and CheckPolicyCompliance().
   def PolicyOptValidator(self, hostServices, _notUsed = None):
      assert _notUsed is None, \
             '%s: _notUsed param %s expected None' % (str(self), str(_notUsed))
      if (self.channel != '*' and not self.channel.isdigit()) or \
         (self.target != '*' and not self.target.isdigit()):
         return LogAndReturnError(self,
                                  PSA_LOCATION_PARAMETERS_NOT_DIGITS_OR_ASTERIX)
      elif self.lun != '*' and not self.lun.isdigit():
         return LogAndReturnError(self,
                                  PSA_LUN_PARAMETER_IS_NOT_DIGITS_OR_ASTERIX)
      else:
         return (True, [])

   # esxcli options needed to add this policy option to the host
   def GetEsxcliOptionString(self, _notUsed):
      optStr = '--type=location --adapter="%s"' % self.adapterName
      #Don't wrap channel, target, lun numbers in quotes because they're numeric
      if self.channel.isdigit():
         optStr += ' --channel=%s' % self.channel
      if self.target.isdigit():
         optStr += ' --target=%s' % self.target
      if self.lun.isdigit():
         optStr += ' --lun=%s' % self.lun
      return optStr

#
# Policy option for the PSA Device Sharing policy
#
class PsaDeviceSharingPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for PSA Device Sharing policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the PSA device sharing described by the policy
         option is valid and matches what's on the host
      """

      return (True, [])

class PsaDeviceSharingPolicyOption(FixedPolicyOption):
   """Policy Option type containing sharing info for a PSA device.
   """
   paramMeta = [ ParameterMetadata('deviceName', 'string', False),
                 ParameterMetadata('isSharedClusterwide', 'bool', True) ]

   complianceChecker = PsaDeviceSharingPolicyOptComplianceChecker

   def GetComparisonKey(self):
      return 'deviceName'

   def GetComplianceTaskDict(self):
      '''This will return a dictionary of values that are used during
      compliance error generation. AddInstancesToTaskList() will check if this
      function is available in the policyOption, and fill paramDict with
      returned dictionary values. CheckMyCompliance() will use these to
      generate compliance mismatch errors.
      '''
      complianceTask = {}
      complianceTask['messageCode'] = PSA_MISMATCH_SHARED_CLUSTERWIDE
      complianceTask['messageDict'] = {'Device': self.deviceName}
      complianceTask['comparisonIdentifier'] = "SharedClusterwide"
      complianceTask['hostValue'] = self.isSharedClusterwide
      complianceTask['profileValue'] = self.isSharedClusterwide
      complianceTask['profileInstance'] = self.deviceName
      return complianceTask

   # esxcli options needed to add this policy option to the host
   def GetEsxcliDict(self, _notUsed):
      assert _notUsed is None, \
             '%s: _notUsed param %s expected None' % (str(self), str(_notUsed))

      # This policy option must process all devices, shared clusterwide or not,
      # since otherwise a user cannot change devices back from not shared
      # clusterwide to shared clusterwide without both editing profile and
      # configuring reference host.  We persist sharing state onto hosts so that
      # if more devices that are not shared clusterwide are attached to the
      # reference host and the is profile re-extracted the sharing state is not
      # lost and users do not have to respecify sharing state for old devices.
      # We have eight (8) cases between host and profile, shared clusterwide and
      # not shared clusterwide, and present and absent:
      #
      # If the device is shared clusterwide and device ...
      # 1) is only on host then remediate host (set SharedClusterwide to False).
      #    This can only happen on delete op since there's no profile add op.*
      # 2) is only in profile then attempt to remediate by setting absent host
      #    device SharedClusterwide to True.  Similarly, this can only happen on
      #    the add op. Also, we will want to warn about device not zoned to host.
      # 3) has SharedClusterwide == True in profile and on host then do nothing.
      #    Since the add and delete ops will match the lexical strip compare
      #    will ensure that we do nothing.
      # 4) has SharedClusterwide == True in profile and == False on host, then
      #    remediate host (set SharedClusterwide to True).  This will happen on
      #    the add op and thus the host delete op can be dropped*.
      #
      # If device is not shared clusterwide and device is ...
      # 5) only on host then do nothing.
      # 6) only in profile then do nothing.
      # 7) has SharedClusterwide == False in profile and on host, do nothing**.
      # 8) has SharedClusterwide == False in profile and True on host, then
      #    remediate host (set to SharedClusterwide == False) but this can happen
      #    on the delete op** which will not be dropped since the host device is
      #    shared clusterwide* .
      #
      # * Add op (operation) remediation is only needed for cases where the
      #   profile device is shared clusterwide so we can unconditionally set
      #   device SharedClusterwide == False on the delete operation.  Plus,
      #   delete op is only needed when host device is shared clusterwide
      #   (cases 1) 3) and 8) although 3) will compare identical and thus be
      #   stripped.  This enables us to unconditionally do nothing when the
      #   device has SharedClusterwide == False (either for profile or host).
      #   GetEsxcliDict semantic has been modified so that None may be returned
      #   if no task is required based on device sharing, skipping any lexical
      #   comparison.  This enables us to do nothing for cases 5) and 6) where
      #   otherwise lexical compare would force a profile operation to happen.
      # ** This correctly handles profile application to reference host as well
      #    as false positives due to aliasing errors with local devices with
      #    hba identifiers.  However, it suppresses valid compliance failures
      #    for SAS devices which may be shared JBOD or similar (see PR 1293043).
      #    It also ignores mis-zoning and/or profile editing errors.  A future
      #    PR may address this issue as it is under discussion with host profiles
      #    feature team how profile might determine that it is running on the
      #    reference host.
      #
      if not self.isSharedClusterwide:
         return None

      addOptStr = '--device="%s" --shared-clusterwide="true"' % self.deviceName
      delOptStr = '--device="%s" --shared-clusterwide="false"' % self.deviceName

      # As explained above add operation remediation is only needed when the
      # device is marked shared clusterwide in the profile and marked not
      # shared clusterwide on or is absent from the host.  So add operation
      # unconditionally sets the device to shared clusterwide.  If the device
      # is absent on the host it's a likely zoning error (case 2) otherwise
      # it's probably first application of the profile to this host.  Other
      # shared clusterwide cases above (1 and 3) don't apply as case 1
      # has no add op while case 3 is stripped by the lexical compare.
      assert self.isSharedClusterwide, '%s: not reached' % (str(self))
      addMsgDict = {'Device': self.deviceName,
                    'Params': 'Is Shared Clusterwide = "true"',
                    'Zoning': '(check zoning if device is not present on host)'}
      delMsgDict = {'Device': self.deviceName,
                    'Params': 'Is Shared Clusterwide = "false"'}
      messageDict = MakeMessageDict(PSA_ADD_DEVICE_SHARING_KEY,
                                    PSA_DEL_DEVICE_SHARING_KEY,
                                    addMsgDict, delMsgDict)

      # For this profile we cannot specify the device parameter because that
      # mechanism of stripping depends on the global host and profile device
      # lists that this policy's profile populates.  Also, the requirements here
      # are subtly different in that a host device not in the profile but marked
      # "shared clusterwide" needs remediation whereas any other configuration
      # is a don't care.  So instead use the above logic (cases 1) through 8).
      return  MakeEsxcliDict('storage core', 'device', 'setconfig', \
                             'setconfig', addOptStr, delOptStr, messageDict)

   # Optionally pre-process input dictionaries from GenerateMyProfileFromConfig
   def __init__(self, inputParam):
      if isinstance(inputParam, dict):
         paramList = [ ('deviceName', inputParam['Device'])]
         paramList.append( ('isSharedClusterwide',
                            inputParam['Is Shared Clusterwide']) )

      elif isinstance(inputParam, list):
         paramList = inputParam
      else:
         assert False,                                                     \
                '%s: __init__ inputParam must be a dictionary or a list' % \
                str(self)

      FixedPolicyOption.__init__(self, paramList)


#
# Policy option for the PSA Device Setting policy
#
class PsaDeviceSettingPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for PSA Device Setting policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the PSA device setting described by the policy
         option is valid and matches what's on the host
      """

      return (True, [])

class PsaDeviceSettingPolicyOption(FixedPolicyOption):
   """Policy Option type containing Setting for a PSA device.
   """
   paramMeta = [ ParameterMetadata('deviceName', 'string', False),
                 ParameterMetadata('isPerenniallyReserved', 'bool', True)]

   complianceChecker = PsaDeviceSettingPolicyOptComplianceChecker

   def GetComparisonKey(self):
      return 'deviceName'

   # esxcli options needed to add this policy option to the host
   def GetEsxcliDict(self, _notUsed):
      assert _notUsed is None, \
             '%s: _notUsed param %s expected None' % (str(self), str(_notUsed))
      addOptStr = '--device="%s" --perennially-reserved="%s"' % \
                  (self.deviceName, 'yes' if self.isPerenniallyReserved else 'no')
      delOptStr = '--device="%s" --perennially-reserved="no"' % self.deviceName

      addMsgDict = {'Device': self.deviceName,
                    'Params': 'Is Perennially Reserved = "%s"' % \
                    ('true' if self.isPerenniallyReserved else 'false')}
      delMsgDict = {'Device': self.deviceName}
      messageDict = MakeMessageDict(PSA_ADD_DEVICE_CONFIG_KEY,
                                    PSA_DEL_DEVICE_CONFIG_KEY,
                                    addMsgDict, delMsgDict)

      return  MakeEsxcliDict('storage core', 'device', 'setconfig', 'setconfig',
                 addOptStr, delOptStr, messageDict, dictDevice = self.deviceName)

   # Optionally pre-process input dictionaries from GenerateMyProfileFromConfig
   def __init__(self, inputParam):
      if isinstance(inputParam, dict):
         paramList = [ ('deviceName', inputParam['Device'])]
         paramList.append( ('isPerenniallyReserved', inputParam['Is Perennially Reserved']) )

      elif isinstance(inputParam, list):
         paramList = inputParam
      else:
         assert False,                                                     \
                '%s: __init__ inputParam must be a dictionary or a list' % \
                str(self)

      FixedPolicyOption.__init__(self, paramList)


#
# Policy option for the PSA Device Configuration policy
#
class PsaDeviceConfigurationPolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for PSA Device Configuration policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Checks whether the PSA device configuration described by the policy
         option is valid and matches what's on the host
      """

      return (True, [])

class PsaDeviceConfigurationPolicyOption(FixedPolicyOption):
   """Policy Option type containing configuration for a PSA device.
   """
   paramMeta = [
      ParameterMetadata('deviceName', 'string', False),
      ParameterMetadata('deviceStateOn', 'bool', False),
      ParameterMetadata('queueFullThreshold', 'int', True,
               paramChecker=RangeValidator(0, DEVICE_MAX_QFULL_THRESHOLD)),
      ParameterMetadata('queueFullSampleSize', 'int', True),
      ParameterMetadata('numReqOutstanding', 'int', True,
               paramChecker=RangeValidator(DEVICE_MIN_OUTSTANDING_REQ, DEVICE_MAX_OUTSTANDING_REQ))]

   complianceChecker = PsaDeviceConfigurationPolicyOptComplianceChecker

   # helper function used to collect info for CC error messages
   def GetComparisonKey(self):
      return 'deviceName'

   # esxcli options needed to add this policy option to the host
   def GetEsxcliDict(self, _notUsed):
      assert _notUsed is None, \
             '%s: _notUsed param %s expected None' % (str(self), str(_notUsed))
      addOptStr = '--device="%s" --state="%s" --queue-full-threshold="%d" \
                   --queue-full-sample-size="%d" \
                   --sched-num-req-outstanding="%d"' % \
                  (self.deviceName, 'on' if self.deviceStateOn else 'off',
                   0 if self.queueFullThreshold is None \
                   else self.queueFullThreshold,
                   0 if self.queueFullSampleSize is None \
                   else self.queueFullSampleSize,
                   32 if self.numReqOutstanding is None \
                   else self.numReqOutstanding)
      delOptStr = '--device="%s" --state="on" --queue-full-threshold=0 \
                   --queue-full-sample-size=0' % self.deviceName

      addMsgDict = {'Device': self.deviceName,
                    'Params': 'State = "%s" \
                               Queue Full Sample Size = "%d" \
                               Queue Full Threshold = "%d" \
                               No of outstanding IOs with competing worlds = "%d"' % \
                       ('on' if self.deviceStateOn else 'off',
                        0 if self.queueFullSampleSize is None \
                        else self.queueFullSampleSize,
                        0 if self.queueFullThreshold is None \
                        else self.queueFullThreshold,
                        32 if self.numReqOutstanding is None \
                        else self.numReqOutstanding)}
      delMsgDict = {'Device': self.deviceName}
      messageDict = MakeMessageDict(PSA_ADD_DEVICE_CONFIG_KEY,
                                    PSA_DEL_DEVICE_CONFIG_KEY,
                                    addMsgDict, delMsgDict)

      return MakeEsxcliDict('storage core', 'device', 'set', 'set',
                addOptStr, delOptStr, messageDict, dictDevice = self.deviceName)

   # Optionally pre-process input dictionaries from GenerateMyProfileFromConfig
   def __init__(self, inputParam):
      if isinstance(inputParam, dict):
         paramList = [ ('deviceName', inputParam['Device'])]
         if inputParam['Status'] == 'off':
            paramList.append( ('deviceStateOn', False) )
         else:
            paramList.append( ('deviceStateOn', True) )
         paramList.append( ('queueFullThreshold', inputParam['Queue Full Threshold']) )
         paramList.append( ('queueFullSampleSize', inputParam['Queue Full Sample Size']) )
         paramList.append( ('numReqOutstanding', inputParam['No of outstanding IOs with competing worlds']) )
      elif isinstance(inputParam, list):
         paramList = inputParam
      else:
         assert False,                                                     \
                '%s: __init__ inputParam must be a dictionary or a list' % \
                str(self)

      FixedPolicyOption.__init__(self, paramList)

class PsaBootDevicePolicyOptComplianceChecker(PolicyOptComplianceChecker):
   """A compliance checker type for PSA Boot Device policy option.
   """
   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, hostServices, profileData):
      """Nothing needs to be done for now.
      """

      return (True, [])

#
# Policies
#

# Policy option for the PSA Boot Device policy
class PsaBootDevicePolicyOption(FixedPolicyOption):
   """Policy Option type containing properties for the boot device.
   """
   paramMeta = [
      ParameterMetadata('haveBootDisk', 'bool', False, readOnly=True),
      ParameterMetadata('bootDisk', 'string', False, readOnly=True),
      ParameterMetadata('isLocal', 'bool', False, readOnly=True)]

   complianceChecker = PsaBootDevicePolicyOptComplianceChecker

   # Optionally pre-process input
   def __init__(self, inputParam):
      if isinstance(inputParam, list):
         paramList = inputParam
      elif isinstance(inputParam, tuple):
         haveDisk, bootDisk, isLocal = inputParam
         paramList = [ ('haveBootDisk', haveDisk) ]
         paramList.append( ('bootDisk', bootDisk) )
         paramList.append( ('isLocal', isLocal) )
      else:
         assert False, 'Incorrect input param type received'

      FixedPolicyOption.__init__(self, paramList)

class PsaClaimInformationPolicy(Policy):
   """Define the claim information policy for the PSA Claimrules profile.
   """
   possibleOptions = [ PsaClaimInformationPolicyOption ]

class PsaClaimTypePolicy(Policy):
   """Define the claim type policy for the PSA Claimrules profile.
   """
   possibleOptions = [ DevicePolicyOption,
                       DriverPolicyOption,
                       FcTargetPolicyOption,
                       IscsiTargetPolicyOption,
                       LocationPolicyOption,
                       TransportPolicyOption,
                       VendorModelPolicyOption ]

   # Instantiate policy option based on esxcli output containing a claimrule
   @classmethod
   def GetPolicyOption(cls, esxcliRule, _notUsed = False):
      badMatchesEntry = False
      psaClaimTypePolicyOpt = None

      assert not _notUsed,                                                     \
             '%s: GetPolicyOption boolean param value of True not supported' % \
             str(cls)
      assert isinstance(esxcliRule, dict), \
             '%s: esxcliRule must be a dict' % str(cls)

      # The rule type is specified in the "Type" field but the "Matches" field
      # redundantly includes the type as well as details (e.g., vendor name).
      # (note: transport type would be an exception; see below).
      #
      # For vendor/model rules, whitespace is arbitrary so we can't assume
      # that it delimits anything.  So, use "=" and deduce after the fact.
      # For example, the following is valid "vendor=a b c corp model=f g 1".
      # We initially split on '=' and then rpartition on ' ' to break this
      # into [ ('vendor', 'a b c corp'), ('model','f g 1') ].  We then check
      # this list for valid types (e.g., 'vendor') and create the proper list
      # of parameters for subsequently instantiating the Policy Option.
      if esxcliRule['Type'] == 'vendor':
         if esxcliRule['Matches'].count('=') == 0:
            badMatchesEntry = True
         else:
            rawParams = []
            stage = 0
            for match in esxcliRule['Matches'].split('='):
               if stage == 0:
                  if match.count(' ') != 0:
                     break
                  else:
                     type = match
                     stage = 1
               else:
                  if stage == 3:
                     stage = 4
                     break
                  elif stage == 2:
                     if lastMatch.count(' ') == 0:
                        rawParams.append ( (type, lastMatch) )
                        stage = 3
                     else:
                        param, ignore, newType = lastMatch.rpartition(' ')
                        rawParams.append ( (type, param) )
                        type = newType
                  else:
                     stage = 2
                  lastMatch = match
            if stage == 2:
               rawParams.append ( (type, lastMatch) )
            elif stage != 3:
               badMatchesEntry = True
            if not badMatchesEntry:
               params = []
               for type, param in rawParams:
                  if type == 'vendor':
                     params.append( ('%sName' % type, param) )
                  elif type == 'model':
                     params.append( (type, param) )
                  else:
                     badMatchesEntry = True
                     break
            if not badMatchesEntry:
               psaClaimTypePolicyOpt = VendorModelPolicyOption(params)

      # Format of "Matches" field is "x=y a=b" so check delimeter counts
      elif esxcliRule['Matches'].count('=') != esxcliRule['Matches'].count(' ') + 1:
         badMatchesEntry = True

      # Handle simple types (device, driver, transport)
      elif esxcliRule['Matches'].count(' ') == 0 and \
           esxcliRule['Type'] in ('device', 'deviceuid', 'driver', 'transport'):
         type, match = tuple(esxcliRule['Matches'].split('='))
         if type == esxcliRule['Type'] or \
            (type == 'device' and esxcliRule['Type'] == 'deviceuid'):
            params = [ ('%sName' % type, match) ]
            psaClaimTypePolicyOpt = \
               eval('%sPolicyOption' % type.capitalize())(params)
         else:
            badMatchesEntry = True

      elif esxcliRule['Type'] == 'location' and      \
           esxcliRule['Matches'].count(' ') == 3 and \
           esxcliRule['Matches'].count('=') == 4 and \
           esxcliRule['Matches'][0] != ' ' and       \
           esxcliRule['Matches'][-1] != ' ':
         type = esxcliRule['Type']
         foundLocationParam = { 'adapter': False, 'channel': False, \
                                'target': False, 'lun': False }
         params = []
         for match in esxcliRule['Matches'].split(' '):
            if match.count('=') != 1:
               badMatchesEntry = True
               break
            else:
               what, where = tuple(match.split('='))
               for key in ['adapter', 'channel', 'target', 'lun']:
                  if what == key:
                     if not foundLocationParam[key]:
                        foundLocationParam[key] = True
                        if key == 'adapter':
                           params.append( ('adapterName', where) )
                        else:
                           params.append( (key, where) )
                     else:
                        badMatchesEntry = True
                     break
         for key in ['adapter', 'channel', 'target', 'lun']:
            if not foundLocationParam[key]:
               badMatchesEntry = True
               break
         if not badMatchesEntry:
            psaClaimTypePolicyOpt = LocationPolicyOption(params)

      # Handle target types; these don't have type field redundantly in matches
      elif esxcliRule['Type'] == 'target' and \
           esxcliRule['Matches'].count(' ') < 4:
         params = []
         lastWW = ''
         iqn = ''
         for match in esxcliRule['Matches'].split(' '):
            type, param = tuple(match.split('='))
            if type == 'transport':
               policyOpt = param
               assert policyOpt == 'fc' or policyOpt == 'iscsi',        \
                      '%s: unknown transport type %s for target type' % \
                      (str(cls), policyOpt)
            elif type == 'wwnn' or type == 'wwpn':
               assert lastWW != type,                                     \
                      '%s: fc target requires exactly one %s parameter' % \
                      (str(cls), type)
               params.append( (type, param) )
               lastWW = type if lastWW == '' else ''
            elif type == 'iqn':
               iqn = type if iqn == '' else ''
               params.append( (type, param) )
            elif type == 'lun' and (param == '*' or param.isdigit()):
               params.append( (type, param) )
            else:
               badMatchesEntry = True
         if not badMatchesEntry and                                         \
            (policyOpt == 'fc' and esxcliRule['Matches'].count(' ') == 3 or \
             policyOpt == 'iscsi' and esxcliRule['Matches'].count(' ') == 2):
            assert lastWW == '' and (policyOpt == 'fc' or iqn != ''),      \
                   ('%s: fc target requires both wwnn and wwpn parameters' \
                    if policyOpt == 'fc' else                              \
                    '%s: iscsi target needs iqn parameter') % str(cls)
            psaClaimTypePolicyOpt = \
               eval('%sTargetPolicyOption' % policyOpt.capitalize())(params)
         else:
            badMatchesEntry = True

      # None of the above is an error
      else:
         badMatchesEntry = True

      # If error throw an exception (for now, might warn and skip in future)
      if badMatchesEntry:
         LogAndRaiseException(cls, PSA_ESXCLI_CMD_BADDATA_KEY,
            '"Matches" value "%s" does not match expectations for %s type' %\
            (esxcliRule['Matches'], esxcliRule['Type']))

      return psaClaimTypePolicyOpt

class PsaDeviceSettingPolicy(Policy):
   """Define the policy for the PSA Device Setting Profile.
   """
   possibleOptions = [ PsaDeviceSettingPolicyOption ]

class PsaDeviceSharingPolicy(Policy):
   """Define the policy for the PSA Device Sharing Profile.
   """
   possibleOptions = [ PsaDeviceSharingPolicyOption ]

class PsaDeviceConfigurationPolicy(Policy):
   """Define the policy for the PSA Device Configuration Profile.
   """
   possibleOptions = [ PsaDeviceConfigurationPolicyOption ]

class PsaBootDevicePolicy(Policy):
   """Define the policy for the PSA Device Profile.
   """
   possibleOptions = [ PsaBootDevicePolicyOption ]

#
# Singleton Leaf Profiles
#
class PsaBootDeviceProfile(GenericProfile):
   """A leaf Host Profile that manages the boot device and
      its properties on the ESX host.
   """
   #
   # Define required class attributes
   #
   policies = [ PsaBootDevicePolicy ]

   complianceChecker = None

   singleton = True

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves the boot device.
      """
      bootDisk = vmkctl.SystemInfoImpl().GetBootDevice()
      isLocal = False
      if bootDisk:
         log.info('Found boot disk: %s' % bootDisk)
         cmdOpt = '--device="%s"' % bootDisk
         cmd = ['storage', 'core', 'device', 'list', cmdOpt]
         status, output = hostServices.ExecuteLocalEsxcli(cmd)
         if not status:
            # if it is a USB device just ignore it
            if not output[0]['Is USB']:
               haveDisk = True
               isLocal = output[0]['Is Local']
               return (haveDisk, bootDisk, isLocal)
            else:
               log.info('Found a USB Boot device, skipping')
         else:
            log.warn('Lun for bootdisk %s NOT found' % bootDisk)
      haveDisk = False
      bootDisk = 'None'

      return (haveDisk, bootDisk, isLocal)

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance for the ESX host.
      """
      policyOpt = PsaBootDevicePolicyOption(config)
      policy = PsaBootDevicePolicy(True, policyOpt)
      return cls([policy])

   @classmethod
   def CreateBootMapping(cls, profileInstances, hostServices,
                         config, parent):
      """Internal function used to create the boot device mapping
         Returns status used by GenerateTaskList function
      """
      # First the reference profile
      policy = profileInstances[0].PsaBootDevicePolicy
      policyOpt = policy.policyOption

      assert hasattr(policyOpt, 'haveBootDisk')
      assert hasattr(policyOpt, 'bootDisk')
      assert hasattr(policyOpt, 'isLocal')

      refBootDisk = ''
      refLocal = False
      if policyOpt.haveBootDisk:
         refBootDisk = policyOpt.bootDisk
         refLocal = policyOpt.isLocal
      else:
         # If either or both hosts are stateless we
         # don't want to find any mapping
         return TASK_LIST_RES_OK

      # on the host
      hostBootDisk = ''
      hostLocal = False
      haveBootDisk, bootDisk, isLocal = config
      if haveBootDisk:
         hostBootDisk = bootDisk
         hostLocal = isLocal
      else:
         return TASK_LIST_RES_OK

      # The local-ness attribute of the two disks don't match,
      # can't form an equivalence class
      if refLocal != hostLocal:
         return TASK_LIST_RES_OK

      # We reach here only if ref and target hosts are stateful
      # and 'Is Local' values match
      assert refBootDisk != '' and hostBootDisk != ''

      if refBootDisk == hostBootDisk:
         # if they are non-local devices flag an error.
         if refLocal != True:
            # PR 1237391: Can't flag an error yet. This will result in a
            # host booted from a SAN Lun to become non-compliant with itself
            log.warn('Reference profile\'s boot device %s visible on '
                     'target host. This maybe a zoning problem' % refBootDisk)
         else:
            log.info('Boot devices are local with same names.')
      else:
         # TODO: check if this ref boot disk is seen on the host.

         # check we don't already have mapping with this device
         if refBootDisk not in mappingDict:
            mappingDict[refBootDisk] = hostBootDisk
            log.info('Found a mapping between boot disks '
                     '%s:%s' % (refBootDisk, hostBootDisk))
         else:
            log.warn('Found duplicate mapping for boot disk %s' % refBootDisk)

      return TASK_LIST_RES_OK

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
                        parent):
      """Use this to compare the boot disk on host and on the reference host.
         This will decide how to translate the ref profile policies.
      """
      # Singleton class should have only one object
      assert len(profileInstances) == 1, '%s is a singleton class' % str(cls)

      status = cls.CreateBootMapping(profileInstances, hostServices,
                                     config, parent)
      return status

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Implementation of remediate config that takes the supplied task list
         and adds and/or removes the datastores indicated in the task list.
      """
      pass

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      return True

#
# Compliance checker for PsaBootDeviceProfile
#
class PsaBootDeviceProfileComplianceChecker(ProfileComplianceChecker):
   """A compliance checker type for PsaBootDeviceProfile
   """
   def __init__(self, profileClass):
      self.profileClass = profileClass

   def CheckProfileCompliance(self, profileInsts, hostServices, profileData,
                              parent):
      """Checks whether the boot device configuration is valid.
      """
      profile = self.profileClass
      status = profile.CreateBootMapping(profileInsts, hostServices,
                                         profileData, parent)
      return (True, [])


PsaBootDeviceProfile.complianceChecker = \
      PsaBootDeviceProfileComplianceChecker(PsaBootDeviceProfile)

#
# Non-Singleton Leaf Profiles
#
class PsaDeviceSharingProfile(GenericProfile):
   """A leaf Host Profile that manages PSA device sharing on the ESX host.
   """
   #
   # Define required class attributes
   #
   policies = [ PsaDeviceSharingPolicy ]

   complianceChecker = None

   singleton = False

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves a list of dictionaries, one per PSA device on the host.
         Skip absent devices not shared clusterwide and USB devices except
         USB cdroms.
      """
      # For this profile we ignore USB disk devices (includes flash drives)
      # but not USB CD-ROMs because these are never passed through to guests.
      # Also we can't ignore devices not shared clusterwide because the reference
      # profile might have been revised to recategorize a device previously
      # incorrectly marked as not shared clusterwide to be shared clusterwide.
      # If the old profile was applied to any hosts in the cluster then the
      # device will forever be marked as not shared clusterwide on such hosts
      # absent manual CLI fixup.
      return GatherEsxcliData(cls, hostServices,
                              'storage core', 'device', 'list', '--exclude-offline',
         itemIfFct = (
            lambda x: (x['Is USB'] != True or x['Device Type'][:6] == 'CD-ROM')))

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance per PSA device on the ESX host.
         Also build the global list of host devices.
      """
      # Here we populate the list of host devices which is used by
      # GenerateMyTaskList() helper function RemoveRedundantEntriesFromList().
      for entry in config:
         assert entry['Device'] not in hostDeviceList,      \
                '%s: device %s already in hostDeviceList' % \
                (str(cls), entry['Device'])
         hostDeviceList.append( entry['Device'] )

      return GenerateMyProfileFromConfig(cls, hostServices, config,
                                         PsaDeviceSharingPolicyOption)

   @classmethod
   def CreateSharedDeviceLists(cls, profileInstances):
      for inst in profileInstances:
         policyOpt = inst.policies[0].policyOption
         assert policyOpt.deviceName not in profileSharedClusterwideDeviceList, \
                '%s: device %s already in profileSharedClusterwideDeviceList' % \
                (str(cls), policyOpt.deviceName)
         assert policyOpt.deviceName not in profileNotSharedClusterwideDeviceList, \
                '%s: device %s already in profileNotSharedClusterwideDeviceList' % \
                (str(cls), policyOpt.deviceName)
         if policyOpt.isSharedClusterwide:
            profileSharedClusterwideDeviceList.append( policyOpt.deviceName )
         else:
            profileNotSharedClusterwideDeviceList.append( policyOpt.deviceName )

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
                        parent):
      """Generates a list of the data in the profileInstances.
         Also build global lists of profile devices shared clusterwide and not.
      """
      # Background: GenerateMyTaskList works on pairs of operations when devices
      # are present in profile and on host and on single operations otherwise,
      # respectively adds if the operation is only in profile and deletes if the
      # operation is only on the host.  Comparisons for stripping are lexical.
      # If operations remain after stripping then compliance check fails and
      # profile application has a non-empty set of esxcli commands to execute.
      #
      # Previously local SAS devices were stripped at GatherEsxcliData and thus
      # never were part of the profile nor the visible host data.  All devices
      # that passed this filter were deemed to need to be present both in
      # profile and on host.  Thus single operations as well as non-matching
      # pairs constituted compliance failures requiring remediation.
      #
      # With PR 1178674 and PR 703778 this semantic has broadened to all devices
      # which are not shared between all hosts in the cluster.  Local devices
      # are always set to be not shared "clusterwide" but the user can edit this
      # profile (PsaDeviceSharingProfile) or configure sharing manually on
      # non-local devices on reference host for which an automated tool is also
      # provided (/bin/sharedStorageHostProfile.sh).
      #
      # Here we populate the twin lists profileSharedClusterwideDeviceList and
      # profileNotSharedClusterwideDeviceList used by GenerateMyTaskList()
      # helper function RemoveRedundantEntriesFromList() which can be called
      # from GenerateTaskList for profiles which need to implement own function.
      # We MUST populate these lists before any profile calls GenerateMyTaskList

      cls.CreateSharedDeviceLists(profileInstances)
      # addsOnly must be False, there are cases where only the DEL_OP is present
      return GenerateMyTaskList(cls, profileInstances, taskList, hostServices,
                                config, parent, None,
                                None, False, False, True, False)

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Implementation of remediate config that takes the supplied task list
         and sets the --shared-clusterwise bit as indicated
         in the task list.
      """
      RemediateMyConfig(cls, taskList, hostServices, config, True)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
                                      profileData, validationErrors)

#
# Compliance checker for PsaDeviceSharingProfile
#
class PsaDeviceSharingProfileComplianceChecker(ProfileComplianceChecker):
   """A compliance checker type for PsaDeviceSharingProfile
   """
   def __init__(self, profileClass):
      self.profileClass = profileClass

   def CheckProfileCompliance(self, profileInsts, hostServices, profileData,
                              parent):
      """Checks if the --shared-clusterwide bit is in compliance.
      """
      profile = self.profileClass
      status = profile.CreateSharedDeviceLists(profileInsts)

      msgKeyDict = {'ProfNotFound' : PSA_PROFILE_NOT_FOUND_KEY,
                    'ParamMismatch' : PSA_PROFILE_MISMATCH_PARAM_KEY,
                    'PolicyMismatch' : PSA_PROFILE_POLICY_MISMATCH_KEY,
                    'KeyBase' : PSA_PROFILE_BASE}

      return CheckMyCompliance(profile, profileInsts, hostServices,
                               profileData, parent, msgKeyDict)

PsaDeviceSharingProfile.complianceChecker = \
      PsaDeviceSharingProfileComplianceChecker(PsaDeviceSharingProfile)


class PsaClaimrulesProfile(GenericProfile):
   """A leaf Host Profile that manages PSA claimrules on the ESX host.
   """
   #
   # Define required class attributes
   #
   policies = [ PsaClaimInformationPolicy, PsaClaimTypePolicy ]

   complianceChecker = None

   singleton = False

   dependencies = [ PsaDeviceSharingProfile ]

   sortOrder = [ (PsaClaimInformationPolicy, 'ruleNumber'),
                 (PsaClaimInformationPolicy, 'claimruleClass') ]

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves a list of dictionaries, one per PSA claimrule on
         the host and creates and returns a list of dictionaries, one for
         each PSA user claimrules on the host.
      """
      return GatherEsxcliData(cls, hostServices,
         'storage core', 'claimrule', 'list', '--claimrule-class=all',
         None, None, None, None, (lambda x: x['Class'] == 'file'))

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance per PSA claimrule on the ESX host.
      """
      return GenerateMyProfileFromConfig(cls, hostServices, config,
                                         PsaClaimInformationPolicyOption,
                                         PsaClaimTypePolicy)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
                        parent):
      """Generates a tasklist for the claimrules in the profileInstances.
         We don't compare anything: all rules in the host config are marked
         for deletion while all rules in the profile instances are added.
      """
      tmpTaskList = []

      # GenerateMyTaskList doesn't sort multiple classes of rules before adding

      # Add all filtered rules (user and editable system default rules) to
      # tasklist for deletion.
      for inst in cls.GenerateProfileFromConfig(hostServices, config, parent):
         # Queue an esxcli command to delete the rule
         policyOptInfo = inst.PsaClaimInformationPolicy.policyOption
         policyOptType = inst.PsaClaimTypePolicy.policyOption
         esxcliDict = policyOptInfo.GetEsxcliDict(policyOptType)
         assert esxcliDict is not None,                                 \
            '%s: (Primary) policy option %s must not return None from ' \
            'GetEsxcliDict() method' % (str(cls), str(policyOptInfo))
         messageKey = esxcliDict['MessageDict']['DelKey']
         messageDict = esxcliDict['MessageDict']['DelDict']
         delMsg = MakeTaskMessage(cls, messageKey, messageDict)
         delData = (PSA_OP_DEL, esxcliDict)
         tmpTaskList.append( (delMsg, delData) )
         if hostServices.earlyBoot == True:
            log.info('%s GenerateTaskList: found (expected?) early boot state: %s'
                     % (str(cls), str(esxcliDict)))

      # Make a dictionary by claimrule class of dictionaries by claimrule
      # number of all rules as tuples of the two policy options
      # Check for duplicated rule numbers within a claimrule class
      policyOptMaps = dict()

      for inst in profileInstances:
         policyOptInfo = inst.PsaClaimInformationPolicy.policyOption
         policyOptType = inst.PsaClaimTypePolicy.policyOption
         if policyOptInfo.claimruleClass not in list(policyOptMaps.keys()):
            policyOptMaps[policyOptInfo.claimruleClass] = dict()
         if policyOptInfo.ruleNumber in \
            policyOptMaps[policyOptInfo.claimruleClass]:
            LogAndRaiseException(cls, PSA_DUPLICATE_CLAIM_RULE_NUMBER_KEY,
               {'RuleNumber' : '%d' % policyOptInfo.ruleNumber,
                'ClaimruleClassName' : '%s' % policyOptInfo.claimruleClass})
         policyOptMaps[policyOptInfo.claimruleClass][policyOptInfo.ruleNumber] \
            = (policyOptInfo, policyOptType)

      # Add profile rules in rule number order by claimrule class to tasklist
      for policyOptMapKey in policyOptMaps:
         for psaPolicyOptKey in sorted(policyOptMaps[policyOptMapKey].keys()):
            psaPolicyOptValue = policyOptMaps[policyOptMapKey][psaPolicyOptKey]
            esxcliDict = psaPolicyOptValue[0].GetEsxcliDict(psaPolicyOptValue[1])
            messageKey = esxcliDict['MessageDict']['AddKey']
            messageDict = esxcliDict['MessageDict']['AddDict']
            addMsg = MakeTaskMessage(cls, messageKey, messageDict)
            addData = (PSA_OP_ADD, esxcliDict)
            tmpTaskList.append( (addMsg, addData) )

      # If the stripped list is empty then we're done (no state change)
      strippedList = RemoveRedundantEntriesFromList(cls, tmpTaskList)
      if len(strippedList) == 0:
         return TASK_LIST_RES_OK
      else:
         log.info('%s GenerateTaskList: stripped length %d, full length %d' %
                  (str(cls), len(strippedList), len(tmpTaskList)))
         # At early boot claiming is not yet turned on so use the stripped list
         if hostServices.earlyBoot == True:
            for modMsg, modData in strippedList:
               taskList.addTask(modMsg, modData)
               psaOp, esxcliDict = modData
               if psaOp == PSA_OP_DEL:
                  log.debug('%s GenerateTaskList: found early boot stripped state: %s'
                           % (str(cls), str(modData)))
            # At early boot claiming is not yet turned on so no reboot is needed
            return TASK_LIST_RES_OK

         # After early boot claiming is on so must clear out all old rule state
         # before adding new rules and then require a reboot after profile apply
         else:
            for modMsg, modData in tmpTaskList:
               taskList.addTask(modMsg, modData)
            return TASK_LIST_RES_OK

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, config):
      """Implementation of remediate config that takes the supplied task list
         and adds and/or removes the NAS datastores indicated in the task list.
      """
      RemediateMyConfig(cls, taskList, hostServices, config)
      cls._ReclaimPSAClaimrules(cls, hostServices)

   @classmethod
   def VerifyProfile(cls, profileInstance, hostServices, profileData,
                     validationErrors):
      return VerifyMyProfilesPolicies(cls, profileInstance, hostServices,
                                      profileData, validationErrors)

   def _ReclaimPSAClaimrules(cls, hostServices):
      '''Execute claimrule load and run after psa rules were
      added by RemediateMyConfig(). Skip "claimrule run" for earlyBoot since
      claiming is already disabled by PSA-boot-config.json when
      PsaClaimrulesProfile is called from psa-load-rules.json.
      '''
      log.debug('%s RemediateConfig: Reclaiming PSA claimrules' %
                (str(cls)))
      RunEsxcli(cls, hostServices, 'storage core', 'claimrule', 'load', '')
      if not hostServices.earlyBoot:
         RunEsxcli(cls, hostServices, 'storage core', 'claimrule', 'run', '')

PsaClaimrulesProfile.complianceChecker = \
   PsaProfileComplianceChecker(PsaClaimrulesProfile)


class PsaDeviceSettingProfile(GenericProfile):
   """A leaf Host Profile that manages PSA device setting on the ESX host.
   """
   #
   # Define required class attributes
   #
   policies = [ PsaDeviceSettingPolicy ]

   complianceChecker = None

   singleton = False

   dependencies = [ PsaBootDeviceProfile, PsaDeviceSharingProfile ]

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves a list of dictionaries, one per PSA device on the host.
      """
      return GatherEsxcliData(cls, hostServices,
                              'storage core', 'device', 'list', '--exclude-offline',
         itemIfFct = (
            lambda x: (x['Is USB'] != True or x['Device Type'][:6] == 'CD-ROM')))

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance per PSA device on the ESX host.
      """
      return GenerateMyProfileFromConfig(cls, hostServices, config,
                                         PsaDeviceSettingPolicyOption)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
                        parent):
      """Generates a list of the data in the profileInstances.
      """
      return GenerateMyTaskList(cls, profileInstances, taskList, hostServices,
                                config, parent, GetTranslatedTaskList,
                                None, False, False, True, True)

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

PsaDeviceSettingProfile.complianceChecker = \
      PsaProfileComplianceChecker(PsaDeviceSettingProfile, GetTranslatedTaskList)


class PsaDeviceConfigurationProfile(GenericProfile):
   """A leaf Host Profile that manages PSA device configuration on the ESX host.
   """
   #
   # Define required class attributes
   #
   policies = [ PsaDeviceConfigurationPolicy ]

   complianceChecker = None

   singleton = False

   dependencies = [ PsaBootDeviceProfile, PsaDeviceSharingProfile ]

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves a list of dictionaries, one per PSA device on the host.
         Skip absent devices not shared clusterwide and USB devices except
         for USB cdroms.
      """
      return GatherEsxcliData(cls, hostServices,
                              'storage core', 'device', 'list', '--exclude-offline',
         itemIfFct = (
            lambda x: (x['Is USB'] != True or x['Device Type'][:6] == 'CD-ROM')))

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, config, parent):
      """Retrieves one profile instance per PSA device on the ESX host.
      """
      return GenerateMyProfileFromConfig(cls, hostServices, config,
                                         PsaDeviceConfigurationPolicyOption)

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, config,
                        parent):
      """Generates a list of the data in the profileInstances.
      """
      return GenerateMyTaskList(cls, profileInstances, taskList, hostServices,
                                config, parent, GetTranslatedTaskList,
                                None, False, False, True, True)

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

PsaDeviceConfigurationProfile.complianceChecker = \
      PsaProfileComplianceChecker(PsaDeviceConfigurationProfile, GetTranslatedTaskList)

#
# Parent Profiles
#
class PluggableStorageArchitectureProfile(GenericProfile):
   """A Host Profile that manages Pluggable Storage Architecture (PSA) on the ESX host.
   """
   #
   # Define required class attributes
   #
   subprofiles = [
                   PsaDeviceSharingProfile,
                   PsaClaimrulesProfile,
                   PsaDeviceSettingProfile,
                   PsaDeviceConfigurationProfile,
                   PsaBootDeviceProfile ]

   parentProfiles = [ StorageProfile ]

   singleton = True

   category = CATEGORY_STORAGE
   component = COMPONENT_CORE_STORAGE

