#!/usr/bin/python
"""
Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""
from pluginApi import PROFILE_IFACE_51
profileInterfaceVersion = PROFILE_IFACE_51

#
# Import the iscsiProfile plugin. We have to import at least the profile as
# a first-class citizen of the iscsi module so that the host profile
# engine can find the appropriate profile.
from .iscsiProfile import *
