#!/usr/bin/python
# **********************************************************
# Copyright 2013-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


#
VSAN_PROFILE_VERSION = '2.0'

VSAN_VPD_CASTORE = '/etc/vmware/ssl/vsanvp_castore.pem'

# Defaults
VSAN_DEFAULT_ENABLED = False
VSAN_DEFAULT_STRETCHED_ENABLED = False
VSAN_DEFAULT_UUID = '00000000-0000-0000-0000-000000000000'
VSAN_DEFAULT_DATASTORENAME = 'vsanDatastore'
VSAN_DEFAULT_AUTOCLAIMSTORAGE = False
VSAN_DEFAULT_CLUSTERPOLICY = '()'
VSAN_DEFAULT_VDISKPOLICY = '()'
VSAN_DEFAULT_VMNAMESPACE = '()'
VSAN_DEFAULT_VMSWAP = '(("hostFailuresToTolerate" i1) ("forceProvisioning" i1))'
VSAN_DEFAULT_VMEM = '(("hostFailuresToTolerate" i1) ("forceProvisioning" i1))'
VSAN_DEFAULT_VMKNICNAME = 'vmk0'
VSAN_DEFAULT_IPPROTOCOL = 'IP'
VSAN_DEPRECATED_DEFAULT_IPPROTOCOL = 'IPv4'
VSAN_SUPPORTED_IPPROTOCALS = [VSAN_DEFAULT_IPPROTOCOL, VSAN_DEPRECATED_DEFAULT_IPPROTOCOL]
VSAN_DEFAULT_AGENTMCADDR = '224.2.3.4'
VSAN_DEFAULT_AGENTMCPORT = 23451
VSAN_DEFAULT_MASTERMCADDR = '224.1.2.3'
VSAN_DEFAULT_MASTERMCPORT = 12345
VSAN_DEFAULT_MCTTL = 5
VSAN_DEFAULT_FAULTDOMAIN = ''
VSAN_DEFAULT_IPV6_AGENTMCADDR = 'ff19::2:3:4'
VSAN_DEFAULT_IPV6_MASTERMCADDR = 'ff19::1:2:3'
VSAN_DEFAULT_TRAFFICTYPE = 'vsan'
VSAN_SUPPORTED_TRAFFICTYPES = ['vsan', 'witness']
VSAN_FAULTDOMAIN_MAX_LENGTH = 256

VSAN_DEFAULT_IS_WITNESS = False
VSAN_DEFAULT_PREFERREDFD = ''
VSAN_DEFAULT_UNICAST_AGENT = ''
# NIC option conversion for esxcli
VSAN_NIC_OPTIONS = {'AgentGroupMulticastAddress'    : 'agent-mc-addr', \
                    'AgentGroupMulticastPort'       : 'agent-mc-port', \
                    'MasterGroupMulticastAddress'   : 'master-mc-addr', \
                    'MasterGroupMulticastPort'      : 'master-mc-port', \
                    'MulticastTTL'                  : 'multicast-ttl', \
                    'AgentGroupIPv6MulticastAddress'  : 'agent-v6-mc-addr', \
                    'MasterGroupIPv6MulticastAddress' : 'master-v6-mc-addr', \
                    'TrafficType' : 'traffic-type',}

# Task ids
# The number decides the execution sequence.
# Any new task to be added, please pick a
# proper number.
VSAN_VPD_CASTORE_TASK = 1
# Reserve 9 OPs for pre-request of VSAN enablement
VSAN_CLUSTER_JOIN_TASK = 10
# Cluster configuration OPs
VSAN_AUTOCLAIM_TASK = 20
VSAN_FAULTDOMAIN_TASK = 25
VSAN_SET_PREFERREDFD_TASK = 30
VSAN_ADD_UNICAST_AGENT_TASK = 35
# VSAN datastore related OPs
VSAN_DATASTORENAME_TASK = 50
VSAN_STORAGEPOLICY_TASK = 55
# NIC related OPs
VSAN_NIC_TASK = 60
VSAN_NIC_MISSING_TASK = 65
VSAN_NIC_EXTRA_TASK = 70
# Reserve for future
# Disable VSAN is the last thing to do
VSAN_CLUSTER_LEAVE_TASK = 100

