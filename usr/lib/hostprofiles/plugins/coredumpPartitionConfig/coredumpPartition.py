#!/usr/bin/python
# **********************************************************
# Copyright 2011-2016 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

import sys

from pluginApi import ParameterMetadata, log, ProfileComplianceChecker
from pluginApi import CreateLocalizedException
from pluginApi.extensions import SimpleConfigProfile
from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING, COMPONENT_COREDUMP_CONFIG
from hpCommon.constants import RELEASE_VERSION_2017

ESXCLI_NAMESPACE = 'system'
ESXCLI_APP = 'coredump partition'

# Define constants for the parameters get command
ESXCLI_GET_CMD = 'get'
ESXCLI_GET_ACTIVE_FIELD = 'Active'
ESXCLI_GET_CONFIGURED_FIELD = 'Configured'

# Define constants for the parameters set command
ESXCLI_SET_CMD = 'set'
ESXCLI_ENABLE_CP_OPT = '-e true'
ESXCLI_SMART_ENABLE_CP_OPT = '-s -e true'
ESXCLI_DISABLE_CP_OPT = '-e false'

# Define constants for the parameters list command
ESXCLI_LIST_CMD = 'list'
ESXCLI_LIST_NAME_FIELD = 'Name'

# Define error message keys
CP_MSG_KEY_BASE = 'com.vmware.profile.coredumpPartition'
ESXCLI_ERROR_KEY = '%s.%s' % (CP_MSG_KEY_BASE, 'esxcliError')

# Message keys for module parameter validation
CP_NO_VALID_PARTITION_FOUND = '%s.%s' % (CP_MSG_KEY_BASE, 'noValidPartitionFound')
CP_FAILED_DISABLING_COREDUMP_PARTITION = '%s.%s' % (CP_MSG_KEY_BASE,
                                                    'failedDisablingCoredumpPartition')
CP_FAILED_ACTIVATING_COREDUMP_PARTITION = '%s.%s' % (CP_MSG_KEY_BASE,
                                                    'failedActivatingCoredumpPartition')

def isString(arg):
   """Check if the argument is a string
   """
   if sys.version_info.major >= 3:
      return isinstance(arg, str)
   else:
      return isinstance(arg, basestring)

def InvokeEsxcli(hostServices, command, opts=None):
   """Helper function for invoking esxcli and processing errors.
   """
   if opts is None:
      opts = ''
   log.debug('Coredump partition provider invoking esxcli command %s %s' % \
             (command, opts))
   status, output = hostServices.ExecuteEsxcli(
                          ESXCLI_NAMESPACE, ESXCLI_APP, command, opts)
   if status != 0:
      if not isString(output):
         log.warning('ESXCLI error output not a string for coredump ' + \
                     'partition command %s with options %s' % (command, opts))
      errMsgData = { 'error': output }
      errMsg = 'Coredump  Partition Provider: Error issuing esxcli ' + \
               'command %s with options %s: %s' % \
               (command, str(opts), str(output))
      log.error(errMsg)
      raise CreateLocalizedException(None, ESXCLI_ERROR_KEY, errMsgData)
   return output


