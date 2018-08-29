#!/usr/bin/python
# **********************************************************
# Copyright 2014-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


from pluginApi import GenericProfile, Policy, FixedPolicyOption, \
                      ParameterMetadata, PolicyOptComplianceChecker, \
                      UserInputRequiredOption, ProfileComplianceChecker, \
                      CreateLocalizedMessage, log

import pdb
import os
import pprint
import ipaddress
from ipaddress import AddressValueError
from .iscsiCommonUtils import *
from hpCommon.constants import RELEASE_VERSION_2015

try:
   unicode
except NameError:
   unicode = str

# Return if the profile is disabled or not
def isDisabledInitiatorProfile(profInst):
   disabled = ExtractPolicyOptionValue(profInst,
                  IscsiSoftwareInitiatorSelectionPolicy,
                  [([IscsiInitiatorSelectionDisabled], FROM_ATTRIBUTE, 'disabled')],
                  False)

   return disabled == True

#
# Return if the param is settable or not
#
def IsSettable(param):
   if isinstance(param, tuple):
      tstParam = param[0]
   else:
      tstParam = param

   if isinstance(tstParam, str) and tstParam == 'SettingNotSupported':
      return False

   return True

#
# Policy/PolicyOption verifiers
#
def GenericVerifyPolicyOption():
   return False

#
# Generic verify procuedure that calls VerifyPolicyOption procedure of the
# current policyOption of a policy.
#
def GenericVerifyPolicy(policy,
                        profileInstance,
                        hba,
                        forApply,
                        validationErrors):
   failed = False

   policyOpt = policy.policyOption
   if hasattr(policyOpt, 'VerifyPolicyOption'):
      failed |= policyOpt.VerifyPolicyOption(policy,
                                             profileInstance,
                                             hba,
                                             forApply,
                                             validationErrors)

   return failed

#
# Verifies if the selected hba profile is valid or not.
#
# Returns:
#  True if not OK
#  False if it is OK
#
def VerifyHbaProfileInstance(policyOpt,
                             policy,
                             profileInstance,
                             validationErrors):
   failed = False

   if (not hasattr(policyOpt, 'macAddress')) or \
       policyOpt.macAddress == None or \
       len(policyOpt.macAddress) == 0:
      failed = True
      IscsiCreateLocalizedMessage(profileInstance,
         ISCSI_ERROR_EMPTY_PARAM_NOT_ALLOWED,
         {'param': 'macAddress',
          'policy': policy.__class__.__name__},
         validationErrors)
   else:
      hba = GetIscsiHbaFromProfile(None, profileInstance, False)
      if hba is None:
         failed = True
         IscsiCreateLocalizedMessage(profileInstance,
            ISCSI_ERROR_NO_HBA_SELECTED,
            {}, validationErrors)

         #EnterDebugger()

   return failed

#
# Helper function to convert a given value to a Policy option
#
def ParamValueToPolicyOption(policyOptClass,
                             param,
                             value):
   if isinstance(value, str):
      if value == 'SettingNotSupported':
         return SettingNotSupported([])
      elif value == 'InheritFromParent':
         return InheritFromParent([])

   return policyOptClass([(param, value)])

#
# Validators Helper functions
#

#
# Validate IPv4 or v6 address to be in correct format.
#
# The list of ip versions to be validated can be given
# as an argument (ipVersions).
#
# Arguments:
#  obj: Generic object to which the IP address belongs.
#  argName: The param name
#  arg: The param value to be validated
#  errors: In case of validation failure, the errors will be attached to this
#  msgKey: The key for message
#  msgArg: The args to the msg
#  ipVersions: List of IP versions to be validated
#
# Returns:
#  True if the IP is OK
#  False if the IP is not OK
#
def ValidateIPAddress(obj,
                      argName,
                      arg,
                      errors,
                      msgKey,
                      msgArg,
                      ipVersions):
   try:
      return ipaddress.ip_address(arg).version in ipVersions
   except ValueError:
      if msgKey:
         IscsiCreateLocalizedMessage(obj, msgKey, msgArg, errors)
   return False

#
# Caller should pass a valid IPv6 address
#
def ValidateLinkLocalAddress(obj,
                             argName,
                             arg,
                             errors,
                             msgKey,
                             msgArg):
   try:
      return ipaddress.IPv6Address(arg).is_link_local
   except AddressValueError:
      if msgKey:
         IscsiCreateLocalizedMessage(obj, msgKey, msgArg, errors)
      return False

#
# Function to validate IPv4 address
#
class IscsiIPv4AddressValidator:
   @staticmethod
   def Validate(obj, argName, arg, errors):
      return ValidateIPAddress(obj, argName, arg, errors,
                                 ISCSI_INVALID_IPV4_ADDRESS,
                                 {'paramName': argName}, [4])

#
# Function to validate IPv4 address
# All bit zero or null IPv4 address is not allowed
#
class IscsiIPv4ConfigAddressValidator:
   @staticmethod
   def Validate(obj, argName, arg, errors):
      try:
         ipAddress = ipaddress.ip_address(arg)
         if ipAddress.version == 4:
            if ipaddress.ip_address('0.0.0.0') == ipAddress:
               IscsiCreateLocalizedMessage(obj,
                   ISCSI_INVALID_IPV4_ADDRESS,
                   {'paramName': argName}, errors)
               return False

            return True
      except:
         pass

      IscsiCreateLocalizedMessage(obj,
         ISCSI_INVALID_IPV4_ADDRESS,
         {'paramName': argName}, errors)
      return False

#
# Function to validate IPv4 netmask
#
class IscsiIpv4NetmaskValidator:
   @staticmethod
   def Validate(obj, argName, arg, errors):
      return ValidateIPAddress(obj, argName, arg, errors,
                                 ISCSI_INVALID_IPV4_NETMASK,
                                 {'paramName': argName}, [4])

#
# Function to validate IPv4 gateway address
#
class IscsiIpv4GatewayValidator:
   @staticmethod
   def Validate(obj, argName, arg, errors):
      try:
         ipAddress = ipaddress.ip_address(arg)
         if ipAddress.version == 4:
            if ipaddress.ip_address('0.0.0.0') == ipAddress:
               IscsiCreateLocalizedMessage(obj,
                   ISCSI_INVALID_IPV4_GATEWAY,
                   {'paramName': argName}, errors)
               return False

            return True
      except:
         pass

      IscsiCreateLocalizedMessage(obj,
         ISCSI_INVALID_IPV4_GATEWAY,
         {'paramName': argName}, errors)
      return False

#
# function to validate IPv4 port number
#
class IscsiTcpPortNumberValidator:
   @staticmethod
   def Validate(obj, argName, arg, errors):
      try:
         value=int(arg)
         if value >= 1 and value <= (1<<16)-1:
            return True
      except:
         pass

      IscsiCreateLocalizedMessage(obj,
                  ISCSI_INVALID_TCP_PORT_NUMBER,
                  {'paramName': argName}, errors)
      return False

#
# Function to validate both IPv4 and v6 address
#
class IscsiIPAddressValidator:
   @staticmethod
   def Validate(obj, argName, arg, errors):
      return ValidateIPAddress(obj, argName, arg, errors,
                               ISCSI_INVALID_IP_ADDRESS,
                               {'paramName': argName}, [4,6])

#
# Function to validate IPv6 address
#
class IscsiIPv6AddressValidator:
   @staticmethod
   def Validate(obj, argName, arg, errors):
      # for now empty ipv6 is accepted as it's optional on independent hw iscsi
      if arg == '':
         return True
      return ValidateIPAddress(obj, argName, arg, errors,
                                 ISCSI_INVALID_IPV6_ADDRESS,
                                 {'paramName': argName}, [6])

#
# Validate IPv6 address.
#
def ValidateIPv6ConfigAddress(obj,
                              argName,
                              arg,
                              errors,
                              msgArg):
   try:
      ipAddressObj = ipaddress.ip_address(arg)
      if ipAddressObj.version == 6:
         if ipaddress.ip_address('::') == ipAddressObj:
            IscsiCreateLocalizedMessage(obj,
                ISCSI_INVALID_IPV6_ADDRESS,
                {'paramName': argName}, errors)
            return False

         if ipAddressObj.is_link_local:
            IscsiCreateLocalizedMessage(obj,
                ISCSI_LINKLOCAL_ADDRESS_NOT_ALLOWED,
                {'paramName': argName}, errors)
            return False

         return True
   except:
      pass

   IscsiCreateLocalizedMessage(obj,
      ISCSI_INVALID_IPV6_ADDRESS,
      {'paramName': argName}, errors)

   return False

#
# Validate IPv6 prefix length
#
def ValidateIpv6ConfigPrefixLen(obj,
                                argName,
                                arg,
                                errors,
                                msgArg):
   try:
      value=int(arg)
      if value >= 1 and value <= 128:
         return True
   except:
      pass

   IscsiCreateLocalizedMessage(obj,
               ISCSI_INVALID_IPV6_PREFIX,
               {'paramName': argName}, errors)
   return False

#
# Function to validate IPv6 address list.
# The list is in format X:X:X::X/X,X:X:X::X/X
# None of the address in the list should be link-local
#
class IscsiIPv6ConfigAddressValidator:
   @staticmethod
   def Validate(obj, argName, arg, errors):
      if arg == '':
         return True
      addrList = arg.split(",")
      for x in addrList:
         addrSplit = x.split("/")
         if len(addrSplit) == 2:
            addr = addrSplit[0]
            prefix = addrSplit[1]
            if ValidateIPv6ConfigAddress(obj, argName, addr, errors,
               {'paramName': argName}) == False:
               return False
            if ValidateIpv6ConfigPrefixLen(obj, argName, prefix, errors,
               {'paramName': argName}) == False:
               return False
         else:
            IscsiCreateLocalizedMessage(obj,
               ISCSI_INVALID_IPV6_ADDRESS,
               {'paramName': argName}, errors)
            return False

      return True

#
# Function to validate IPv6 Linklocal address
#
class IscsiLinklocalAddressValidator:
   @staticmethod
   def Validate(obj, argName, arg, errors):
      if ValidateIPAddress(obj, argName, arg, errors,
                           ISCSI_INVALID_IPV6_ADDRESS,
                           {'paramName': argName}, [6]) == True:
         return ValidateLinkLocalAddress(obj, argName, arg, errors,
                                         ISCSI_INVALID_LINKLOCAL_ADDRESS,
                                         {'paramName': argName})
      else:
         return False