#
# Messages
#

VSAN_BASE = 'com.vmware.profile.plugins.vsan'
VSAN_ERROR_BASE = '%s.%s' % (VSAN_BASE, 'error')
VSAN_FAIL_BASE = '%s.%s' % (VSAN_BASE, 'fail')
VSAN_COMPLIANCE_BASE = '%s.%s' % (VSAN_BASE, 'compliance')
VSAN_TASK_BASE = '%s.%s' % (VSAN_BASE, 'task')

# Failure messages
VSAN_GETAUTOCLAIM_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'GetAutoclaim')
VSAN_GETDATASTORENAME_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'GetDatastoreName')
VSAN_GETDEFAULT_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'GetDefault')
VSAN_NETWORKLIST_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'NetworkList')
VSAN_SYSNETWORKLIST_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'SysNetworkList')
VSAN_INCONSISTENTNETWORKLIST_FAIL_KEY = '%s.%s' % \
                                   (VSAN_FAIL_BASE, 'InconsistentNetworkList')
VSAN_JOIN_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'Join')
VSAN_LEAVE_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'Leave')
VSAN_UNKNOWNTASK_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'UnknownTask')
VSAN_SETAUTOCLAIM_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'SetAutoclaim')
VSAN_SETDATASTORENAME_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'SetDatastoreName')
VSAN_STORAGEPOLICY_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'StoragePolicy')
VSAN_NIC_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'NetworkInterface')
VSAN_NIC_MISSING_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'NicMissing')
VSAN_NIC_EXTRA_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'NicExtra')
VSAN_BADIPPROTOCOL_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'BadIProtocol')
VSAN_GETFAULTDOMAIN_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'GetFaultDomain')
VSAN_SETFAULTDOMAIN_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'SetFaultDomain')
VSAN_GET_PREFERREDFD_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, 'GetPreferredFD')
VSAN_SET_PREFERREDFD_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, \
                                           'SetPreferredFD')
VSAN_GET_UNICASTAGENT_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, \
                                            'GetUnicastAgent')
VSAN_ADD_UNICASTAGENT_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, \
                                            'AddUnicastAgent')
VSAN_REMOVE_UNICASTAGENT_FAIL_KEY = '%s.%s' % (VSAN_FAIL_BASE, \
                                               'RemoveUnicastAgent')
# Validation error messages
VSAN_UUID_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, 'ClusterUUID')
VSAN_DATASTORENAME_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, 'DatastoreName')
VSAN_STORAGEPOLICY_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, 'StoragePolicy')
VSAN_IPPROTOCOL_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, 'IpProtocol')
VSAN_ENABLEDUUID_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, 'EnabledUUID')
VSAN_NULL_UUID_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, 'NullUUID')
VSAN_NIC_NOVSANTAG_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, 'NicNoVSANTag')
VSAN_NIC_EXTRA_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, 'NicExtra')
VSAN_NIC_MISSING_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, 'NicMissing')
VSAN_FAULTDOMAIN_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, 'FaultDomain')
VSAN_WITNESS_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, 'WitnessNotSpecified')
VSAN_STRETCHED_ENABLED_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, \
                                              'StretchedWithoutVSAN')
VSAN_PREFERREDFD_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, \
                                        'PreferredFDNotCorrect')
VSAN_UNICAST_AGENT_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, \
                                          'UnicastAgentNotCorrect')
VSAN_TRAFFICTYPE_ERROR_KEY = '%s.%s' % (VSAN_ERROR_BASE, 'TrafficType')

