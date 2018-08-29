#!/usr/bin/python
# **********************************************************
# Copyright 2014-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import GenericProfile, Policy, FixedPolicyOption, \
                      ParameterMetadata, PolicyOptComplianceChecker, \
                      ProfileComplianceChecker, CreateLocalizedMessage, log, \
                      TASK_LIST_REQ_MAINT_MODE, TASK_LIST_RES_OK, \
                      CreateLocalizedException, CreateComplianceFailureValues, \
                      PARAM_NAME, MESSAGE_VALUE, MESSAGE_KEY

import pdb
import os
import time
from datetime import date
import pprint
import subprocess
import random
import sys

from functools import wraps
from .iscsiPolicies import *

from pyVmomi import Vmodl, Differ, Vim
import codecs
from vmware import runcommand

# The current profile version. The format is MAJOR.MINOR.RELEASE.
# The minor and release version updates should not break the compatibility.
ISCSI_PROFILE_VERSION               = '5.1.0'

# The default port number used if not given
ISCSI_DEFAULT_PORT_NUMBER           = 3260

# Some hacks for qlogic hba's
ISCSI_QLOGIC_DRIVER                 = 'qla4xxx'

# The string used to indicate 'UserInitiatorDefault'
ISCSI_INITIATOR_DEFAULT_VALUE       = 'default'

# Capabilities for VMware software initiator
SOFTWARE_ISCSI_CAPS = {
   'mutualChapSupported'               : True,
   'uniChapSupported'                  : True,
   'mtuSettable'                       : False,
   'arpRedirectSettable'               : False,
   'targetLevelUniAuthSupported'       : True,
   'targetLevelMutualAuthSupported'    : True,
   'inheritanceSupported'              : True,
   'supportedChapLevels' : {
      'hba': {
         'uni': {
            'SettingNotSupported'                  : False,
            'DoNotUseChap'                         : True,
            'DoNotUseChapUnlessRequiredByTarget'   : True,
            'UseChapUnlessProhibitedByTarget'      : True,
            'UseChap'                              : True,
         },
         'mutual': {
            'SettingNotSupported'                  : False,
            'DoNotUseChap'                         : True,
            'DoNotUseChapUnlessRequiredByTarget'   : False,
            'UseChapUnlessProhibitedByTarget'      : False,
            'UseChap'                              : True,
         },
      },
      'target': {
         'uni': {
            'SettingNotSupported'                  : False,
            'DoNotUseChap'                         : True,
            'DoNotUseChapUnlessRequiredByTarget'   : True,
            'UseChapUnlessProhibitedByTarget'      : True,
            'UseChap'                              : True,
         },
         'mutual': {
            'SettingNotSupported'                  : False,
            'DoNotUseChap'                         : True,
            'DoNotUseChapUnlessRequiredByTarget'   : False,
            'UseChapUnlessProhibitedByTarget'      : False,
            'UseChap'                              : True,
         },
      },
   },
}


# The reason for task's existance in the task set
ISCSI_REASON_UPDATE                 = 'Update'
ISCSI_REASON_ADD                    = 'Add'

# VMware software iscsi driver name
SOFTWARE_ISCSI_DRIVER_NAME          = 'iscsi_vmk'

# When software-iscsi is not enabled on the system but it is enabled in the
# profile, we do not know the HBA name for tasks until it is enabled on the
# system. We use this place-holder in place of real hba name during GenerateTaskList
# and then replace this with the real hba name during apply
SOFTWARE_ISCSI_ADAPTER_PLACE_HOLDER = '@@%s@@' % SOFTWARE_ISCSI_DRIVER_NAME
SOFTWARE_ISCSI_ADAPTER_DESCRIPTION = 'Software iSCSI Adapter'

# When extracting params from policy option (ExtractPolicyOptionValue()) indicate
# how it needs to extracted.
FROM_CONSTANT                       = 1
FROM_ATTRIBUTE                      = 2
FROM_CLASS_NAME                     = 3
FROM_FUNCTION_CALL                  = 4

# HBA Selection return codes
ISCSI_HBA_SELECTION_OK              = 0
ISCSI_HBA_DISABLED                  = 1
ISCSI_HBA_ALREADY_ASSIGNED          = 2
ISCSI_HBA_NOTFOUND_AT_ADDRESS       = 3
ISCSI_HBA_MISMATCH                  = 4
ISCSI_HBA_NO_MACADDRESS             = 5

# Target types
ISCSI_STATIC_TARGETS                = 'statictargets'
ISCSI_SEND_TARGETS                  = 'sendtargets'

# HBA profile types
ISCSI_HBA_PROFILE_SOFTWARE          = 'software'
ISCSI_HBA_PROFILE_DEPENDENT         = 'dependent'
ISCSI_HBA_PROFILE_INDEPENDENT       = 'independent'

# Parameter names
ARPREDIRECT                         = 'InitiatorArpRedirection'
MTU                                 = 'InitiatorMTU'
INITIATOR_CHAP                      = 'InitiatorChap'
TARGET_CHAP                         = 'TargetChap'
HEADER_DIGEST                       = 'HeaderDigest'
DATA_DIGEST                         = 'DataDigest'
MAX_R2T                             = 'MaxOutstandingR2T'
FIRST_BURST_LENGTH                  = 'FirstBurstLength'
MAX_BURST_LENGTH                    = 'MaxBurstLength'
MAX_RECV_SEG_LENGTH                 = 'MaxRecvDataSegment'
NOOP_OUT_INTERVAL                   = 'NoopOutInterval'
NOOP_OUT_TIMEOUT                    = 'NoopOutTimeout'
RECOVERY_TIMEOUT                    = 'RecoveryTimeout'
LOGIN_TIMEOUT                       = 'LoginTimeout'
DELAYED_ACK                         = 'DelayedAck'

# parameter min, max and defaults
ISCSI_DEFAULT_ARPREDIRECT           = True

ISCSI_DEFAULT_MTU                   = 1500
ISCSI_MIN_MTU                       = 1280
ISCSI_MAX_MTU                       = 16000

ISCSI_DEFAULT_HEADERDIGEST          = 'prohibited'
ISCSI_DEFAULT_DATADIGEST            = 'prohibited'

ISCSI_DEFAULT_MAXR2T                = 1
ISCSI_MIN_MAXR2T                    = 1
ISCSI_MAX_MAXR2T                    = 8

ISCSI_DEFAULT_FIRSTBURSTLENGTH      = 256 * 1024
ISCSI_MIN_FIRSTBURSTLENGTH          = 512
ISCSI_MAX_FIRSTBURSTLENGTH          = 16777215

ISCSI_DEFAULT_MAXBURSTLENGTH        = 256 * 1024
ISCSI_MIN_MAXBURSTLENGTH            = 512
ISCSI_MAX_MAXBURSTLENGTH            = 16777215

ISCSI_DEFAULT_MAXRECVSEGLENGTH      = 64 * 1024
ISCSI_MIN_MAXRECVSEGLENGTH          = 512
ISCSI_MAX_MAXRECVSEGLENGTH          = 16777215

ISCSI_DEFAULT_NOOPOUTINTERVAL       = 15
ISCSI_MIN_NOOPOUTINTERVAL           = 1
ISCSI_MAX_NOOPOUTINTERVAL           = 60

ISCSI_DEFAULT_NOOPOUTTIMEOUT        = 10
ISCSI_MIN_NOOPOUTTIMEOUT            = 10
ISCSI_MAX_NOOPOUTTIMEOUT            = 30

ISCSI_DEFAULT_RECOVERYTIMEOUT       = 10
ISCSI_MIN_RECOVERYTIMEOUT           = 1
ISCSI_MAX_RECOVERYTIMEOUT           = 120

ISCSI_DEFAULT_LOGINTIMEOUT          = 5
ISCSI_MIN_LOGINTIMEOUT              = 1
ISCSI_MAX_LOGINTIMEOUT              = 60

ISCSI_DEFAULT_DELAYEDACK            = True

# enables using Esxcli if True
USE_ESXCLI_CMD = False

# Base message code
ISCSI_BASE = 'com.vmware.profile.iscsi'

# Base profile code
ISCSI_PROFILE_BASE = 'com.vmware.vim.profile.Profile.iscsi'

# Exception message codes
ISCSI_BASE_EXCEPTION                      = '%s.exception' %(ISCSI_BASE)
ISCSI_EXCEPTION_INVALID_HBA_SELECTION     = "%s.%s.label" %(ISCSI_BASE_EXCEPTION, 'InvalidHbaSelection')
ISCSI_EXCEPTION_CLICMD_FAILED             = "%s.%s.label" %(ISCSI_BASE_EXCEPTION, 'CliCmdFailed')

# Verify errors
ISCSI_ERROR_MISSING_REQUIRED_POLICY       = "%s.%s.label" %(ISCSI_BASE, 'MissingRequiredPolicy')
ISCSI_ERROR_EMPTY_PARAM_NOT_ALLOWED       = "%s.%s.label" %(ISCSI_BASE, 'EmptyParamNotAllowed')
ISCSI_ERROR_NO_HBA_SELECTED               = "%s.%s.label" %(ISCSI_BASE, 'NoHbaSelected')
ISCSI_ERROR_INHERITANCE_NOT_SUPPORTED     = "%s.%s.label" %(ISCSI_BASE, 'InheritanceNotSupported')
ISCSI_ERROR_CHAP_POLICY_OPTION_NOT_SUPPORTED \
                                          = "%s.%s.label" %(ISCSI_BASE, 'ChapPolicyOptionNotSupported')
ISCSI_ERROR_SETTING_NOT_SUPPORTED         = "%s.%s.label" %(ISCSI_BASE, 'SettingNotSupported')
ISCSI_ERROR_MAX_IPV6_ADDRESS_LIMIT_EXCEEDED = "%s.%s.label" %(ISCSI_BASE, 'MaxIpv6AddrExceeded')
ISCSI_ERROR_FIXED_IPV6_PREFIX_LENGTH_SUPPORTED \
                                          = "%s.%s.label" %(ISCSI_BASE, 'FixedPrefixLenSupported')
