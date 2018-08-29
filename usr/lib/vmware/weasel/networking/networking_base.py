#! /usr/bin/env python

from __future__ import print_function

import time
import vmkctl
import struct
from weasel import userchoices
from weasel import task_progress
from weasel.exception import HandledError
from weasel.log import log

from . import vmknic_functions

TASKNAME = 'Networking'
TASKDESC = 'Configuring network settings'

# ==========================================================================
_connectedVmkNic = None

# aliases to vmkctl singletons
_netInfo = vmkctl.NetworkInfoImpl()
#_routingInfo = vmkctl.RoutingInfoImpl()
_vswitchInfo = vmkctl.VirtualSwitchInfoImpl()
_vmkernelNicInfo = vmkctl.VmKernelNicInfoImpl()
_storageInfo = vmkctl.StorageInfoImpl()

class ConnectException(Exception):
    '''An Exception that occurs during a connect* function'''

class WrappedVmkctlException(HandledError):
    def __init__(self, hostCtlException):
        HandledError.__init__(self, hostCtlException.GetMessage())
    def __repr__(self):
        return '<WrappedVmkctlException (%s)>' % self.shortMessage

# -----------------------------------------------------------------------------
def init():
    pass

# -----------------------------------------------------------------------------
def connected():
    return _connectedVmkNic != None