# Compliance messages
VSAN_AUTOCLAIMSTORAGE_COMPLIANCE_KEY = '%s.%s' % \
                                    (VSAN_COMPLIANCE_BASE, 'AutoclaimStorage')
VSAN_ENABLE_COMPLIANCE_KEY = '%s.%s' % (VSAN_COMPLIANCE_BASE, 'Enable')
VSAN_UUID_COMPLIANCE_KEY = '%s.%s' % (VSAN_COMPLIANCE_BASE, 'ClusterUUID')
VSAN_DATASTORENAME_COMPLIANCE_KEY = '%s.%s' % \
                                    (VSAN_COMPLIANCE_BASE, 'DatastoreName')
VSAN_STORAGEPOLICY_COMPLIANCE_KEY = '%s.%s' % \
                                       (VSAN_COMPLIANCE_BASE, 'StoragePolicy')
VSAN_NIC_COMPLIANCE_KEY = '%s.%s' % (VSAN_COMPLIANCE_BASE, 'NetworkInterface')
VSAN_NIC_MISSING_COMPLIANCE_KEY = '%s.%s' % \
                                          (VSAN_COMPLIANCE_BASE, 'NicMissing')
VSAN_NIC_EXTRA_COMPLIANCE_KEY = '%s.%s' % (VSAN_COMPLIANCE_BASE, 'NicExtra')
VSAN_FAULTDOMAIN_COMPLIANCE_KEY = '%s.%s' % \
                                    (VSAN_COMPLIANCE_BASE, 'FaultDomain')
VSAN_STRETCHED_ENABLE_COMPLIANCE_KEY = '%s.%s' % \
                                    (VSAN_COMPLIANCE_BASE, 'StretchedEnabled')
VSAN_UNICAST_AGENT_COMPLIANCE_KEY = '%s.%s' % \
                                    (VSAN_COMPLIANCE_BASE, 'UnicastAgent')
VSAN_PREFERRED_FD_COMPLIANCE_KEY = '%s.%s' % \
                                   (VSAN_COMPLIANCE_BASE, 'PreferredFaultDomain')
VSAN_VPD_CASTORE_COMPLIANCE_KEY = '%s.%s' % \
                                  (VSAN_COMPLIANCE_BASE, 'VSANVpdCastore')
# Tasklist messages
VSAN_AUTOCLAIM_TASK_KEY = '%s.%s' % (VSAN_TASK_BASE, 'Autoclaim')
VSAN_ENABLE_TASK_KEY = '%s.%s' % (VSAN_TASK_BASE, 'Enable')
VSAN_UUID_TASK_KEY = '%s.%s' % (VSAN_TASK_BASE, 'ClusterUUID')
VSAN_DATASTORENAME_TASK_KEY = '%s.%s' % (VSAN_TASK_BASE, 'DatastoreName')
VSAN_STORAGEPOLICY_TASK_KEY = '%s.%s' % (VSAN_TASK_BASE, 'StoragePolicy')
VSAN_NIC_TASK_KEY = '%s.%s' % (VSAN_TASK_BASE, 'NetworkInterface')
VSAN_NIC_MISSING_TASK_KEY = '%s.%s' % (VSAN_TASK_BASE, 'NicMissing')
VSAN_NIC_EXTRA_TASK_KEY = '%s.%s' % (VSAN_TASK_BASE, 'NicExtra')
VSAN_FAULTDOMAIN_TASK_KEY = '%s.%s' % (VSAN_TASK_BASE, 'FaultDomain')
VSAN_ADD_UNIAGENT_TASK_KEY = '%s.%s' % (VSAN_TASK_BASE, 'AddUnicastAgent')
VSAN_SET_PREFERREDFD_TASK_KEY = '%s.%s' % (VSAN_TASK_BASE, 'SetPreferredFD')
VSAN_VPD_CASTORE_TASK_KEY = '%s.%s' % (VSAN_TASK_BASE, 'VSANVpdCastore')