#
# Function to validate IPv6 gateway
# All bits zero address is not allowed
#
class IscsiIPv6GatewayValidator:
   @staticmethod
   def Validate(obj, argName, arg, errors):
      try:
         ipAddress = ipaddress.ip_address(arg)
         if ipAddress.version == 6:
            if ipaddress.ip_address('::') == ipAddress:
               IscsiCreateLocalizedMessage(obj,
                   ISCSI_INVALID_IPV6_GATEWAY,
                   {'paramName': argName}, errors)
               return False

            return True
         else:
            IscsiCreateLocalizedMessage(obj,
                     ISCSI_INVALID_IPV6_GATEWAY,
                     {'paramName': argName}, errors)
            return False
      except:
         pass

      IscsiCreateLocalizedMessage(obj,
         ISCSI_INVALID_IPV6_GATEWAY,
         {'paramName': argName}, errors)
      return False

#
# Function to validate IPv6 prefix
#
class IscsiIPv6PrepixValidator:
   @staticmethod
   def Validate(obj, argName, arg, errors):
      return True

class IscsiStringNonEmptyValidator:
   @staticmethod
   def Validate(self, argName, arg, errors):
      if not isinstance(arg, str) and not isinstance(arg, unicode):
         IscsiCreateLocalizedMessage(self,
               ISCSI_INVALID_PARAM_TYPE,
               {'paramName': argName},
               errors)
         return False
      elif arg is None or arg == '':
         IscsiCreateLocalizedMessage(self,
               ISCSI_ERROR_EMPTY_PARAM_NOT_ALLOWED,
               {'policy': self.__class__.__name__,
                'param': argName},
               errors)
         return False
      return True

class IscsiRangeValidator:
   def __init__(self, rangeMin, rangeMax):
      self.rangeMin = rangeMin
      self.rangeMax = rangeMax

   def Validate(self, obj, argName, arg, errors):
      if not isinstance(arg, int):
         IscsiCreateLocalizedMessage(obj,
               ISCSI_INVALID_PARAM_TYPE,
               {'paramName': argName},
               errors)
         return False
      if arg < self.rangeMin or arg > self.rangeMax:
         IscsiCreateLocalizedMessage(obj,
               ISCSI_INVALID_VALUE_OUT_OF_RANGE,
               {'minValue': self.rangeMin,
                'maxValue': self.rangeMax},
               errors)
         return False
      return True

#
# Valitator function that always returns success (dummy validator)
#
class AlwaysSuccessValidator:
   @staticmethod
   def Validate(self, argName, arg, errors):
      IscsiLog(3, 'AlwaysSuccessValidator: argName=%s arg=%s' % (argName, arg))
      #EnterDebugger()

      return True

#
# Validator function that checks for empty
#
def CheckEmptyString(obj, stringAttr, msgKey, msgArg, errors):
   failed =False

   if stringAttr == None or \
      len(stringAttr) == 0:
      if errors:
         IscsiCreateLocalizedMessage(obj, msgKey, msgArg, errors)
      failed = True

   return failed

#
# Verify the chap parameters
#
# Arguments:
#  profileInstance: An instance of the profile
#  hba: iSCSI Adapter object
#  policy: policy to be validated
#  policyOpt: policy Option to be validated
#  paramName:
#  msgKey: Message key incase the validation error to be added
#  msgArg: Args to the message key
#  validationErrors: In case validation error to be added
#
# Returns:
#  True if the validator failed
#  False if the validation is success
#
def VerifyChapParam(profileInstance,
                    hba,
                    policy,
                    policyOpt,
                    paramName,
                    msgKey,
                    msgArg,
                    validationErrors):

   # Build a dependency map for chap selection policy
   chapDependencyMap = [
      (
         [Hba_InitiatorChapNameSelectionPolicy,
          Hba_InitiatorChapSecretSelectionPolicy
         ], Hba_InitiatorChapTypeSelectionPolicy
      ),
      (  [Hba_TargetChapNameSelectionPolicy,
          Hba_TargetChapSecretSelectionPolicy
         ], Hba_TargetChapTypeSelectionPolicy
      ),
      (  [Target_InitiatorChapNameSelectionPolicy,
          Target_InitiatorChapSecretSelectionPolicy
         ], Target_InitiatorChapTypeSelectionPolicy
      ),
      (  [Target_TargetChapNameSelectionPolicy,
          Target_TargetChapSecretSelectionPolicy
         ], Target_TargetChapTypeSelectionPolicy
      ),
   ]

   IscsiLog(4, 'VerifyChapParam: policy=%s option=%s param=%s value=%s' % \
      (policy.__class__.__name__,
       policyOpt.__class__.__name__, paramName,
       unicode(getattr(policyOpt, paramName))))

   # Assume no failure
   failed = False

   # Get the policy class which will be used to get the
   # corresponding chap selection policy option
   policyClass = policy.__class__

   # Search for the chap type selection policy
   for dep in chapDependencyMap:
      if policyClass in dep[0]:
         checkPolicyName = dep[1].__name__

   # Get the chap selection policy
   checkPolicyOpt = getattr(profileInstance,
                            checkPolicyName).policyOption

   # If the policy option is to use chap,
   # then verify that chap name and secret
   # is not empty.
   if not isinstance(checkPolicyOpt,
                     (DoNotUseChap, InheritFromParent, SettingNotSupported)):
      attrValue = getattr(policyOpt, paramName)
      if isinstance(attrValue, Vim.PasswordField):
         attrValue = attrValue.value

      assert isinstance(attrValue, str) or isinstance(attrValue, unicode), \
         'Param Value is not a string'

      failed = CheckEmptyString(profileInstance,
                                attrValue,
                                msgKey, msgArg,
                                None)
      if failed:
         policyOpt.SetParameterRequired(paramName)
         IscsiLog(3, 'VerifyChapParam: Failed verification for ' + \
                     'policy=%s option=%s param=%s value=%s' % \
                     (policy.__class__.__name__,
                     policyOpt.__class__.__name__, paramName,
                     unicode(getattr(policyOpt, paramName))))

   return failed

#
# IPv4 Configuration for independent iSCSI adapter
#
class Ipv4Config:
   def __init__(self, ignore = None, enabled = None, useDhcp = None, address = '',
      subnet = '', gateway = ''):
      self.ignore = ignore
      self.enabled = enabled
      self.useDhcp = useDhcp
      self.address = address
      self.subnet = subnet
      self.gateway = gateway

#
# IPv6 Configuration for independent iSCSI adapter
#
class Ipv6Config:
   def __init__(self, ignore = None, supported = None, enabled = None, useDhcp6 = None,
      useRouterAdv = None, ipv6AddressOriginal = '', ipv6AddressModified = '', gateway6 = '',
      globalAddrCount = 0):
      self.ignore = ignore
      self.supported = supported
      self.enabled = enabled
      self.useDhcp6 = useDhcp6
      self.useRouterAdv = useRouterAdv
      self.ipv6AddressOriginal = ipv6AddressOriginal    # in format ipv6/prefix,ipv6/prefix
      self.ipv6AddressModified = ipv6AddressModified
      self.gateway6 = gateway6
      self.globalAddrCount = globalAddrCount

#
# linklocal Configuration for independent iSCSI adapter
#
class LinklocalConfig:
   def __init__(self, ignore = None, useLinklocalAutoConf = None, linklocalAddr = ''):
      self.ignore = ignore
      self.useLinklocalAutoConf = useLinklocalAutoConf
      self.linklocalAddr = linklocalAddr

#
# IP capabilities for independent iSCSI adapter
#
class IpCapabilties:
   def __init__(self, ipv4Enable = None, ipv6Enable = None, ipv6RouterAdv = None,
      dhcpv6 = None, linklocalAuto = None, prefixLen = None, maxIpv6AddrSupported = None,
      fixedPrefixLen = None):
      self.ipv4Enable = ipv4Enable
      self.ipv6Enable = ipv6Enable
      self.ipv6RouterAdv = ipv6RouterAdv
      self.dhcpv6 = dhcpv6
      self.linklocalAuto = linklocalAuto
      self.prefixLen = prefixLen
      self.maxIpv6AddrSupported = maxIpv6AddrSupported
      self.fixedPrefixLen = fixedPrefixLen

#############################################################################
#### Policy and policy options
#############################################################################

#
# User input IQN policy option
#
# If the IQN is not given in the answer file, during VerifyProfile operation,
# we will propagate the current IQN from the adapter back to the answerfile.
#
class UserInputIqn(UserInputRequiredOption):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('iqn', 'string', False, '') ]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      IscsiLog(3,'UserInputIqn::VerifyPolicyOption: %s[%s]' % (profileInstance.__class__.__name__, profileInstance.GetKey()))
      # Update the profile with the iqn from the adapter
      # The function takes care to not to update if the value
      # already given in the profile/answerfile
      IscsiUpdatePolicyOptParam(self, 'iqn', hba.iqn)

      return False

# Initiator IQN selection policy. Only support user input selection.
class Hba_InitiatorIqnSelectionPolicy(Policy):
   possibleOptions = [ UserInputIqn ]

   GenericVerifyPolicy = True

#
# User input Alias policy option
#
# We will propagate up the alias from adapter if profile does not
# provide one.
#
class UserInputAlias(UserInputRequiredOption):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('alias',
                                            'string',
                                            True, '') ]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):

      IscsiUpdatePolicyOptParam(self, 'alias', hba.alias)

      return False

#
# Initiator Alias selection policy. Only user input option is supported.
#
class Hba_InitiatorAliasSelectionPolicy(Policy):
   possibleOptions = [ UserInputAlias ]

   GenericVerifyPolicy = True

class IscsiNoIpv4PolicyOptVerifier:
   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      if not forApply:
         return False

      failed = False

      # check if we can change current value of ipv4 enable for the adapter
      if hba.ipv4Config.enabled == True and hba.ipCaps.ipv4Enable == False:
         failed = True
         IscsiCreateLocalizedMessage(profileInstance,
                                     ISCSI_ERROR_NOIPV4_POLICY_OPTION_NOT_SUPPORTED,
                                     {'hba': hba.GetName()},
                                     validationErrors)
      return failed

#
# Use DHCP for IPv4 configuration
#
class FixedDhcpv4Config(FixedPolicyOption):
   paramMeta = []

#
# Disable IPv4
#
class NoIpv4Config(FixedPolicyOption, IscsiNoIpv4PolicyOptVerifier):
   paramMeta = []

#
# Ignore IPv4 configuration
#
class IgnoreIpv4Config(FixedPolicyOption):
   paramMeta = []

