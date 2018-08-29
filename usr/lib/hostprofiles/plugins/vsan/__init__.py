#!/usr/bin/python
"""
Copyright 2014-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""
from pluginApi import PROFILE_IFACE_51
profileInterfaceVersion = PROFILE_IFACE_51

#
# Import all profiles to make them visible to the host profile engine
#
from .vsanProfiles import VSANProfile
from .vsanNicProfiles import VSANNicProfile
