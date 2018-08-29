#!/usr/bin/python
# **********************************************************
# Copyright 2017 VMware, Inc.  All rights reserved.
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi.extensions import SimpleConfigProfile
from pluginApi import log, ParameterMetadata
from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING
from pluginApi import TASK_LIST_RES_OK

BUILD = 'Build'
VERSION = 'Version'
UPDATE = 'Update'
PRODUCT = 'Product'
PATCH = 'Patch'

paramNameList = [BUILD, VERSION, UPDATE, PRODUCT, PATCH]

params = []
for paramName in paramNameList:
    params.append(ParameterMetadata(paramName, 'string', True, readOnly=True))

class EsxInfo(SimpleConfigProfile):
    ''' ESX Info Profile

        This profile captures version settings.

        All parameters are readonly and this profile does not report
        compliance failures/task lists. Remediation is a noop.
    '''
    isOptional = True
    singleton = True
    parameters = params
    CATEGORY = CATEGORY_GENERAL_SYSTEM_SETTING
    COMPONENT = 'Info'
    ignoreCompliance = True

    @classmethod
    def ExtractConfig(cls, hostServices):
        try:
            rc, result = hostServices.ExecuteEsxcli('system version get')
            if not rc:
                return result
            log.error('Failed to get esx version: %s' % result)
        except:
            log.exception('Failed to get esx version.')
        return {}

    @classmethod
    def SetConfig(cls, config, hostServices):
        pass

    @classmethod
    def GenerateTaskList(cls, profileInstances, taskList, hostServices,
                         profileData, validationErrors):
        return TASK_LIST_RES_OK