ISCSI_ERROR_NOIPV4_POLICY_OPTION_NOT_SUPPORTED \
                                          = "%s.%s.label" %(ISCSI_BASE, 'DisablingIpv4NotSupported')
ISCSI_ERROR_NOIPV6_POLICY_OPTION_NOT_SUPPORTED \
                                          = "%s.%s.label" %(ISCSI_BASE, 'DisablingIpv6NotSupported')
ISCSI_ERROR_SETTING_DHCPV6_POLICY_OPTION_NOT_SUPPORTED \
                                          = "%s.%s.label" %(ISCSI_BASE, 'SettingDhcpv6NotSupported')
ISCSI_ERROR_SETTING_RA_POLICY_OPTION_NOT_SUPPORTED \
                                          = "%s.%s.label" %(ISCSI_BASE, 'SettingRANotSupported')
ISCSI_ERROR_BOTH_RA_AND_DHCPV6_CANNOT_BE_FALSE \
                                          = "%s.%s.label" %(ISCSI_BASE, 'BothRAAndDhcpv6CannotBeFalse')

ISCSI_ERROR_TARGET_CHAP_REQUIRES_INITIATOR_CHAP \
                                          = "%s.%s.label" %(ISCSI_BASE, 'RequiresInitiatorChap')

# Validation errors
ISCSI_INVALID_IP_ADDRESS                  = '%s.InvalidIPAddress.label' % (ISCSI_BASE)
ISCSI_INVALID_IPV4_ADDRESS                = '%s.InvalidIPv4Address.label' % (ISCSI_BASE)
ISCSI_INVALID_IPV4_NETMASK                = '%s.InvalidIPv4Netmask.label' % (ISCSI_BASE)
ISCSI_INVALID_IPV4_GATEWAY                = '%s.InvalidIPv4Gateway.label' % (ISCSI_BASE)
ISCSI_INVALID_TCP_PORT_NUMBER             = '%s.InvalidTcpPortNumber.label' % (ISCSI_BASE)
ISCSI_INVALID_IPV6_ADDRESS                = '%s.InvalidIPv6Address.label' % (ISCSI_BASE)
ISCSI_INVALID_IPV6_PREFIX                 = '%s.InvalidIPv6Prefix.label' % (ISCSI_BASE)
ISCSI_INVALID_IPV6_GATEWAY                = '%s.InvalidIPv6Gateway.label' % (ISCSI_BASE) 
ISCSI_INVALID_LINKLOCAL_ADDRESS           = '%s.InvalidLinklocalAddress.label' % (ISCSI_BASE)
ISCSI_LINKLOCAL_ADDRESS_NOT_ALLOWED       = '%s.LinklocalAddressNotAllowed.label' % (ISCSI_BASE)
ISCSI_INVALID_VALUE_OUT_OF_RANGE          = '%s.ValueOutOfRange.label' %(ISCSI_BASE)
ISCSI_INVALID_PARAM_TYPE                  = '%s.InvalidParamType.label' %(ISCSI_BASE)

# Initiator Config TaskList Keys
ISCSI_DISABLE_SOFTWARE_ISCSI              = '%s.%s' %(ISCSI_BASE, 'DisableSoftwareIscsi')
ISCSI_ENABLE_SOFTWARE_ISCSI               = '%s.%s' %(ISCSI_BASE, 'EnableSoftwareIscsi')

ISCSI_ISCSI_FIREWALL_CONFIG               = "%s.%s.label" %(ISCSI_BASE, 'IscsiFirewallConfig')
ISCSI_ISCSI_OPEN_FIREWALL                 = "%s.%s" %(ISCSI_BASE, 'OpenIscsiFirewall')
ISCSI_ISCSI_CLOSE_FIREWALL                = "%s.%s" %(ISCSI_BASE, 'CloseIscsiFirewall')

ISCSI_INITIATOR_CONFIG                    = '%s.%s' %(ISCSI_BASE, 'InitiatorConfig')
ISCSI_INITIATOR_CONFIG_CHECK              = '%s.%s' %(ISCSI_INITIATOR_CONFIG, 'Check')
ISCSI_INITIATOR_CONFIG_UPDATE             = '%s.%s' %(ISCSI_INITIATOR_CONFIG, 'Update')
ISCSI_INITIATOR_CONFIG_ADD                = '%s.%s' %(ISCSI_INITIATOR_CONFIG, 'Add')
ISCSI_INITIATOR_CONFIG_REM                = '%s.%s' %(ISCSI_INITIATOR_CONFIG, 'Remove')
ISCSI_INITIATOR_CONFIG_IQN                = '%s.%s' %(ISCSI_INITIATOR_CONFIG_UPDATE, 'Iqn')
ISCSI_INITIATOR_CONFIG_ALIAS              = '%s.%s' %(ISCSI_INITIATOR_CONFIG_UPDATE, 'Alias')
ISCSI_INITIATOR_CONFIG_IPv4CONFIG         = '%s.%s' %(ISCSI_INITIATOR_CONFIG_UPDATE, 'Ipv4Config')
ISCSI_INITIATOR_CONFIG_INITIATOR_CHAP     = '%s.%s' %(ISCSI_INITIATOR_CONFIG, INITIATOR_CHAP)
ISCSI_INITIATOR_CONFIG_TARGET_CHAP        = '%s.%s' %(ISCSI_INITIATOR_CONFIG, TARGET_CHAP)
ISCSI_INITIATOR_CONFIG_HEADER_DIGEST      = '%s.%s' %(ISCSI_INITIATOR_CONFIG, HEADER_DIGEST)
ISCSI_INITIATOR_CONFIG_DATA_DIGEST        = '%s.%s' %(ISCSI_INITIATOR_CONFIG, DATA_DIGEST)
ISCSI_INITIATOR_CONFIG_MAX_R2T            = '%s.%s' %(ISCSI_INITIATOR_CONFIG, MAX_R2T)
ISCSI_INITIATOR_CONFIG_FIRST_BURST_LENGTH = '%s.%s' %(ISCSI_INITIATOR_CONFIG, FIRST_BURST_LENGTH)
ISCSI_INITIATOR_CONFIG_MAX_BURST_LENGTH   = '%s.%s' %(ISCSI_INITIATOR_CONFIG, MAX_BURST_LENGTH)
ISCSI_INITIATOR_CONFIG_MAX_RECV_SEG_LENGTH = '%s.%s' %(ISCSI_INITIATOR_CONFIG, MAX_RECV_SEG_LENGTH)
ISCSI_INITIATOR_CONFIG_NOOP_OUT_INTERVAL  = '%s.%s' %(ISCSI_INITIATOR_CONFIG, NOOP_OUT_INTERVAL)
ISCSI_INITIATOR_CONFIG_NOOP_OUT_TIMEOUT   = '%s.%s' %(ISCSI_INITIATOR_CONFIG, NOOP_OUT_TIMEOUT)
ISCSI_INITIATOR_CONFIG_RECOVERY_TIMEOUT   = '%s.%s' %(ISCSI_INITIATOR_CONFIG, RECOVERY_TIMEOUT)
ISCSI_INITIATOR_CONFIG_LOGIN_TIMEOUT   = '%s.%s' %(ISCSI_INITIATOR_CONFIG, LOGIN_TIMEOUT)
ISCSI_INITIATOR_CONFIG_DELAYED_ACK        = '%s.%s' %(ISCSI_INITIATOR_CONFIG, DELAYED_ACK)

# Sendtargets Discovery TaskList Keys
ISCSI_SENDTARGET_DISCOVERY_CONFIG                     = '%s.%s' %(ISCSI_BASE, 'SendTargetsDiscoveryConfig')
ISCSI_SENDTARGET_DISCOVERY_CONFIG_CHECK               = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, 'Check')
ISCSI_SENDTARGET_DISCOVERY_CONFIG_UPDATE              = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, 'Update')
ISCSI_SENDTARGET_DISCOVERY_CONFIG_ADD                 = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, 'Add')
ISCSI_SENDTARGET_DISCOVERY_CONFIG_REM                 = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, 'Remove')
ISCSI_SENDTARGET_DISCOVERY_CONFIG_INITIATOR_CHAP      = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, INITIATOR_CHAP)
ISCSI_SENDTARGET_DISCOVERY_CONFIG_TARGET_CHAP         = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, TARGET_CHAP)
ISCSI_SENDTARGET_DISCOVERY_CONFIG_HEADER_DIGEST       = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, HEADER_DIGEST)
ISCSI_SENDTARGET_DISCOVERY_CONFIG_DATA_DIGEST         = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, DATA_DIGEST)
ISCSI_SENDTARGET_DISCOVERY_CONFIG_MAX_R2T             = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, MAX_R2T)
ISCSI_SENDTARGET_DISCOVERY_CONFIG_FIRST_BURST_LENGTH  = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, FIRST_BURST_LENGTH)
ISCSI_SENDTARGET_DISCOVERY_CONFIG_MAX_BURST_LENGTH    = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, MAX_BURST_LENGTH)
ISCSI_SENDTARGET_DISCOVERY_CONFIG_MAX_RECV_SEG_LENGTH = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, MAX_RECV_SEG_LENGTH)
ISCSI_SENDTARGET_DISCOVERY_CONFIG_NOOP_OUT_INTERVAL   = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, NOOP_OUT_INTERVAL)
ISCSI_SENDTARGET_DISCOVERY_CONFIG_NOOP_OUT_TIMEOUT    = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, NOOP_OUT_TIMEOUT)
ISCSI_SENDTARGET_DISCOVERY_CONFIG_RECOVERY_TIMEOUT    = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, RECOVERY_TIMEOUT)
ISCSI_SENDTARGET_DISCOVERY_CONFIG_LOGIN_TIMEOUT       = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, LOGIN_TIMEOUT)
ISCSI_SENDTARGET_DISCOVERY_CONFIG_DELAYED_ACK         = '%s.%s' %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, DELAYED_ACK)

