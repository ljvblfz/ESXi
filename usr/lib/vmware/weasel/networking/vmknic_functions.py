#! /usr/bin/env python

'''
This module contains the functions to set up vmknics

IMPORTANT: This module is intended to be used from 2 separate environments.
Do not make changes without testing in BOTH environments

Firstly, it is imported by weasel networking code to set up the network
during installs and scripted boot.

Secondly, (and this is the tricky part) the entire text of this module is
used to create a first-boot script.  The environment the first-boot script
runs in will not have access to any of the weasel modules.  It will be very
rudimentary, having only access to vmkctl and ESXi's subset of the Python
standard library.
'''

from __future__ import print_function

import vmkctl

try:
    from weasel import task_progress
    from weasel.log import log
except ImportError:
    # the weasel package is not available in the current environment (which
    # means we're running as a first-boot script).  So replace taskProgress
    # and log with a dummy object that just prints to stdout
    class StdoutPrinter:
        def printArgs(self, *args):
            print(args)
        taskProgress = error = warn = info = debug = printArgs
    task_progress = StdoutPrinter()
    log = task_progress

TASKNAME = 'Networking'

# =============================================================================
# aliases to vmkctl singletons
_netInfo = vmkctl.NetworkInfoImpl()
_vswitchInfo = vmkctl.VirtualSwitchInfoImpl()
_vmkernelNicInfo = vmkctl.VmKernelNicInfoImpl()

# -----------------------------------------------------------------------------
class VmKernelNicFacade(object):
    def __init__(self, realVmknic):
        self._realVmknic = realVmknic

    def __str__(self):
        return '<VmKernelNicFacade %s %s>' % (self.interfaceName, self.name)

    def __repr__(self):
        return self.__str__()

    def __getattr__(self, attrname):
        if hasattr(self._realVmknic, attrname):
            return getattr(self._realVmknic, attrname)
        elif attrname == 'macAddress':
            return self._realVmknic.GetMacAddress().GetStringAddress()
        elif attrname == 'name':
            return self._realVmknic.GetName()
        elif attrname == 'interfaceName':
            return self._realVmknic.GetInterfaceName()
        else:
            raise AttributeError('VmKernelNicFacade has no attribute "%s"'
                                 % attrname)

    def getVirtualSwitch(self, failVal=None):
        '''
        Support both Traditional & vDS switch types
        '''
        connPoint = self.GetConnectionPoint().get()
        if connPoint is None:
            return failVal
        swtype = connPoint.GetType()
        if swtype == connPoint.CONN_TYPE_PG:
            for switch in [vs.get() for vs in _vswitchInfo.GetVirtualSwitches()]:
                for pg in [pgPtr.get() for pgPtr in switch.GetPortGroups()]:
                    if connPoint.GetName() == pg.GetName():
                        return switch
        elif swtype == connPoint.CONN_TYPE_DVP:
            param = connPoint.GetDVPortParam()
            for switch in [dvs.get() for dvs in _vswitchInfo.GetDVSwitches()]:
                if param.dvsId == switch.GetDvsId():
                    return switch
        else:
            log.error('VmKernelNicFacade saw unknown switch port type "%d"' % swtype)
        log.error("Failed to locate vswitch connected to the vmknic")
        return failVal

    def SetVlanID(self, vlanId):
        ''' Apply the vlan id to the given interface'''
        vswitch = self.getVirtualSwitch()
        if hasattr(vswitch, 'GetPortGroups'): # is traditional vswitch
            pgname = self.GetPortGroupName()
            if not pgname:
                return False
            for pg in [pgPtr.get() for pgPtr in vswitch.GetPortGroups()]:
                if pgname == pg.GetName():
                    pg.SetVlanId(int(vlanId))
                    return True
        else:
            connPoint = self.GetConnectionPoint().get()
            if connPoint is None:
                return False
            param = connPoint.GetDVPortParam()
            port = vswitch.GetDVPort(param.portId).get()
            cfg = vmkctl.DVPortVlanPolicy()
            cfg.vlanId = int(vlanId)
            port.SetVlanPolicy(cfg)
            return True
        return False

    def getPnics(self):
        pnics = []
        switch = self.getVirtualSwitch()
        if not switch:
            return pnics
        for pnic in [pnicPtr.get() for pnicPtr in _netInfo.GetPnics()]:
            if pnic.GetName() in switch.GetUplinks():
                pnics.append(pnic)
        return pnics

    def attachToPnic(self, pnicName):
        ''' Add pnic to the vswitch this interface is attached to. All other
            pnics will be removed from the vswitch.
            If connected to vDS and there is no uplink create a temporary traditional
            switch and move the interface
        '''
        switch = self.getVirtualSwitch()
        if not switch:
            raise Exception('VmkNic was not connected to a VirtualSwitch')

        for uplink in switch.GetUplinks():
            # don't trust existing uplinks to be functional
            switch.RemoveUplink(uplink)

        if hasattr(switch, 'GetPortGroups'): # is traditional vswitch
            switch.AddUplink(pnicName)
        else:
            try:
                sw = _vswitchInfo.AddVirtualSwitch("tmp-vum-switch").get()
                sw.AddUplink(pnicName)
                sw.AddPortGroup("tmp-vum-pg")
                vmkNic = getManagementNic()
                vmkNic.SetPortGroup("tmp-vum-pg")
            except vmkctl.HostCtlException as ex:
                log.error("Add pnic to vswitch failed %s" % ex)
                return
        # set the MAC address to be the same for consistency
        # TODO: when SetMacAddressFromPnic is exposed through SWIG, update this
        pnic = findPhysicalNicByName(pnicName)
        mac = pnic.GetMacAddress()
        self.SetMacAddress(mac)