class CoredumpPartitionProfile(SimpleConfigProfile):
    """A Host Profile that manages whether a coredump partition is
    enabled or disabled on ESX hosts.
    """
    #
    # Define required class attributes
    #

    deprecatedFlag = True
    deprecatedVersion = RELEASE_VERSION_2017
    enableDeprecatedVerify = True
    enableDeprecatedApply = True
    supersededBy = 'coredumpPartitionConfig.coredumpPartitionProfile.CoredumpPartition'
    parameters = [ ParameterMetadata('Enabled', 'bool', True) ]

    singleton = True

    category = CATEGORY_GENERAL_SYSTEM_SETTING
    component = COMPONENT_COREDUMP_CONFIG

    @classmethod
    def _GetPartitionName(cls, hostServices, partition):
        """Internal method that gets the name of the given partition
        (active or configured).
        """
        cliRes = InvokeEsxcli(hostServices, ESXCLI_GET_CMD)
        return cliRes[partition]

    @classmethod
    def _CheckActivePartitionSet(cls, hostServices):
        """Internal method that checks whether an active
        coredump partition is defined.
        """
        return len(cls._GetPartitionName(hostServices, ESXCLI_GET_ACTIVE_FIELD)) > 0

    @classmethod
    def _CheckPartitionValid(cls, hostServices, partition):
        """Internal method that checks whether the given partition
        (active or configured) is a valid partition. A valid partition
        is listed as coredump partition.
        """
        # Extract the partition name.
        partitionName = cls._GetPartitionName(hostServices, partition)
        
        if not partitionName:
           # No partition of the given type is defined.
           return False

        # Check whether the partition name is a valid.
        cliRes = InvokeEsxcli(hostServices, ESXCLI_LIST_CMD)
        if not cliRes:
           # The host doesn't have any coredump partitions configured.
           return False
        
        for curPartitionEntry in cliRes:
           if partitionName == curPartitionEntry[ESXCLI_LIST_NAME_FIELD]:
              return True
        # We couldn't find the partition name in the list of valid partitions.
        return False
     
    @classmethod
    def _ActivatePartition(cls, hostServices):
        """Internal method that will invoke esxcli to activate a coredump partition.
        """
        partitions = InvokeEsxcli(hostServices, ESXCLI_LIST_CMD)
        if not partitions:
           # The host doesn't have any coredump partitions configured.
           raise CreateLocalizedException(None, CP_NO_VALID_PARTITION_FOUND, None)
        

        # We verified that the we can configure a dump partion.
        # Check whether the configured partition is valid.
        res = cls._CheckPartitionValid(hostServices, ESXCLI_GET_CONFIGURED_FIELD)
        if res:
           # The configured partition is valid, we should honor this setting.
           InvokeEsxcli(hostServices, ESXCLI_SET_CMD, ESXCLI_ENABLE_CP_OPT)
        else:
           # The configured partition is invalid, let the smart algorithm pick
           # the dump partition.
           InvokeEsxcli(hostServices, ESXCLI_SET_CMD, ESXCLI_SMART_ENABLE_CP_OPT)

        # Verify whether we have successfully enabled the coredump partition.
        if (not cls._CheckActivePartitionSet(hostServices)):
           errMsgData = { 'NumValidPartitions' : len(partitions) }
           raise CreateLocalizedException(None, CP_FAILED_ACTIVATING_COREDUMP_PARTITION,
                                          errMsgData)
        
    @classmethod
    def _DeactivatePartition(cls, hostServices):
        """Internal method that will invoke esxcli to disable the active
        coredump partition.
        """

        # We know that a valid partition exists that we need to disable.
        InvokeEsxcli(hostServices, ESXCLI_SET_CMD, ESXCLI_DISABLE_CP_OPT)
        
        if (not cls._CheckActivePartitionSet(hostServices)):
           # We successfully disabled the coredump partition.
           return
        else:
           # We failed to disable the coredump partition.
           errMsgData = { 'ActivePartition' :
                          cls._GetPartitionName(hostServices, ESXCLI_GET_ACTIVE_FIELD)}
           raise CreateLocalizedException(None, CP_FAILED_DISABLING_COREDUMP_PARTITION,
                                          errMsgData)


    @classmethod
    def ExtractConfig(cls, hostServices):
        """Check whether we have an active partition set, and if yes,
        whether the coredump partition is valid.
        """
        result = (cls._CheckActivePartitionSet(hostServices) and
                  cls._CheckPartitionValid(hostServices, ESXCLI_GET_ACTIVE_FIELD))
        return {'Enabled' : result }


    @classmethod
    def SetConfig(cls, configInfo, hostServices):
        """For the coredump partitioin profile, the config parameter should contain
        a list of dicts (list will have one element), where the dict contain
        the parameter enable.
        """

        # Get the config dictionary.
        config = configInfo[0]
        
        if config['Enabled']:
           # We should enable the coredump partition.
           if (cls._CheckActivePartitionSet(hostServices) and
               cls._CheckPartitionValid(hostServices, ESXCLI_GET_ACTIVE_FIELD)):
              # The coredump partition is already enabled and valid, we don't
              # need to do anything.
              return True
           else:
              # We need to activate a coredump partition.
              cls._ActivatePartition(hostServices)
              return True
        else:
           # We should disable the coredump partition.
           if (not cls._CheckActivePartitionSet(hostServices)):
              # The host doesn't have an active coredump partition configured,
              # we don't need to do anything.
              return True
           else:
              # The host has configured an active coredump partition, we need
              # to disable it.
              cls._DeactivatePartition(hostServices)
              return True

                
        
