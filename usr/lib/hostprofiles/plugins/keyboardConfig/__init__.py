#!/usr/bin/python
"""
Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""
from hostprofiles.pluginApi import PROFILE_IFACE_51
profileInterfaceVersion = PROFILE_IFACE_51

#
# Import the keyboard config plugin. We have to import the profiles as a
# first-class citizen of the package so that the host profile engine can find
# those profiles properly.
#
from .keyboardProfile import KeyboardProfile

