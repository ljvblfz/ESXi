#! /usr/bin/env python
'''
The networking package.

Modules and functions for actions related to NICs, IP addresses,
hostnames, virtual switches, and configuring the host's network settings
'''

from . import utils
from .host_config import config
from .networking_base import \
                            TASKNAME, \
                            TASKDESC, \
                            ConnectException, \
                            WrappedVmkctlException, \
                            init, \
                            hostAction, \
                            getFirstBootConfigFiles, \
                            getPhysicalNics, \
                            getPluggedInPhysicalNic, \
                            findPhysicalNicByMacAddress, \
                            findPhysicalNicByName, \
                            connected, \
                            enactHostWideUserchoices, \
                            connect