#
# Use IPv4 configuration provides by the user
#
class UserInputIpv4Config(UserInputRequiredOption):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('ipv4Addr',
                                            'string',
                                            True,
                                            '',
                                            IscsiIPv4ConfigAddressValidator()),
                          ParameterMetadata('ipv4Subnetmask',
                                            'string',
                                            True,
                                            '',
                                            IscsiIpv4NetmaskValidator()),
                          ParameterMetadata('gateway4',
                                            'string',
                                            True,
                                            '',
                                            IscsiIpv4GatewayValidator()) ]
   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      IscsiUpdatePolicyOptParam(self, 'ipv4Addr', hba.ipv4Config.address)
      IscsiUpdatePolicyOptParam(self, 'ipv4Subnetmask', hba.ipv4Config.subnet)
      IscsiUpdatePolicyOptParam(self, 'gateway4', hba.ipv4Config.gateway)
      return False

#
# IPv4 configuration selection policy for independent adapters
#
class Hba_InitiatorIpv4ConfigSelectionPolicy(Policy):
   possibleOptions = [ FixedDhcpv4Config, UserInputIpv4Config, NoIpv4Config, IgnoreIpv4Config ]
   GenericVerifyPolicy  = True
   OptionalPolicy = True

class IscsiNoIpv6PolicyOptVerifier:
   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      if not forApply:
         return False

      failed = False

      # check if currently IPv6 is enabled and can be disabled or not
      if hba.ipv6Config.enabled == True and hba.ipCaps.ipv6Enable == False:
         failed = True
         IscsiCreateLocalizedMessage(profileInstance,
                                     ISCSI_ERROR_NOIPV6_POLICY_OPTION_NOT_SUPPORTED,
                                     {'hba': hba.GetName()},
                                     validationErrors)
      return failed

class IscsiAutoConfPolicyOptVerifier:
   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      if not forApply:
         return False

      failed = False
      # get policy option routerAdv and dhcp values
      routerAdv = getattr(self, 'useRouterAdvertisement')
      dhcp6 = getattr(self, 'useDhcpv6')

      # check if we can change dhcpv6 or routerAdv for this adapter
      if (routerAdv != hba.ipv6Config.useRouterAdv) and hba.ipCaps.ipv6RouterAdv == False:
         failed = True
         IscsiCreateLocalizedMessage(profileInstance,
                                     ISCSI_ERROR_SETTING_RA_POLICY_OPTION_NOT_SUPPORTED,
                                     {'hba': hba.GetName()},
                                     validationErrors)
         return failed

      if (dhcp6 != hba.ipv6Config.useDhcp6) and hba.ipCaps.dhcpv6 == False:
         failed = True
         IscsiCreateLocalizedMessage(profileInstance,
                                     ISCSI_ERROR_SETTING_DHCPV6_POLICY_OPTION_NOT_SUPPORTED,
                                     {'hba': hba.GetName()},
                                     validationErrors)
         return failed

      # both dhcpv6 and routerAdv cannot be false
      if routerAdv == False and dhcp6 == False:
         failed = True
         IscsiCreateLocalizedMessage(profileInstance,
                                     ISCSI_ERROR_BOTH_RA_AND_DHCPV6_CANNOT_BE_FALSE,
                                     {'hba': hba.GetName()},
                                     validationErrors)
         return failed

      return failed

#
# Obtain IPv6 settings automatically
#
class AutoConfigureIpv6(FixedPolicyOption, IscsiAutoConfPolicyOptVerifier):
   paramMeta = [ ParameterMetadata('useRouterAdvertisement',
                                   'bool',
                                   True),
                 ParameterMetadata('useDhcpv6',
                                   'bool',
                                   True) ]

#
# Disable IPv6
#
class NoIpv6Config(FixedPolicyOption, IscsiNoIpv6PolicyOptVerifier):
   paramMeta = []

class IgnoreIpv6Config(FixedPolicyOption):
   paramMeta = []

#
# Use IPv6 configuration provided by the user
#
class UserInputIpv6Config(UserInputRequiredOption):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('ipv6AddrList',
                                            'string',
                                            True,
                                            '',
                                            IscsiIPv6ConfigAddressValidator()),
                          ParameterMetadata('gateway6',
                                            'string',
                                            True,
                                            '',
                                            IscsiIPv6GatewayValidator()) ]
   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      if not forApply:
         return False

      addrStr = getattr(self, 'ipv6AddrList')
      if addrStr:
         addrList = addrStr.split(",")
         if len(addrList) > hba.ipCaps.maxIpv6AddrSupported:
            msg = IscsiCreateLocalizedMessage(profileInstance,
                                              ISCSI_ERROR_MAX_IPV6_ADDRESS_LIMIT_EXCEEDED,
                                              {'hba': hba.GetName(),
                                               'maxAddrSupported': hba.ipCaps.maxIpv6AddrSupported})
            msg.SetRelatedPathInfo(profile=profileInstance, policy=policy,
                                   paramId='ipv6AddrList')
            validationErrors.append(msg)
            return True
         if len(addrList) > 0:
            for x in addrList:
               addrSplit = x.split("/")
               if len(addrSplit) == 2:
                  addr = addrSplit[0]
                  prefix = addrSplit[1]
                  if hba.ipCaps.prefixLen == False:
                     if int(prefix) != hba.ipCaps.fixedPrefixLen:
                        msg = IscsiCreateLocalizedMessage(profileInstance,
                                                          ISCSI_ERROR_FIXED_IPV6_PREFIX_LENGTH_SUPPORTED,
                                                          {'hba': hba.GetName(),
                                                           'prefixLen' : hba.ipCaps.fixedPrefixLen})
                        msg.SetRelatedPathInfo(profile=profileInstance, policy=policy,
                                               paramId='ipv6AddrList')
                        validationErrors.append(msg)
                        return True
               else:
                  msg = IscsiCreateLocalizedMessage(profileInstance,
                                                    ISCSI_INVALID_IPV6_ADDRESS,
                                                    {})
                  msg.SetRelatedPathInfo(profile=profileInstance, policy=policy,
                                         paramId='ipv6AddrList')
                  validationErrors.append(msg)
                  return True
      IscsiUpdatePolicyOptParam(self, 'ipv6AddrList', hba.ipv6Config.ipv6AddressOriginal)
      IscsiUpdatePolicyOptParam(self, 'gateway6', hba.ipv6Config.gateway6)
      return False

#
# IPv6 configuration selection policy for independent adapters
#
class Hba_InitiatorIpv6ConfigSelectionPolicy(Policy):
   possibleOptions = [ UserInputIpv6Config, AutoConfigureIpv6, NoIpv6Config, IgnoreIpv6Config ]
   GenericVerifyPolicy  = True
   OptionalPolicy = True

#
# Auto configure linklocal address
#
class AutoConfigureLinkLocal(FixedPolicyOption):
   paramMeta = []

#
# Ignore Link-local configuration
#
class IgnoreLinkLocalConfig(FixedPolicyOption):
   paramMeta = []

class UserInputLinkLocalAddr(UserInputRequiredOption):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('linklocalAddr',
                                            'string',
                                            True,
                                            '',
                                            IscsiLinklocalAddressValidator()) ]
   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      IscsiUpdatePolicyOptParam(self, 'linklocalAddr', hba.linklocalConfig.linklocalAddr)
      return False

#
# IPv6 linklocal address configuration selection policy for independent adapters
#
class Hba_InitiatorLinkLocalConfigSelectionPolicy(Policy):
   possibleOptions = [ UserInputLinkLocalAddr, AutoConfigureLinkLocal, IgnoreLinkLocalConfig ]
   GenericVerifyPolicy  = True
   OptionalPolicy = True

#
# IPv4 address for independent adapters
#
class UserInputIpv4Address(UserInputRequiredOption):
   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('ipv4Address',
                                            'string',
                                            True,
                                            '',
                                            IscsiIPv4ConfigAddressValidator()) ]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      IscsiUpdatePolicyOptParam(self, 'ipv4Address', hba.ipv4Address)

      return False

#
# IPv4 address selection policy for independent adapters
#
class Hba_InitiatorIpv4AddressSelectionPolicy(Policy):
   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

   possibleOptions = [ UserInputIpv4Address ]

   GenericVerifyPolicy = True
   OptionalPolicy = True

#
# IPv4 netmask for independent adapters
#
class UserInputIpv4Netmask(UserInputRequiredOption):
   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('ipv4Netmask',
                                            'string',
                                            True,
                                            '',
                                            IscsiIpv4NetmaskValidator()) ]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      IscsiUpdatePolicyOptParam(self, 'ipv4Netmask', hba.ipv4Netmask)

      return False

#
# IPv4 netmask selection policy for independent adapters
#
class Hba_InitiatorIpv4NetmaskSelectionPolicy(Policy):
   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

   possibleOptions = [ UserInputIpv4Netmask ]

   GenericVerifyPolicy = True
   OptionalPolicy = True

#
# IPv4 gateway address for independent adapters
#
class UserInputIpv4Gateway(UserInputRequiredOption):
   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('ipv4Gateway',
                                            'string',
                                            True,
                                            '',
                                            IscsiIpv4GatewayValidator()) ]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      IscsiUpdatePolicyOptParam(self, 'ipv4Gateway', hba.ipv4Gateway)

      return False

#
# IPv4 gateway address selection policy for independent adapters
#
class Hba_InitiatorIpv4GatewaySelectionPolicy(Policy):
   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

   possibleOptions = [ UserInputIpv4Gateway ]

   GenericVerifyPolicy = True
   OptionalPolicy = True

#
# IPv6 address for independent adapters
#
class UserInputIpv6Address(UserInputRequiredOption):
   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('ipv6Address',
                                            'string',
                                            True,
                                            '',
                                            IscsiIPv6AddressValidator) ]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      IscsiUpdatePolicyOptParam(self, 'ipv6Address', hba.ipv6Address)

      return False

#
# IPv6 address selection policy for independent adapters
#
class Hba_InitiatorIpv6AddressSelectionPolicy(Policy):
   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

   possibleOptions = [ UserInputIpv6Address ]

   GenericVerifyPolicy = True
   OptionalPolicy = True

#
# IPv6 prefix for independent adapters
#
class UserInputIpv6Prefix(UserInputRequiredOption):
   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('ipv6Prefix',
                                            'string',
                                            True,
                                            '0',
                                            IscsiIPv6PrepixValidator) ]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      IscsiUpdatePolicyOptParam(self, 'ipv6Prefix', hba.ipv6Prefix)

      return False

#
# IPv6 prefix selection policy for independent adapters
#
class Hba_InitiatorIpv6PrefixSelectionPolicy(Policy):
   deprecatedFlag = True
   deprecatedVersion = RELEASE_VERSION_2015

   possibleOptions = [ UserInputIpv6Prefix ]

   GenericVerifyPolicy = True
   OptionalPolicy = True

