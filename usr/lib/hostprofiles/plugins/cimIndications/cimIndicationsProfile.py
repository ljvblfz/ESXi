#!/usr/bin/python
# **********************************************************
# Copyright 2010-2016 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import GenericProfile
from pluginApi import (CATEGORY_GENERAL_SYSTEM_SETTING,
                        COMPONENT_MANAGED_AGENT_CONFIG)

#
# Define a parent profile that will contain the CIM-XML indications profile and
# WS-Man indications profile.
#
class CimIndications(GenericProfile):
   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_MANAGED_AGENT_CONFIG
