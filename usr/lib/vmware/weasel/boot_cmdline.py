#! /usr/bin/env python
# Copyright 2008-2015 VMware, Inc.
# All rights reserved. -- VMware Confidential

'''
boot_cmdline.py

This module is responsible for parsing arguments that were set on the
"boot:" command line
'''
import os
import re
import vmkctl
import util
import visor_cdrom
import networking
from weasel import userchoices # always import via weasel.
from weasel.log import log
from weasel.util import isNOVA, getMissingDevices

# from consts import CDROM_DEVICE_PATH
from exception import HandledError
from weasel.featureSwitch import AddFeatureSwitch, CollectAllFeatureSwitches

# USB_MOUNT_PATH = "/mnt/usbdisk"
# UUID_MOUNT_PATH = "/mnt/by-uuid"
CDROM_MOUNT_PATH = "/mnt/cdrom"

genericErr = ('There was a problem with the %s specified on the command'
              ' line.  Error: %s.')

KERNEL_BUFFER_LEN = 4096
USB_RESCAN_TIME = 10

def failWithLog(msg):
    log.error("installation aborted")
    log.error(msg)
    raise HandledError(msg)

def getMissingNicMsg():
   extraMsg = None
   deviceList = getMissingDevices('vmnic')
   if deviceList:
      extraMsg = ('\n\nWarning: This system image lacks '
                  'drivers for these NIC(s): %s. '
                  'To proceed, please reset this system '
                  'and then use an installer containing '
                  'the needed drivers.' % deviceList)
   log.debug(extraMsg)

   return extraMsg

class NetworkChoiceMaker(object):
    '''A NetworkChoiceMaker object will add choices to userchoices that
    are necessary consequences of the user adding some earlier choice.
    For example, if the user chooses an IP address, but doesn't make a
    choice for the netmask, we need to make a guess for the netmask.
    If the user doesn't choose ANY networking options, then the
    assumption is that we're not doing a network install and the
    NetworkChoiceMaker object's "needed" attribute will be False.
    '''
    def __init__(self):
        self.needed = False

    def setup(self):
        log.debug('Setting network options for media downloads')
        nicChoices = userchoices.getDownloadNic()

        # Note, nicChoices['device'] might be ''
        nic = nicChoices.get('device', None)

        if nic and not nic.IsLinkUp():
            failWithLog(('The specified network interface card (Name: %s'
                         ' MAC Address: %s) is not plugged in.'
                         ' Installation cannot continue as requested') %\
                        (nic.GetName(), nic.GetMacAddress().GetStringAddress())
                       )
        elif not nic and not networking.getPluggedInPhysicalNic():
            # Check for an available NIC before we go further.
            # It's best to fail early and provide a descriptive error
            extraMsg = getMissingNicMsg() if isNOVA() else ''
            failWithLog('This system does not have a network interface'
                        ' card that is plugged in, or all network'
                        ' interface cards are already claimed. '
                        ' Installation cannot continue as requested.%s' %
                        extraMsg)
        # Create a netmask if it was left out
        ip = nicChoices.get('ip', None)
        netmask = nicChoices.get('netmask', None)

        if netmask and not ip:
            failWithLog('Netmask specified, but no IP given.')
        if ip and not netmask:
            log.warn('IP specified, but no netmask given.  Guessing netmask.')
            try:
                netmask = networking.utils.calculateNetmask(ip)
            except ValueError as ex:
                msg = ((genericErr + ' A netmask could not be created.')
                       % ('IP Address', str(ex)))
                failWithLog(msg)
            nicChoices.update(netmask=netmask)
            userchoices.setDownloadNic(**nicChoices)

        log.debug("  nic options from boot command line -- %s" % nicChoices)
        log.debug("  net options from boot command line -- %s" %
                  userchoices.getDownloadNetwork())

    def updateNetworkChoices(self, **kwargs):
        self.needed = True
        netChoices = userchoices.getDownloadNetwork()
        if not netChoices:
            newArgs = dict(gateway='', nameserver1='', nameserver2='',
                           hostname='localhost')
        else:
            newArgs = netChoices
        newArgs.update(kwargs)
        userchoices.setDownloadNetwork(**newArgs)

    def updateNicChoices(self, **kwargs):
        self.needed = True
        nicChoices = userchoices.getDownloadNic()
        if not nicChoices:
            # was empty - this is the first time populating it.
            newArgs = dict(device='', vlanID=0) #set defaults
        else:
            newArgs = nicChoices
        newArgs.update(kwargs)
        userchoices.setDownloadNic(**newArgs)