#
# Common inheritance class for advanced param policy
#
class IscsiParamPolicyCommon:
   def GetParam(self, hba, profileInstance, polOpt):
      params = profileInstance.GetParams(hba)
      if params is None:
         params = hba.params

      return params[self.paramName]

#
# Common inheritance class to verify the advanced param policyOptions
#
class IscsiParamVerifier:
   # Returns True if verify failed and False if verify successeds
   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      #
      # Do the verify only for apply (we may not have aceess to hba otherwise).
      #
      if not forApply:
         return False

      failed = False

      param = policy.GetParam(hba, profileInstance, self)

      IscsiLog(4, 'VerifyPolicyOption: policy=%s option=%s param=%s value=%s' % \
            (policy.__class__.__name__,
             self.__class__.__name__,
             policy.paramName,
             param))

      # If hba does not support setting
      if not IsSettable(param):
         failed =  True
         IscsiCreateLocalizedMessage(profileInstance,
                                     ISCSI_ERROR_SETTING_NOT_SUPPORTED,
                                     {'hba': hba.GetName(),
                                      'param' : policy.paramName},
                                     validationErrors)
      return failed

class SettingNotSupported(FixedPolicyOption):
   paramMeta = []

class UseInitiatorDefault(FixedPolicyOption):
   paramMeta = []

#
# ARP redirection selection
#
class UserInputArpRedirection(UserInputRequiredOption):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('arpRedirection', 'bool', True) ]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):

      IscsiUpdatePolicyOptParam(self, 'arpRedirection' , hba.arpRedirection)

      return False

class UseFixedArpRedirection(FixedPolicyOption):
   paramMeta = [ ParameterMetadata('arpRedirection', 'bool', False) ]

#
# Enable/Disable ARP redirection policy
#
class Hba_ArpRedirectionSelectionPolicy(Policy):
   possibleOptions = [
                       UserInputArpRedirection,
                       UseFixedArpRedirection
                     ]

   GenericVerifyPolicy = True

class UserInputJumboFrame(UserInputRequiredOption):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('jumboFrame', 'int', True) ]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):

      IscsiUpdatePolicyOptParam(self, 'jumboFrame' , hba.jumboFrame)

      return False

class UseFixedMTU(FixedPolicyOption):
   paramMeta = [ ParameterMetadata('jumboFrame', 'int', False, ISCSI_DEFAULT_MTU,
                                   IscsiRangeValidator(ISCSI_MIN_MTU, ISCSI_MAX_MTU)) ]

class Hba_JumboFrameSelectionPolicy(Policy):
   possibleOptions = [
                       UserInputJumboFrame,
                       UseFixedMTU
                     ]

   GenericVerifyPolicy = True

class InheritFromParent(FixedPolicyOption):
   paramMeta = []

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      failed = False

      # If hba does not support inheritance
      if not hba.caps['inheritanceSupported']:
         failed =  True
         IscsiCreateLocalizedMessage(profileInstance,
                                     ISCSI_ERROR_INHERITANCE_NOT_SUPPORTED,
                                     {},
                                     validationErrors)
      return failed

class IscsiChapPolicyOptionVerifier:
   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      failed = False

      chapType = policy.chapType
      chapLevel = self.__class__.__name__

      IscsiLog(4, 'VerifyPolicyOption: policy=%s chapType=%s polcyOption=%s level=%s supported=%s' % \
            (policy.__class__.__name__,
             str(policy.chapType),
             self.__class__.__name__,
             chapLevel,
             str(hba.caps['supportedChapLevels'][chapType[0]][chapType[1]][chapLevel])))

      if not hba.caps['supportedChapLevels'][chapType[0]][chapType[1]][chapLevel]:
         failed = True
         IscsiLog(3, 'hba=%s' %(str(hba.__dict__)))
         IscsiCreateLocalizedMessage(profileInstance,
                                     ISCSI_ERROR_CHAP_POLICY_OPTION_NOT_SUPPORTED,
                                     {'option': self.__class__.__name__},
                                     validationErrors)
      return failed

class DoNotUseChap(FixedPolicyOption, IscsiChapPolicyOptionVerifier):
   paramMeta = []

class DoNotUseChapUnlessRequiredByTarget(FixedPolicyOption, IscsiChapPolicyOptionVerifier):
   paramMeta = []

class UseChapUnlessProhibitedByTarget(FixedPolicyOption, IscsiChapPolicyOptionVerifier):
   paramMeta = []

class UseChap(FixedPolicyOption, IscsiChapPolicyOptionVerifier):
   paramMeta = []

class Hba_InitiatorChapTypeSelectionPolicy(Policy):
   possibleOptions = [ SettingNotSupported,
                       DoNotUseChap,
                       DoNotUseChapUnlessRequiredByTarget,
                       UseChapUnlessProhibitedByTarget,
                       UseChap
                     ]

   chapType = ('hba', 'uni')

   GenericVerifyPolicy = True

class UseFixedChapName(FixedPolicyOption):
   paramMeta = [ ParameterMetadata('chapName', 'string', True, '')]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):

      failed = VerifyChapParam(profileInstance,
                               hba,
                               policy,
                               self,
                               'chapName',
                               ISCSI_ERROR_EMPTY_PARAM_NOT_ALLOWED,
                               {'policy': policy.__class__.__name__,
                                'param': 'chapName'},
                               validationErrors)
      return False

class UseInitiatorIqnAsChapName(FixedPolicyOption):
   paramMeta = []

class UserInputChapName(UserInputRequiredOption):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('chapName', 'string', True, '') ]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):

      if not forApply:
         return False

      failed = VerifyChapParam(profileInstance,
                               hba,
                               policy,
                               self,
                               'chapName',
                               ISCSI_ERROR_EMPTY_PARAM_NOT_ALLOWED,
                               {'policy': policy.__class__.__name__, 'param': 'chapName'},
                               validationErrors)
      return False

class Hba_InitiatorChapNameSelectionPolicy(Policy):
   possibleOptions = [ UseFixedChapName,
                       UseInitiatorIqnAsChapName,
                       UserInputChapName
                     ]

   GenericVerifyPolicy = True

class UseFixedChapSecret(FixedPolicyOption):
   paramMeta = [ ParameterMetadata('chapSecret', 'Vim.PasswordField', True, Vim.PasswordField())]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):

      if not forApply:
         return False

      failed = VerifyChapParam(profileInstance,
                               hba,
                               policy,
                               self,
                               'chapSecret',
                               ISCSI_ERROR_EMPTY_PARAM_NOT_ALLOWED,
                               {'policy': policy.__class__.__name__, 'param': 'chapSecret'},
                               validationErrors)
      return False

class UserInputChapSecret(UserInputRequiredOption):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('chapSecret', 'Vim.PasswordField', True, Vim.PasswordField())]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      if not forApply:
         return False

      failed = VerifyChapParam(profileInstance,
                               hba,
                               policy,
                               self,
                               'chapSecret',
                               ISCSI_ERROR_EMPTY_PARAM_NOT_ALLOWED,
                               {'policy': policy.__class__.__name__, 'param': 'chapSecret'},
                               validationErrors)
      return False

class Hba_InitiatorChapSecretSelectionPolicy(Policy):
   possibleOptions = [ UseFixedChapSecret,
                       UserInputChapSecret
                     ]

   GenericVerifyPolicy = True

class Hba_TargetChapTypeSelectionPolicy(Policy):
   possibleOptions = [ SettingNotSupported,
                       DoNotUseChap,
                       UseChap
                     ]

   chapType = ('hba', 'mutual')

   GenericVerifyPolicy = True

   def VerifyPolicy(self,
                    profileInstance,
                    hba,
                    forApply,
                    validationErrors):

      if forApply != True:
         return False

      if isinstance(self.policyOption, UseChap) and \
         not isinstance(profileInstance.Hba_InitiatorChapTypeSelectionPolicy.policyOption,
                        UseChap):
         IscsiCreateLocalizedMessage(self,
                                     ISCSI_ERROR_TARGET_CHAP_REQUIRES_INITIATOR_CHAP,
                                     {},
                                     validationErrors)
         return True

      return False

class Hba_TargetChapNameSelectionPolicy(Policy):
   possibleOptions = [ UseFixedChapName,
                       UseInitiatorIqnAsChapName,
                       UserInputChapName
                     ]

   GenericVerifyPolicy = True

class Hba_TargetChapSecretSelectionPolicy(Policy):
   possibleOptions = [ UseFixedChapSecret,
                       UserInputChapSecret
                     ]

   GenericVerifyPolicy = True

class DigestProhibited(FixedPolicyOption, IscsiParamVerifier):
   paramMeta = []

class DigestDiscouraged(FixedPolicyOption, IscsiParamVerifier):
   paramMeta = []

class DigestPreferred(FixedPolicyOption, IscsiParamVerifier):
   paramMeta = []

class DigestRequired(FixedPolicyOption, IscsiParamVerifier):
   paramMeta = []

class Hba_HeaderDigestSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       DigestProhibited,
                       DigestDiscouraged,
                       DigestPreferred,
                       DigestRequired
                     ]

   GenericVerifyPolicy = True

   paramName = HEADER_DIGEST

class Hba_DataDigestSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       DigestProhibited,
                       DigestDiscouraged,
                       DigestPreferred,
                       DigestRequired
                     ]

   GenericVerifyPolicy = True

   paramName = DATA_DIGEST

class UseFixedMaxOutstandingR2T(FixedPolicyOption, IscsiParamVerifier):
   paramMeta = [ ParameterMetadata('maxOutstandingR2T', 'int', False, ISCSI_DEFAULT_MAXR2T,
                                   IscsiRangeValidator(ISCSI_MIN_MAXR2T, ISCSI_MAX_MAXR2T)) ]

class UseFixedFirstBurstLength(FixedPolicyOption, IscsiParamVerifier):
   paramMeta = [ ParameterMetadata('firstBurstLength', 'int', False, ISCSI_DEFAULT_FIRSTBURSTLENGTH,
                                   IscsiRangeValidator(ISCSI_MIN_FIRSTBURSTLENGTH, ISCSI_MAX_FIRSTBURSTLENGTH)) ]

class UseFixedMaxBurstLength(FixedPolicyOption, IscsiParamVerifier):
   paramMeta = [ ParameterMetadata('maxBurstLength', 'int', False, ISCSI_DEFAULT_MAXBURSTLENGTH,
                                   IscsiRangeValidator(ISCSI_MIN_MAXBURSTLENGTH, ISCSI_MAX_MAXBURSTLENGTH)) ]

