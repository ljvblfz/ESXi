#! /usr/bin/env python

# We will still need this for creating a data structure that contains the
# current layout of the disk.  We need to handle the migration at some point
# (MBR scribbling) for now, we'll just remove unnecessary stuff.

from __future__ import print_function

import os
import re
import sys
import time
import parted
import vmkctl
from weasel import util
from weasel import fsset
from weasel import datastore
from weasel import userchoices # always import via weasel.
from weasel import task_progress
from weasel.log import log
from weasel.util import units, loadVmfsModule, rescanVmfsVolumes
from weasel.exception import HandledError

def longInt(n):
    if sys.version_info[0] >= 3:
        return int(n)
    else:
        return long(n)

TASKNAME_CLEAR = 'Clearpart'
TASKDESC_CLEAR = 'Clearing partitions'

TASKNAME_CHECK = 'Checkpart'
TASKDESC_CHECK = 'Checking partitions'

TASKNAME_WRITE = 'Writepart'
TASKDESC_WRITE = 'Writing new partitions'

PRIMARY = 0
LOGICAL = 1
EXTENDED = 2
FREESPACE = 4
METADATA = 8
PROTECTED = 16

VMFS_PARTITION_TYPE = vmkctl.DiskLunPartition.PART_TYPE_VMKERNEL

MAX_PRIMARY_PARTITIONS = 4
MAX_PARTITIONS = 15

def joinPath(devicePath, partitionNum):
    '''Join a path for a whole device with a partition number.

    >>> joinPath("/vmfs/devices/disks/vml.1234", 1)
    '/vmfs/devices/disks/vml.1234:1'
    '''
    # ESXi doesn't put the disks under /vmfs/devices
    #if not devicePath.startswith('/vmfs/devices/disks/vml.'):
    #    raise ValueError('Got unexpected console device: %s' % (devicePath))
    return "%s:%d" % (devicePath, partitionNum)

class NotEnoughSpaceException(HandledError): pass

class ScanError(HandledError): pass