# Targets Config TaskList Keys
ISCSI_TARGET_CONFIG                       = '%s.%s' %(ISCSI_BASE, 'TargetConfig')
ISCSI_TARGET_CONFIG_CHECK                 = '%s.%s' %(ISCSI_TARGET_CONFIG, 'Check')
ISCSI_TARGET_CONFIG_UPDATE                = '%s.%s' %(ISCSI_TARGET_CONFIG, 'Update')
ISCSI_TARGET_CONFIG_ADD                   = '%s.%s' %(ISCSI_TARGET_CONFIG, 'Add')
ISCSI_TARGET_CONFIG_REM                   = '%s.%s' %(ISCSI_TARGET_CONFIG, 'Remove')
ISCSI_TARGET_CONFIG_INITIATOR_CHAP        = '%s.%s' %(ISCSI_TARGET_CONFIG, INITIATOR_CHAP)
ISCSI_TARGET_CONFIG_TARGET_CHAP           = '%s.%s' %(ISCSI_TARGET_CONFIG, TARGET_CHAP)
ISCSI_TARGET_CONFIG_HEADER_DIGEST         = '%s.%s' %(ISCSI_TARGET_CONFIG, HEADER_DIGEST)
ISCSI_TARGET_CONFIG_DATA_DIGEST           = '%s.%s' %(ISCSI_TARGET_CONFIG, DATA_DIGEST)
ISCSI_TARGET_CONFIG_MAX_R2T               = '%s.%s' %(ISCSI_TARGET_CONFIG, MAX_R2T)
ISCSI_TARGET_CONFIG_FIRST_BURST_LENGTH    = '%s.%s' %(ISCSI_TARGET_CONFIG, FIRST_BURST_LENGTH)
ISCSI_TARGET_CONFIG_MAX_BURST_LENGTH      = '%s.%s' %(ISCSI_TARGET_CONFIG, MAX_BURST_LENGTH)
ISCSI_TARGET_CONFIG_MAX_RECV_SEG_LENGTH   = '%s.%s' %(ISCSI_TARGET_CONFIG, MAX_RECV_SEG_LENGTH)
ISCSI_TARGET_CONFIG_NOOP_OUT_INTERVAL     = '%s.%s' %(ISCSI_TARGET_CONFIG, NOOP_OUT_INTERVAL)
ISCSI_TARGET_CONFIG_NOOP_OUT_TIMEOUT      = '%s.%s' %(ISCSI_TARGET_CONFIG, NOOP_OUT_TIMEOUT)
ISCSI_TARGET_CONFIG_RECOVERY_TIMEOUT      = '%s.%s' %(ISCSI_TARGET_CONFIG, RECOVERY_TIMEOUT)
ISCSI_TARGET_CONFIG_LOGIN_TIMEOUT         = '%s.%s' %(ISCSI_TARGET_CONFIG, LOGIN_TIMEOUT)
ISCSI_TARGET_CONFIG_DELAYED_ACK           = '%s.%s' %(ISCSI_TARGET_CONFIG, DELAYED_ACK)

# Portbinding Config TaskList Keys
ISCSI_PORT_BINDING_CONFIG                 = '%s.%s' %(ISCSI_BASE, 'PortBindingConfig')
ISCSI_PORT_BINDING_CONFIG_CHECK           = '%s.%s' %(ISCSI_PORT_BINDING_CONFIG, 'Check')
ISCSI_PORT_BINDING_CONFIG_UPDATE          = '%s.%s' %(ISCSI_PORT_BINDING_CONFIG, 'Update')
ISCSI_PORT_BINDING_CONFIG_ADD             = '%s.%s' %(ISCSI_PORT_BINDING_CONFIG, 'Add')
ISCSI_PORT_BINDING_CONFIG_REM             = '%s.%s' %(ISCSI_PORT_BINDING_CONFIG, 'Remove')

# Portbinding config MESSAGE_KEY
ISCSI_PROFILE_PORT_BINDING                =  '%s.%s' %(ISCSI_PROFILE_BASE, 'iscsiPortBindingConfigProfile')
ISCSI_PROFILE_PORT_BINDING_PROFILE        =  '%s.%s' %(ISCSI_PROFILE_PORT_BINDING, 'IscsiPortBindingConfigProfile.label')

#
# Task naming rules:
#
# All esxcli tasks that go into GenerateTaskList's tasklist should follow
# rule of _CMD and _CHECK naming conventions. _CMD will be used for apply
# and _CHECK will be used for Compliance Check. Since same tasklist is used
# for both apply and also for Compliance Check, the tasklist should not
# include _CMD. Here is an example of the tasklist entry:
# {
#  'task': 'ISCSI_INITIATOR_CONFIG_IQN_SET',
#  'iqn' : newHbaData.iqn,
#  'hba' : newHbaData.name
# }
#
# At the apply time, above will look for ISCSI_INITIATOR_CONFIG_IQN_SET_CMD
# and then substitute the params from the dict. Where as at Compliance Check
# time, the code will look for ISCSI_INITIATOR_CONFIG_IQN_SET_CHECK and
# substitute the params from dict.
#

# ESXCLI commands
GET_HOST_NAME_CMD             = 'system hostname get'
NETWORK_GETIPV6_INTERFACES    = 'network ip interface ipv6 address list'
NETWORK_GETIPV4_INTERFACES    = 'network ip interface ipv4 get'
NETWORK_INTERFACE_LIST        = 'network ip interface list'

FIREWALL_LIST_CMD             = 'network firewall ruleset list'

HARDWARE_PCI_LIST_CMD         = 'hardware pci list'

ISCSI_RESCAN_ADAPTER_LUNS     = 'storage core adapter rescan --adapter %(hba)s -t all'

ISCSI_STORAGE_CORE_ADAPTER_LIST_CMD        = 'storage core adapter list'
ISCSI_INITIATOR_CONFIG_ADAPTER_LIST_CMD   = 'iscsi adapter list'

ISCSI_INITIATOR_CONFIG_DO_REDISCOVERY_CMD = \
   'iscsi adapter discovery rediscover --adapter "%(hba)s"'
ISCSI_INITIATOR_CONFIG_DO_REDISCOVERY_CHECK \
                                          = "%s.%s.Check" %(ISCSI_INITIATOR_CONFIG, 'Rediscovery')

ISCSI_INITIATOR_CONFIG_GET_CMD            = \
   'iscsi adapter get --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_IQN_SET_CMD        = \
   'iscsi adapter set --name "%(iqn)s" --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_IQN_SET_CHECK      = "%s.%s.Check" %(ISCSI_INITIATOR_CONFIG, 'Iqn')
ISCSI_INITIATOR_CONFIG_ALIAS_SET_CMD      = \
   'iscsi adapter set --alias "%(alias)s" --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_ALIAS_SET_CHECK    = "%s.%s.check" %(ISCSI_INITIATOR_CONFIG, 'Alias')

ISCSI_INITIATOR_CONFIG_ARPRED_SET_CMD     = \
   'iscsi physicalnetworkportal param set  --option ArpRedirect --value %(arpRedirection)s --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_ARPRED_GET_CMD     = \
   'iscsi physicalnetworkportal param get --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_ARPRED_SET_CHECK   = "%s.%s.check" %(ISCSI_INITIATOR_CONFIG, 'ArpRedirection')

ISCSI_INITIATOR_CONFIG_MTU_SET_CMD     = \
   'iscsi physicalnetworkportal param set  --option MTU --value %(jumboFrame)s --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_MTU_GET_CMD     = \
   'iscsi physicalnetworkportal param get --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_MTU_SET_CHECK   = "%s.%s.check" %(ISCSI_INITIATOR_CONFIG, 'MTU')

ISCSI_INITIATOR_CONFIG_PARM_GET_CMD       = \
   'iscsi adapter param get --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_PARM_SET_CMD       = \
   'iscsi adapter param set --adapter "%(hba)s" --key "%(key)s" %(keyValue)s'
ISCSI_INITIATOR_CONFIG_PARM_SET_CHECK     = "%s.%s.Check" %(ISCSI_INITIATOR_CONFIG, 'Param')

ISCSI_INITIATOR_CONFIG_CHAP_UNI_GET_CMD   = \
   'iscsi adapter auth chap get --direction uni --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_CHAP_MUTUAL_GET_CMD \
                                          = 'iscsi adapter auth chap get --direction mutual --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_CHAP_SET_CMD       = \
   'iscsi adapter auth chap set --adapter "%(hba)s" --direction %(direction)s %(keyValue)s'
ISCSI_INITIATOR_CONFIG_CHAP_SET_CHECK     = \
   "%s.%s.Check" %(ISCSI_INITIATOR_CONFIG, 'Auth')

ISCSI_INITIATOR_CONFIG_GET_CAPS_CMD       = \
   'iscsi adapter capabilities get --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_NP_LIST_CMD        = 'iscsi networkportal list --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_NP_ADD_CMD         = \
   'iscsi networkportal add --nic %(vnic)s --adapter %(hba)s --force %(force)s'
ISCSI_INITIATOR_CONFIG_NP_ADD_CHECK       = "%s.%s.Check" %(ISCSI_PORT_BINDING_CONFIG, 'Add')

ISCSI_INITIATOR_CONFIG_NP_REM_CMD         = 'iscsi networkportal remove --nic %(vnic)s --adapter %(hba)s --force true'
ISCSI_INITIATOR_CONFIG_NP_REM_CHECK       = "%s.%s.Check" %(ISCSI_PORT_BINDING_CONFIG, 'Remove')

ISCSI_INITIATOR_CONFIG_IPCONFIG_GET_CMD   = \
   'iscsi networkportal ipconfig get --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_IPV6CONFIG_GET_CMD = \
   'iscsi networkportal ipv6config get --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_IPV6CONFIG_ADDRESS_GET_CMD = \
   'iscsi networkportal ipv6config address list --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_IPV6CONFIG_ADDRESS_ADD_CMD = \
   'iscsi networkportal ipv6config address add %(cmd)s  --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_IPV6CONFIG_ADDRESS_ADD_CHECK = "%s.%s.Check" % (ISCSI_INITIATOR_CONFIG, 'Ipv6Config')

ISCSI_INITIATOR_CONFIG_IPV6CONFIG_SET_CMD = \
   'iscsi networkportal ipv6config  set %(cmd)s --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_IPV6CONFIG_SET_CHECK = "%s.%s.Check" %(ISCSI_INITIATOR_CONFIG, 'Ipv6Config')

