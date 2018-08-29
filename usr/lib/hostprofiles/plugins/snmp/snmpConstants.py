#!/usr/bin/python
# **********************************************************
# Copyright 2014-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

# The following 14 xml elements returned by cmd: esxcli system snmp get
# mostly match the xml element names found /etc/vmware/snmp.xml
# for which the mappings to snmp.xml are provided below. Differences
# were due to maintaining --flag-name backward compatiblity
# with RCLI: vicfg-snmp command
AUTH_PROTOCOL = 'authentication' # aka authProtocol
COMMUNITIES = 'communities'
ENABLE = 'enable'
ENGINEID = 'engineid'
EV_FILTER = 'notraps' # aka EventFilter
EV_SOURCE = 'hwsrc' # aka EnvEventSource
LOGLEVEL = 'loglevel'
PORT = 'port'
PRIV_PROTOCOL = 'privacy' # aka privProtocol
SYSCONTACT = 'syscontact'
SYSLOCATION = 'syslocation'
TARGETS = 'targets'
USERS = "users"
REMOTE_USERS = 'remote-users'
V3TARGETS = 'v3targets'
LARGESTORAGE = 'largestorage'

SNMP_CONFIG_FILE = '/etc/vmware/snmp.xml'

# localized msgs in profile.vmsg for this module are keyed from:
AGENT_BASE_KEY = 'com.vmware.profile.GenericAgentConfigProfile'
DEFAULT_SNMP_PORT = 161
# Constants for esxcli commands and errors
ESXCLI_SNMP_NS = 'system snmp'
ESXCLI_SNMP_GET = 'get'
ESXCLI_SNMP_SET = 'set'
ESXCLI_BASE_ERR_KEY = '%s.Esxcli' % AGENT_BASE_KEY

# Task ID's
SNMP_USERS_TASK = 1
SNMP_V3TARGETS_TASK = 2
SNMP_ENGINEID_TASK = 3
SNMP_SYSLOCATION_TASK = 4
SNMP_SYSCONTACT_TASK = 5

TASK_MAP = { SNMP_USERS_TASK : USERS, SNMP_V3TARGETS_TASK : V3TARGETS,
             SNMP_ENGINEID_TASK: ENGINEID, SNMP_SYSLOCATION_TASK: SYSLOCATION,
             SNMP_SYSCONTACT_TASK: SYSCONTACT }
#
# Messages
#

SNMP_BASE = 'com.vmware.vim.profile.Profile.snmp'
SNMP_POLICYOPTION_BASE = 'com.vmware.vim.profile.PolicyOption.'\
                         'snmp.GenericAgentPolicies'
SNMP_ERROR_BASE = '%s.%s' % (SNMP_BASE, 'error')
SNMP_FAIL_BASE = '%s.%s' % (SNMP_BASE, 'fail')
SNMP_COMPLIANCE_BASE = '%s.%s' % (SNMP_BASE, 'compliance')
SNMP_TASK_BASE = '%s.%s' % (SNMP_BASE, 'task')

# Failure Messages
SNMP_CONFIG_FILE_ERROR = '%s.%s' % (AGENT_BASE_KEY, 'ConfigError')
SNMP_VALIDATE_ERROR = '%s.%s' % (AGENT_BASE_KEY, 'ValidateError')

# Compliance Messages
SNMP_COMMON_COMPLIANCE_KEY = '%s.%s' % (SNMP_COMPLIANCE_BASE, 'common')

# task messages
SNMP_USERS_TASK_KEY = '%s.%s' % (SNMP_TASK_BASE, 'users')
SNMP_V3TARGETS_TASK_KEY = '%s.%s' % (SNMP_TASK_BASE, 'v3targets')
SNMP_ENGINEID_TASK_KEY = '%s.%s' % (SNMP_TASK_BASE, 'engineid')
SNMP_SYSLOCATION_TASK_KEY = '%s.%s' % (SNMP_TASK_BASE, 'syslocation')
SNMP_SYSCONTACT_TASK_KEY = '%s.%s' % (SNMP_TASK_BASE, 'syscontact')