class Partition:
    def __init__(self, name="", fsType=None, partitionType=PRIMARY,
                 startSector=-1, endSector=-1, partitionId=-1, mountPoint=None,
                 format=False, consoleDevicePath=None):
        '''Basic Partition class.

           name                 - name related to the partition (usually blank)
           fsType               - file system class (from fsset)
           partitionType        - type of partition can be PRIMARY, EXTENDED
                                  LOGICAL
           partitionId          - id of the partition on disk.  -1 is free
                                  space.  1-4 are primary partitions (or 1
                                  extended partition)
           mountPoint           - absolute path to real mount point (place
                                  where the directory would normally be
                                  mounted)
           format               - boolean value to format the partition
           consoleDevicePath    - device node for how to access the partition
        '''
        assert fsType is None or isinstance(fsType, fsset.FileSystemType)

        self.name = name
        self.fsType = fsType
        self.startSector = longInt(startSector)
        self.endSector = longInt(endSector)
        self.partitionId = partitionId
        self.mountPoint = mountPoint
        self.consoleDevicePath = consoleDevicePath

        if partitionType == PRIMARY or partitionType == LOGICAL or \
           partitionType == EXTENDED or partitionType == FREESPACE or \
           partitionType == LOGICAL + FREESPACE:
            self.partitionType = partitionType
        else:
            raise ValueError("Partition type must be set to PRIMARY, "
                             "LOGICAL or EXTENDED.")

        if format and not fsType.formattable:
            raise RuntimeError("File system type %s is not formattable "
                               "however it has been flagged to be formatted."
                               % fsType.name)
        self.format = format

    def getName(self):
        return self.name

    def getStartSector(self):
        return self.startSector

    def getEndSector(self):
        return self.endSector

    def getLength(self):
        return longInt(self.endSector - self.startSector + 1)

    def getFileSystem(self):
        return self.fsType

    def getId(self):
        return self.partitionId

    def getMountPoint(self):
        return self.mountPoint

    def getPartitionType(self):
        return self.partitionType

    def setFormat(self, format):
        self.format = format

    def getFormat(self):
        return self.format

    def getFsTypeName(self):
        if self.fsType:
            retval = self.fsType.name
        else:
            retval = None

        return retval

    def createDeviceFromFile(self, sourceFile):
        util.loadFiledriverModule()
        cmd = 'vmkmkdev -Y file'

        if self.startSector is None or self.startSector < 0:
            cmd += ' -o "ro,%s"' % sourceFile
        else:
            cmd += ' -o "ro,%d,%d,%s"' % (self.startSector * 512,
                                          self.getLength() * 512,
                                          sourceFile)

        consoleDevicePathBasename = os.path.basename(self.consoleDevicePath)
        cmd += ' %s' % consoleDevicePathBasename

        rc, stdout, stderr = util.execCommand(cmd)

        if rc:
            log.error("'%s' failed with (%s, %s, %s)."
                      % (cmd, rc, stdout, stderr))
            raise HandledError("Unable to mount %s to %s."
                               % (sourceFile, self.consoleDevicePath))

        self.mountPoint = '/dev/file/' + consoleDevicePathBasename

    def removeDeviceLinkedFile(self):
        """
        Removes the filedev so that it frees up the device for other uses.
        """
        try:
            if self.mountPoint:
                log.debug("Unlinking %s." % self.mountPoint)
                os.unlink(self.mountPoint)
                # XXX: Maybe the vmkernel guys know more about what's going
                #      on here. Ask them about it, at some point?
                time.sleep(0.5)
        except OSError as ex:
            msg = "Failed to 'unmount' filedevice: %s" % ex
            log.error(msg)
            raise HandledError(msg)

    def getFileList(self, path):
        return self.fsType.getFileList(self.mountPoint, path)

    def getFile(self, filename):
        return self.fsType.getFile(self.mountPoint, filename)

    def copyFile(self, src, dest, raiseException=True):
        return self.fsType.copyFile(self.mountPoint, src, dest, raiseException)

    def readSymlink(self, symlink):
        return self.fsType.readSymlink(self.mountPoint, symlink)

    def isDirectory(self, directory):
        return self.fsType.isDirectory(self.mountPoint, directory)


class GPTPartition(Partition):
    """
    Similar to the Partition object, except wraps GPT partitions.
    Note: GPT Partitions don't have a 'partitionType'.
    """
    def __init__(self, name="", fsType=None, startSector=-1, endSector=-1,
                 partitionId=None, mountPoint=None, format=False,
                 consoleDevicePath=None):
        self.name = name
        self.fsType = fsType
        self.startSector = longInt(startSector)
        self.endSector = longInt(endSector)
        self.partitionId = partitionId
        self.mountPoint = mountPoint
        self.consoleDevicePath = consoleDevicePath


