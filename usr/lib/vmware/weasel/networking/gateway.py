#! /usr/bin/env python
'''
This module defines a class used to set the vmkernel default gateway

IMPORTANT: This module is intended to be used from 2 separate environments.
Do not make changes without testing in BOTH environments

Firstly, it is imported by weasel networking code to configure the gateway
during installs and scripted boot.

Secondly, (and this is the tricky part) the entire text of this module is
used to create a first-boot script.  The environment the first-boot script
runs in will not have access to any of the weasel modules.  It will be very
rudimentary, having only access to vmkctl and ESXi's subset of the Python
standard library.  The access to vmkctl depends on vmkctl.py and .so getting
copied over by script.py
See: bora/lib/hostctl/include/network/RoutingInfo.h
'''


import vmkctl

DEFAULT_GATEWAY = '0.0.0.0'

def getGateway():
    routeInfo = vmkctl.RoutingInfoImpl()
    return routeInfo.GetVmKernelDefaultGateway().GetStringAddress()

def getV6Gateway():
    routeInfo = vmkctl.RoutingInfoImpl()
    return routeInfo.GetIpv6VmKernelDefaultGateway().GetStringAddress()

def setGateway(newGateway):
    '''Set the default network gateway based on IP address family.'''
    routeInfo = vmkctl.RoutingInfoImpl()
    if ':' in newGateway:
        vmkctlGateway = vmkctl.Ipv6Address(newGateway)
        routeInfo.SetIpv6VmKernelDefaultGateway(vmkctlGateway)
    else:
        vmkctlGateway = vmkctl.Ipv4Address(newGateway)
        routeInfo.SetVmKernelDefaultGateway(vmkctlGateway)


# IMPORTANT! The following line is used by networking_base. Don't change it!
#INSERT FIRSTBOOT COMMANDS HERE#
