#!/usr/bin/python
"""
Copyright 2011-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
"""

#
# Import the /etc/hosts plugin. We have to import the profiles as a
# first-class citizen of the package so that the host profile engine can find
# those profiles properly.
#
from .hostsFile import EtcHostsProfile