class PartitionSet:
    """Container object for a set of partitions"""

    def __init__(self, partitions=None, device=None, scan=False):
        if partitions == None:
            self.partitions = []
        else:
            self.partitions = partitions
        self.partedPartsTableType = None

        # Don't initialize disk that has a disk label that parted doesn't
        # understand. It can lead to data loss. See PR 1007325 for more details.
        # Just log the error and move on.
        if device:
            self.partedDevice = device.partedDevice
            try:
                if sys.version_info[0] <= 2:
                    self.partedDisk = parted.PedDisk.new(self.partedDevice)
                else:
                    self.partedDisk = parted._ped.disk_new(self.partedDevice)
            except Exception as ex:
                log.error("Exception: %s" % str(ex))
                self.partedDevice = None
                self.partedDisk = None
                self.device = None
                return

        self.device = device

        if scan:
            self.scanPartitionsOnDevice()

    def __len__(self):
        return len(self.partitions)

    def __getitem__(self, key):
        return self.partitions[key]

    def append(self, partition):
        self.partitions.append(partition)

    def __str__(self):
        buf = ""
        for entry in self.partitions:
            length = entry.getLength()

            buf += "%d: pos=%d start=%d end=%d size=%d (%d MB) type=%s\n" % \
            (entry.partitionType, entry.partitionId, entry.startSector,
             entry.endSector, length,
             units.getValueInMebibytesFromSectors(length), entry.fsType)
        return '<PartitionSet (%s) of device %s>' % (buf, self.device.name)

    def __getstate__(self):
        stateDict = self.__dict__.copy()
        stateDict['partedDevice'] = None
        stateDict['partedDisk'] = None

        return stateDict

    def __setstate__(self, state):
        self.__dict__.update(state)

    def clear(self):
        if not self.partedDisk:
            log.info("Skipping clearing partition")
            return

        self.partedDisk.delete_all()

        # re-init the disk in case the partition table is corrupt
        if sys.version_info[0] <= 2:
            self.partedDisk = self.partedDevice.disk_new_fresh(
                parted.disk_type_get("msdos"))
        else:
            self.partedDisk = parted._ped.disk_new_fresh(self.partedDevice,
                parted._ped.disk_type_get("msdos"))
        self.partedDisk.commit()

        self.partitions = []
        try:
            self.scanPartitionsOnDevice()
        except ScanError as ex:
            log.warn('ScanError probing disk %s after clearing (%s).'
                     % (self.device, str(ex)))

    def getPartitions(self, showFreeSpace=False, showUsedSpace=True):
        """Return a PartitionSet with a Free or Used Space"""
        # First, check that the partitions have been scanned...
        if not self.partitions:
            # GPT disks can legitimately have partitions == [], so
            # make sure not to re-scan.
            if self.getPartitionTableType() != 'gpt':
                self.scanPartitionsOnDevice()
        if showFreeSpace and showUsedSpace:
            # XXX - this should probably return a copy
            return self
        else:
            partTableType = self.getPartitionTableType()
            if partTableType == 'msdos':
                partitions = PartitionSet(device=self.device)
                for partition in self.partitions:
                    if (showFreeSpace
                        and partition.getPartitionType() & FREESPACE):
                        partitions.append(partition)
                    elif (showUsedSpace
                          and not partition.getPartitionType() & FREESPACE):
                        partitions.append(partition)
            elif partTableType == 'gpt' and showUsedSpace:
                # We don't keep track of free space in GPT tables.  Do we even
                # need to any more now that we don't allow users to specify
                # their partition table?
                partitions = PartitionSet(partitions=self.partitions,
                                          device=self.device,
                                          scan=False)
            else:
                raise HandledError('Partitions not initialized!')
            return partitions

    def getPartitionTableType(self):
        if self.partedPartsTableType:
            return self.partedPartsTableType
        elif self.partitions:
            if isinstance(self.partitions[0], GPTPartition):
                return 'gpt'
            elif isinstance(self.partitions[0], Partition):
                return 'msdos'
        return None

    def getPartitionsOfType(self, fsType):
        '''Takes in a string describing a file system and returns a list of
        partitions that matches that type.

        >>> from weasel import devices, fsset
        >>> d = devices.DiskSet(forceReprobe=True)
        >>> extParts = d['vml.0000'].getPartitionSet().getPartitionsOfType(fsset.ext3FileSystem)
        >>> extParts
        [<weasel.partition.Partition instance at ...>, <weasel.partition.Partition instance at ...>]
        >>> len(extParts)
        2
        '''
        if not self.partitions:
            self.scanPartitionsOnDevice()
        return [ p for p in self.partitions
                 if p.fsType and isinstance(p.fsType, fsType) ]

    def scanMSDOSPartitions(self, device, partedDev, partedDisk,
                            requests, fsTable):
        '''A helper function for scanPartitionsOnDevice'''
        partition = partedDisk.next_partition()
        while partition:
            if partition.num > 0:
                try:
                    name = partition.get_name()
                except:
                    name = ""

                mountPoint = None
                consoleDevicePath = None
                format = False


                if requests:
                    request = requests.findRequestByPartitionID(partition.num)
                    if request:
                        mountPoint = request.mountPoint
                        consoleDevicePath = request.consoleDevicePath
                        # if we have a request, format every partition possible
                        if request.fsType.formattable:
                            format = True
                elif partedDisk.type.name == "loop":
                    # The "loop" type means there is no partition table, for
                    # example, if the whole disk is formatted as FAT.
                    consoleDevicePath = partedDev.path
                else:
                    consoleDevicePath = joinPath(partedDev.path, partition.num)

                # XXX - we need to be able to figure out what filesystem
                #       type we've found instead of setting it to None
                if partition.type & EXTENDED:
                    fsType = None
                elif partition.fs_type and partition.fs_type.name in fsTable:
                    fsClass = fsTable[partition.fs_type.name]
                    fsType = fsClass()
                else:
                    partedFsTypeName = "unknown"
                    if partition.fs_type:
                        partedFsTypeName = partition.fs_type.name
                    log.debug("Unknown parted file system type ('%s') for "
                              "partition: %s%d" %
                              (partedFsTypeName,
                               device.consoleDevicePath,
                               partition.num))
                    fsType = None
                    format = False # XXX

                self.partitions.append(Partition(name, fsType, partition.type,
                    partition.geom.start, partition.geom.end, partition.num,
                    mountPoint, format, consoleDevicePath))
            else:
                if partition.type and partition.type & FREESPACE:
                    name = ""
                    self.partitions.append(Partition(name, None,
                        partition.type, partition.geom.start,
                        partition.geom.end, partition.num))

            partition = partedDisk.next_partition(partition)

    def scanGPTPartitions(self, device, partedDev, partedDisk,
                          requests, fsTable):
        '''A helper function for scanPartitionsOnDevice'''
        # This is really ghetto.  We're going to go through and figure out
        # the partitions using partedUtil.  Maybe this can be fixed
        # eventually when pyparted and libparted get updated properly, but
        # this'll do for now.
        cmd = 'partedUtil getptbl %s' % device.consoleDevicePath
        rc, stdout, stderr = util.execCommand(cmd)

        if rc:
            msg = "Unable to read partition table for '%s'." % \
                  device.consoleDevicePath
            log.error(msg)
            raise ScanError(msg)

        """ Expected output ...
        # partedUtil getptbl /dev/disks/mpx.vmhba1:C0:T0:L0
        gpt
        1305 255 63 20971520
        1 64 8191 C12A7328F81F11D2BA4B00A0C93EC93B systemPartition 128
        5 8192 588323 EBD0A0A2B9E5443387C068B6B72699C7 linuxNaive 0
        ...
        """
        # The first two lines are irrelevant in making Partitions; first is
        # the table type, second is the disk geometry.
        output = stdout.splitlines()
        output = output[2:]
        for partition in output:
            partGeom = partition.split(' ')
            log.debug("Got partGeom: '%s'." % partGeom)

            partNum = int(partGeom[0])
            startSector = partGeom[1]
            endSector = partGeom[2]
            fsTypeName = partGeom[4]
            activePart = partGeom[5]

            fsType = None

            if fsTypeName in fsTable:
                fsClass = fsTable[fsTypeName]
                fsType = fsClass()
            elif fsTypeName != 'vmfs':
                    log.debug("partedUtil gave us an unknown fsType: '%s'."
                              % fsTypeName)

            name = ""

            # If it is a VMFS file system, then lets find its name, and
            # its version.
            # We're going to trust partedUtil with telling us that it's a
            # 'vmfs' partition.
            if fsTypeName == 'vmfs':
                datastores = datastore.DatastoreSet()
                baseName = os.path.basename(device.consoleDevicePath)
                vmfsPart = datastores.getEntriesByDriveName(baseName)

                # If there's more than 1 vmfsPart on the drive, then
                # something's wrong.
                if vmfsPart:
                    if len(vmfsPart) != 1:
                        msg = ("More than one VMFS partition found on disk "
                               "'%s'." % device.consoleDevicePath)
                        log.error(msg)
                        raise ScanError(msg)
                    vmfsPart = vmfsPart[0]

                    if vmfsPart.name:
                        name = vmfsPart.name

                    # Also make it the right fsType
                    vmfsVer = vmfsPart.majorVersion
                    if vmfsVer == 3:
                        fsType = fsTable['vmfs3']()
                    elif vmfsVer == 5:
                        fsType = fsTable['vmfs5']()
                    elif vmfsVer == 6:
                        fsType = fsTable['vmfs6']()
                    else:
                        log.warn("Invalid VMFS major version number: '%d'"
                                 % vmfsVer)

            self.partitions.append(GPTPartition(name, fsType, startSector,
                 endSector, partNum, None, False, device.consoleDevicePath))

    def scanPartitionsOnDevice(self, device=None, partedDev=None,
                               partedDisk=None, requests=None):
        """Walk through each of the partitions on a given disk and
        populate self.partitions"""
        if not device:
            if not self.device:
                log.debug('PartitionSet with no device - scan skipped.')
                return
            device = self.device

        if not partedDev:
            partedDev = self.partedDevice
        if not partedDisk:
            partedDisk = self.partedDisk

        self.partitions = []

        fsTable = fsset.getSupportedFileSystems(partedKeys=True, gptKeys=True)

        partsTable = partedDisk.type.name

        if partsTable == 'msdos':
            self.partedPartsTableType = partsTable
            self.scanMSDOSPartitions(device, partedDev, partedDisk,
                                     requests, fsTable)
        elif partsTable == 'gpt':
            self.partedPartsTableType = partsTable
            self.scanGPTPartitions(device, partedDev, partedDisk,
                                   requests, fsTable)
        else:
            # We've hit something really wrong, we really shouldn't find
            # anything other than 'msdos' or 'gpt' ... but it could be blank,
            # and in that case we probably can't rely on the partition
            # information anyways.
            self.partedPartsTableType = partsTable
            msg = "Found invalid partition table type: '%s'." % partsTable
            log.error(msg)

    def getDevice(self):
        return self.device