# ----------------------------------------------------------------------------
def getVmkNics():
    return [VmKernelNicFacade(vmknicPtr.get()) for vmknicPtr in
            _vmkernelNicInfo.GetVmKernelNics()]

# ----------------------------------------------------------------------------
def getManagementNic():
    '''
    Lookup the interface name tagged for mgmt (eg vmk0, vmk1,..)
    Should eventually switch to VmKernelNicInfo::GetTags, see PR 580080
    '''
    _netInfo.UpdateManagementInterface()
    vnic = _netInfo.GetManagementInterface().get()
    if vnic:
        for vmknic in [ptr.get() for ptr in _vmkernelNicInfo.GetVmKernelNics()]:
            if vnic.GetInterfaceName() == vmknic.GetInterfaceName():
                return VmKernelNicFacade(vmknic)
    else:
        log.warn('No vnic tagged for mgmt, looking for well-known portgroup')
        for vmknic in [ptr.get() for ptr in _vmkernelNicInfo.GetVmKernelNics()]:
            if vmknic.GetPortGroupName() == "Management Network":
                return VmKernelNicFacade(vmknic)
    raise Exception("No vmknic tagged for management was found.")

# ----------------------------------------------------------------------------
def findPhysicalNicByName(name):
    # TODO: this is duplicated from networking_base.  Drop this if there's
    #       no need to run this module in the first-boot environment
    for pnic in [pnicPtr.get() for pnicPtr in _netInfo.GetPnics()]:
        if name == pnic.GetName():
            if not pnic.IsLinkUp():
                log.warn('Physical NIC %s is not linked' % pnic.GetName())
            return pnic
    return None

# ----------------------------------------------------------------------------
def connectStatic(pnicName, ip, netmask, vlanId=0):
    ''' Install an IPv4 or IPv6 address to the vswitch for this interface'''

    log.info('Setting up IP Addressing on %s, ip=%s/%s' % (pnicName, ip, netmask))

    vmkNic = getManagementNic()
    vmkNic.Disable()
    vmkNic.attachToPnic(pnicName)
    ipconf = vmkctl.IpConfig()
    ipconf.SetUseDhcp(False)
    if ":" in ip:
        ipconf.SetUseIpv6Dhcp(False)
        ipconf.SetUseIpv6RouterAdvertised(False)
        ipv6n = vmkctl.Ipv6Network("%s/%s" % (ip, netmask))
        ipconf.AddIpv6Network(ipv6n)
        vmkNic.SetIpConfig(ipconf)
    else:
        ipconf.SetIpv4Address(vmkctl.Ipv4Address(ip))
        ipconf.SetIpv4Netmask(vmkctl.Ipv4Address(netmask))
        vmkNic.SetIpv4Config(ipconf)


    vmkNic.SetVlanID(vlanId)
    task_progress.taskProgress(TASKNAME, 1)
    vmkNic.Enable()

# ----------------------------------------------------------------------------
def connectDhcp(pnicName=None, vlanId=0):
    vmkNic = getManagementNic()
    # first, check if we even need to do anything
    if vmkNic.GetIpConfig().GetUseDhcp():
        if pnicName == None:
            log.warn('no pnicName specified, no changes made to connect via DHCP')
            return # caller didn't request any specific pnic
        if findPhysicalNicByName(pnicName) in vmkNic.getPnics():
            log.info('pnic already connected')
            return # requested pnic is already connected via dhcp

    log.info('Connecting %s via DHCP' % pnicName)

    ipconf = vmkctl.IpConfig()
    ipconf.SetUseDhcp(True)
    ipconf.SetDhcpDns(True)
    log.info("setting dhcpdns")
    vmkNic.Disable()
    if pnicName != None:
        vmkNic.attachToPnic(pnicName)
    vmkNic.SetIpv4Config(ipconf)
    log.info('setting vlan id and enabling')
    vmkNic.SetVlanID(vlanId)
    task_progress.taskProgress(TASKNAME, 1)
    vmkNic.Enable()
    task_progress.taskProgress(TASKNAME, 1)
    log.info('connectDhcp done')

    # NOTE: at this point we may still be waiting on the DHCP server to
    #       give us an IP address.


# IMPORTANT! The following line is used by networking_base. Don't change it!
#INSERT FIRSTBOOT COMMANDS HERE#

