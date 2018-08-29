#!/usr/bin/python
"""
Copyright 2014-2017 VMware, Inc.  All rights reserved. -- VMware Confidential
"""

#
# Import the coredump file plugin. We have to import the profile as
# a first-class citizen of the coredump file module so that the
# host profile engine can find the profile.
#
from .coredumpFile import CoredumpFileProfile
from .coredumpFileProfile import CoredumpFile
