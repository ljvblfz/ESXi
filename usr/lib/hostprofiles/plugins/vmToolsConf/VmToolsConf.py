#!/usr/bin/python
# **********************************************************
# Copyright 2016 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import ParameterMetadata, log, CreateLocalizedException
from pluginApi.extensions import SimpleConfigProfile
from pluginApi import CATEGORY_ADVANCED_CONFIG_SETTING, COMPONENT_FILE_CONFIG

TC_CONF_FILE = "/etc/vmware-tools/tools.conf"

BASE_MSG_KEY = 'com.vmware.profile.Profile.vmToolsConf'
FAILED_TO_SAVE_CONF_KEY = '%s.FailedToSaveVMToolsConf' % BASE_MSG_KEY

CONFIG_FILE_PARAM = 'ConfigFile'


class VmToolsConfProfile(SimpleConfigProfile):
    """A Host Profile that manages contents of tools.conf
    """
    #
    # Define required class attributes
    #
    parameters = [ ParameterMetadata(CONFIG_FILE_PARAM, 'string', True) ]

    singleton = True

    category = CATEGORY_ADVANCED_CONFIG_SETTING
    component = COMPONENT_FILE_CONFIG

    @classmethod
    def ExtractConfig(cls, hostServices):
        """Return the contents of the tools.conf file
        """
        try:
            with open(TC_CONF_FILE, 'r') as confFile:
               result = confFile.read()
        except Exception as exc:
            # just return an empty file
            log.debug("Failed to read tools.conf, returning empty: %s" % exc)
            result = ''
            log.debug("toolsConf extract data %s" % result)

        return {CONFIG_FILE_PARAM : result }


    @classmethod
    def SetConfig(cls, configInfo, hostServices):
        """For the tools conf profile, the config parameter should contain
        a list of dicts (list will have one element), where the dict contain
        the file contents.
        """

        # Get the config dictionary.
        config = configInfo[0]
        contents = config[CONFIG_FILE_PARAM]
        log.debug("In toolsConf set '%s'" % contents)

        # just make an empty tools.conf is we have no contents
        try:
            with open(TC_CONF_FILE, 'w') as confFile:
               confFile.write(contents)
        except Exception as exc:
            log.error("Failed to save tools.conf file: %s" % exc)
            fault = CreateLocalizedException(None,
                                             FAILED_TO_SAVE_CONF_KEY)
            raise fault
