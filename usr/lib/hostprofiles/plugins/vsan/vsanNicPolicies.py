#!/usr/bin/python
# **********************************************************
# Copyright 2013-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import Policy, FixedPolicyOption, \
                      ParameterMetadata, PolicyOptComplianceChecker, \
                      CreateLocalizedMessage, log, \
                      CreateComplianceFailureValues, \
                      TASK_LIST_REQ_REBOOT, TASK_LIST_REQ_MAINT_MODE, \
                      TASK_LIST_RES_OK, PARAM_NAME

from pluginApi.extensions import IpAddressValidator

from pyEngine import networkprofile


from .vsanConstants import *



###
### Vmkernel portgroup policy
###

# Ancillary routine to check compliance and generate remediation task list
def VSANNicComplianceAndTask(policyOpt, profileData, taskList):
   log.debug('in nics complianceandtask')

   complianceErrors = []
   taskResult = TASK_LIST_RES_OK

   desiredNic = policyOpt.VmkNicName
   log.debug('checking for nic %s' % desiredNic)

   # Find the corresponding actual nic
   actualNics = profileData
   for actualNic in actualNics:
      if actualNic['VmkNicName'] == desiredNic:
         # Check all parameters
         for paramName, desired in policyOpt.paramValue:
            log.debug('examining %s' % paramName)
            log.debug('desired is %s, actual is %s' % \
                                                (desired, actualNic[paramName]))
            if paramName == 'TrafficType':
               # Drop duplicated value
               actValue = set([val.strip() for val in actualNic[paramName].split(',')])
               desValue = set([val.strip() for val in desired.split(',')])
            else:
               actValue = actualNic[paramName]
               desValue = desired
            if actValue != desValue \
                  and paramName in VSAN_NIC_OPTIONS:
               log.debug('mismatch for %s' % paramName)
               if taskList:
                  msg = CreateLocalizedMessage(None, VSAN_NIC_TASK_KEY,
                           {'paramName': paramName, 'VmkNicName': desiredNic})
                  paramOption = VSAN_NIC_OPTIONS[paramName]
                  taskList.addTask(msg,
                            (VSAN_NIC_TASK, (desiredNic, paramOption, desired)))
               else:
                  msg = CreateLocalizedMessage(None, VSAN_NIC_COMPLIANCE_KEY,
                             {'paramName': paramName, 'VmkNicName': desiredNic})
                  comparisonValues = CreateComplianceFailureValues(
                     paramName, PARAM_NAME, profileValue=desired,
                     profileInstance=desiredNic,
                     hostValue=actualNic[paramName])
                  complianceErrors.append((msg, [comparisonValues]))
         # Done checking the parameters
         break

   # NOTE: We don't check if there is another actual nic with the same name
   # since the system should ensure that it is impossible.
   #
   # NOTE: We do not report non-compliance here if we cannot find the actual
   # nic. Matching sets of desired nics and actual nics is done at the profile
   # level.

   if taskList:
      return taskResult
   else:
      return complianceErrors

#
class VSANNicComplianceChecker(PolicyOptComplianceChecker):

   @classmethod
   def CheckPolicyCompliance(cls, profile, policyOpt, \
                                                   hostServices, profileData):
      # Called implicitly
      log.debug('in nics compliancechecker')

      complianceErrors = VSANNicComplianceAndTask(policyOpt, profileData, None)

      return (len(complianceErrors) == 0, complianceErrors)

# Ancillary routine to validate special inputs
class VSANIpProtocolValidator:

   @staticmethod
   def Validate(policyOpt, name, value, errors):
      # Called implicitly
      log.debug('in VSANIpProtocolValidator for %s' % name)

      # Allow IPv4 and IP for now
      if value not in VSAN_SUPPORTED_IPPROTOCALS:
         msg = CreateLocalizedMessage(None, VSAN_IPPROTOCOL_ERROR_KEY)
         errors.append(msg)
         return False

      return True

# Validate traffic type for specific vmknic
class VSANTrafficTypeValidator:

   @staticmethod
   def Validate(policyOpt, name, value, errors):
      # Called implicitly
      log.debug('in VSANTrafficTypeValidator for %s' % name)

      # Allow vsan and witness for now, and valie compositions are:
      # vsan; witness; vsan,witness; total three.
      vals = set([val.strip() for val in value.split(',')])
      for val in vals:
         if val not in VSAN_SUPPORTED_TRAFFICTYPES:
            msg = CreateLocalizedMessage(None, VSAN_TRAFFICTYPE_ERROR_KEY)
            errors.append(msg)
            return False

      return True