class UseFixedMaxReceiveSegmentLength(FixedPolicyOption, IscsiParamVerifier):
   paramMeta = [ ParameterMetadata('maxReceiveSegmentLength', 'int', False, ISCSI_DEFAULT_MAXRECVSEGLENGTH,
                                   IscsiRangeValidator(ISCSI_MIN_MAXRECVSEGLENGTH, ISCSI_MAX_MAXRECVSEGLENGTH)) ]

class UseFixedNoopOutInterval(FixedPolicyOption, IscsiParamVerifier):
   paramMeta = [ ParameterMetadata('noopOutInterval', 'int', False, ISCSI_DEFAULT_NOOPOUTINTERVAL,
                                   IscsiRangeValidator(ISCSI_MIN_NOOPOUTINTERVAL, ISCSI_MAX_NOOPOUTINTERVAL)) ]

class UseFixedNoopOutTimeout(FixedPolicyOption, IscsiParamVerifier):
   paramMeta = [ ParameterMetadata('noopOutTimeout', 'int', False, ISCSI_DEFAULT_NOOPOUTTIMEOUT,
                                   IscsiRangeValidator(ISCSI_MIN_NOOPOUTTIMEOUT, ISCSI_MAX_NOOPOUTTIMEOUT)) ]

class UseFixedRecoveryTimeout(FixedPolicyOption, IscsiParamVerifier):
   paramMeta = [ ParameterMetadata('recoveryTimeout', 'int', False, ISCSI_DEFAULT_RECOVERYTIMEOUT,
                                   IscsiRangeValidator(ISCSI_MIN_RECOVERYTIMEOUT, ISCSI_MAX_RECOVERYTIMEOUT)) ]

class UseFixedLoginTimeout(FixedPolicyOption, IscsiParamVerifier):
   paramMeta = [ ParameterMetadata('loginTimeout', 'int', True, ISCSI_DEFAULT_LOGINTIMEOUT,
                                   IscsiRangeValidator(ISCSI_MIN_LOGINTIMEOUT, ISCSI_MAX_LOGINTIMEOUT)) ]

class UseFixedDelayedAck(FixedPolicyOption, IscsiParamVerifier):
   paramMeta = [ ParameterMetadata('delayedAckEnabled', 'bool', False) ]

class UserInputMaxOutstandingR2T(UserInputRequiredOption, IscsiParamVerifier):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('maxOutstandingR2T', 'int', False, ISCSI_DEFAULT_MAXR2T,
                                            IscsiRangeValidator(ISCSI_MIN_MAXR2T, ISCSI_MAX_MAXR2T)) ]

class UserInputFirstBurstLength(UserInputRequiredOption, IscsiParamVerifier):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('firstBurstLength', 'int', False, ISCSI_DEFAULT_FIRSTBURSTLENGTH,
                                            IscsiRangeValidator(ISCSI_MIN_FIRSTBURSTLENGTH, ISCSI_MAX_FIRSTBURSTLENGTH)) ]

class UserInputMaxBurstLength(UserInputRequiredOption, IscsiParamVerifier):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('maxBurstLength', 'int', False, ISCSI_DEFAULT_MAXBURSTLENGTH,
                                            IscsiRangeValidator(ISCSI_MIN_MAXBURSTLENGTH, ISCSI_MAX_MAXBURSTLENGTH)) ]

class UserInputMaxReceiveSegmentLength(UserInputRequiredOption, IscsiParamVerifier):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('maxReceiveSegmentLength', 'int', False, ISCSI_DEFAULT_MAXRECVSEGLENGTH,
                                            IscsiRangeValidator(ISCSI_MIN_MAXRECVSEGLENGTH, ISCSI_MAX_MAXRECVSEGLENGTH)) ]

class UserInputNoopOutInterval(UserInputRequiredOption, IscsiParamVerifier):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('noopOutInterval', 'int', False, ISCSI_DEFAULT_NOOPOUTINTERVAL,
                                            IscsiRangeValidator(ISCSI_MIN_NOOPOUTINTERVAL, ISCSI_MAX_NOOPOUTINTERVAL)) ]

class UserInputNoopOutTimeout(UserInputRequiredOption, IscsiParamVerifier):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('noopOutTimeout', 'int', False, ISCSI_DEFAULT_NOOPOUTTIMEOUT,
                                            IscsiRangeValidator(ISCSI_MIN_NOOPOUTTIMEOUT, ISCSI_MAX_NOOPOUTTIMEOUT)) ]

class UserInputRecoveryTimeout(UserInputRequiredOption, IscsiParamVerifier):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('recoveryTimeout', 'int', False, ISCSI_DEFAULT_RECOVERYTIMEOUT,
                                            IscsiRangeValidator(ISCSI_MIN_RECOVERYTIMEOUT, ISCSI_MAX_RECOVERYTIMEOUT)) ]

class UserInputLoginTimeout(UserInputRequiredOption, IscsiParamVerifier):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('loginTimeout', 'int', True, ISCSI_DEFAULT_LOGINTIMEOUT,
                                            IscsiRangeValidator(ISCSI_MIN_LOGINTIMEOUT, ISCSI_MAX_LOGINTIMEOUT)) ]

class UserInputDelayedAck(UserInputRequiredOption, IscsiParamVerifier):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('delayedAckEnabled', 'bool', False) ]

class Hba_MaxOutstandingR2TSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       UseInitiatorDefault,
                       UserInputMaxOutstandingR2T,
                       UseFixedMaxOutstandingR2T
                     ]

   paramName = MAX_R2T

   GenericVerifyPolicy = True

class Hba_FirstBurstLengthSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       UseInitiatorDefault,
                       UserInputFirstBurstLength,
                       UseFixedFirstBurstLength
                     ]

   paramName = FIRST_BURST_LENGTH

   GenericVerifyPolicy = True

class Hba_MaxBurstLengthSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       UseInitiatorDefault,
                       UserInputMaxBurstLength,
                       UseFixedMaxBurstLength
                     ]

   paramName = MAX_BURST_LENGTH

   GenericVerifyPolicy = True

class Hba_MaxReceiveSegmentLengthSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       UseInitiatorDefault,
                       UserInputMaxReceiveSegmentLength,
                       UseFixedMaxReceiveSegmentLength
                     ]

   paramName = MAX_RECV_SEG_LENGTH

   GenericVerifyPolicy = True

class Hba_NoopOutIntervalSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       UseInitiatorDefault,
                       UserInputNoopOutInterval,
                       UseFixedNoopOutInterval
                     ]

   paramName = NOOP_OUT_INTERVAL

   GenericVerifyPolicy = True

class Hba_NoopOutTimeoutSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       UseInitiatorDefault,
                       UserInputNoopOutTimeout,
                       UseFixedNoopOutTimeout
                     ]

   paramName = NOOP_OUT_TIMEOUT

   GenericVerifyPolicy = True

class Hba_RecoveryTimeoutSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       UseInitiatorDefault,
                       UserInputRecoveryTimeout,
                       UseFixedRecoveryTimeout
                     ]

   paramName = RECOVERY_TIMEOUT

   GenericVerifyPolicy = True

class Hba_LoginTimeoutSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       UseInitiatorDefault,
                       UserInputLoginTimeout,
                       UseFixedLoginTimeout
                     ]

   paramName = LOGIN_TIMEOUT

   GenericVerifyPolicy = True
   OptionalPolicy = True

class Hba_DelayedAckSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       UseFixedDelayedAck,
                       UserInputDelayedAck
                     ]

   paramName = DELAYED_ACK

   GenericVerifyPolicy = True

class IscsiInitiatorSelectionMatchByPciSlotInfo(UserInputRequiredOption):
   paramMeta = [ ParameterMetadata('pciSlotInfo', 'string', False, '') ]
   userInputParamMeta = [ ParameterMetadata('macAddress', 'string', True, '')]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      failed = VerifyHbaProfileInstance(self, policy, profileInstance, validationErrors)

      return failed

class IscsiInitiatorSelectionMatchByDriverName(UserInputRequiredOption):
   paramMeta = [ ParameterMetadata('driverName', 'string', False, '')]
   userInputParamMeta = [ ParameterMetadata('macAddress', 'string', True, '')]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      failed = VerifyHbaProfileInstance(self, policy, profileInstance, validationErrors)

      return failed

class IscsiInitiatorSelectionMatchByVendorId(UserInputRequiredOption):
   paramMeta = [ ParameterMetadata('vendorId', 'string', False, '')]
   userInputParamMeta = [ ParameterMetadata('macAddress', 'string', True, '')]

   def VerifyPolicyOption(self,
                          policy,
                          profileInstance,
                          hba,
                          forApply,
                          validationErrors):
      failed = VerifyHbaProfileInstance(self, policy, profileInstance, validationErrors)

      return failed

class IscsiInitiatorSelectionDisabled(UserInputRequiredOption):
   paramMeta = []
   userInputParamMeta = [ ParameterMetadata('disabled', 'bool', True, False)]

class IscsiSoftwareInitiatorSelectionPolicy(Policy):
   # Enable or Disable on a per host basis
   possibleOptions = [ IscsiInitiatorSelectionDisabled ]

class IscsiHardwareInitiatorSelectionPolicy(Policy):
   # Define a policy for the iSCSI Initiator Selection
   possibleOptions = [ IscsiInitiatorSelectionMatchByPciSlotInfo,
                       IscsiInitiatorSelectionMatchByDriverName,
                       IscsiInitiatorSelectionMatchByVendorId
                     ]

   GenericVerifyPolicy = True

class IscsiInitiatorIdentityPolicyOption(FixedPolicyOption):
   paramMeta = [ ParameterMetadata('name', 'string', False, '')]

class IscsiInitiatorIdentityPolicy(Policy):
   # Define a policy for the iSCSI Initiator Profile Instance Identity
   possibleOptions = [ IscsiInitiatorIdentityPolicyOption ]

class IscsiSendTargetsDiscoveryIdentityPolicyOption(FixedPolicyOption):
   paramMeta = [
      ParameterMetadata('discoveryAddress', 'string', False, '', IscsiStringNonEmptyValidator()),
      ParameterMetadata('discoveryPort', 'string', True, '3260', IscsiTcpPortNumberValidator())
   ]

class IscsiSendTargetsDiscoveryIdentityPolicy(Policy):
   possibleOptions = [ IscsiSendTargetsDiscoveryIdentityPolicyOption ]

class IscsiTargetIdentityPolicyOption(FixedPolicyOption):
   paramMeta = [
      ParameterMetadata('targetAddress', 'string', False, '', IscsiStringNonEmptyValidator()),
      ParameterMetadata('targetPort', 'string', True, '3260', IscsiTcpPortNumberValidator()),
      ParameterMetadata('targetIqn', 'string', False, '')
   ]