ISCSI_INITIATOR_CONFIG_IPCONFIG_SET_CMD = \
   'iscsi networkportal ipconfig set %(cmd)s --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_IPCONFIG_SET_CHECK = "%s.%s.Check" %(ISCSI_INITIATOR_CONFIG, 'Ipv4Config')

ISCSI_INITIATOR_CONFIG_IPCONFIG_GW_SET_CMD = \
   'iscsi networkportal ipconfig set --ip %(ip)s --subnet %(subnet)s --gateway %(gateway)s --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_IPCONFIG_GW_SET_CHECK \
                                          = "%s.%s.Check" %(ISCSI_INITIATOR_CONFIG, 'Ipv4Config')

ISCSI_INITIATOR_CONFIG_PNP_LIST_CMD       = 'iscsi physicalnetworkportal list'
ISCSI_INITIATOR_CONFIG_PNP_PARM_GET_CMD   = \
   'iscsi physicalnetworkportal param get --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_SENDTARGET_LIST_CMD \
                                          = 'iscsi adapter discovery sendtarget list --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_SENDTARGET_ADD_CMD = \
   'iscsi adapter discovery sendtarget add --address "%(ip)s:%(port)s" --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_SENDTARGET_ADD_CHECK \
                                          = "%s.%s.Check" %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, 'Add')

ISCSI_INITIATOR_CONFIG_SENDTARGET_REM_CMD = \
   'iscsi adapter discovery sendtarget remove --address "%(ip)s:%(port)s" --adapter %(hba)s '
ISCSI_INITIATOR_CONFIG_SENDTARGET_REM_CHECK \
                                          = "%s.%s.Check" %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, 'Remove')

ISCSI_INITIATOR_CONFIG_SENDTARGET_CHAP_UNI_GET_CMD = \
   'iscsi adapter discovery sendtarget auth chap get --direction uni --address "%(ip)s:%(port)s" --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_SENDTARGET_CHAP_MUTUAL_GET_CMD = \
   'iscsi adapter discovery sendtarget auth chap get --direction mutual --address "%(ip)s:%(port)s" --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_SENDTARGET_CHAP_SET_CMD = \
   'iscsi adapter discovery sendtarget auth chap set --address "%(ip)s:%(port)s" --adapter "%(hba)s" --direction %(direction)s %(keyValue)s'
ISCSI_INITIATOR_CONFIG_SENDTARGET_CHAP_SET_CHECK \
                                          = "%s.%s.Check" %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, 'Auth')

ISCSI_INITIATOR_CONFIG_SENDTARGET_PARM_GET_CMD = \
   'iscsi adapter discovery sendtarget param get --address "%(ip)s:%(port)s" --adapter "%(hba)s"'
ISCSI_INITIATOR_CONFIG_SENDTARGET_PARM_SET_CMD = \
   'iscsi adapter discovery sendtarget param set --address "%(ip)s:%(port)s" --adapter "%(hba)s" --key "%(key)s" %(keyValue)s'
ISCSI_INITIATOR_CONFIG_SENDTARGET_PARM_SET_CHECK \
                                          = "%s.%s.Check" %(ISCSI_SENDTARGET_DISCOVERY_CONFIG, 'Param')

ISCSI_INITIATOR_CONFIG_STATICTARGET_LIST_CMD \
                                          = 'iscsi adapter discovery statictarget list --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_DISCOVEREDTARGET_MISSING_CHECK \
                                          = "%s.%s.Check" %(ISCSI_TARGET_CONFIG, 'Add')

ISCSI_INITIATOR_CONFIG_STATICTARGET_ADD_CMD = \
   'iscsi adapter discovery statictarget add --address "%(targetAddress)s" --name "%(iqn)s" --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_STATICTARGET_ADD_CHECK \
                                          = "%s.%s.Check" %(ISCSI_TARGET_CONFIG, 'Add')

ISCSI_INITIATOR_CONFIG_STATICTARGET_REM_CMD = \
   'iscsi adapter discovery statictarget remove --address "%(targetAddress)s" --name "%(iqn)s" --adapter "%(hba)s"'
ISCSI_INITIATOR_CONFIG_STATICTARGET_REM_CHECK \
                                          = "%s.%s.Check" %(ISCSI_TARGET_CONFIG, 'Remove')

ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_LIST_CMD = \
   'iscsi adapter target portal list --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_PARM_GET_CMD = \
   'iscsi adapter target portal param get --address "%(targetAddress)s" --name "%(iqn)s" --adapter "%(hba)s"'
ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_PARM_SET_CMD = \
   'iscsi adapter target portal param set --address "%(targetAddress)s" --name "%(iqn)s" --adapter "%(hba)s" --key "%(key)s" %(keyValue)s'
ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_PARM_SET_CHECK \
                                          = "%s.%s.Check" %(ISCSI_TARGET_CONFIG, 'Param')

ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_CHAP_UNI_GET_CMD = \
   'iscsi adapter target portal auth chap get --direction uni --address %(targetAddress)s --name %(iqn)s --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_CHAP_MUTUAL_GET_CMD = \
   'iscsi adapter target portal auth chap get --direction mutual --address %(targetAddress)s --name %(iqn)s --adapter %(hba)s'
ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_CHAP_SET_CMD = \
   'iscsi adapter target portal auth chap set --address "%(targetAddress)s" --name "%(iqn)s" --adapter "%(hba)s" --direction %(direction)s %(keyValue)s'
ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_CHAP_SET_CHECK \
                                          = "%s.%s.Check" %(ISCSI_TARGET_CONFIG, 'Auth')

ISCSI_INITIATOR_CONFIG_LNP_LIST_CMD       = 'iscsi logicalnetworkportal list --adapter %(hba)s'

ISCSI_INITIATOR_CONFIG_SWISCSI_ENABLED_GET_CMD \
                                          = 'iscsi software get'
ISCSI_INITIATOR_CONFIG_SWISCSI_DISABLE_CMD \
                                          = 'iscsi software set --enabled false'
ISCSI_INITIATOR_CONFIG_SWISCSI_DISABLE_CHECK \
                                          = "%s.Check" %(ISCSI_DISABLE_SOFTWARE_ISCSI)
ISCSI_INITIATOR_CONFIG_SWISCSI_ENABLE_CMD   = \
                           'iscsi software set --enabled true --name %(iqn)s'
ISCSI_INITIATOR_CONFIG_SWISCSI_ENABLE_CHECK = \
                           "%s.Check" %(ISCSI_ENABLE_SOFTWARE_ISCSI)

ISCSI_INITIATOR_CONFIG_OPEN_FIREWALL_CMD  = 'network firewall ruleset set -r iSCSI -e true'
ISCSI_INITIATOR_CONFIG_OPEN_FIREWALL_CHECK \
                                          = "%s.Check" %(ISCSI_ISCSI_OPEN_FIREWALL)

ISCSI_INITIATOR_CONFIG_CLOSE_FIREWALL_CMD  = 'network firewall ruleset set -r iSCSI -e false'
ISCSI_INITIATOR_CONFIG_CLOSE_FIREWALL_CHECK \
                                          = "%s.Check" %(ISCSI_ISCSI_CLOSE_FIREWALL)

# Set the correct loglevel. User can set Environment variable
# ISCSILOGLEVEL to an integer value indicating the loglevel.
iscsiLogLevel = 4
if 'ISCSILOGLEVEL' in os.environ:
   iscsiLogLevel = int(os.environ['ISCSILOGLEVEL'])

# For debugging only: In case want to disable the task to be executed,
# set this environment variable to 1.
ExecuteTaskDisabled = False
if 'EXECUTETASKDISABLED' in os.environ:
   ExecuteTaskDisabled = int(os.environ['EXECUTETASKDISABLED']) == 1

# For debugging only: In case want to break into the debugger, set this
# environment variable.
debugger = 0
if 'ISCSIPROFILEDEBUG' in os.environ:
   debugger = int(os.environ['ISCSIPROFILEDEBUG'])

# Check if debugger is enabled
def debuggerEnabled():
   return debugger

# Invoking this funtion enters debugger on developer builds, asserts otherwise.
def EnterDebugger(errorMsg = None, forced=False):
   status, version = runcommand.runcommand('vmware -v')
   if forced or debuggerEnabled() or (status == 0 and version[-6:-1] == '00000'):
      log.warning('Entering debugger due to %s' %
                  (errorMsg if errorMsg is not None else 'no reason provided'))
      pdb.set_trace()
   else:
      log.warning('Assert on EnterDebugger with debugger not enabled and '
                  'non-developer build, errorMsg is %s' %
                  (errorMsg if errorMsg is not None else 'None'))
      assert False, \
             errorMsg if errorMsg is not None else 'no assert message provided'

# This function is used to log messages
def IscsiLog(level, logMessage, prefix=''):
   if level > iscsiLogLevel:
      return

   if level == 0:
      logFunc = log.critical
   elif level == 1:
      logFunc = log.error
   elif level == 2:
      logFunc = log.warn
   elif level == 3:
      logFunc = log.info
   else:
      logFunc = log.debug

   logFunc("ISCSI(%f):%s%s" %(time.time(), prefix, logMessage))

# Prints taskset in string
def PrintTaskData(taskData):
   if not iscsiLogLevel >= 4:
      return

   for taskDataInst in taskData:
      IscsiLog(4, taskDataInst, 'PrintTaskData: ')

# Pretty print the dictionary entries for a given object
def pdict(obj):
   pprint.pprint(obj.__dict__)

# Pretty print the directory entries for a given object
def pdir(obj):
   pprint.pprint(dir(obj))

# Convert given param to a Int value. While converting, it takes the
# "inheritence" into consideration.
#
# The tuple passed should have following format:
#  (current value, Inherited Flag, Settable or not, default value)
#
# The returned tuple will have following format:
#  (current value, current value, default value, Inherited Flag)
def ParamToInt(paramStr):
   # See if Settable or not
   if paramStr[2] == False:
      return ('SettingNotSupported', paramStr[0], paramStr[3], paramStr[1])

   # See if Inherit or not
   if paramStr[1] == True:
      return ('InheritFromParent', paramStr[0], paramStr[3], paramStr[1])

   assert(str(paramStr[0]).upper() != 'NA')

   return (int(paramStr[0]), paramStr[0], paramStr[3], paramStr[1])

