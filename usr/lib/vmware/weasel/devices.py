from __future__ import print_function

import os
import sys
import parted
import json
import subprocess
import vmkctl
from weasel import consts
from weasel import partition
from weasel import userchoices # always import via weasel.
from weasel import util
from weasel.log import log

from weasel.exception import HandledError
from weasel.util.singleton import Singleton
from weasel.util import units

VMKCTL_SCSI_DISK = 0

# size in MB
VMDK_OVERHEAD_SIZE = 1000
TMP_MOUNT_PATH = '/mnt/testdir'

PATHID_ADAPTER_NAME = 0
PATHID_CHANNEL = 1
PATHID_TARGET = 2
PATHID_LUN = 3

def getAdapterInfo():
   """Return the content of the 'localcli storage core adapter list' command,
   formatted as a python dictionary.

   Note that we must fork the 32-bit /bin/localcli because calls into this
   localcli namespace ends up loading 32-bit iscsi libraries. This libraries
   couldn't load if we were executing from a 64-bit esxclipy context.
   """
   p = subprocess.Popen(['/bin/localcli', '--formatter', 'json',
                         'storage', 'core', 'adapter', 'list'],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
   out, err = p.communicate()
   if p.returncode != 0:
      raise Exception('Failed to retrieve storage paths: %s' % err.decode())
   return json.loads(out.decode())

def getAdapterDriver(adapterName, info):
   for adapter in info:
      if adapter['HBA Name'] == adapterName:
         return adapter['Driver']
   return None

class ESXVariant(object):
    scanned = False
    esxi = False
    newPartLayout = False

    # Used to store the version info, in the form of a tuple.
    version = (0, 0, 0)
    pathToActiveBootbank = None
    if util.isNOVA():
        bootbankIsRecent = False

    def __str__(self):
        v = 'None' if self.version == (0, 0, 0) else self.version
        return "{esxi : %s; version: %s}" % \
               (self.esxi, v)

    # Overwrite its internal truth test. (e.g. 'if [ESXVariant]')
    def __nonzero__(self):
        """For python2"""
        return (self.esxi)

    def __bool__(self):
        """For python3"""
        return self.__nonzero__()

    def getPrettyString(self):
        if self.esxi:
            esxVerStr = "ESXi"
        else:
            return ""

        if self.version != (0, 0, 0):
            verNo = ".".join(map(str, self.version))
        else:
            verNo = "(unknown version)"

        return esxVerStr + " " + verNo


class InvalidDriveOrder(HandledError):
    '''Exception to describe the case when the user specifies a disk
    with the --driveorder flag that doesn't exist (physically)
    '''
    def __init__(self, drive):
        HandledError.__init__(self, 'Invalid drive order', str(drive))

class DiskDev:
    # Name of the driver for USB storage.
    DRIVER_USB_STORAGE = ["vmkusb", "umass", "usb-storage"]

    def __init__(self, name, device=None, path=None, consoleDevicePath=None,
                 vendor=None, model=None, size=0, sectorSize=512, sizeUnit='KiB',
                 deviceExists=True, probePartitions=True, driverName=None,
                 pathIds=None, vmkLun=None,
                 supportsVmfs=False, local=True, isUSB=False, vsanClaimed=None,
                 isSSD=False, interfaceType = None, diskFormatType=None):
        '''Disk Device container class for both physical and virtual
           disk devices.

           name                 - name string
           device               - parted device reference
           path                 - path to device (usually under /vmfs)
           consoleDevicePath    - Console OS device path (usually /dev/sdX)
           vendor               - vendor string
           model                - model string
           size                 - size of the disk device (in KB or MB)
           sectorSize           - size of a disk sector in bytes
           sizeUnit             - KiB or MiB for kibibytes or mebibytes
           deviceExists         - used for virtual devices to not probe
                                  the partition table
           probePartitions      - boolean value to search for partitions
           driverName           - name of the driver associated with the
                                  device
           pathIds              -
           vmkLun               -
           supportsVmfs         - device supports vmfs
           local                - device is local (not remote)
           isUSB                - device is a USB device
           isSSD                - device is a SSD device
           vsanClaimed          - device is claimed by vSAN.  None if False,
                                  contains vSAN disk group UUID if True.
           interfaceType        - the type of SCSI interface.
        '''
        self.name = name
        self.path = path
        self.consoleDevicePath = consoleDevicePath
        self.vendor = vendor
        self.model = model
        self.size = size
        self.sectorSize = sectorSize
        self.sizeUnit = sizeUnit
        self.deviceExists = deviceExists
        self.driverName = driverName
        self.pathIds = pathIds
        self.local = local
        self.interfaceType = interfaceType
        self.diskFormatType = diskFormatType
        self.partedDevice = device

        # Set it to our variant type, then set the fields as necessary
        self.containsEsx = ESXVariant()

        self.initRdLocation = None
        self.vmfsLocation = None
        self.canSaveVmfs = None

        self.vmkLun = vmkLun

        # Determines whether we'll be able to install to this disk.
        self.supportsVmfs = supportsVmfs

        # Flag for whether vSAN has claimed this disk or not.
        self.vsanClaimed = vsanClaimed

        self.isUSB = isUSB
        self.isSSD = isSSD

        self._partitions = None
        self.requests = None

        # Stable refers to whether or not the device object can change out
        # from under us.
        self.stable = False

        if probePartitions:
            self.probePartitions()

    def __str__(self):
        return "%s (console %s) -- %s (%d MiB, %s)" % (
            self.name,
            self.consoleDevicePath,
            self.getVendorModelString(),
            self.getSizeInMebibytes(),
            self.driverName or "no-driver")

    def __repr__(self):
        return '<%s>' % self.__str__()

    def __getstate__(self):
        # Undefine the unpickable objects (Swig, C-modules).
        stateDict = self.__dict__.copy()

        stateDict['vmkLun'] = None
        stateDict['partedDevice'] = None

        return stateDict

    def __setstate__(self, state):
        # Redefine the unpickable objects.
        if sys.info_version[0] <= 2:
            partedDev = parted.PedDevice.get(state['consoleDevicePath'])
        else:
            partedDev = parted._ped.device_get(state['consoleDevicePath'])

        luns = [ptr.get() for ptr in vmkctl.StorageInfoImpl().GetDiskLuns()]
        vmkLun = None
        for entry in luns:
            if entry.GetConsoleDevice == state['consoleDevicePath']:
                vmkLun = entry

        self.__dict__.update(state)

        self.partedDevice = partedDev
        self.vmkLun = vmkLun

        self._partitions.partedDevice = partedDev
        if sys.info_version[0] <= 2:
             self._partitions.partedDisk = parted.PedDisk.new(partedDev)
        else:
             self._partitions.partedDisk = parted._ped.disk_new(partedDev)

    def getSizeInMebibytes(self):
        assert self.sizeUnit in ['KiB', 'MiB']

        if self.sizeUnit == 'MiB':
            return self.size
        elif self.sizeUnit == 'KiB':
            return units.getValueInMebibytesFromSectors(self.size,
                                                        self.sectorSize)

    # XXX - make this work for MB at some point
    def getSizeInKibibytes(self):
        assert self.sizeUnit == 'KiB'
        return units.getValueInKibibytesFromSectors(self.size, self.sectorSize)

    def getFormattedSize(self):
        return units.formatValue(self.getSizeInKibibytes())

    def getPartitionSet(self):
        '''If a PartitionSet is cached, return that.  Otherwise, probe first.
        May raise a partition.ScanError
        '''
        if self._partitions == None:
            self.probePartitions()
        return self._partitions

    def probePartitions(self):
        # XXX - we should probably raise an exception here
        if not self.deviceExists:
            log.error("Device was probed but doesn't exist yet!")
        else:
            self._partitions = partition.PartitionSet(device=self, scan=True)

    def getPartitionDevicePath(self, partitionNumber):
        '''Return the '/vmfs/devices' path for a given partition number.

        The format for the path can vary somewhat, so it's best to query vmkctl
        for the actual path.  We do this on-demand since the partitions can
        change out from under us.  Also, in the interest of not becoming more
        entangled with vmkctl, this method should really only be used with
        vmfs partitions.
        '''

        vmkPartitions = [vmkPartPtr.get() for vmkPartPtr in self.vmkLun.GetPartitions()]
        for vmkPart in vmkPartitions:
            if vmkPart.GetPartition() == partitionNumber:
                return vmkPart.GetDevfsPath()

        assert False, "Could not find partition %d in vmkctl" % partitionNumber

    def getVendorModelString(self):
        """Return a string that contains the vendor and model name of this
        device.

        If the vendor and model are the same generic string, only one is
        returned.
        """
        if self.vendor == self.model:
            retval = self.vendor
        else:
            retval = "%s %s" % (self.vendor, self.model)

        return retval

    def isControllerOnly(self):
        '''Return true if there is no disk attached to the controller.'''

        # See bug # 273709.  The size for the fake cciss disk that represents
        # the controller is one sector, so we check for zero megs.
        return int(self.getSizeInMebibytes()) == 0

    def canUpgradeToNOVA(self, forceRecheck=False):
        ''' In the case of missing or nominal drivers, NOVA should not permit
        an install, only an upgrade. Here we make sure that we present only
        the disks disks which can be upgraded. '''
        from weasel.upgrade import checkForPreviousInstalls
        checkForPreviousInstalls(self, forceRecheck)
        if self.canSaveVmfs is False:
            log.debug('diskDev::canUpgradeToNOVA: %s can\'t save vmfs' % self.name)
            return False
        elif not self.containsEsx.esxi:
            log.debug('diskDev::canUpgradeToNOVA: %s does not contain esxi' % self.name)
            return False
        elif self.containsEsx.version < (6, 0,):
            log.debug('diskDev::canUpgradeToNOVA: %s esx version too old' % self.name)
            return False
        elif not self.containsEsx.bootbankIsRecent:
            log.debug('diskDev::canUpgradeToNOVA: %s bootbank is stale' % self.name)
            return False
        else:
           return True

class DiskSet(Singleton):
    ''' An iterable data structure that represents all the disks on
    the system.

    This is a singleton object. You can re-probe the cached disk list by
    calling the constructor with forceReprobe=True, however this will
    cause the disk list to lose all information about the disks that has
    been contributed by client code.
    '''
    def _singleton_init(self, forceReprobe=False, probePartitions=True):
        self.disks = {}

        # XXX: This can be removed in favor of OrderedDict when ESXi moves to
        # python 2.7
        self.diskOrder = []

        # XXX temporary workaround for unsupported ide disks, remove later
        self.nonStandardDisks = []

    def __init__(self, forceReprobe=False, probePartitions=True):
        if forceReprobe or not self.disks:
            self.probeDisks(probePartitions=probePartitions)

    def __getitem__(self, key):
        return self.disks[key]

    def __contains__(self, item):
        return (item in self.disks)

    def items(self):
        return [(lun.name, lun) for lun in self.values()]

    def keys(self):
        return [lun.name for lun in self.values()]

    def values(self):
        # Annotate the values with the pathIds so we can sort based on the path.
        sortedIdPairs = [
            (diskDev.pathIds, diskDev) for diskDev in self.disks.values()]

        from functools import cmp_to_key

        # if a>b:  int(a>b) is 1, int(a<b) is 0, return  1
        # if a<b:  int(a>b) is 0, int(a<b) is 1, return -1
        # if a==b: int(a>b) is 0, int(a<b) is 0, return  0
        def compare(a,b): return (a > b) - (a < b)

        sortedIdPairs = sorted(sortedIdPairs, key=cmp_to_key(compare))

        # Strip the pathIds ... we just need the DiskDevs.
        retval = [pair[1] for pair in sortedIdPairs]

        return retval

    def _adapterIsUSB(self, adapter):
        '''Returns True for USB adapters only.'''

        return adapter.GetInterfaceType() in [
            vmkctl.ScsiInterface.SCSI_IFACE_TYPE_USB ]

    def _adapterSupportsVmfs(self, adapter):
        '''Not all disk/adapter types can support vmfs.'''

        return not self._adapterIsUSB(adapter)

    def probeDisks(self, diskList=None, probePartitions=True):
        self.disks = {} # Need to reset in case of a reprobe.
        self.diskOrder = []

        if diskList:
            for entry in diskList:
                if sys.version_info[0] <= 2:
                       partedDev = parted.PedDevice.get(entry[1])
                else:
                       partedDev = parted._ped.device_get(entry[1])
                try:
                    diskDev = DiskDev(name=entry[0], device=partedDev,
                        path=entry[1], model=partedDev.model,
                        size=partedDev.length, sectorSize=partedDev.sector_size,
                        probePartitions=probePartitions)
                except partition.ScanError as ex:
                    # Don't let one bad apple spoil the whole bunch
                    log.warn('ScanError probing disk %s (%s)'
                             % (entry[0], str(ex)))
                    diskDev = DiskDev(name=entry[0], device=partedDev,
                        path=entry[1], model=partedDev.model,
                        size=partedDev.length, sectorSize=partedDev.sector_size,
                        probePartitions=False)
                self.disks[entry[0]] = diskDev
                self.diskOrder.append(entry[0])
        else:
            log.debug("Querying disks")

            storage = vmkctl.StorageInfoImpl()
            luns = [ptr.get() for ptr in storage.GetDiskLuns()]

            vsanDiskNames = {}
            vsanListOutput = util.execLocalcliCommand("vsan storage list")

            if vsanListOutput:
                for entry in vsanListOutput:
                    vsanDiskNames[entry['Device']] = entry['VSAN Disk Group UUID']

            # Get metadata about all adapters.
            adapterInfo = getAdapterInfo()

            for entry in luns:
                path = entry.GetDevfsPath()

                log.debug(" lun -- %s" % entry.GetName())

                # skip anything which isn't a disk
                # XXX - replace this with the correct constant from vmkctl
                #       if vmkctlpy gets fixed
                if entry.GetLunType() != VMKCTL_SCSI_DISK:
                    log.warn("Lun at %s is not a proper disk. Skipping lun." %
                             (path))
                    continue

                if entry.IsPseudoLun():
                    log.warn("Lun at %s is a pseudo lun.  Skipping lun." %
                             (path))
                    continue

                # XXX - Console Device paths are broken for some USB devices.
                try:
                    consoleDevicePath = entry.GetConsoleDevice()
                except vmkctl.HostCtlException as msg:
                    log.warn("No Console Path for %s.  Skipping lun." % (path))
                    continue

                # XXX - check to see if the disk has been initialized
                # we should probably be prompting the user to initialize it
                if consoleDevicePath:
                    log.debug("  Trying %s" % (consoleDevicePath))
                else:
                    # XXX work around bug 173969 in vmklinux26 that causes
                    # broken luns to be reported
                    log.warn("No Console Path for %s.  Skipping lun." % (path))
                    continue

                if not os.path.exists(consoleDevicePath):
                    log.warn("console device is missing -- %s" %
                             consoleDevicePath)
                    continue

                try:
                    if sys.version_info[0] <= 2:
                        partedDev = parted.PedDevice.get(consoleDevicePath)
                    else:
                        partedDev = parted._ped.device_get(consoleDevicePath)
                except Exception:
                    log.warn("Pared could not open device %s. Skipping lun." %
                            (consoleDevicePath))
                    continue


                driverName = None
                supportsVmfs = False
                isUSB = False
                isLocalOnlyAdapter = False
                interfaceType = 'unknown'

                # Set a default path with a large value so it's at the end of
                # the sorted list.
                pathIds = [ 'z' * 5 ]

                # The order of the paths returned by GetPaths() can be random.
                # Sort them based on the value of GetName() before installer
                # picks paths[0]
                paths = sorted([pathPtr.get() for pathPtr in entry.GetPaths()],
                               key=lambda path: path.GetName())
                if paths:
                    try:
                        adapter = paths[0].GetAdapter().get()
                        interfaceType = adapter.GetInterfaceTypeString(
                                                    adapter.GetInterfaceType())
                        adapterName = paths[0].GetAdapterName()
                        driverName = getAdapterDriver(adapterName, adapterInfo)
                        # isLocalOnly means we should treat all disks on it as
                        # local w.r.t. installation
                        isLocalOnlyAdapter = adapter.IsLocalOnly()
                        pathIds = [
                            util.splitInts(paths[0].GetAdapterName()),
                            paths[0].GetChannelNumber(),
                            paths[0].GetTargetNumber(),
                            paths[0].GetLun()]

                        isUSB = self._adapterIsUSB(adapter)
                        supportsVmfs = self._adapterSupportsVmfs(adapter)
                    except vmkctl.HostCtlException as ex:
                        ## Should be a problem only until iSCSI driver situation is stabilized.
                        log.warn("Could not get driver for path %s -- %s" %
                                 (consoleDevicePath, str(ex.GetMessage())))
                else:
                    log.warn("Could not get driver name for %s" %
                             consoleDevicePath)
                try:
                    hasVsan = vsanDiskNames.get(entry.GetName(), None)
                    #hasVsan = entry.GetName() in vsanDiskNames
                    diskDev = DiskDev(name=entry.GetName(), device=partedDev,
                        path=path, consoleDevicePath=consoleDevicePath,
                        vendor=entry.GetVendor(), model=entry.GetModel(),
                        size=partedDev.length, sectorSize=partedDev.sector_size,
                        probePartitions=probePartitions,
                        driverName=driverName, pathIds=pathIds,
                        vmkLun=entry,
                        supportsVmfs=supportsVmfs, local=entry.IsLocal() or isLocalOnlyAdapter,
                        isUSB=isUSB, vsanClaimed=hasVsan, isSSD=entry.IsSSD(),
                        interfaceType=interfaceType, diskFormatType=entry.GetFormatType())
                except partition.ScanError as ex:
                    # Don't let one bad apple spoil the whole bunch
                    log.warn('ScanError probing disk %s (%s)'
                             % (entry.GetName(), str(ex)))

                    hasVsan = vsanDiskNames.get(entry.GetName(), None)
                    #hasVsan = entry.GetName() in vsanDiskNames
                    diskDev = DiskDev(name=entry.GetName(), device=partedDev,
                        path=path, consoleDevicePath=consoleDevicePath,
                        vendor=entry.GetVendor(), model=entry.GetModel(),
                        size=partedDev.length, sectorSize=partedDev.sector_size,
                        probePartitions=False,
                        driverName=driverName, pathIds=pathIds,
                        vmkLun=entry,
                        supportsVmfs=supportsVmfs, local=entry.IsLocal() or isLocalOnlyAdapter,
                        isUSB=isUSB, vsanClaimed=hasVsan, isSSD=entry.IsSSD(),
                        interfaceType=interfaceType, diskFormatType=entry.GetFormatType())

                log.info("Discovered lun -- %s" % str(diskDev))

                self.disks[entry.GetName()] = diskDev
                self.diskOrder.append(entry.GetName())

        #self._attachUpgradableMounts()

    def getOrderedDrives(self, allowUserOverride=True):
        '''Return a list of drives. The order will be the order that the
        BIOS puts them in, unless the user has specified a particular device
        to go first.

        This is primarily used to set up GRUB

        TODO: the scripted install "driveOrder" command  only affects the order
        of at most one device.  This is how I understand it should work.  If
        that's the case, maybe we need to change the name from "driveOrder"
        to something else.
        '''
        allDrives = self.disks.values()

        # XXX - remove this at some point since mixing userchoices here
        #       is bad.
        if allowUserOverride:
            bootOptions = userchoices.getBoot()
            if bootOptions:
                driveOrder = bootOptions['driveOrder']
                if driveOrder:
                    firstDrive = driveOrder[0]
                    if firstDrive not in allDrives:
                        raise InvalidDriveOrder(firstDrive)
                    allDrives.remove(firstDrive)
                    allDrives.insert(0, firstDrive)
                else:
                    log.debug("No drive order specified.  Set to default.")
            else:
                log.debug("Drive order set to default.")
        return allDrives

    def getDiskByName(self, name):
        if name in self.disks:
            return self.disks[name]
        return None

    def getDiskByPath(self, path, console=True):
        '''Find the disk that exactly matches path.'''

        for disk in self.disks.values():
           if console:
               if disk.consoleDevicePath == path:
                   return disk
           else:
               if disk.path == path:
                   return disk
        return None

    def _buildDisksToSearch(self, searchVirtual=False):
        '''Build a list of disks to search, including non-standard disks and,
        optionally, virtual disks.
        '''

        retval = list(self.disks.values())

        # TODO: it's kind of ugly that this has knowledge of userchoices
        #       in the future, this knowledge should be removed.
        if searchVirtual:
            virtualDevices = userchoices.getVirtualDevices()
            for virtualDevice in virtualDevices:
                virtDiskDev = virtualDevice['device']
                retval.append( virtDiskDev )

        retval.extend(self.nonStandardDisks)

        return retval

    def findDiskContainingPartition(self, part, searchVirtual=False):
        '''Find the disk containing part.
        Returns None if part can't be found
        '''
        disksToSearch = self._buildDisksToSearch(searchVirtual)

        for disk in disksToSearch:
            if part in disk.getPartitionSet():
                return disk
        return None

if __name__ == "__main__":
    disks = DiskSet()

    print(disks['vmhba32:0:0']._partitions)

    print(disks['vmhba32:0:0'].size)
    print(disks['vmhba32:0:0'].model)
    print(disks['vmhba32:0:0'].sectorSize)
    print(disks['vmhba32:0:0'].path)

    #print x.disks['vmhba0:0:0']._partitions
    print(len(disks['vmhba32:0:0']._partitions ))
    for entry in disks['vmhba32:0:0']._partitions:
        print("%d: start = %d end = %d size=%d" %
              (entry.partitionId, entry.startSector, entry.endSector,
               entry.getLength()))