#
class VSANNicOption(FixedPolicyOption):
   paramMeta = [
                  ParameterMetadata('VmkNicName', 'string',
                                    False, VSAN_DEFAULT_VMKNICNAME),
                  ParameterMetadata('IPProtocol', 'string',
                                    False, VSAN_DEFAULT_IPPROTOCOL,
                                    VSANIpProtocolValidator),
                  ParameterMetadata('AgentGroupMulticastAddress', 'string',
                                    True, VSAN_DEFAULT_AGENTMCADDR,
                                    IpAddressValidator),
                  ParameterMetadata('AgentGroupMulticastPort', 'int',
                                    True, VSAN_DEFAULT_AGENTMCPORT),
                  ParameterMetadata('MasterGroupMulticastAddress', 'string',
                                    True, VSAN_DEFAULT_MASTERMCADDR,
                                    IpAddressValidator),
                  ParameterMetadata('MasterGroupMulticastPort', 'int',
                                    True, VSAN_DEFAULT_MASTERMCPORT),
                  ParameterMetadata('MulticastTTL', 'int',
                                    True, VSAN_DEFAULT_MCTTL),
                  ParameterMetadata('AgentGroupIPv6MulticastAddress', 'string',
                                    True, VSAN_DEFAULT_IPV6_AGENTMCADDR,
                                    IpAddressValidator),
                  ParameterMetadata('MasterGroupIPv6MulticastAddress', 'string',
                                    True, VSAN_DEFAULT_IPV6_MASTERMCADDR,
                                    IpAddressValidator),
                  ParameterMetadata('TrafficType', 'string',
                                    True, VSAN_DEFAULT_TRAFFICTYPE,
                                    VSANTrafficTypeValidator),
               ]

   complianceChecker = VSANNicComplianceChecker

   @classmethod
   def CreateOption(cls, profileData):
      optParams = [('VmkNicName', profileData['VmkNicName']),
                   ('IPProtocol', profileData['IPProtocol']),
                   ('AgentGroupMulticastAddress', \
                                  profileData['AgentGroupMulticastAddress']),
                   ('AgentGroupMulticastPort', \
                                  profileData['AgentGroupMulticastPort']),
                   ('MasterGroupMulticastAddress', \
                                  profileData['MasterGroupMulticastAddress']),
                   ('MasterGroupMulticastPort', \
                                  profileData['MasterGroupMulticastPort']),
                   ('MulticastTTL', profileData['MulticastTTL']),
                   ('AgentGroupIPv6MulticastAddress', \
                                  profileData['AgentGroupIPv6MulticastAddress']),
                   ('MasterGroupIPv6MulticastAddress', \
                                  profileData['MasterGroupIPv6MulticastAddress']),
                   ('TrafficType', profileData['TrafficType']),
                  ]
      return cls(optParams)

   # Ancillary routine to create a string covering all the parameters associated
   # with a nic as used in the "esxcli vsan network ip add" command.
   @classmethod
   def BuildParams(cls, policyOpt):
      log.debug('in nics build params')

      nicName = policyOpt.VmkNicName
      log.debug('building for nic %s' % nicName)

      if policyOpt.IPProtocol not in VSAN_SUPPORTED_IPPROTOCALS:
         log.error('Unsupported IP Protocol %s' % policyOpt.IPProtocol)
         raise CreateLocalizedException(None, VSAN_BADIPPROTOCOL_FAIL_KEY)

      allCmds = []
      for paramName, desired in policyOpt.paramValue:
         log.debug('examining %s' % paramName)
         if paramName in VSAN_NIC_OPTIONS:
            # Option traffic-type might contain multi values, valid composition
            # vsan; witness; vsan,witness; total three
            # So here we should split desired value, to parse actual traffic
            # types;
            # And multi-value option for esxcli should follow style as:
            # --option value1 --option value2.
            if paramName == 'TrafficType':
               # Use set to drop duplicated value, even esxcli could handle this.
               vals = set([val.strip() for val in desired.split(',')])
               for val in vals:
                  cmd = '--%s=%s' % (VSAN_NIC_OPTIONS[paramName], val)
                  allCmds.append(cmd)
            else:
               cmd = '--%s=%s' % (VSAN_NIC_OPTIONS[paramName], desired)
               allCmds.append(cmd)

      params = ' '.join(allCmds)
      log.debug('resulting command is %s' % params)

      return params

#
# Main class
#
# !!! All methods must be called explicitly from the profile's corresponding
# methods.
#
class VSANNicPolicy(Policy):
   possibleOptions = [
                        VSANNicOption
                     ]

   @classmethod
   def CreatePolicy(cls, profileData):
      policyOpt = cls.possibleOptions[0].CreateOption(profileData)
      return cls(True, policyOpt)

   @classmethod
   def GenerateTaskList(cls, policy, taskList, profileData, parent):
      log.debug('in nics generate tasklist')
      policyOpt = policy.policyOption

      result = VSANNicComplianceAndTask(policyOpt, profileData, taskList)

      return result

   @classmethod
   def VerifyPolicy(cls, policy, profileData, validationErrors):
      log.debug('in nics verify policy')

      # XXX Is there any cross-parameter consistency checks to perform ?

      return True