# Convert given param to a Bool value. While converting, it takes the
# "inheritence" into consideration.
#
# The tuple passed should have following format:
#  (current value, Inherited Flag, Settable or not, default value)
#
# The returned tuple will have following format:
#  (current value, current value, default value, Inherited Flag)
def ParamToBool(paramStr):
   if paramStr[2] == False:
      return ('SettingNotSupported', paramStr[0], paramStr[3], paramStr[1])

   if paramStr[1] == True:
      return ('InheritFromParent', paramStr[0], paramStr[3], paramStr[1])

   if paramStr[0].upper() == 'TRUE':
      return (True, paramStr[0], paramStr[3], paramStr[1])
   else:
      return (False, paramStr[0], paramStr[3], paramStr[1])

# Version verification
def VerifyVersionCompatibility(cls, version):
   profileMajorVersion = version.split('.')
   currentMajorVersion = cls.version.split('.')

   if (profileMajorVersion[0] != currentMajorVersion[0]):
      IscsiLog(0, 'Version compatibility verification failed for profile %s, ' %(cls.__name__) + \
                  'current version is %s but the profile version is %s' \
                  %(cls.version, version))
      return False
   else:
      IscsiLog(3, 'Successfully verified the version ' +
                  'compatibility for profile %s, ' %(cls.__name__) + \
                  'current version is %s and the profile version is %s' \
                  %(cls.version, version))
      return True

# Returns the HBA instance from the profile instance. The profile
# instance must have been populated with the HBA instance, or else
# and exception is raised. An exception is also raised if there are
# multiple instances of HBA assigned to the profile instance.
def GetIscsiHbaFromProfile(config, profInst, exceptionOnError):
   hba = None
   if hasattr(profInst, 'selectedHbaInstances') and \
      len(profInst.selectedHbaInstances) == 1 and \
      profInst.selectedHbaInstances[0].type == profInst.iscsiProfileType:
         hba = profInst.selectedHbaInstances[0]

   if hba == None and exceptionOnError:
      IscsiRaiseException(profInst, ISCSI_EXCEPTION_INVALID_HBA_SELECTION, {'id': id(profInst)})

   return hba

# Copy the orginal dict and update the copy with given params
def CopyDictAndUpdate(origDict, addonDict):
   newDict = origDict.copy()
   newDict.update(addonDict)
   return newDict

# Create a localized exception message and raise the exception 
def IscsiRaiseException(obj, exceptionKey, exceptionArgs):
   locException = CreateLocalizedException(obj, exceptionKey, exceptionArgs)

   if locException == None:
      msg = 'IscsiRaiseException : Exception Key "%s" not found in the catalog' % exceptionKey
      log.error(msg)
      raise Exception(msg)
   else:
      raise locException

# Create a localized message for a given msgKey and msgArg and
# optionally append it to the list. If the msgKey is not in the msg catalog,
# CreateLocalizedMessage() will return None and we log an error indicating
# the missing msgKey.
def IscsiCreateLocalizedMessage(obj, mesgCode, msgArgs, errors=None,
       hostValue=None, profileValue=None, comparisonIdentifier=None,
       profileInstance=None, complianceValueOption=None,
       errorForCompliance=False):
   # Remove the dict primitives
   msgArgs = dict([x for x in list(msgArgs.items()) if not \
      isinstance(msgArgs[x[0]], dict)])
   # Filter extra keys added for CreateComplianceFailureValues.
   msgArgs = dict(item for item in list(msgArgs.items()) \
                  if item[0] != 'hostValue'
                  and item[0] != 'profileValue'
                  and item[0] != 'comparisonIdentifier'
                  and item[0] != 'complianceValueOption'
                  and item[0] != 'profileInstance')

   tmpMsg = CreateLocalizedMessage(obj, mesgCode, msgArgs)
   IscsiLog(3, "LocalizedMessage : %s" % (tmpMsg))
   if comparisonIdentifier is None: comparisonIdentifier = 'iscsi'

   comparisonValues = CreateComplianceFailureValues(comparisonIdentifier,
                                                    complianceValueOption,
                                                    profileValue = profileValue,
                                                    hostValue = hostValue,
                                                    profileInstance = profileInstance)

   if tmpMsg is None:
      log.error('Message Code: "%s" not found in the catalog' % mesgCode)
   # if errorForCompliance is set then tuple() is generated for
   # complaince comparison, otherwise a LocalizedMessage is appended
   elif errors is not None and errorForCompliance:
      errors.append((tmpMsg, [comparisonValues]))
      IscsiLog(3, "CreateComplianceFailureValues is " + str(comparisonValues))
   elif errors is not None:
      errors.append(tmpMsg)
   return tmpMsg

# Run ESXCLI the command line passed and raise an exception if the ESXCLI fails
def RunEsxCli(hostServices, cmdLine, failOK=False, logLevel=4):
   output = []

   IscsiLog(logLevel, 'RunEsxCli : %s, failOK=%s' %(cmdLine, failOK))

   cliCmd = cmdLine.split(' ', 2)

   status, output = hostServices.ExecuteEsxcli(cliCmd[0], cliCmd[1], cliCmd[2])
   if status != 0:
      if not failOK:
         IscsiRaiseException(cmdLine, ISCSI_EXCEPTION_CLICMD_FAILED, {'cmdline': cmdLine, 'error': output})
         log.error('Failed to execute "%s" command. Status = %d, Error = %s' % (cmdLine, status, output))

   return status, output

def logInfo(message=None):
   '''Decorator for logging which function is being called during extract'''
   def logDecorator(func):
      logMessage = func.__name__ + '()'

      @wraps(func)
      def logWrapper(*args, **kwargs):
         if message:
            logMessage = tuple(arg for args in args[2:])
            logMessage = message % logMessage
         IscsiLog(3, "Calling %s" % logMessage)
         return func(*args, **kwargs)
      return logWrapper
   return logDecorator


def IsHbaReady(hostServices):
   # check if storageDevice is available in hostServices
   isHbaReady =  hasattr(hostServices,'hostConfigInfo') and \
      hasattr(hostServices.hostConfigInfo, 'config') and \
      hasattr(hostServices.hostConfigInfo.config, 'storageDevice') and \
      hasattr(hostServices.hostConfigInfo.config.storageDevice, 'hostBusAdapter')
   if not isHbaReady:
      IscsiLog(2, 'Cached iscsi information is not available through hostServices')
   return isHbaReady


def GetHostData(hostServices, cmd, hbaName=None, ip=None,
                port=None, targetAddress=None, iqn=None,
                runEsxcli=False):
   """Gathers data from localcli if earlyBoot enabled or USE_ESXCLI_CMD is set.
   It also verifies if data is available thorough hostServices, Otherwise
   gather it from hostConfig.
   """
   if USE_ESXCLI_CMD or hostServices.earlyBoot or \
      (not IsHbaReady(hostServices)) or \
      runEsxcli:
      if hbaName != None and ip != None and port != None:
         cmd = cmd % {'hba':hbaName, 'ip':ip, 'port':port}
      elif hbaName != None and targetAddress != None and iqn != None:
         cmd = cmd % {'hba':hbaName, 'targetAddress':targetAddress, 'iqn':iqn}
      elif hbaName != None:
         cmd = cmd % {'hba':hbaName}
      return RunEsxCli(hostServices, cmd)
   else:
      return GetDataFromHostConfig(hostServices,
                                   cmd,
                                   hbaName,
                                   ip,
                                   port)


# Gets data from hostConfig for cmd passed, exception raised if invalid key
# passed to access hostConfig object.
def GetDataFromHostConfig(hostServices,
                          cmd,
                          hbaName=None,
                          ip=None,
                          port=None,
                          logLevel=4):
   output = []
   status = True
   IscsiLog(logLevel, 'Fetching from hostConfigInfo: %s' % (cmd))
   hostBusAdapter = hostServices.hostConfigInfo.\
      config.storageDevice.hostBusAdapter

   if cmd == ISCSI_STORAGE_CORE_ADAPTER_LIST_CMD:
      status, output = GetCoreAdapterList(hostBusAdapter, cmd)
   elif cmd == ISCSI_INITIATOR_CONFIG_ADAPTER_LIST_CMD:
      status, output = GetIscsiAdapterList(hostBusAdapter, cmd)
   elif cmd == ISCSI_INITIATOR_CONFIG_PARM_GET_CMD and hbaName != None:
      status, output = GetIscsiAdapterParam(hostBusAdapter, cmd, hbaName)
   elif cmd == ISCSI_INITIATOR_CONFIG_STATICTARGET_LIST_CMD and hbaName != None:
      status, output = GetInitiatorStaticTargetList(hostBusAdapter, cmd, hbaName)
   elif cmd == ISCSI_INITIATOR_CONFIG_CHAP_UNI_GET_CMD and hbaName != None:
      status, output = GetInitiatorChapUni(hostBusAdapter, cmd, hbaName)
   elif cmd == ISCSI_INITIATOR_CONFIG_CHAP_MUTUAL_GET_CMD and hbaName != None:
      status, output = GetInitiatorChapMutual(hostBusAdapter, cmd, hbaName)
   elif cmd == ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_CHAP_UNI_GET_CMD and \
        hbaName != None:
      status, output = GetTargetPortalChapUniAll(hostBusAdapter, cmd, hbaName)
   elif cmd == ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_CHAP_MUTUAL_GET_CMD and \
        hbaName != None:
      status, output = GetTargetPortalChapMutualAll(hostBusAdapter, cmd, hbaName)
   elif cmd == ISCSI_INITIATOR_CONFIG_TARGET_PORTAL_PARM_GET_CMD and \
        hbaName != None:
      status, output = GetTargetPortalParamAll(hostBusAdapter, cmd, hbaName)
   elif cmd == ISCSI_INITIATOR_CONFIG_GET_CAPS_CMD and hbaName != None:
      status, output = GetAdapterCapability(hostBusAdapter, cmd, hbaName)
   elif cmd == ISCSI_INITIATOR_CONFIG_GET_CMD and hbaName != None:
      status, output = GetInitiatorConfig(hostBusAdapter, cmd, hbaName)
   elif cmd == ISCSI_INITIATOR_CONFIG_SENDTARGET_LIST_CMD and hbaName != None:
      status, output = GetInitiatorSendTargetList(hostBusAdapter, cmd, hbaName)
   elif cmd == ISCSI_INITIATOR_CONFIG_SENDTARGET_CHAP_MUTUAL_GET_CMD and \
        hbaName != None and ip != None and port != None:
      status, output = GetSendTargetChapMutual(hostBusAdapter, cmd, hbaName, ip, port)
   elif cmd == ISCSI_INITIATOR_CONFIG_SENDTARGET_CHAP_UNI_GET_CMD and \
        hbaName != None and ip != None and port != None:
      status, output = GetSendTargetChapUni(hostBusAdapter, cmd, hbaName, ip, port)
   elif cmd == ISCSI_INITIATOR_CONFIG_IPCONFIG_GET_CMD and hbaName != None:
      status, output = GetIpConfig(hostBusAdapter, cmd, hbaName)
   elif cmd == ISCSI_INITIATOR_CONFIG_IPV6CONFIG_GET_CMD and hbaName != None:
      status, output = GetIpv6Config(hostBusAdapter, cmd, hbaName)
   elif cmd == ISCSI_INITIATOR_CONFIG_IPV6CONFIG_ADDRESS_GET_CMD and \
        hbaName != None:
      status, output = GetIpv6Address(hostBusAdapter, cmd, hbaName)
   elif cmd == ISCSI_INITIATOR_CONFIG_PNP_PARM_GET_CMD and hbaName != None:
      status, output = GetPnpParam(hostBusAdapter, cmd, hbaName)
   elif cmd == ISCSI_INITIATOR_CONFIG_SENDTARGET_PARM_GET_CMD and \
        hbaName != None and ip != None and port != None:
      status, output = GetSendtargetParam(hostBusAdapter, cmd, hbaName, ip, port)
   return status, output