class IscsiTargetIdentityPolicy(Policy):
   possibleOptions = [ IscsiTargetIdentityPolicyOption ]

class Target_InitiatorChapTypeSelectionPolicy(Policy):
   possibleOptions = [ SettingNotSupported,
                       InheritFromParent,
                       DoNotUseChap,
                       DoNotUseChapUnlessRequiredByTarget,
                       UseChapUnlessProhibitedByTarget,
                       UseChap
                     ]

   chapType = ('target', 'uni')

   GenericVerifyPolicy = True

class Target_InitiatorChapNameSelectionPolicy(Policy):
   possibleOptions = [ UseFixedChapName,
                       UseInitiatorIqnAsChapName,
                       UserInputChapName
                     ]

   GenericVerifyPolicy = True

class Target_InitiatorChapSecretSelectionPolicy(Policy):
   possibleOptions = [ UseFixedChapSecret,
                       UserInputChapSecret
                     ]

   GenericVerifyPolicy = True

class Target_TargetChapTypeSelectionPolicy(Policy):
   possibleOptions = [ SettingNotSupported,
                       InheritFromParent,
                       DoNotUseChap,
                       UseChap
                     ]

   chapType = ('target', 'mutual')

   GenericVerifyPolicy = True

class Target_TargetChapNameSelectionPolicy(Policy):
   possibleOptions = [ UseFixedChapName,
                       UseInitiatorIqnAsChapName,
                       UserInputChapName
                     ]

   GenericVerifyPolicy = True

class Target_TargetChapSecretSelectionPolicy(Policy):
   possibleOptions = [ UseFixedChapSecret,
                       UserInputChapSecret
                     ]

class Target_HeaderDigestSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       InheritFromParent,
                       DigestProhibited,
                       DigestDiscouraged,
                       DigestPreferred,
                       DigestRequired
                     ]

   paramName = HEADER_DIGEST

   GenericVerifyPolicy = True

class Target_DataDigestSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       InheritFromParent,
                       DigestProhibited,
                       DigestDiscouraged,
                       DigestPreferred,
                       DigestRequired
                     ]

   paramName = DATA_DIGEST

   GenericVerifyPolicy = True

class Target_MaxOutstandingR2TSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       InheritFromParent,
                       UseInitiatorDefault,
                       UserInputMaxOutstandingR2T,
                       UseFixedMaxOutstandingR2T
                     ]

   paramName = MAX_R2T

   GenericVerifyPolicy = True

class Target_FirstBurstLengthSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       InheritFromParent,
                       UseInitiatorDefault,
                       UserInputFirstBurstLength,
                       UseFixedFirstBurstLength
                     ]

   paramName = FIRST_BURST_LENGTH

   GenericVerifyPolicy = True

class Target_MaxBurstLengthSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       InheritFromParent,
                       UseInitiatorDefault,
                       UserInputMaxBurstLength,
                       UseFixedMaxBurstLength
                     ]

   paramName = MAX_BURST_LENGTH

   GenericVerifyPolicy = True

class Target_MaxReceiveSegmentLengthSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       InheritFromParent,
                       UseInitiatorDefault,
                       UserInputMaxReceiveSegmentLength,
                       UseFixedMaxReceiveSegmentLength
                     ]

   paramName = MAX_RECV_SEG_LENGTH

   GenericVerifyPolicy = True

class Target_NoopOutIntervalSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       InheritFromParent,
                       UseInitiatorDefault,
                       UserInputNoopOutInterval,
                       UseFixedNoopOutInterval
                     ]

   paramName = NOOP_OUT_INTERVAL

   GenericVerifyPolicy = True

class Target_NoopOutTimeoutSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       InheritFromParent,
                       UseInitiatorDefault,
                       UserInputNoopOutTimeout,
                       UseFixedNoopOutTimeout
                     ]

   paramName = NOOP_OUT_TIMEOUT

   GenericVerifyPolicy = True

class Target_RecoveryTimeoutSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       InheritFromParent,
                       UseInitiatorDefault,
                       UserInputRecoveryTimeout,
                       UseFixedRecoveryTimeout
                     ]

   paramName = RECOVERY_TIMEOUT

   GenericVerifyPolicy = True

class Target_LoginTimeoutSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       InheritFromParent,
                       UseInitiatorDefault,
                       UserInputLoginTimeout,
                       UseFixedLoginTimeout
                     ]

   paramName = LOGIN_TIMEOUT

   GenericVerifyPolicy = True
   OptionalPolicy = True

class Target_DelayedAckSelectionPolicy(Policy, IscsiParamPolicyCommon):
   possibleOptions = [ SettingNotSupported,
                       InheritFromParent,
                       UseFixedDelayedAck,
                       UserInputDelayedAck
                     ]

   paramName = DELAYED_ACK

   GenericVerifyPolicy = True

class BindVnicByIpv6Subnet(FixedPolicyOption):
   paramMeta = [ ParameterMetadata('all', 'bool', False, False),
                 ParameterMetadata('ipv6Address', 'string', False, '', IscsiIPv6AddressValidator()),
                 ParameterMetadata('ipv6Prefix', 'string', False, '', IscsiIPv6PrepixValidator())
               ]

   def toTaskSet(self):
      return {'policyOption': self.__class__.__name__,
              'all': self.all,
              'ipv6Address': self.ipv6Address,
              'ipv6Prefix': self.ipv6Prefix,
              }

class BindVnicByIpv4Subnet(FixedPolicyOption):
   paramMeta = [ ParameterMetadata('all', 'bool', False, False),
                 ParameterMetadata('ipv4Address', 'string', False, '', IscsiIPv4AddressValidator()),
                 ParameterMetadata('ipv4Netmask', 'string', False, '', IscsiIpv4NetmaskValidator())
               ]

   def toTaskSet(self):
      return {'policyOption': self.__class__.__name__,
              'all': self.all,
              'ipv4Address': self.ipv4Address,
              'ipv4Netmask': self.ipv4Netmask,
              }

class BindCompatibleVnics(FixedPolicyOption):
   paramMeta = [ ParameterMetadata('all', 'bool', False, False),
                 ParameterMetadata('portgroups', 'string', True, '')
               ]

   def toTaskSet(self):
      return {'policyOption': self.__class__.__name__,
              'all': self.all,
              'portgroups': self.portgroups
             }

class BindVnicByDevice(FixedPolicyOption):
   paramMeta = [ ParameterMetadata('vnicDevice', 'string', False, '') ]

   def toTaskSet(self):
      return {'policyOption': self.__class__.__name__,
              'device': self.vnicDevice
             }

class IscsiVnicSelectionPolicy(Policy):
   possibleOptions = [ BindVnicByDevice,
                       BindCompatibleVnics,
                       BindVnicByIpv4Subnet,
                       BindVnicByIpv6Subnet
                     ]

   GenericVerifyPolicy = True

# Name of the policy, (esxcli output/input, policy class)
digestPolicyOptionsMap = dict([
         ('SettingNotSupported', ('SettingNotSupported', SettingNotSupported)),
         ('InheritFromParent', ('InheritFromParent', InheritFromParent)),
         ('DigestProhibited', ('prohibited', DigestProhibited)),
         ('DigestDiscouraged', ('discouraged', DigestDiscouraged)),
         ('DigestPreferred', ('preferred', DigestPreferred)),
         ('DigestRequired', ('required', DigestRequired)),
      ])

# Name of the policy, (esxcli output/input, policy class)
chapPolicyOptionsMap = dict([
         ('SettingNotSupported', ('SettingNotSupported', SettingNotSupported)),
         ('InheritFromParent', ('InheritFromParent', InheritFromParent)),
         ('DoNotUseChap', ('prohibited', DoNotUseChap)),
         ('DoNotUseChapUnlessRequiredByTarget', ('discouraged', DoNotUseChapUnlessRequiredByTarget)),
         ('UseChapUnlessProhibitedByTarget', ('preferred', UseChapUnlessProhibitedByTarget)),
         ('UseChap', ('required', UseChap)),
      ])

def ExtractPolicyOptionValue(profInst,
                             policyClass,
                             policyOptionSpec,
                             assertOnNone):
   retValue = None

   policyName = policyClass.__name__
   if hasattr(profInst, policyName):
      policyInst = getattr(profInst, policyName)
   else:
      assert(assertOnNone == False or retValue != None), 'Could not obtain parameter value for policy %s' %(policyName)
      return None

   AssertForInvariantPolicyOptions(policyInst, policyClass)

   for (_policyOptionList, _valueSourceFlag, _valueSource) in policyOptionSpec:
      for _policyOption in _policyOptionList:
         if isinstance(policyInst.policyOption, _policyOption):
            if _valueSourceFlag == FROM_CONSTANT:
               retValue = _valueSource
            elif _valueSourceFlag == FROM_ATTRIBUTE:
               retValue = getattr(policyInst.policyOption, _valueSource)
            elif _valueSourceFlag == FROM_CLASS_NAME:
               tmpClass = getattr(policyInst.policyOption, '__class__')
               retValue = getattr(tmpClass, '__name__')
            elif _valueSourceFlag == FROM_FUNCTION_CALL:
               retValue = _valueSource(profInst, policyInst, policyInst.policyOption)
            else:
               assert()
            break

   assert(assertOnNone == False or retValue != None), 'Could not obtain parameter value for policy %s' %(policyName)
   return retValue

#
# Given a policy instance and policy class, make sure all the policy options
# are valid instances.
#
def AssertForInvariantPolicyOptions(policyInst, policyClass):
   found = False
   for option in policyClass.possibleOptions:
      if isinstance(policyInst.policyOption, option):
         found = True
         break

   if found != True:
      assert 'Policy instance %s has invalid policy options' % (policyInst.__class__.__name__)

   return

