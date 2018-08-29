#!/usr/bin/python
"""
Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""
from pluginApi import PROFILE_IFACE_51
profileInterfaceVersion = PROFILE_IFACE_51

#
# Import the NMP storage plugin.
#
from .nmpProfile import NativeMultiPathingProfile
from .nmpProfile import StorageArrayTypePluginProfile
from .nmpProfile import NmpDeviceProfile
from .nmpProfile import PathSelectionPolicyProfile
from .nmpProfile import SatpClaimrulesProfile
from .nmpProfile import DefaultPspProfile
from .nmpProfile import NmpDeviceConfigurationProfile
from .nmpProfile import SatpDeviceProfile
from .nmpProfile import PspDeviceConfigurationProfile
from .nmpProfile import FixedPspConfigurationProfile
from .nmpProfile import RoundRobinPspConfigurationProfile
