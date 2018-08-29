#!/usr/bin/python
"""
Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""

#
# Import the netdump config plugin. We have to import at least the profile as
# a first-class citizen of the netdump module so that the host profile
# engine can find the appropriate profile.
#
from .netdump import NetdumpProfile
