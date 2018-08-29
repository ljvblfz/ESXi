#!/usr/bin/python
"""
Copyright 2011-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""
from pluginApi import PROFILE_IFACE_51
profileInterfaceVersion = PROFILE_IFACE_51

#
# Import the PCI Passthrough plugin. We have to import the profiles as a
# first-class citizen of the package so that the host profile engine can find
# those profiles properly.
#
from .pciPassThru import PciPassThroughProfile, \
                        PciPassThroughConfigProfile