@logInfo(ISCSI_STORAGE_CORE_ADAPTER_LIST_CMD)
def GetCoreAdapterList(hostBusAdapter, cmd):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         output.append({'HBA Name':hba.device, 'Driver':hba.driver})
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() Failed to get "%s" from hostConfigInfo' % \
         (GetCoreAdapterList.__name__, cmd))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


@logInfo(ISCSI_INITIATOR_CONFIG_ADAPTER_LIST_CMD)
def GetIscsiAdapterList(hostBusAdapter, cmd):
   output = []
   status = True

   try:
      output = [{'Adapter':hba.device} for hba in hostBusAdapter if \
                'InternetScsiHba' in hba.key]
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetIscsiAdapterList.__name__, cmd))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetEsxcliMappedName(name):
   """Returns modified name according to esxcli output"""
   modifiedName = None
   if name == 'MaxCommands':
      modifiedName = 'MaxCmds'
   elif name == 'LoginRetryMax':
      modifiedName = 'InitialLoginRetryMax'
   elif name == 'MaxRecvDataSegLen':
      modifiedName = 'MaxRecvDataSegment'
   elif name == 'DefaultTimeToWait':
      modifiedName = 'DefaultTime2Wait'
   elif name == 'DefaultTimeToRetain':
      modifiedName = 'DefaultTime2Retain'
   elif name == 'NoopTimeout':
      modifiedName = 'NoopOutTimeout'
   elif name == 'NoopInterval':
      modifiedName = 'NoopOutInterval'
   elif name == 'InitR2T':
      modifiedName = 'InitialR2T'
   return modifiedName if modifiedName else name


def GetIscsiAdapterParam(hostBusAdapter, cmd, hbaName):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            FillOutputWithParams(output,
                                 hbaName,
                                 hba.supportedAdvancedOptions,
                                 hba.advancedOptions,
                                 hba.digestCapabilities,
                                 hba.digestProperties)
            break

   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetIscsiAdapterParam.__name__, cmd % {'hba':hbaName}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetMappedProps(digestProp):
   """Maps digest propertoes name used in hostConfigInfo to
   the name used in esx.
   e.g. digestProhibited => prohibited
   """
   if digestProp is None:
      return ''

   digestProp = digestProp.lower()
   if 'preferred' in digestProp:
      return 'preferred'
   elif 'prohibited' in digestProp:
      return 'prohibited'
   elif 'discourage' in digestProp:
      return 'discouraged'
   elif 'required' in digestProp:
      return 'required'


def FillOutputWithParams(output,
                         ID,
                         supportedAdvancedOptions,
                         advancedOptions,
                         digestCapabilities,
                         digestProperties,
                         forTarget=False):
   """Helper function to populated properties for adapter, sendtarget
   and target portal.
   """
   for (supOpt, advOpt) in zip(supportedAdvancedOptions, advancedOptions):
      outDict = dict()
      outDict['ID'] = str(ID)
      outDict['Name'] = GetEsxcliMappedName(supOpt.key)
      outDict['Default'] = str(supOpt.optionType.defaultValue).lower()
      outDict['Min'] = str(supOpt.optionType.min) if \
         hasattr(supOpt.optionType, 'min') else 'na'
      outDict['Max'] = str(supOpt.optionType.max) if \
         hasattr(supOpt.optionType, 'max') else 'na'
      outDict['Settable'] = False if supOpt.optionType.valueIsReadonly else True
      outDict['Current'] = str(advOpt.value).lower()
      outDict['Inherit'] = False if advOpt.isInherited is None else True
      output.append(outDict)
   # Add header digest and data digest info seperately
   headerDigest = dict()
   headerDigest['ID'] = str(ID)
   headerDigest['Name'] = 'HeaderDigest'
   headerDigest['Default'] = 'prohibited'
   headerDigest['Min'] = 'na'
   headerDigest['Max'] = 'na'
   headerDigest['Settable'] = digestCapabilities.dataDigestSettable if not \
      forTarget else digestCapabilities.targetHeaderDigestSettable
   headerDigest['Current'] = GetMappedProps(digestProperties.headerDigestType)
   headerDigest['Inherit'] = digestProperties.headerDigestInherited if \
                             digestProperties.headerDigestInherited else False
   output.append(headerDigest)
   dataDigest = dict()
   dataDigest['ID'] = str(ID)
   dataDigest['Name'] = 'DataDigest'
   dataDigest['Default'] = 'prohibited'
   dataDigest['Min'] = 'na'
   dataDigest['Max'] = 'na'
   dataDigest['Settable'] = digestCapabilities.dataDigestSettable if not \
      forTarget else digestCapabilities.targetDataDigestSettable
   dataDigest['Current'] = GetMappedProps(digestProperties.dataDigestType)
   dataDigest['Inherit'] =  digestProperties.dataDigestInherited if \
                            digestProperties.dataDigestInherited else False
   output.append(dataDigest)


def GetInitiatorChapUni(hostBusAdapter, cmd, hbaName):
   output = []
   status = True
   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            outDict = dict()
            authProps = hba.authenticationProperties
            outDict['Direction'] = 'uni'
            outDict['Name'] = authProps.chapName
            outDict['Adapter'] = hbaName
            outDict['Level'] = GetMappedProps(authProps.chapAuthenticationType)
            output.append(outDict)
            break

   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetInitiatorChapUni.__name__, cmd % {'hba':hbaName}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetInitiatorChapMutual(hostBusAdapter, cmd, hbaName):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            outDict = dict()
            authProps = hba.authenticationProperties
            outDict['Direction'] = 'mutual'
            outDict['Name'] = authProps.mutualChapName
            outDict['Adapter'] = hbaName
            outDict['Level'] = GetMappedProps(authProps.mutualChapAuthenticationType)
            output.append(outDict)
            break
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetInitiatorChapMutual.__name__, cmd % {'hba':hbaName}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetInitiatorStaticTargetList(hostBusAdapter, cmd, hbaName):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            targetList = hba.configuredStaticTarget
            for target in targetList:
               if target.discoveryMethod == 'staticMethod':
                  outDict = dict()
                  outDict['Adapter'] = hbaName
                  outDict['Target Name'] = target.iScsiName
                  outDict['Target Address'] = \
                     ''.join([target.address, ":", str(target.port)])
                  outDict['TGPT'] = 'na'
                  outDict['Boot'] = 'False'
                  output.append(outDict)
            break
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetInitiatorStaticTargetList.__name__, cmd % {'hba':hbaName}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetTargetPortalChapUniAll(hostBusAdapter, cmd, hbaName):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            for target in hba.configuredStaticTarget:
               outDict = dict()
               outDict['Direction'] = 'uni'
               outDict['Method'] = 'chap'
               outDict['TargetName'] = target.iScsiName
               outDict['Inheritance'] = target.authenticationProperties.chapInherited
               outDict['Level'] = \
                  GetMappedProps(target.authenticationProperties.chapAuthenticationType)
               outDict['Parent'] = target.parent
               outDict['Address'] = \
                  ''.join([target.address, ":", str(target.port)])
               outDict['Name'] = target.authenticationProperties.chapName
               output.append(outDict)
            break
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetTargetPortalChapUniAll.__name__, cmd % {'hba':hbaName}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})

   return status, output


