from __future__ import print_function

import string
import os
import re
import parted
from . import util
import time
import struct

from weasel.log import log
from . exception import HandledError
from . util.regexlocator import RegexLocator

class FileSystemType:
    formattable = False
    uuidable = False
    partedFileSystemName = None
    partedPartitionFlags = []
    minSizeMB = 16
    maxSizeMB = 2 * 1024 * 1024
    supported = False
    defaultOptions = "defaults"
    extraFormatArgs = []
    name = None
    # Determines whether the FS can be found or is expected on a disk with GPT.
    canBeGpt = False


    def __init__(self, name=""):
        if name:
            self.name = name

    def __str__(self):
        return '<%s instance (%s)>' % (self.__class__.__name__, self.name)

    def mount(self, device, mountPoint, readOnly=False, bindMount=False,
              loopMount=False):

        status = util.mount(device, mountPoint, readOnly, bindMount, loopMount)
        if status:
            raise HandledError("Could not mount '%s' onto '%s'." % (
                    device, mountPoint))

    def umount(self, mountPoint):
        status = util.umount(mountPoint)
        if status:
            raise HandledError("Could not unmount '%s'." % mountPoint)

    def formatDevice(self, entry=None, progress=None, chroot='/'):
        if self.isFormattable():
            raise RuntimeError("formatDevice method not defined")

    def uuidDevice(self, entry=None, chroot='/'):
        if self.isUuidable():
            raise RuntimeError("uuidDevice method not defined")

    def isFormattable(self):
        return self.formattable

    def isUuidable(self):
        return self.uuidable

    def getPartedPartitionFlags(self):
        return self.partedPartitionFlags

    def getMinSizeMB(self):
        return self.minSizeMB

    def getMaxSizeMB(self):
        '''returns the maximum size of a filesystem in megabytes'''
        return self.maxSizeMB

    def getDefaultOptions(self):
        return self.defaultOptions

    def getUuid(self, devicePath):
        # XXX Maybe we should just install the vol_id package...
        log.warn('This FS Type does not have a UUID')
        return None

    def getFileList(self, devicePath, path):
        raise HandledError("getFileList is not implemented for filesystem "
                           "%s." % self.name)

    def getFile(self, devicePath, filename):
        raise HandledError("getFile is not implemented for filesystem "
                           "%s." % self.name)

    def copyFile(self, devicePath, src, dest):
        raise HandledError("copyFile is not implemented for filesystem "
                           "%s." % self.name)

    def readSymlink(self, devicePath, symlink):
        raise HandledError("readSymlink is not implemented for filesystem "
                           "%s." % self.name)

    def isDirectory(self, devicePath, directory):
        raise HandledError("isDirectory is not implemented for filesystem "
                           "%s." % self.name)

class vmfsFileSystem(FileSystemType):
    formattable = True
    vmwarefs = True
    minSizeMB = 1200
    maxSizeMB = 2 * 1024 * 1024
    blockSizeMB = 1

    canBeGpt = True
    gptName = "vmfs"

    maxLabelLength = 64 # From lvm_public.h
    maxFilenameLength = 127 # From statvfs of /vmfs

    @staticmethod
    def sanityCheckVolumeLabel(label):
        '''Return True if the given label is valid.

        XXX Not totally sure what all the constraints are for a label.

        >>> vmfsFileSystem.sanityCheckVolumeLabel('hello')
        >>> vmfsFileSystem.sanityCheckVolumeLabel('hello/world')
        Traceback (most recent call last):
        ...
        ValueError: Datastore names may not contain the '/' character.
        >>> vmfsFileSystem.sanityCheckVolumeLabel('hello' * 128)
        Traceback (most recent call last):
        ...
        ValueError: Datastore names must be less than 64 characters long.
        '''

        if not label:
            raise ValueError("Datastore names must be contain at least one "
                             "character.")

        if len(label) > vmfsFileSystem.maxLabelLength:
            raise ValueError("Datastore names must be less than %d characters "
                             "long." % vmfsFileSystem.maxLabelLength)

        if label[0] in string.whitespace or label[-1] in string.whitespace:
            raise ValueError("Datastore names may not start or end with "
                             "spaces.")

        if not re.match('^(' + RegexLocator.vmfsvolume + ')$', label):
            raise ValueError("Datastore names may not contain the '/' "
                             "character.")

    @classmethod
    def getEligibleDisks(cls, disks=None):
        from weasel import devices # avoid circular imports
        retval = []

        if disks == None:
            disks = devices.DiskSet().values()

        for disk in disks:
            diskSize = disk.getSizeInMebibytes()

            log.debug("Checking if disk %s is eligible for vmfs." % disk)

            if not disk.supportsVmfs:
                log.debug("  %s does not support vmfs." % disk)
                continue

            if not (cls.minSizeMB <= diskSize <= cls.maxSizeMB):
                log.debug("  %s does not support vmfs." % disk)
                continue

            retval.append(disk)

        return retval

    @classmethod
    def systemUniqueName(cls, prefix):
        '''Given a prefix return a filename that is unique for this installed
        system.'''
        import vmkctl

        uuid = vmkctl.SystemInfoImpl().GetSystemUuid()
        retval = "%s-%s" % (prefix, uuid.uuidStr)
        if len(retval) > cls.maxFilenameLength:
            raise ValueError(
                "name is too long when prepended to UUID "
                "(max %d chars) -- %s" % (cls.maxFilenameLength, retval))
        return retval

    def __init__(self, volumeName=None):
        FileSystemType.__init__(self)
        self.volumeName = volumeName

    def mount(self, device, mountPoint, readOnly=False, bindMount=False,
              loopMount=False):
        pass

    def umount(self, mountPoint=None):
        pass

    def uuidDevice(self):
        pass

    def formatDevice(self, devicePath=None, progress=None):
        assert self.volumeName is not None

        args = ["/usr/sbin/vmkfstools", "-C", self.name,
                "-b", "%dm" % self.blockSizeMB, "-S", '%s' % self.volumeName,
                devicePath]
        args.extend(self.extraFormatArgs)

        try:
            util.execWithLog(args[0], args, raiseException=True)
        except Exception as e:
            raise HandledError("Could not format a vmfs volume.", str(e))