class PartitionRequest(Partition):
    def __init__(self, mountPoint=None, fsType=None, drive=None,
                 primaryPartition=False):
        # XXX - don't call this or the nosetests will fail
        #assert fsType is None or isinstance(fsType, fsset.FileSystemType)

        self.mountPoint = mountPoint
        self.fsType = fsType

        self.apparentSize = 0
        self.consoleDevicePath = ""
        self.partitionId = 0

        # XXX - check to see if there is enough space for another primary
        # partition here
        self.primaryPartition = primaryPartition

    def __repr__(self):
        return repr(self.__dict__)

class PartitionRequestSet(object):
    """Container object for holding PartitionRequests"""

    def __init__(self, deviceName=None, deviceObj=None):
        self.deviceName = deviceName
        self._deviceObj = deviceObj
        self.requests = []

    def __str__(self):
        return '<PartitionRequestSet %d parts on %s>' % (len(self),
                                                         self.deviceName)

    def __repr__(self):
        return self.__str__()

    def __getitem__(self, key):
        return self.requests[key]

    def __len__(self):
        return len(self.requests)

    def __add__(self, oldSet):
        """Add two request sets together.  This is useful for determining
           the mount order of each of the partitions, however the device will
           be invalid for the entire set so you will not be able to partition
           after combining two sets.
        """
        newSet = PartitionRequestSet()
        newSet.requests = self.requests + oldSet.requests

        # set the device to the old one although it's possible this could
        # be invalid
        newSet.deviceName = oldSet.deviceName
        newSet._deviceObj = oldSet._deviceObj

        return newSet

    def _getDevice(self):
        from weasel import devices # avoid circular imports
        return self._deviceObj or devices.DiskSet()[self.deviceName]
    device = property(_getDevice)

    def append(self, request):
        self.requests.append(request)

    def remove(self, request):
        self.requests.remove(request)

    def reverse(self):
        self.requests.reverse()

    def findRequestByMountPoint(self, mountPoint):
        for request in self.requests:
            if request.mountPoint == mountPoint:
                return request
        return None

    def findRequestByPartitionID(self, partID):
        for part in self.requests:
            if part.partitionId == partID:
                return part
        return None

    def _findFreeSpace(self):
        return self.device.getPartitionSet().getPartitions(showFreeSpace=True,
                                                    showUsedSpace=False)

    def _addPartition(self, partitionType, fsType, startSector, endSector,
                      partReq):
        partitionSet = self.device.getPartitionSet()
        newPartition = partitionSet.partedDisk.partition_new(partitionType,
                           fsType, startSector, endSector)

        newConstraint = partitionSet.partedDevice.constraint_any()
        partitionSet.partedDisk.add_partition(newPartition, newConstraint)

        partReq.consoleDevicePath = joinPath(partitionSet.partedDevice.path,
                                             newPartition.num)

        log.debug("New partition console path:%s" % (partReq.consoleDevicePath))

        # save the new partition id so we can reference requests with it later
        partReq.partitionId = newPartition.num