def GetTargetPortalChapMutualAll(hostBusAdapter, cmd, hbaName):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            for target in hba.configuredStaticTarget:
               outDict = dict()
               outDict['Direction'] = 'mutual'
               outDict['Method'] = 'chap'
               outDict['TargetName'] = target.iScsiName
               outDict['Inheritance'] = \
                  target.authenticationProperties.mutualChapInherited
               outDict['Level'] = \
                  GetMappedProps(target.authenticationProperties.mutualChapAuthenticationType)
               outDict['Parent'] = target.parent
               outDict['Address'] = \
                  ''.join([target.address, ":", str(target.port)])
               outDict['Name'] = target.authenticationProperties.mutualChapName
               output.append(outDict)
            break
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetTargetPortalChapMutualAll.__name__, cmd % {'hba':hbaName}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetTargetPortalParamAll(hostBusAdapter, cmd, hbaName):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            for target in hba.configuredStaticTarget:
               ID = ''.join([target.iScsiName, ',', target.address,
                             ':', str(target.port)])
               FillOutputWithParams(output,
                                    ID,
                                    target.supportedAdvancedOptions,
                                    target.advancedOptions,
                                    hba.digestCapabilities,
                                    target.digestProperties,
                                    forTarget=True)
            break
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetTargetPortalParamAll.__name__, cmd % {'hba':hbaName}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetAdapterCapability(hostBusAdapter, cmd, hbaName):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            outDict = dict()
            hbaCaps = hba.discoveryCapabilities
            hbaAuth = hba.authenticationCapabilities
            hbaDigestCap = hba.digestCapabilities
            hbaIPCap = hba.ipCapabilities
            outDict['ID'] = hbaName
            outDict['ISnS Settable'] = hbaCaps.iSnsDiscoverySettable
            outDict['SLP Settable'] = hbaCaps.slpDiscoverySettable
            outDict['Static Discovery Settable'] = hbaCaps.staticTargetDiscoverySettable
            outDict['Sendtarget Discovery Settable'] = \
               hbaCaps.sendTargetsDiscoverySettable
            outDict['Authorization Method Settable'] = hbaAuth.chapAuthSettable
            outDict['CHAP Authorization Supported'] = hbaAuth.chapAuthSettable
            outDict['SRP Authorization Supported'] = hbaAuth.srpAuthSettable
            outDict['KRB5 Authorization Supported'] = hbaAuth.krb5AuthSettable
            outDict['SPKM1 Authorization Supported'] = hbaAuth.spkmAuthSettable
            outDict['SPKM2 Authorization Supported'] = hbaAuth.spkmAuthSettable
            outDict['Mutual Authentication Supported'] = hbaAuth.mutualChapSettable
            outDict['Target Level Authentication Supported'] = hbaAuth.targetChapSettable
            outDict['Target Level Mutual Authentication Supported'] = \
               hbaAuth.targetMutualChapSettable
            outDict['Adapter Header Digest Supported'] = \
               hbaDigestCap.headerDigestSettable
            outDict['Target Level Header Digest Supported'] = \
               hbaDigestCap.targetHeaderDigestSettable
            outDict['Adapter Data Digest Supported'] = hbaDigestCap.dataDigestSettable
            outDict['Target Level Data Digest Supported'] = \
               hbaDigestCap.targetDataDigestSettable
            outDict['ARP Redirect Settable'] = hbaIPCap.arpRedirectSettable
            outDict['MTU Settable'] = hbaIPCap.mtuSettable
            outDict['Delayed Ack Settable'] = None
            outDict['IPv6 Supported'] = hbaIPCap.ipv6Supported
            outDict['DNS Based Address Supported'] = \
               hbaIPCap.hostNameAsTargetAddress
            outDict['Inheritance Supported'] = True
            outDict['IPv4 Enable Settable'] = hbaIPCap.ipv4EnableSettable
            outDict['IP Configuration Method Settable'] = \
               hbaIPCap.ipConfigurationMethodSettable
            outDict['Subnet Mask Setttable'] = hbaIPCap.subnetMaskSettable
            outDict['Default Gateway Settable'] = hbaIPCap.defaultGatewaySettable
            outDict['IPv6 Enable Settable'] = hbaIPCap.ipv6EnableSettable
            outDict['IPv6 Prefix Length Settable'] = hbaIPCap.ipv6PrefixLengthSettable
            outDict['IPv6 DHCP Configuration Method Settable'] = \
               hbaIPCap.ipv6DhcpConfigurationSettable
            outDict['IPv6 Linklocal Auto Configuration Method Settable'] = \
               hbaIPCap.ipv6LinkLocalAutoConfigurationSettable
            outDict['IPv6 Router Advertisement Configuration Method Settable'] = \
               hbaIPCap.ipv6RouterAdvertisementConfigurationSettable
            outDict['IPv6 Default Gateway Settable'] = \
               hbaIPCap.ipv6DefaultGatewaySettable
            outDict['Primary DNS Settable'] = \
               hbaIPCap.primaryDnsServerAddressSettable
            outDict['Secondary DNS Settable'] = \
               hbaIPCap.alternateDnsServerAddressSettable
            outDict['Name And Alias Settable'] = hbaIPCap.nameAliasSettable
            output += [outDict]
            break
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetAdapterCapability.__name__, cmd % {'hba':hbaName}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetInitiatorConfig(hostBusAdapter, cmd, hbaName):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            outDict = dict()
            outDict['ID'] = hbaName
            outDict['Name'] = hba.iScsiName
            outDict['Alias'] = hba.iScsiAlias
            outDict['Driver Name'] = hba.driver
            outDict['TCP Protocol Supported'] = hba.networkBindingSupport
            outDict['Bidirectional Transfers Supported'] = ''
            outDict['Can Be NIC'] = ''
            outDict['Is NIC'] = 'true' if hba.isSoftwareBased and \
               (not hba.canBeDisabled) else 'false'
            outDict['Using TCP Offload Engine'] = 'true' if \
               hba.networkBindingSupport in ['notsupported', 'required'] else 'false'
            outDict['Using ISCSI Offload Engine'] =  'true' if \
               hba.networkBindingSupport in ['notsupported', 'required'] else 'false'
            output.append(outDict)
            break
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetInitiatorConfig.__name__, cmd % {'hba':hbaName}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetInitiatorSendTargetList(hostBusAdapter, cmd, hbaName):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            for target in hba.configuredSendTarget:
               outDict = dict()
               outDict['Sendtarget'] = ''.join([target.address, ':', str(target.port)])
               outDict['Adapter'] = hbaName
               output.append(outDict)
            break
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetInitiatorSendTargetList.__name__, cmd % {'hba':hbaName}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetSendTargetChapMutual(hostBusAdapter, cmd, hbaName, ip, port):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            for target in hba.configuredSendTarget:
               if target.address == ip and str(target.port) == port:
                  outDict = dict()
                  outDict['Sendtarget'] = \
                     ''.join([target.address, ':', str(target.port)])
                  outDict['Direction'] = 'mutual'
                  outDict['Parent'] = hbaName
                  outDict['Name'] = target.authenticationProperties.mutualChapName
                  outDict['Inheritance'] = \
                     target.authenticationProperties.mutualChapInherited
                  outDict['Level'] = \
                     GetMappedProps(target.authenticationProperties.mutualChapAuthenticationType)
                  output.append(outDict)
                  break
            break
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetSendTargetChapMutual.__name__, \
         cmd % {'hba':hbaName, 'ip':ip, 'port':port}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetSendTargetChapUni(hostBusAdapter, cmd, hbaName, ip, port):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            for target in hba.configuredSendTarget:
               if target.address == ip and str(target.port) == port:
                  outDict = dict()
                  outDict['Sendtarget'] = \
                     ''.join([target.address, ':', str(target.port)])
                  outDict['Direction'] = 'uni'
                  outDict['Parent'] = hbaName
                  outDict['Name'] = target.authenticationProperties.chapName
                  outDict['Inheritance'] = \
                     target.authenticationProperties.chapInherited
                  outDict['Level'] = \
                     GetMappedProps(target.authenticationProperties.chapAuthenticationType)
                  output.append(outDict)
                  break
            break
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetSendTargetChapUni.__name__, \
          cmd % {'hba':hbaName, 'ip':ip, 'port':port}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetIpConfig(hostBusAdapter, cmd, hbaName):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            outDict = dict()
            outDict['IPv4Enabled'] = hba.ipProperties.ipv4Enabled
            outDict['IPv4'] = hba.ipProperties.address
            outDict['IPv4SubnetMask'] = hba.ipProperties.subnetMask
            outDict['IPv6'] =  hba.ipProperties.ipv6Address
            outDict['UseDhcpv4'] = hba.ipProperties.dhcpConfigurationEnabled
            outDict['Gateway'] = hba.ipProperties.defaultGateway
            outDict['PrimaryDNS'] = hba.ipProperties.primaryDnsServerAddress
            outDict['SecondaryDNS'] = hba.ipProperties.alternateDnsServerAddress
            output.append(outDict)
            break
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetIpConfig.__name__, cmd % {'hba':hbaName}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetIpv6Config(hostBusAdapter, cmd, hbaName):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            outDict = dict()
            outDict['IPv6 Supported'] = hba.ipCapabilities.ipv6Supported
            outDict['IPv6 Enabled'] = hba.ipProperties.ipv6Enabled
            outDict['Gateway6'] = hba.ipProperties.ipv6properties.ipv6DefaultGateway if\
               hba.ipProperties.ipv6properties else ''
            outDict['Use IPv6 Router Advertisement'] = hba.ipProperties.\
               ipv6properties.ipv6RouterAdvertisementConfigurationEnabled if\
               hba.ipProperties.ipv6properties else ''
            outDict['Use Link Local Auto Configuration'] = hba.ipProperties.\
               ipv6properties.ipv6LinkLocalAutoConfigurationEnabled if\
               hba.ipProperties.ipv6properties else ''
            outDict['Use Dhcpv6'] = hba.ipProperties.\
               ipv6properties.ipv6DhcpConfigurationEnabled if\
               hba.ipProperties.ipv6properties else ''
            outDict['IPv6 Prefix Length'] = hba.ipCapabilities.ipv6PrefixLength
            outDict['IPv6 Max Static Address Supported'] = hba.ipCapabilities.\
               ipv6MaxStaticAddressesSupported
            output.append(outDict)
            break;
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetIpv6Config.__name__, cmd % {'hba':hbaName}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, dict(output[0])


def parseIpv6AddressOrigin(addrOrigin):
   addressOrigin = addrOrigin.lower()
   if 'autoconfig' in addressOrigin:
      return 'AUTOCONF'
   elif 'linklocal' in addressOrigin:
      return 'LINKLOCAL'
   else:
      return addrOrigin