# module-level NetworkChoiceMaker object
__networkChoiceMaker = None
def getNetworkChoiceMaker():
    global __networkChoiceMaker
    if not __networkChoiceMaker:
        __networkChoiceMaker = NetworkChoiceMaker()
    return __networkChoiceMaker


def _setDownloadIP(match):
    '''Handle the "ip=..." option.'''
    ip = match.group(1)
    try:
        log.debug("  boot command line ip='%s'" % ip)
        networking.utils.sanityCheckIPString(ip)
    except ValueError as ex:
        failWithLog(genericErr % ('IP Address', str(ex)))

    networkChoiceMaker = getNetworkChoiceMaker()
    networkChoiceMaker.updateNicChoices(ip=ip,
                                        bootProto=userchoices.NIC_BOOT_STATIC)

def _setDownloadNetmask(match):
    '''Handle the "netmask=..." option.'''
    netmask = match.group(1)
    try:
        log.debug("  boot command line netmask=%s" % netmask)
        networking.utils.sanityCheckNetmaskString(netmask)
    except ValueError as ex:
        failWithLog(genericErr % ('Netmask', str(ex)))

    networkChoiceMaker = getNetworkChoiceMaker()
    networkChoiceMaker.updateNicChoices(netmask=netmask)

def _setDownloadGateway(match):
    '''Handle the "gateway=..." option.'''
    gateway = match.group(1)
    try:
        log.debug("  boot command line gateway='%s'" % gateway)
        networking.utils.sanityCheckGatewayString(gateway)
    except ValueError as ex:
        failWithLog(genericErr % ('Gateway Address', str(ex)))

    networkChoiceMaker = getNetworkChoiceMaker()
    networkChoiceMaker.updateNetworkChoices(gateway=gateway)


def _setNetDevice(match):
    '''Handle the "netdevice=..." option.'''
    # The pxelinux BOOTIF option uses dashes instead of colons.
    nicName = match.group(1).replace('-', ':')
    try:
        extraMsg = getMissingNicMsg() if isNOVA() else ''
        if ':' in nicName:
            # assume it is a MAC address
            nic = networking.findPhysicalNicByMacAddress(nicName)
            if not nic:
                raise ValueError('No NIC found with MAC address "%s".%s' %
                                 (nicName, extraMsg))
        else:
            # assume it is a vmnicXX style name
            nic = networking.findPhysicalNicByName(nicName)
            if not nic:
                raise ValueError('No NIC found with name "%s".%s' %
                                 (nicName, extraMsg))
    except ValueError as ex:
        failWithLog(genericErr % ('Network Device', str(ex)))

    networkChoiceMaker = getNetworkChoiceMaker()
    networkChoiceMaker.updateNicChoices(device=nic)

def _setVlanID(match):
    '''Handle the "vlanid=..." option.'''
    vlanID = match.group(1)
    try:
        networking.utils.sanityCheckVlanID(vlanID)
    except ValueError as ex:
        failWithLog(genericErr % ('VLAN ID', str(ex)))
    networkChoiceMaker = getNetworkChoiceMaker()
    networkChoiceMaker.updateNicChoices(vlanID=vlanID)


def _setDownloadNameserver(match):
    '''Handle the "nameserver=..." option.'''
    nameserver = match.group(1)
    try:
        networking.utils.sanityCheckIPString(nameserver)
    except ValueError as ex:
        failWithLog(genericErr % ('Nameserver Address', str(ex)))

    networkChoiceMaker = getNetworkChoiceMaker()
    networkChoiceMaker.updateNetworkChoices(nameserver1=nameserver)

# def _urlOption(match):
#     '''Handle the "url=..." option.'''
#     return [('--url', match.group(1))]

def _ksFileOption(match):
    '''Handle the "ks=http://<urn>", "ks=file://<path>", etc option.'''
    import remote_files

    filePath = match.group(1)
    if remote_files.isURL(filePath) and not filePath.startswith('file'):
        networkChoiceMaker = getNetworkChoiceMaker()
        networkChoiceMaker.needed = True
    return [('-s', filePath)]

# def _ksFileUUIDOption(match):
#     uuid = match.group(1)
#     path = match.group(2)
#
#     mountPath = os.path.join(UUID_MOUNT_PATH, uuid)
#     if not os.path.exists(mountPath):
#         os.makedirs(mountPath)
#         if util.mount(uuid, mountPath, isUUID=True):
#             os.rmdir(mountPath)
#             failWithLog("error: cannot mount partition with UUID: %s\n" % uuid)
#
#     ksPath = os.path.join(mountPath, path[1:])
#     return [('-s', ksPath)]