# -----------------------------------------------------------------------------
def wrapHostCtlExceptions(fn):
    '''A decorator that you can use to modify functions that call vmkctl
    methods.  It will catch any vmkctl.HostCtlException and wrap it in a
    more python friendly WrappedVmkctlException
    '''
    def newFn(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except vmkctl.HostCtlException as ex:
            raise WrappedVmkctlException(ex)
    newFn.__name__ = fn.__name__ #to make the stacktrace look better
    return newFn

# ----------------------------------------------------------------------------
def getPhysicalNics():
    return [pnicPtr.get() for pnicPtr in _netInfo.GetPnics()]

# ----------------------------------------------------------------------------
def getPluggedInPhysicalNic():
    ''' Return a pnic object which is reporting linkUp state'''
    for pnic in [pnicPtr.get() for pnicPtr in _netInfo.GetPnics()]:
        if pnic.IsLinkUp():
            return pnic
    return None

# ----------------------------------------------------------------------------
def getPluggedInPhysicalNicName():
    ''' Return a device name string of a pnic which is reporting linkUp state'''
    pnic = getPluggedInPhysicalNic()
    if pnic:
        return pnic.GetName()
    return None

# -----------------------------------------------------------------------------
def findPhysicalNicByName(name):
    for pnic in [pnicPtr.get() for pnicPtr in _netInfo.GetPnics()]:
        if name == pnic.GetName():
            if not pnic.IsLinkUp():
                log.warn('Physical NIC %s is not linked' % pnic.GetName())
            return pnic
    return None


def MacStringToBinary(mac):
    '''Convert mac in format X:X:X:X:X:X to packed binary
    and on error return empty string'''
    invalidMac = ""
    macBytes = mac.split(":")
    if len(macBytes) < 6:
        return invalidMac
    binaryMac = []
    try:
        for byte in macBytes:
            binaryMac.append(int(byte, 16))

        return struct.pack("BBBBBB",
                           binaryMac[0],
                           binaryMac[1],
                           binaryMac[2],
                           binaryMac[3],
                           binaryMac[4],
                           binaryMac[5])
    except ValueError:
        return invalidMac
    except struct.error:
        return invalidMac

# -----------------------------------------------------------------------------
def findPhysicalNicByMacAddress(mac):
    if not ':' in mac:
        log.error('Expected MAC address delimiter is ":"')
        return None
    log.info('findPhysicalNicByMacAddress processing "%s"' % mac)
    searchMac = MacStringToBinary(mac)
    if len(searchMac) == 0:
        log.error('Invalid MAC address requested "%s"' % mac)
        return None
    for pnic in [pnicPtr.get() for pnicPtr in _netInfo.GetPnics()]:
        #log.info('findPhysicalNicByMacAddress checking against pnic mac: "%s"' % pnic.GetMacAddress().GetStringAddress())
        pnicMac = MacStringToBinary(pnic.GetMacAddress().GetStringAddress())
        if searchMac == pnicMac:
            if not pnic.IsLinkUp():
                log.warn('Physical NIC %s is not linked' % pnic.GetName())
            return pnic
    log.error('findPhysicalNicByMacAddress did not find a maching mac')
    return None

# -----------------------------------------------------------------------------
def queryFCOEboot():
    fcoenics = [ptr.get() for ptr in _netInfo.GetFcoeCapablePnics()]
    vlanid = 0
    if len(fcoenics):
       for nic in fcoenics:
           if nic.IsFcoeBootable(vlanid):
              log.info('FCOE boot is enabled')
              return True
    return False

# -----------------------------------------------------------------------------
@wrapHostCtlExceptions
def connectStatic(pnicName, ip, netmask, vlanId=0):
    log.info("connectStatic called for pnic %s" % pnicName)
    global _connectedVmkNic
    vmkNic = vmknic_functions.getManagementNic()
    vmknic_functions.connectStatic(pnicName, ip, netmask, vlanId)
    task_progress.taskFinished(TASKNAME)
    _connectedVmkNic = vmkNic

# -----------------------------------------------------------------------------
@wrapHostCtlExceptions
def connectDhcp(pnicName=None, vlanId=0):
    log.info("connectDhcp called for pnic %s" % pnicName)

    global _connectedVmkNic
    vmkNic = vmknic_functions.getManagementNic()
    vmknic_functions.connectDhcp(pnicName, vlanId)

    # Now wait until we get an IP address returned from the DHCP server
    failureTime = time.time() + 60 # allow a minute before failing
    while not vmkNic.GetDhcpBound(): # do we have an IP?
        if time.time() > failureTime:
            raise ConnectException('Did not get an IP Address from DHCP server')
        log.warn('Still waiting for an IP address from DHCP')
        time.sleep(3)
        task_progress.taskProgress(TASKNAME) # let the UI know we're alive
        vmkNic.Refresh()

    # We've got a lease, but the vmkernel still might need a second or two
    # to bring up it's TCP/IP stack, so sleep for 4 seconds.
    # TODO: add python interface for VMKernel_RPCRegister() to be able to fetch ip vmkevent
    time.sleep(4)

    task_progress.taskFinished(TASKNAME)
    log.info("connectDhcp complete for %s vland %s" % (pnicName, vlanId))
    _connectedVmkNic = vmkNic

# -----------------------------------------------------------------------------
@wrapHostCtlExceptions
def connect(force=False, nicChoices=None):
    '''Connect a device (physical nic) to the network
    If (nicChoices['device']=vmkctl.Pnic|pnicName) is not specfied, the first plugged in
    nic will be attempted.
    This function can throw ConnectExceptions
    '''
    global _connectedVmkNic
    vmkNic = vmknic_functions.getManagementNic()

    task_progress.taskProgress(TASKNAME, 2)

    if not nicChoices:
        log.info('Network choices not specified.  Using DHCP.')
        if vmkNic.GetDhcpBound() and not force: # already have an IP address
            _connectedVmkNic = vmkNic
            return
        return connectDhcp(None)

    if 'device' in nicChoices:
        if hasattr(nicChoices['device'], "GetName"):
            pnicName = nicChoices['device'].GetName()
        else:
            pnicName = nicChoices['device']
            if not pnicName:
                log.info("device specfied but no value, using first plugged in nic")
                pnicName = getPluggedInPhysicalNicName()
    else:
        log.info("device specfied but no value, using first plugged in nic")
        pnicName = getPluggedInPhysicalNicName()
    log.info('Using nic: "%s"' % pnicName)
    if nicChoices['bootProto'] == userchoices.NIC_BOOT_STATIC:
        log.info('Configuring specified IP address')
        return connectStatic(pnicName,
                             nicChoices['ip'],
                             nicChoices['netmask'],
                             nicChoices['vlanID'])
    else:
        for pnic in vmkNic.getPnics():  # XXX ipv4 centric
            if (pnic.GetName() == pnicName
                and vmkNic.GetDhcpBound() # already have an IPv4 address
                and not force):
                _connectedVmkNic = vmkNic
                log.info('Found existing pnic which has a DCHPv4 address %s' % pnicName)
                return

        log.info('Enabling DHCP on "%s", vlan id: %s to get IPv4 address' % (pnicName, nicChoices['vlanID']))
        return connectDhcp(pnicName, nicChoices['vlanID'])


# -----------------------------------------------------------------------------
def enactHostWideUserchoices(choices):
    '''Enact the userchoices for the host-wide options
    eg, gateway, hostname, nameservers
    The choices argument is either userchoices.getVmkNetwork() or
    userchoices.getDownloadNetwork()
    '''
    import ipaddress
    def validateIp(ipstring):
        validip = True
        try:
           if type(ipstring) is bytes:
              ip = ipstring.decode()
           ipaddress.ip_address(ipstring)
        except ValueError:
           log.info('Domain Name Server %s is not valid, and its value is not set.' % str(ipstring))
           validip = False
        return validip


    log.info('Setting the host-wide networking options')
    log.debug('using choices: %s' % str(choices))
    from . import gateway, host_config # avoid circular imports
    if not choices:
        raise ConnectException('No network conf choices have been made.')

    if choices['gateway']:
        host_config.config.gateway = choices['gateway']
    # XXX vmkctl does not support clearing the gateway right now.
    # else:
    #     gateway = DEFAULT_GATEWAY
    if choices['hostname']:
        host_config.config.hostname = choices['hostname']
    else:
        # vmkctl does not like empty host names.
        host_config.config.hostname = 'localhost'

    # if user did not set any nameserver, keep the existing ones.
    if any(nameserver != None for nameserver in [choices['nameserver1'],choices['nameserver2']]):
         #clear out any existing nameservers
         for nameserver in list(host_config.config.nameservers):
              host_config.config.nameservers.remove(nameserver)

         for nameserver in [choices['nameserver1'], choices['nameserver2']]:
             #only set nameserver with validate ip address
             if nameserver and validateIp(nameserver):
                 host_config.config.nameservers.append(nameserver)


# -----------------------------------------------------------------------------
def hostAction():
    # note: this may throw an exception
    allNicChoices = userchoices.getVmkNICs()
    try:
        if allNicChoices:
            assert len(allNicChoices) == 1
            nicChoices = allNicChoices[0]
            log.info('Network choices specified, trying to connect with them.')
            connect(force=True, nicChoices=nicChoices)
            log.info('connect completed')
        # PR #1125959. If it is a Software iSCSI or FCoE boot then don't overwrite
        # the network connection causing install failure
        elif _storageInfo.SoftwareiScsiBootEnabled() or queryFCOEboot():
            log.info('Software iSCSI or FCoE boot, Using default network configuration')
        else:
            log.info('Network choices not specified.  Using DHCP.')
            connect(force=True, nicChoices=None)
    except ConnectException as ex:
        # don't kill the installation if we couldn't connect.  Maybe the user
        # just wanted to configure DHCP and the host isn't even plugged in.
        log.warn('Could not connect. (%s)' % str(ex))

    netChoices = userchoices.getVmkNetwork()
    if netChoices:
        enactHostWideUserchoices(netChoices)

    # The 'VM Network' PortGroup will be created by default, so if the user
    # chooses addVmPortGroup == True, just ignore it.  If False, we have to
    # manually delete it and rely on esx.conf to persist the change when
    # the system reboots.
    addVmPortGroup = userchoices.getAddVmPortGroup()
    if not addVmPortGroup:
        for switch in [vs.get() for vs in _vswitchInfo.GetVirtualSwitches()]:
            for pg in [pgPtr.get() for pgPtr in switch.GetPortGroups()]:
                if pg.GetName() == 'VM Network':
                    switch.RemovePortGroup(pg.GetName())

# -----------------------------------------------------------------------------
def getFirstBootConfigFiles():
    '''return a list of files which need to be preserved for the hostname
    and domain name server settings to persist
    '''
    return ['/etc/resolv.conf',
            '/etc/hosts',
            '/etc/vmware/esx.conf']

# -----------------------------------------------------------------------------
# Testing code
#  the stuff below is just for testing purposes
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
def downloadKickstart():
    from weasel import remote_files
    connect(nicChoices=userchoices.getDownloadNic())
    netChoices = userchoices.getDownloadNetwork()
    if netChoices:
        enactHostWideUserchoices(netChoices)

    # kickstartfile.KickstartFile() should remoteOpen the file
    ksLocation = userchoices.getRootScriptLocation()['rootScriptLocation']
    localFilepath = remote_files.downloadLocally(ksLocation)
    return localFilepath


# -----------------------------------------------------------------------------
# def downloadBlob():
#     mediaChoices = userchoices.getMediaLocation()
#     mediaLoc = mediaChoices['mediaLocation']
#     localFilepath = remote_files.downloadLocally(mediaLoc)
#     return localFilepath


# -----------------------------------------------------------------------------
def parseAndDump():
    from weasel.scripted.preparser import ScriptedInstallPreparser
    readBootCmdlineIntoUserchoices()
    ksPath = downloadKickstart()
    sip = ScriptedInstallPreparser(ksPath)
    result, errors, warnings = sip.parseAndValidate()
    print(userchoices.dumpToString())
    print('-' * 60)
    print("%s %s %s" % (result, errors, warnings))


# -----------------------------------------------------------------------------
def readBootCmdlineIntoUserchoices():
    userchoices.setRootScriptLocation('http://172.16.221.2/test.ks')
    userchoices.setDownloadNic(device='', vlanID='',
                               bootProto=userchoices.NIC_BOOT_DHCP)
    #userchoices.setDownloadNetwork(gateway='172.16.221.2',
    #                               nameserver1='172.16.221.2',
    #                               nameserver2='',
    #                               hostname='localhost')
    #userchoices.setDownloadNic(device='', vlanID='',
    #                           bootProto=userchoices.NIC_BOOT_STATIC,
    #                           ip='172.16.221.31', netmask='255.255.255.0')

if __name__ == '__main__':
    def prnt(msg):
        print(msg)
    log.debug = log.error = log.warn = log.info = prnt
    readBootCmdlineIntoUserchoices()
    downloadKickstart()
    #parseAndDump()