def GetIpv6Address(hostBusAdapter, cmd, hbaName):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            ipv6Addresses = hba.ipProperties.ipv6properties.iscsiIpv6Address
            for addrs in ipv6Addresses:
               outDict = dict()
               outDict['Type'] = parseIpv6AddressOrigin(addrs.origin)
               outDict['IPv6PrefixLength'] = addrs.prefixLength
               outDict['Address'] = addrs.address
               output.append(outDict)
            break
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetIpv6Address.__name__, cmd % {'hba':hbaName}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetPnpParam(hostBusAdapter, cmd, hbaName):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            output.append({'Value': hba.ipProperties.mtu, 'Option':'MTU'})
            output.append({'Value': hba.ipProperties.arpRedirectEnabled,
                           'Option':'ArpRedirect'})
            break
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetPnpParam.__name__, cmd % {'hba':hbaName}))
      IscsiRaiseException(cmd, str(atrErr),
        {'cmd': cmd, 'error':'Key not found'})
   return status, output


def GetSendtargetParam(hostBusAdapter, cmd, hbaName, ip, port):
   output = []
   status = True

   try:
      for hba in hostBusAdapter:
         if hba.device == hbaName:
            for target in hba.configuredSendTarget:
               if target.address == ip and str(target.port) == port:
                  ID = ''.join([ip, ':', port])
                  FillOutputWithParams(output,
                                       ID,
                                       target.supportedAdvancedOptions,
                                       target.advancedOptions,
                                       hba.digestCapabilities,
                                       target.digestProperties,
                                       forTarget=True)
                  break
            break
   except AttributeError as atrErr:
      status = False
      IscsiLog(1, '%s() failed to get "%s" from hostConfigInfo' % \
         (GetSendtargetParam.__name__, \
          cmd % {'hba':hbaName, 'ip':ip, 'port':port}))
      IscsiRaiseException(cmd, str(atrErr),
         {'cmd': cmd, 'error':'Key not found'})
   return status, output


# Utility function to traverse and print profiles
def TraverseProfiles(profileInstances, indent=0):
   if not iscsiLogLevel >= 5:
      return

   for profInst in profileInstances:
      Spaces=('%'+str(indent)+'s')  % ('')
      print(Spaces, 'Profile : ' + profInst.__class__.__name__ + \
         ' id: %d' % (id(profInst)))
      print(Spaces, ' dependencies : ', profInst.dependencies)
      print(Spaces, ' dependents : ', profInst.dependents)
      TraverseProfiles(profInst.subprofiles, indent+3)

   return

# Utility function to print the given profile instances
def PrintProfileInstances(profileInstances):
   for profInst in profileInstances:
      print('dependencies : ', profInst.dependencies)
      print('dependents : ', profInst.dependents)
      print('Policies for ' + profInst.__class__.__name__ + \
         ' id: %d' % (id(profInst)))
      if profInst.policies is None: continue
      for p in profInst.policies:
         print('\tPolicy=' + p.__class__.__name__ + ' policyOption=' + \
            p.policyOption.__class__.__name__)
         for v in p.policyOption.paramValue:
            print("\t\t{ '%s' : '%s' }" % (v))

# Utility function to print the policy
def PrintPolicy(policyInst):
   print('\npolicy=%s' % policyInst.__class__.__name__ + \
         ' policyOption=%s ' % policyInst.policyOption.__class__.__name__)

   for param in policyInst.policyOption.paramValue:
      print("\t{ '%s' : '%s' }" % (param))

#
# Compares 2 objects to be similar.
#
# Returns:
#  True if not same
#  False if same
#
def Compare(obj1, obj2):
   if (obj1 != None) and (obj1 != obj2):
      return True

   return False

#
# Compares iscsi param to be similar or not.
#
# Arguments:
#  p1 new
#  p2 cur
#
# Returns:
#  True if not same
#  False if same
#
def IscsiParamCompare(p1, p2):
   # If new is None (from profile) return False
   if p1 is None:
      return False

   # if not tuple, compare 2 objects directly
   if not isinstance(p2, tuple):
      if (p1 != p2):
         return True
   else:
      # If it is tuple, then we have: policy, current, default, inherit

      # If the profile indicates that to set initiator default
      if p1[0] == ISCSI_INITIATOR_DEFAULT_VALUE:
         # inherit is False and current and default are same,
         # not need to do anything
         if p2[3] == False and  p2[2] == p2[1]:
            return False
         else:
            return True
      elif p1[0] != p2[0]:
         return True

   return False

# Converts value to a esxcli argument
def ValueToOption(value):
   if isinstance(value, bool):
      return '--value "%s"' % ('true' if value == True else 'false')
   elif isinstance(value, int):
      return '--value "%d"' % (value)
   elif isinstance(value, str):
      if value == 'InheritFromParent':
         return '--inherit'
      elif value == ISCSI_INITIATOR_DEFAULT_VALUE:
         return '--default'
      else:
         return '--value "%s"' % (value)
   else:
      assert()

# Given ipv6address and netmask returns network portion of the address
def NetworkAddress6(ipaddress, netmask):
   return ipaddress.IPv6Network(''.join([ipaddress, '/', netmask]))

# Given ipv4address and netmask returns network portion of the address
def NetworkAddress(ipaddress, netmask):
   return ipaddress.IPv4Network(''.join([ipaddress, '/', netmask]))

#
# Given a task set dict, make a copy and expand the copy'd keyValue
# to cli options.
#
# ex: {'x': 'xyz, keyValue : {'level': 'lvl1', \
#                             'authname' : 'CN', \
#                             'secret': 'CS'}}
# will be expanded to:
# ex: {'x': 'xyz, keyValue : '--level lvl1 --authname CN --secret CS'}
#
def ExpandKeyValues(taskDict):
   newTaskDict = taskDict.copy()
   keyValueDict = taskDict.get('keyValue')
   if isinstance(keyValueDict, dict):
      keyValue = ''
      for keyFromDict in keyValueDict:
         keyValue = '%s --%s "%s"' % (keyValue, keyFromDict, keyValueDict[keyFromDict])

      newTaskDict.update({ 'keyValue': keyValue })

   return newTaskDict

#
# Run any command from task set dict
#
def IscsiRunCommand(cls, hostServices, profileData, taskDict, searchString, replaceString, failOK, logLevel):

   # expand the keyValue options
   newTaskDict = ExpandKeyValues(taskDict)

   # Do the substitute stuff for hba names
   if searchString and newTaskDict.get('hba'):
      newTaskDict['hba'] = newTaskDict['hba'].replace(searchString, replaceString)

   # Format the CLI command
   cliCmd = eval(newTaskDict.get('task')+'_CMD') % newTaskDict

   IscsiLog(logLevel, 'IscsiRunCommand : %s, failOK=%s' %(cliCmd, failOK))

   # Execute the CLI command
   status, output = runcommand.runcommand(cliCmd)

   if status != 0:
      if not failOK:
         IscsiRaiseException(cliCmd, ISCSI_EXCEPTION_CLICMD_FAILED, {'cmdline': cliCmd, 'error': output})
         log.error('Failed to execute "%s" command. Status = %d, Error = %s' % (cliCmd, status, output))

   return status, output

#
# Update the policy param with the new value
# Update only if the value is None or empty
# Returns:
#  True if set
#  False if not
#
def IscsiUpdatePolicyOptParam(policyOptObj, name, value):
   oldValue = getattr(policyOptObj, name, value)
   if oldValue == None or \
      (isinstance(oldValue, str) and len(oldValue) == 0):

      # Set the value in the attribute first
      setattr(policyOptObj, name, value)

      # Replace in the param list if exist
      for n in range(0, len(policyOptObj.paramValue)):
         if policyOptObj.paramValue[n][0] == name:
            policyOptObj.paramValue[n] = (name, value)
            return True

      # Add to the param list if it did not exist
      policyOptObj.paramValue.append((name, value))
      return True

   return False

#
# Helper function to get hostValue, profileValue and comparisonIdentifier
# from taskdict
#
def IscsiGetHostProfileAndComparisonIdentifer(taskDict):
   """ Return hostValue, profileValue, and comparisonIdentifier from taskdict.
   """
   hostValue = None
   profileValue = None
   comparisonIdentifier = None
   if 'hostValue' in taskDict:
      if isinstance(taskDict.get('hostValue'), tuple):
         hostValue = taskDict.get('hostValue')[0]
      else:
         hostValue = taskDict['hostValue']
      if 'profileValue' in taskDict:
         if isinstance(taskDict.get('profileValue'), tuple):
            profileValue = taskDict.get('profileValue')[0]
         else:
            profileValue = taskDict['profileValue']
   comparisonIdentifier = taskDict.get('comparisonIdentifier', 'iscsi')

   return hostValue, profileValue, comparisonIdentifier

#
# Convert the tasks into non-compliant errors.
#
# For Compliance Check we do the generate task list and then convert
# that into compliance errors.
#
def IscsiGenerateComplianceErrors(cls, profileInstances, profInst, hostServices,
                                  configData, parent, taskData, complianceErrors):
   for taskDict in taskData:
      mesgCode = eval(taskDict['task']+'_CHECK')
      reason = taskDict.get('reason')
      noCC = taskDict.get('noCC')
      if reason != ISCSI_REASON_ADD and noCC != True:
         if taskDict.get('hba') == SOFTWARE_ISCSI_ADAPTER_PLACE_HOLDER:
            taskDict['hba'] = SOFTWARE_ISCSI_ADAPTER_DESCRIPTION

         hostValue, profileValue, comparisonIdentifier = \
            IscsiGetHostProfileAndComparisonIdentifer(taskDict)
         hba = GetIscsiHbaFromProfile(None, parent, False)
         # Handling the case where hba software iscsi is not initialized.
         profileInstance = hba.GetName() if hba else \
            taskDict.get('profileInstance', '')
         complianceValueOption = taskDict.get('complianceValueOption',
                                              MESSAGE_VALUE)

         IscsiCreateLocalizedMessage(profInst,
                                     '%s.label' % mesgCode,
                                     taskDict,
                                     complianceErrors,
                                     hostValue,
                                     profileValue,
                                     comparisonIdentifier,
                                     profileInstance,
                                     complianceValueOption,
                                     errorForCompliance=True
                                    )
   return

def IscsiChapSecretToVimPassword(chapSecretStr):
   chapSecret = Vim.PasswordField()

   chapSecret.value = chapSecretStr

   return chapSecret

def VimPasswordToIscsiChapSecret(profInst, policyInst, policyOpt):
   return policyOpt.chapSecret.value