def _ksFileCdromOption(match):
    #import cdutil
    path = match.group(1)

    if not os.path.exists(CDROM_MOUNT_PATH):
        os.makedirs(CDROM_MOUNT_PATH)

    #for cdPath in cdutil.cdromDevicePaths():
    for cdPath in visor_cdrom.cdromDevicePaths():
        mountedPath = visor_cdrom.mount(cdPath)
        if not mountedPath:
            log.warn("cannot mount cd-rom in %s" % cdPath)
            continue

        ksPath = os.path.join(mountedPath, path.lstrip('/'))
        if os.path.exists(ksPath):
            return [('-s', ksPath)]

        visor_cdrom.umount(cdPath)

    failWithLog("cannot find kickstart file on cd-rom with path -- %s" % path)

def _ksFileUsbOption(match):
    '''Handle the "ks=usb" and "ks=usb:<file>" option.'''

    try:
        ksFile = match.group(1)
    except IndexError:
        ksFile = "ks.cfg"

    import usbmedia

    for count in range(5):
        # stop retrying after 5 times
        if count != 0:
            log.info("Insert a USB storage device that contains a '%s' "
                   "file to perform a scripted install..." % ksFile)
            util.rawInputCountdown("\rrescanning in %2d second(s), "
                                   "press <enter> to rescan immediately",
                                   USB_RESCAN_TIME)

        ksPath = usbmedia.copyFileFromUSBMedia(ksFile, usbmedia.KS_PATH)

        if ksPath:
            return [('-s', ksPath)]

    failWithLog("cannot find kickstart file on usb with path -- %s" % ksFile)

def _ntfsOption(match):
    '''Handle the "ks=ntfs" option.'''

    import ntfs

    ksFile = "ks.cfg"
    if ntfs.copyFileFromNtfsPartition(ksFile):
        return [('-s', os.path.join(ntfs.TEMP_DIR, ksFile))]

def _debugOption(_match):
    return [('-d', None)]

def _debugUIOption(_match):
    return [('--debugui', None)]

def _debugPatchOption(match):
    return [('--debugpatch', match.group(1))]

def _compresslevelOption(match):
    try:
        compresslevel = int(match.group(1))
        if compresslevel > 9 or compresslevel < 0:
            raise ValueError
    except ValueError:
        failWithLog('Invalid value for compresslevel.\n'
                    'Valid value is a number between 0 and 9')

    return [('--compresslevel', compresslevel)]

# def _mediaCheckOption(_match):
#     return [('--mediacheck', None)]

# def _askMediaOption(_match):
#     return [('--askmedia', None)]
#
# def _noEjectOption(_match):
#     return [('--noeject', None)]

# def _bootpartOption(match):
#     uuid = match.group(1)
#     if not util.uuidToDevicePath(uuid):
#         failWithLog("error: cannot find device for UUID: %s\n" % uuid)
#
#     userchoices.setBootUUID(uuid)
#
#     mountPath = util.mountByUuid(uuid)
#     if not mountPath:
#         failWithLog("error: cannot mount boot partition with UUID -- %s" % uuid)
#
#     util.umount(mountPath)
#
#     return []

# def _rootpartOption(match):
#     uuid = match.group(1)
#     if not util.uuidToDevicePath(uuid):
#         failWithLog("error: cannot find device for UUID: %s\n" % uuid)
#
#     userchoices.setRootUUID(uuid)
#
#     return []

def _ignoreOption(_match):
    return

# def _sourceOption(match):
#     '''Handle the "source=<path>" option.'''
#     import media
#
#     path = match.group(1)
#
#     if not os.path.exists(path):
#         failWithLog("error: cannot find source -- %s\n" % path)
#
#     if path == CDROM_DEVICE_PATH:
#         pass
#     else:
#         userchoices.setMediaDescriptor(media.MediaDescriptor(
#                 partPath=path, partFsName="iso9660"))
#
#     return []

def _featureStateEnabled(_match):
   """_featureStateEnabled - Enable a feature state switch.
   """
   switchName = _match.group(1)
   AddFeatureSwitch(switchName, True)
   return None

def _featureStateDisabled(_match):
   """DisabletureStateDisabledd - Disable a feature state switch.
   """
   switchName = _match.group(1)
   AddFeatureSwitch(switchName, False)
   return None