class vmfs3FileSystem(vmfsFileSystem):
    partedFileSystemName = "vmfs3"
    supported = True
    name = "vmfs3"
    gptName = "vmfs3"

class vmfs5FileSystem(vmfsFileSystem):
    partedFileSystemName = "vmfs5"
    supported = True
    name = "vmfs5"
    gptName = "vmfs5"

class vmfs6FileSystem(vmfsFileSystem):
    partedFileSystemName = "vmfs6"
    supported = True
    name = "vmfs6"
    gptName = "vmfs6"

def getVmfsFileSystemInstance(version='vmfs6'):

    import featureState
    featureState.init()

    if version == 'vmfs3':
        return vmfs3FileSystem()
    elif version == 'vmfs5':
        return vmfs5FileSystem()
    # If they give us anything but vmfs5, we'll default to vmfs6.
    else:
        return vmfs6FileSystem()

def findVmfsVolumeName(takenNames=None):
    """Find a volume name that we can use to install.

    This function is used to find a default vmfs volume name
    (usually "datastore1") for the VMFS partition of the boot disk of ESXi

    ***It is not shared storage safe.***

    Autopartitioning is not supposed to be done on shared storage since
    the bootbanks can be overwritten by other machines.

    (optional arg)takenNames should be a list of the existing datastore
    names, that should not be used

    >>> findVmfsVolumeName()
    'datastore1'
    >>> findVmfsVolumeName(["datastore1"])
    'datastore2'
    """
    if not takenNames:
        takenNames = []

    count = 0
    while True:
        count += 1

        # XXX - put the string somewhere more useful
        volumeName = "datastore%d" % (count)
        volumePath = os.path.join("/vmfs/volumes", volumeName)

        if not (volumeName in takenNames
                or os.path.exists(volumePath)
                or os.path.islink(volumePath)):
            log.debug("  using auto-generated vmfs volume name -- %s" %
                      volumeName)
            return volumeName

        log.debug("  vmfs volume name already exists, trying again -- %s" %
                  volumePath)

class FATFileSystem(FileSystemType):
    partedFileSystemName = "fat32"
    formattable = False
    maxSizeMB = 1024 * 1024
    name = "vfat"
    supported = True

    def __init__(self):
        FileSystemType.__init__(self)

    def formatDevice(self, entry=None, progress=None, chroot='/'):
        raise RuntimeError("Fat filesystem creation unimplemented.")

class FAT16FileSystem(FATFileSystem):
    partedFileSystemName = "fat16"
    maxSizeMB = 2 * 1024 * 1024


def getSupportedFileSystems(partedKeys=False, gptKeys=False):
    fsTable = {}
    for className in globals():
        value = globals()[className]
        try:
           if issubclass(value, FileSystemType):
               if value.supported:
                   if partedKeys:
                       if value.partedFileSystemName is not None:
                           fsTable[value.partedFileSystemName] = value
                   else:
                       if value.name is not None:
                           fsTable[value.name] = value
                   # Add the GPT entry as well ..
                   # XXX: There could potentially be conflicts, but there
                   # aren't right now.
                   if value.canBeGpt and gptKeys:
                       if value.gptName in fsTable:
                           log.debug("Found overlap in fsTable: '%s' .. overriding '%s' with '%s'."
                                     % ((value.gptName), str(fsTable[value.gptName]), str(value)))
                       fsTable[value.gptName] = value
        except TypeError:
            continue

    return fsTable

if __name__ == "__main__":
    import doctest
    doctest.testmod()

    fstypes = getSupportedFileSystems()

    print(list(fstypes.keys()))

