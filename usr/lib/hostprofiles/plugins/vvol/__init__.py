#!/usr/bin/python
"""
Copyright 2013-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""
from pluginApi import PROFILE_IFACE_51
profileInterfaceVersion = PROFILE_IFACE_51

#
# Import the VVOL storage plugin.
#
from .vvolProfile import VirtualVolumesProfile
from .vvolProfile import VvolVasaProviderConfigurationProfile
from .vvolProfile import VvolStorageContainerConfigurationProfile
from .vvolProfile import VvolVasaContextConfigurationProfile
