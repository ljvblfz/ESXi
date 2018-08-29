#!/usr/bin/python
"""
Copyright 2012-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""

#
# Import the agent VM configuration plugin. We have to import the profiles as a
# first-class citizen of the package so that the host profile engine can find
# those profiles properly.
#
from .agentVmProfile import AgentVmProfile
