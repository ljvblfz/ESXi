#!/usr/bin/python
"""
Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""
from pluginApi import PROFILE_IFACE_51
profileInterfaceVersion = PROFILE_IFACE_51

from pluginApi import CreateComplianceFailureValues, \
                      PARAM_NAME, MESSAGE_KEY, POLICY_NAME
#
# Import the PSA storage plugin.
#
from .psaProfile import PluggableStorageArchitectureProfile
from .psaProfile import PsaDeviceSharingProfile
from .psaProfile import PsaClaimrulesProfile
from .psaProfile import PsaDeviceSettingProfile
from .psaProfile import PsaDeviceConfigurationProfile
from .psaProfile import PsaBootDeviceProfile