def _allUserPartitionRequestSets():
    '''Return all the PartitionRequestSets in userchoices in a list.'''
    retval = []

    for physDevice in userchoices.getPhysicalPartitionRequestsDevices():
        retval.append(userchoices.getPhysicalPartitionRequests(physDevice))

    return retval


# Host-actions are below, these functions are called by the applychoices
# module in order to act on the data in userchoices.

# We need to keep this to clear any other partitions that the user may want to
# clear
def hostActionClearPartitions():
    from weasel import devices # avoid circular imports

    clearParts = userchoices.getClearPartitions()
    if not ('drives' in clearParts and 'whichParts' in clearParts):
        return

    loadVmfsModule()

    # XXX A side-effect of getting the list of vmfs volumes in DatastoreSet
    # is that any existing vmfs volumes will get put into a cache in the
    # kernel.  While in this cache, some SCSI handles are left open which
    # prevent us from clearing the partition table completely.
    #
    # See pr 237236 for more information.
    rescanVmfsVolumes()

    taskEstimate = len(clearParts['drives'])
    task_progress.reviseEstimate(TASKNAME_CLEAR, taskEstimate)
    for deviceName in clearParts['drives']:
        task_progress.taskProgress(TASKNAME_CLEAR, 1)
        device = devices.DiskSet()[deviceName]
        if device.name in userchoices.getDrivesInUse():
            log.info("skipping clearing drive -- %s" % device.name)
            continue
        msg = ("Clearing Partition %s (%s)" % (device.name, device.path))
        log.info(msg)
        task_progress.taskProgress(TASKNAME_CLEAR)
        if clearParts['whichParts'] == userchoices.CLEAR_PARTS_ALL:
            # This check is a bit generic and will cause false positives when a
            # user has more than one USB stick connected, has a bootable
            # installer USB, and wishes to 'clearpart' on all disks.  In that
            # case, we won't 'clearpart' any of the USB disks.