#
# Verifies all the policies for a given profile
#
def VerifyPolicies(cls,
                   profileInstance,
                   hba,
                   hostServices,
                   profileData,
                   forApply,
                   validationErrors):
   failed = False

   # Create empty dict
   policyState={}

   for p  in  cls.policies:
      policyState[p] = hasattr(p, 'OptionalPolicy') and p.OptionalPolicy

   # Traverse thru all the policies and call 'VerifyPolicy'
   # and/or 'GenericVerifyPolicy'. Also, mark the policy
   # state.
   for policyInst in profileInstance.policies:
      if policyInst.__class__ in cls.policies:
         policyState[policyInst.__class__] = True

         # Invoke the VerifyPolicy method if policy has given one
         if hasattr(policyInst, 'VerifyPolicy'):
            failed |= policyInst.VerifyPolicy(profileInstance,
                                              hba,
                                              forApply,
                                              validationErrors)

         # If the policy indicates that to execute 'GenericVerifyPolicy'
         # then invoke that one too.
         if hasattr(policyInst, 'GenericVerifyPolicy') and \
            getattr(policyInst, 'GenericVerifyPolicy') == True:
            failed |= GenericVerifyPolicy(policyInst,
                                          profileInstance,
                                          hba,
                                          forApply,
                                          validationErrors)

   # See if any policies are missing and if yes report error
   for policy in policyState:
      if policyState[policy] == False:
         IscsiCreateLocalizedMessage(profileInstance,
                                     ISCSI_ERROR_MISSING_REQUIRED_POLICY,
                                     {'policy':policy.__name__},
                                     validationErrors)
         failed = True

   return failed == False

def VerifyInitiatorCommonConfigPolicies(cls,
                                        profileInstance,
                                        hba,
                                        hostServices,
                                        profileData,
                                        forApply,
                                        validationErrors):
   result = VerifyPolicies(cls,
                           profileInstance,
                           hba,
                           hostServices,
                           profileData,
                           forApply,
                           validationErrors)
   return result

def GetInitiatorCommonConfigPolicies(hba):
      # Common Initiator config Policies
      _allPolicies = []

      # Initiator Iqn/Alias Policies
      _allPolicies.append(Hba_InitiatorIqnSelectionPolicy(True,
            UserInputIqn([])))

      _allPolicies.append(Hba_InitiatorAliasSelectionPolicy(True,
            UserInputAlias([])))

      # Initiator Chap Policies
      _allPolicies.append(Hba_InitiatorChapTypeSelectionPolicy(True,
            chapPolicyOptionsMap[hba.initiatorChapType][1]([])))

      _allPolicies.append(Hba_InitiatorChapNameSelectionPolicy(True,
            UseFixedChapName([('chapName', hba.initiatorChapName)])))

      _allPolicies.append(Hba_InitiatorChapSecretSelectionPolicy(True,
            UseFixedChapSecret([('chapSecret',
                                 IscsiChapSecretToVimPassword(hba.initiatorChapSecret))])))

      # Target Chap Policies
      _allPolicies.append(Hba_TargetChapTypeSelectionPolicy(True,
            chapPolicyOptionsMap[hba.targetChapType][1]([])))

      _allPolicies.append(Hba_TargetChapNameSelectionPolicy(True,
            UseFixedChapName([('chapName', hba.targetChapName)])))

      _allPolicies.append(Hba_TargetChapSecretSelectionPolicy(True,
            UseFixedChapSecret([('chapSecret',
                                 IscsiChapSecretToVimPassword(hba.targetChapSecret))])))

      # Header Digest Policies
      _allPolicies.append(Hba_HeaderDigestSelectionPolicy(True,
            digestPolicyOptionsMap[hba.params[HEADER_DIGEST][0]][1]([])))

      # Data Digest Policies
      _allPolicies.append(Hba_DataDigestSelectionPolicy(True,
            digestPolicyOptionsMap[hba.params[DATA_DIGEST][0]][1]([])))

      __params = [
         Hba_MaxOutstandingR2TSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedMaxOutstandingR2T,
               'maxOutstandingR2T', hba.params[MAX_R2T][0])),

         Hba_FirstBurstLengthSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedFirstBurstLength,
               'firstBurstLength', hba.params[FIRST_BURST_LENGTH][0])),

         Hba_MaxBurstLengthSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedMaxBurstLength,
               'maxBurstLength', hba.params[MAX_BURST_LENGTH][0])),

         Hba_MaxReceiveSegmentLengthSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedMaxReceiveSegmentLength,
               'maxReceiveSegmentLength', hba.params[MAX_RECV_SEG_LENGTH][0])),

         Hba_NoopOutIntervalSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedNoopOutInterval,
               'noopOutInterval', hba.params[NOOP_OUT_INTERVAL][0])),

         Hba_NoopOutTimeoutSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedNoopOutTimeout,
               'noopOutTimeout', hba.params[NOOP_OUT_TIMEOUT][0])),

         Hba_RecoveryTimeoutSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedRecoveryTimeout,
               'recoveryTimeout', hba.params[RECOVERY_TIMEOUT][0])),

         Hba_LoginTimeoutSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedLoginTimeout,
               'loginTimeout', hba.params[LOGIN_TIMEOUT][0])),

         Hba_DelayedAckSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedDelayedAck,
               'delayedAckEnabled', hba.params[DELAYED_ACK][0]))
      ]

      _allPolicies.extend(__params)

      return _allPolicies

def IscsiGetIqnFromConfigProfile(profInst, policyInst, policyOpt):
   parentProfInst = profInst.parentProfile

   assert hasattr(parentProfInst, 'GetInitiatorConfigSubProfile'), \
      'The InitiatorProfile does not have method to get the ConfigProfile'

   intiatorConfigProfileInst = parentProfInst.GetInitiatorConfigSubProfile()

   assert intiatorConfigProfileInst, \
      'Could not obtain the InitiatorConfigProfile'

   iqn = ExtractPolicyOptionValue(intiatorConfigProfileInst,
                                 Hba_InitiatorIqnSelectionPolicy,
                                 [([UserInputIqn], FROM_ATTRIBUTE,
                                 'iqn')],
                                 True)

   return iqn

def ExtractIpv4Config(profInst, policyInst, policyOpt):
   tmpClass = getattr(policyInst.policyOption, '__class__')
   className =  getattr(tmpClass, '__name__')
   if className == 'FixedDhcpv4Config':
      conf = Ipv4Config()
      conf.ignore = False
      conf.enabled = True
      conf.useDhcp = True
      return conf
   elif className == 'UserInputIpv4Config':
      ip = getattr(policyInst.policyOption, 'ipv4Addr')
      netmask = getattr(policyInst.policyOption, 'ipv4Subnetmask')
      gateway = getattr(policyInst.policyOption, 'gateway4')
      conf = Ipv4Config()
      conf.ignore = False
      conf.enabled = True
      conf.useDhcp = False
      conf.address = ip
      conf.subnet = netmask
      conf.gateway = gateway
      return conf
   elif className == 'NoIpv4Config':
      conf = Ipv4Config()
      conf.ignore = False
      conf.enabled = False
      return conf
   elif className == 'IgnoreIpv4Config':
      conf = Ipv4Config()
      conf.ignore = True
      return conf

def ExtractIpv6Config(profInst, policyInst, policyOpt):
   tmpClass = getattr(policyInst.policyOption, '__class__')
   className = getattr(tmpClass, '__name__')
   if className == 'AutoConfigureIpv6':
      dhcpv6 = getattr(policyInst.policyOption, 'useDhcpv6')
      routerAdv = getattr(policyInst.policyOption, 'useRouterAdvertisement')
      conf = Ipv6Config()
      conf.ignore = False
      conf.enabled = True
      conf.useRouterAdv = routerAdv
      conf.useDhcp6 = dhcpv6
      return conf
   elif className == 'UserInputIpv6Config':
      addr = getattr(policyInst.policyOption, 'ipv6AddrList')
      gateway = getattr(policyInst.policyOption, 'gateway6')
      conf = Ipv6Config()
      conf.ignore = False
      conf.enabled = True
      conf.useRouterAdv = False
      conf.useDhcp6 = False
      conf.ipv6AddressOriginal = addr
      if len(addr):
         list = conf.ipv6AddressOriginal.split(",")
         for x in list:
            addrSplit = x.split("/")
            if len(addrSplit) == 2:
               addr = addrSplit[0]
               prefix = addrSplit[1]
               if not conf.ipv6AddressModified:
                  conf.ipv6AddressModified += \
                     ''.join([str(int(ipaddress.ip_address(addr))), '/', prefix])
               else:
                  conf.ipv6AddressModified += \
                     ''.join([',', str(int(ipaddress.ip_address(addr))),
                              '/', prefix])
            else:
               IscsiLog(0, 'ExtractIpv6Config: User Ipv6 address is not in valid format')
         # sort the adddresses in ipv6AddressModified
         addrList = conf.ipv6AddressModified.split(",")
         addrList.sort()
         conf.ipv6AddressModified = ''
         for x in addrList:
            if not conf.ipv6AddressModified:
               conf.ipv6AddressModified += x
            else:
               conf.ipv6AddressModified += ',' + x
      else:
         conf.ipv6AddressModified = ''

      conf.gateway6 = gateway
      return conf
   elif className == 'NoIpv6Config':
      conf = Ipv6Config()
      conf.ignore = False
      conf.enabled = False
      return conf
   elif className == 'IgnoreIpv6Config':
      conf = Ipv6Config()
      conf.ignore = True
      return conf

def ExtractLinklocalConfig(profInst, policyInst, policyOpt):
   tmpClass = getattr(policyInst.policyOption, '__class__')
   className =  getattr(tmpClass, '__name__')
   if className == 'AutoConfigureLinkLocal':
      conf = LinklocalConfig()
      conf.ignore = False
      conf.useLinklocalAutoConf = True
      return conf
   elif className == 'UserInputLinkLocalAddr':
      addr = getattr(policyInst.policyOption, 'linklocalAddr')
      conf = LinklocalConfig()
      conf.ignore = False
      conf.useLinklocalAutoConf = False
      conf.linklocalAddr = addr
      return conf
   elif className == 'IgnoreLinkLocalConfig':
      conf = LinklocalConfig()
      conf.ignore = True
      return conf

