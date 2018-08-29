#!/usr/bin/python
"""
Copyright 2016 VMware, Inc.  All rights reserved. -- VMware Confidential
"""

#
# Import the tools.conf plugin. We have to import the profiles as a
# first-class citizen of the package so that the host profile engine can find
# those profiles properly.
#
from .VmToolsConf import VmToolsConfProfile

