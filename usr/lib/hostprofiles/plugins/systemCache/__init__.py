#!/usr/bin/python
"""
Copyright 2011-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""
from pluginApi import PROFILE_IFACE_51
profileInterfaceVersion = PROFILE_IFACE_51

#
# Import the caching plugin.
#
from .caching import CachingProfile