#            systemInfoImpl = vmkctl.SystemInfoImpl()
#            if systemInfoImpl.GetBootOptions().usbBoot \
#               and device.isUSB and :
#                log.info("Not clearing USB disk: '%s'" % device.name)
#                continue
#            else:
            device.getPartitionSet().clear()
        else:
            #TODO: finish this for the other options.
            assert False, "clearPartitions not completely implemented"

    # rescan the vmfs volumes in case we need to disconnect any since
    # we have a new partition table
    rescanVmfsVolumes()


def hostActionPartitionPhysicalDevices():
    '''Partitions the disk, then, for each partition, formats it with
    the chosen filesystem
    '''
    loadVmfsModule()
    requestDevices = userchoices.getPhysicalPartitionRequestsDevices()
    taskEstimate = len(requestDevices) * 10
    task_progress.reviseEstimate(TASKNAME_WRITE, taskEstimate)

    # The logic for this becomes much simpler.  Since a disk can only have one
    # request, we'll check just for what type of VMFS they asked for, then make
    # it with GPT.
    for deviceName in requestDevices:
        requests = userchoices.getPhysicalPartitionRequests(deviceName)

        # There really shouldn't be more than one partition request for the
        # device...  there should just be the request for the VMFS, since that's
        # the only request that'll get past the scripted preparser.
        assert len(requests) == 1

        req = requests[0]
        dev = requests.device # make shorthand

        task_progress.taskProgress(TASKNAME_WRITE, 0,
                                   "Partitioning %s (%s)" % (dev.name, dev.path))

        SUBTASKNAME = TASKNAME_WRITE + 'requests'
        task_progress.subtaskStarted(SUBTASKNAME, TASKNAME_WRITE,
              len(requests), share=10,
              taskDesc='Formatting filesystems on disk %s' % dev.name)

        # We're just going to make the vmfs request fill the entire disk and
        # we're going to steal from thin_partitions.py for what we need.
        from weasel import thin_partitions

        diskPath = dev.consoleDevicePath
        partType, diskGeom, parts = thin_partitions.getDiskInfo(diskPath)
        lastSector = int(diskGeom[3])

        # We're going to do this with GPT, just make sure people don't boot to
        # it.

        vmfsGptPart = thin_partitions.GPT_VMFS.split()

        # A little hacky, but we need to make sure that it's marked as the first
        # partition.
        partitionId = 1

        vmfsGptPart[0] = '"%s' % partitionId

        vmfsGptPart = ['gpt'] + vmfsGptPart

        vmfsGptPart = ' '.join(vmfsGptPart)
        # 64, is for the first sector of the partition, where the partition
        # should start.
        # We subtract 32 + 2  to allow for room for the secondary GPT header.
        # It also includes algorithm to ensure the value of end of vmfs is
        # 4k aligned.

        vmfsGptPart = vmfsGptPart % (64, ((lastSector - 32 - 2) // 8)* 8 - 1)

        makePartCmd = ' '.join([thin_partitions.PARTEDUTIL_BIN,
                                thin_partitions.PARTEDUTIL_SETPART,
                                diskPath,
                                vmfsGptPart])

        rc, stderr, stdout = util.execCommand(makePartCmd)

        path = dev.getPartitionDevicePath(req.partitionId)
        msg = "Formatting %s" % path
        log.info(msg)
        task_progress.taskProgress(SUBTASKNAME, 1, msg)
        req.fsType.formatDevice(path + ':%s' % partitionId)

        task_progress.taskFinished(SUBTASKNAME)


if __name__ == "__main__":
    #import doctest
    #doctest.testmod()
    from weasel import devices # avoid circular imports

    diskSet = devices.DiskSet()
    disks = list(diskSet.keys())
    disks.sort()

    diskName = "mpx.vmhba1:C0:T0:L0"
    _requests = PartitionRequestSet(deviceName=diskName)

    #fstype = fsset.ext3FileSystem()
    fstype = fsset.vmfs3FileSystem()

    _requests.append(PartitionRequest(minimumSize=100, grow=True,
                                     fsType=fstype))
    _requests.append(PartitionRequest(minimumSize=100, maximumSize=100,
                                     fsType=fstype))

    userchoices.setClearPartitions(drives=[diskName])
    print('Clearing ============================')
    hostActionClearPartitions()
    print('--------0-------')
    r = _requests[0]
    _path = r.consoleDevicePath
    print('--------1-------')
    r.fsType.volumeName = fsset.findVmfsVolumeName()
    print('--------2-------')
    r.fsType.formatDevice(_path)
    print('--------3-------')

