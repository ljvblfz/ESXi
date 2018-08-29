#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************
 
__author__ = "VMware, Inc."
  
#
# Declare command strings for use in task lists
#
FCoE_OP_ACTIVATE           = 'ActivateNic'
FCoE_OP_DEACTIVATE         = 'DeactivateNic'

#
# Declare the keys needed for task lists and compliance checking
#
FCoE_BASE            = 'com.vmware.profile.plugins.fcoe'
FCoE_OP_BASE         = '%s.%s' % (FCoE_BASE, 'operations')
FCoE_ERRORS_BASE     = '%s.%s' % (FCoE_BASE, 'errors')
FCoE_VALIDATOR_BASE  = '%s.%s' % (FCoE_BASE, 'validator')

# TASK OPERATION KEYS
FCoE_ACTIVATE_KEY          = '%s.%s' % (FCoE_OP_BASE, FCoE_OP_ACTIVATE)
FCoE_DEACTIVATE_KEY        = '%s.%s' % (FCoE_OP_BASE, FCoE_OP_DEACTIVATE)

# KEYS FOR ANY ERRORS
FCoE_NOADAP_FOR_MAC_FAIL_KEY      = '%s.%s' % (FCoE_ERRORS_BASE, 'NoAdapForMacFail')
FCoE_NOADAP_FOR_DRIVER_EXISTS_KEY = '%s.%s' % (FCoE_ERRORS_BASE, 'NoAdapForDriverExistsFail')
FCoE_ADAPFAIL_KEY                 = '%s.%s' % (FCoE_ERRORS_BASE, 'CheckAdapFail')
FCoE_REMEDIATE_INVALID_OP_KEY     = '%s.%s' % (FCoE_ERRORS_BASE, 'RemediateInvalidOp')
FCoE_ESXCLI_EXECUTE_FAIL_KEY      = '%s.%s' % (FCoE_ERRORS_BASE, 'EsxcliExecuteFail')
FCoE_DUP_MAC_ADDR_FOR_ACTIVATION_KEY      = '%s.%s' % (FCoE_ERRORS_BASE, 'DupMacForActivation')

# KEYS FOR VALIDATION ERRORS
FCoE_INVALID_MAC_ADDRESS_KEY      = '%s.%s' % (FCoE_VALIDATOR_BASE, 'InvalidMacAddress')
