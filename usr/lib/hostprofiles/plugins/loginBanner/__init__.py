#!/usr/bin/python
"""
Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""

#
# Import the kernel module plugin. We have to import the profiles as a
# first-class citizen of the package so that the host profile engine can find
# those profiles properly.
#
from .motd import MotdProfile