def translateBootCmdLine(cmdline):
    '''Translate any commands from the given command-line

    The 'ks=' option, for example, takes one of the following arguments:

      file:///<path>     The path to the kickstart file, no mounts are done.

    The return value is a list of (option, value) pairs that match what the
    getopt function would return.

    >>> translateBootCmdLine("foo")
    []

    >>> translateBootCmdLine("linux ks=file:///ks.cfg")
    [('-s', 'file:///ks.cfg')]
    >>> translateBootCmdLine("licks=file:///ks.cfg")
    []
    '''

    import shlex

    if len(cmdline) >= KERNEL_BUFFER_LEN:
        log.warn("boot command line might have been truncated to %d bytes" %
                 KERNEL_BUFFER_LEN)

    retval = []

    # The set of options that are currently handled.  Organized as a list of
    # pairs where the first element is the regex to match and the second is
    # the function that takes the regex and returns a list of (option, value)
    # pairs that match what getopt would return.  The function is also free
    # to perform any necessary setup, like mounting devices.
    # NOTE: order is important
    options = [
        (r'ip=([A-Fa-f\d]+:.*|\d+\.\d+\.\d+\.\d+)', _setDownloadIP), #  http://syslinux.zytor.com/wiki/index.php/SYSLINUX#IPAPPEND_flag_val_.5BPXELINUX_only.5D
        (r'netmask=(.+)', _setDownloadNetmask),
        (r'gateway=(.+)', _setDownloadGateway),
        (r'nameserver=(.+)', _setDownloadNameserver),
        (r'ks=(/.+)', _ksFileOption),
        (r'ks=cdrom:(/.+)', _ksFileCdromOption),
        (r'ks=((?:file|http|https|ftp|nfs)://.+)', _ksFileOption),
        (r'ks=usb:(/.+)', _ksFileUsbOption),
        (r'ks=usb$', _ksFileUsbOption),
        (r'ks=ntfs$', _ntfsOption),
        (r'debug$', _debugOption),
        (r'debugui', _debugUIOption),
        (r'debugpatch=(.+)', _debugPatchOption),
#        (r'url=(.+)', _urlOption),
        (r'ksdevice=(.+)', _setNetDevice), #for compatibility with anaconda
        (r'netdevice=(.+)', _setNetDevice),
#        (r'bootpart=(.+)', _bootpartOption),
#        (r'rootpart=(.+)', _rootpartOption),
#        (r'source=(/.+)', _sourceOption),
#        (r'askmedia', _askMediaOption),
#        (r'askmethod', _askMediaOption),
#        (r'noeject', _noEjectOption),
#        (r'mediacheck', _mediaCheckOption),
#        (r'formatwithmbr', _formatWithMbr),

        (r'vlanid=(.+)', _setVlanID),
        #  The first two hex digits are the hardware interface type.  Usually
        #  01 for ethernet.
        (r'BOOTIF=\w\w-(.+)', _setNetDevice),
        (r'compresslevel=(.+)', _compresslevelOption),

        #  Feature State switch propagation processing
        (r'FeatureState\.(.+)=enabled', _featureStateEnabled),
        (r'FeatureState\.(.+)=disabled', _featureStateDisabled),
        ]

    try:
        addressFamily = None
        numBits = None
        for token in shlex.split(cmdline):
            foundMatch = False
            for regex, func in options:
                match = re.match(regex, token)
                if match:
                    foundMatch = True
                    if func == _setDownloadNetmask:
                        numBits = match.group(1)
                        if "." in numBits: # not ordinal, skip ordinal check
                            numBits = None
                    if func == _setDownloadIP:
                        if match.group(1).count(':') > 1:
                            addressFamily = 'inet6'
                        else:
                            addressFamily = 'inet'

                    result = func(match)
                    if result:
                        retval.extend(result)
            if not foundMatch:
                log.info('Weasel skipped boot command line token (%s)' % token)
                if token.lower().startswith('ks=uuid'):
                    msg = 'ks=uuid is no longer a supported method'
                    raise HandledError(msg)

        if addressFamily and numBits: # PR 628505
            log.debug(
                "Checking ordinal netmask range: numBits %s, af=%s" % \
                (numBits, addressFamily))
            networking.utils.sanityCheckNetmaskOrdinal(numBits, addressFamily)

        networkChoiceMaker = getNetworkChoiceMaker()
        if networkChoiceMaker.needed:
            networkChoiceMaker.setup()

        CollectAllFeatureSwitches()
    except ValueError as e:
        # shlex.split will throw an error if quotation is bad.
        failWithLog("error: invalid boot command line -- %s" % str(e))

    return retval

def getOptionDict():
    # To make testing easier, pull from environment ($BOOT_CMDLINE variable)
    # first.  If it's specified, don't try to use /sbin/bootOption
    bootOptions = os.environ.get('BOOT_CMDLINE', '')
    if not bootOptions:
        rc, bootOptions, _stderr = util.execCommand('/sbin/bootOption -roC')
    log.info('Got boot options "%s"' % bootOptions)

    return dict(translateBootCmdLine(bootOptions))
