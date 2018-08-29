#!/usr/bin/python
"""
Copyright 2011-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""

#
# Import the coredump partition plugin. We have to import the profile as
# a first-class citizen of the coredump partition module so that the
# host profile engine can find the profile.
#
from .coredumpPartition import CoredumpPartitionProfile
from .coredumpPartitionProfile import CoredumpPartition
