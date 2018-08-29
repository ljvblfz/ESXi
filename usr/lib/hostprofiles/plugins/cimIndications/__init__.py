#!/usr/bin/python
"""
Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""
from pluginApi import PROFILE_IFACE_51
profileInterfaceVersion = PROFILE_IFACE_51

#
# Import the cimxmlIndication plugin. We have to import at least the profile as
# a first-class citizen of the cimIndications module so that the host profile
# engine can find the 
#
from .cimIndicationsProfile import CimIndications
from .cimxmlIndications import CimXmlIndicationsProfile


#
# TBD: Import the WS-Man indication profile when it is ready.
#
