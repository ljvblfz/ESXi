#!/usr/bin/python
# **********************************************************
# Copyright 2016 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."


# Parameters.
PROV_PROCS = 'provProcs'
THREAD_POOL_SIZE = 'threadPoolSize'
REQ_QUEUE_SIZE = 'requestQueueSize'
PORT = 'port'
LOG_LEVEL = 'loglevel'
AUTH = 'auth'
CIM_SERVICE = 'enable'
WSMAN_SERVICE = 'ws-man'
CERTIFICATE_STORE = 'certificateStore'
DISABLED_PROVIDERS = 'disabledProviders'
SSLv3 = 'enableSSLv3'
TLSv1 = 'enableTLSv1'
TLSv1_1 = 'enableTLSv1_1'
TLSv1_2 = 'enableTLSv1_2'

OLD_PARAM_KEYS = [PROV_PROCS, THREAD_POOL_SIZE, REQ_QUEUE_SIZE]
NEW_PARAM_KEYS = [PORT, LOG_LEVEL, AUTH, CIM_SERVICE,
                  WSMAN_SERVICE, CERTIFICATE_STORE, DISABLED_PROVIDERS]
SSL_KEYS = [SSLv3, TLSv1, TLSv1_1, TLSv1_2]
SSL_DEFAULT = 'default'
SSL_ENABLED = 'true'
SSL_DISABLED = 'false'

# File paths.
CERTIFICATE_STORE_PATH = '/etc/sfcb/client.pem'
SFCB_CONFIG_FILE = '/etc/sfcb/sfcb.cfg'

# Other constants.
ESXCLI_SFCB_NS = 'system wbem'
ESXCLI_SFCB_GET = 'get'
ESXCLI_SFCB_SET = 'set'
ESXCLI_SFCB_PROVIDERS = 'provider'
ESXCLI_SFCB_LIST = 'list'
ESXCLI_PROVIDER_LIST = ' '.join([ESXCLI_SFCB_NS, ESXCLI_SFCB_PROVIDERS,
                                 ESXCLI_SFCB_LIST])
ESXCLI_PROVIDER_SET = ' '.join([ESXCLI_SFCB_NS, ESXCLI_SFCB_PROVIDERS,
                                ESXCLI_SFCB_SET])
LOGLEVEL_CHOICES = ['error', 'warning', 'info', 'debug']
AUTH_CHOICES = ['password', 'certificate']
SSL_CHOICES = [SSL_DEFAULT, SSL_ENABLED, SSL_DISABLED]

# Mapping between esxcli returned labels and parameter names.
labelMap = { 'Port' : PORT,
             'Authorization Model' : AUTH,
             'Log level' : LOG_LEVEL,
             'Enabled' : CIM_SERVICE,
             'WS-Management Service' : WSMAN_SERVICE }

#
# Define the localization message catalog keys used by this profile
#
BASE_MSG_KEY = 'com.vmware.vim.profile.Profile.sfcbConfig'
FAILED_TO_SAVE_MSG_KEY = '%s.FailedToSaveConfig' % BASE_MSG_KEY
FAILED_TO_READ_MSG_KEY = '%s.FailedToReadConfig' % BASE_MSG_KEY
NO_CERTIFICATE_STORE_PRESENT = '%s.NoCertificateStorePresent' % BASE_MSG_KEY
INVALID_PROVIDERS_LIST = '%s.InvalidProvidersList' % BASE_MSG_KEY