def ExtractTargetParamsFromProfileInstance(profInst):
   params = dict([
      ('initiatorChapType', None),
      ('initiatorChapName', None),
      ('initiatorChapSecret', None),
      ('targetChapType', None),
      ('targetChapName', None),
      ('targetChapSecret', None),
      ('headerDigest', None),
      ('dataDigest', None),
      ('maxOutstandingR2T', None),
      ('firstBurstLength', None),
      ('maxBurstLength', None),
      ('maxRecvSegLength', None),
      ('noopOutInterval', None),
      ('noopOutTimeout', None),
      ('recoveryTimeout', None),
      ('loginTimeout', None),
      ('delayedAck', None),
   ])

   # Initiator Chap
   params['initiatorChapType'] = ExtractPolicyOptionValue(profInst,
                                    Target_InitiatorChapTypeSelectionPolicy,
                                    [([SettingNotSupported,
                                       InheritFromParent,
                                       DoNotUseChap,
                                       DoNotUseChapUnlessRequiredByTarget,
                                       UseChapUnlessProhibitedByTarget,
                                       UseChap],
                                      FROM_CLASS_NAME,
                                      '')],
                                    True)

   params['initiatorChapName'] = ExtractPolicyOptionValue(profInst,
                                    Target_InitiatorChapNameSelectionPolicy,
                                    [([UseFixedChapName,
                                       UserInputChapName],
                                      FROM_ATTRIBUTE,
                                      'chapName'),
                                     ([UseInitiatorIqnAsChapName],
                                      FROM_CLASS_NAME,
                                      '')],
                                    True)

   if params['initiatorChapName'] == 'UseInitiatorIqnAsChapName':
      parentProfile = profInst.parentProfile.GetInitiatorConfigSubProfile()
      if parentProfile != None:
         adapterIqn = ExtractPolicyOptionValue(parentProfile,
                                               Hba_InitiatorIqnSelectionPolicy,
                                               [([UserInputIqn], FROM_ATTRIBUTE, 'iqn')],
                                               True)
         params['initiatorChapName'] = adapterIqn


   params['initiatorChapSecret'] = ExtractPolicyOptionValue(profInst,
                                    Target_InitiatorChapSecretSelectionPolicy,
                                    [([UseFixedChapSecret,
                                       UserInputChapSecret],
                                      FROM_FUNCTION_CALL,
                                      VimPasswordToIscsiChapSecret)],
                                    True)

   # Target Chap
   params['targetChapType'] = ExtractPolicyOptionValue(profInst,
                                    Target_TargetChapTypeSelectionPolicy,
                                    [([SettingNotSupported,
                                       InheritFromParent,
                                       DoNotUseChap,
                                       DoNotUseChapUnlessRequiredByTarget,
                                       UseChapUnlessProhibitedByTarget,
                                       UseChap],
                                      FROM_CLASS_NAME,
                                      '')],
                                    True)

   params['targetChapName'] = ExtractPolicyOptionValue(profInst,
                                    Target_TargetChapNameSelectionPolicy,
                                    [
                                     ([UseFixedChapName,
                                       UserInputChapName],
                                      FROM_ATTRIBUTE,
                                      'chapName'),
                                     ([UseInitiatorIqnAsChapName],
                                      FROM_CLASS_NAME,
                                      ''),
                                    ],
                                    True)


   if params['targetChapName'] == 'UseInitiatorIqnAsChapName':
      parentProfile = profInst.parentProfile.GetInitiatorConfigSubProfile()
      if parentProfile != None:
         adapterIqn = ExtractPolicyOptionValue(parentProfile,
                                               Hba_InitiatorIqnSelectionPolicy,
                                               [([UserInputIqn], FROM_ATTRIBUTE, 'iqn')],
                                               True)
         params['targetChapName'] = adapterIqn

   params['targetChapSecret'] = ExtractPolicyOptionValue(profInst,
                                    Target_TargetChapSecretSelectionPolicy,
                                    [
                                     ([UseFixedChapSecret,
                                       UserInputChapSecret],
                                      FROM_FUNCTION_CALL,
                                      VimPasswordToIscsiChapSecret),
                                    ],
                                    True)

   # Header Digest
   params['headerDigest'] = ExtractPolicyOptionValue(profInst,
                                    Target_HeaderDigestSelectionPolicy,
                                    [
                                     ([SettingNotSupported,
                                       InheritFromParent,
                                       DigestProhibited,
                                       DigestDiscouraged,
                                       DigestPreferred,
                                       DigestRequired],
                                      FROM_CLASS_NAME,
                                      ''),
                                    ],
                                    True)

   # Data Digest
   params['dataDigest'] = ExtractPolicyOptionValue(profInst,
                                    Target_DataDigestSelectionPolicy,
                                    [
                                     ([SettingNotSupported,
                                       InheritFromParent,
                                       DigestProhibited,
                                       DigestDiscouraged,
                                       DigestPreferred,
                                       DigestRequired],
                                      FROM_CLASS_NAME,
                                      ''),
                                    ],
                                    True)

   # Max Outstanding R2T
   params['maxOutstandingR2T'] = ExtractPolicyOptionValue(profInst,
                                    Target_MaxOutstandingR2TSelectionPolicy,
                                    [
                                     ([InheritFromParent, SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedMaxOutstandingR2T, UserInputMaxOutstandingR2T], FROM_ATTRIBUTE, 'maxOutstandingR2T'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    True)

   # First Burst Length
   params['firstBurstLength'] = ExtractPolicyOptionValue(profInst,
                                    Target_FirstBurstLengthSelectionPolicy,
                                    [
                                     ([InheritFromParent, SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedFirstBurstLength, UserInputFirstBurstLength], FROM_ATTRIBUTE, 'firstBurstLength'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    True)

   # Max Burst Length
   params['maxBurstLength'] = ExtractPolicyOptionValue(profInst,
                                    Target_MaxBurstLengthSelectionPolicy,
                                    [
                                     ([InheritFromParent, SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedMaxBurstLength, UserInputMaxBurstLength], FROM_ATTRIBUTE, 'maxBurstLength'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    True)

   # Max Receive Data Segment Length
   params['maxRecvSegLength'] = ExtractPolicyOptionValue(profInst,
                                    Target_MaxReceiveSegmentLengthSelectionPolicy,
                                    [
                                     ([InheritFromParent, SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedMaxReceiveSegmentLength, UserInputMaxReceiveSegmentLength], FROM_ATTRIBUTE, 'maxReceiveSegmentLength'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    True)

   # NOOP Out Interval
   params['noopOutInterval'] = ExtractPolicyOptionValue(profInst,
                                    Target_NoopOutIntervalSelectionPolicy,
                                    [
                                     ([InheritFromParent, SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedNoopOutInterval, UserInputNoopOutInterval], FROM_ATTRIBUTE, 'noopOutInterval'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    True)

   # NOOP Timeout
   params['noopOutTimeout'] = ExtractPolicyOptionValue(profInst,
                                    Target_NoopOutTimeoutSelectionPolicy,
                                    [
                                     ([InheritFromParent, SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedNoopOutTimeout, UserInputNoopOutTimeout], FROM_ATTRIBUTE, 'noopOutTimeout'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    True)

   # Recovery Timeout
   params['recoveryTimeout'] = ExtractPolicyOptionValue(profInst,
                                    Target_RecoveryTimeoutSelectionPolicy,
                                    [
                                     ([InheritFromParent, SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedRecoveryTimeout, UserInputRecoveryTimeout], FROM_ATTRIBUTE, 'recoveryTimeout'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    True)
   # Login Timeout
   params['loginTimeout'] = ExtractPolicyOptionValue(profInst,
                                    Target_LoginTimeoutSelectionPolicy,
                                    [
                                     ([InheritFromParent, SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedLoginTimeout, UserInputLoginTimeout], FROM_ATTRIBUTE, 'loginTimeout'),
                                     ([UseInitiatorDefault], FROM_CONSTANT, ISCSI_INITIATOR_DEFAULT_VALUE),
                                    ],
                                    False)

   if params['loginTimeout'] is None:
      params['loginTimeout'] = ISCSI_DEFAULT_LOGINTIMEOUT

   # Delayed Ack
   params['delayedAck'] = ExtractPolicyOptionValue(profInst,
                                    Target_DelayedAckSelectionPolicy,
                                    [
                                     ([InheritFromParent, SettingNotSupported], FROM_CLASS_NAME, ''),
                                     ([UseFixedDelayedAck, UserInputDelayedAck], FROM_ATTRIBUTE, 'delayedAckEnabled'),
                                    ],
                                    True)
   return params

def GetTargetCommonConfigPolicies(target):
      # Common Target/SendTarget Config Policies
      _allPolicies = []

      # Initiator Chap Policies
      _allPolicies.append(Target_InitiatorChapTypeSelectionPolicy(True,
            chapPolicyOptionsMap[target.initiatorChapType][1]([])))

      _allPolicies.append(Target_InitiatorChapNameSelectionPolicy(True,
            UseFixedChapName([('chapName', target.initiatorChapName)])))

      _allPolicies.append(Target_InitiatorChapSecretSelectionPolicy(True,
            UseFixedChapSecret([('chapSecret',
                                 IscsiChapSecretToVimPassword(target.initiatorChapSecret))])))

      # Target Chap Policies
      _allPolicies.append(Target_TargetChapTypeSelectionPolicy(True,
            chapPolicyOptionsMap[target.targetChapType][1]([])))

      _allPolicies.append(Target_TargetChapNameSelectionPolicy(True,
            UseFixedChapName([('chapName', target.targetChapName)])))

      _allPolicies.append(Target_TargetChapSecretSelectionPolicy(True,
            UseFixedChapSecret([('chapSecret',
                                 IscsiChapSecretToVimPassword(target.targetChapSecret))])))

      # Header Digest Policies
      _allPolicies.append(Target_HeaderDigestSelectionPolicy(True,
            digestPolicyOptionsMap[target.params[HEADER_DIGEST][0]][1]([])))

      # Data Digest Policies
      _allPolicies.append(Target_DataDigestSelectionPolicy(True,
            digestPolicyOptionsMap[target.params[DATA_DIGEST][0]][1]([])))

      __params = [
         Target_MaxOutstandingR2TSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedMaxOutstandingR2T,
               'maxOutstandingR2T', target.params[MAX_R2T][0])),

         Target_FirstBurstLengthSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedFirstBurstLength,
               'firstBurstLength', target.params[FIRST_BURST_LENGTH][0])),

         Target_MaxBurstLengthSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedMaxBurstLength,
               'maxBurstLength', target.params[MAX_BURST_LENGTH][0])),

         Target_MaxReceiveSegmentLengthSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedMaxReceiveSegmentLength,
               'maxReceiveSegmentLength', target.params[MAX_RECV_SEG_LENGTH][0])),

         Target_NoopOutIntervalSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedNoopOutInterval,
               'noopOutInterval', target.params[NOOP_OUT_INTERVAL][0])),

         Target_NoopOutTimeoutSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedNoopOutTimeout,
               'noopOutTimeout', target.params[NOOP_OUT_TIMEOUT][0])),

         Target_RecoveryTimeoutSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedRecoveryTimeout,
               'recoveryTimeout', target.params[RECOVERY_TIMEOUT][0])),

         Target_LoginTimeoutSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedLoginTimeout,
               'loginTimeout', target.params[LOGIN_TIMEOUT][0])),

         Target_DelayedAckSelectionPolicy(True,
            ParamValueToPolicyOption(UseFixedDelayedAck,
               'delayedAckEnabled', target.params[DELAYED_ACK][0])),
      ]

      _allPolicies.extend(__params)

      return _allPolicies
