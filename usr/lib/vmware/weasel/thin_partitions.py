'''
ESXi must contain the following partitions:

==== MSDOS ====
Boot:
    Partition: 4
    Start Sector: 32
    End Sector: 524287
    File System: 0x04

Extended Partition:
    Partition: 1
    Start Sector: 524288
    End Sector: 5529599
    File System: 0x05

    Bootbank 1:
        Partition: 5
        Start Sector: 524320
        End Sector: 2621439
        File System: 0x06

    Bootbank 2:
        Partition: 6
        Start Sector: 2621472
        End Sector: 4718591
        File System: 0x06

    Vmkcore:
        Partition: 7
        Start Sector: 4718624
        End Sector: 4943871
        File System: 0xFC

    Locker:
        Partition: 8
        Start Sector: 4943904
        End Sector: 5529599
        File System: 0x06

Scratch (only Thin):
    Partition: 2
    Start Sector: 5529600
    End Sector: 19161087 (nominally)
    File System: 0x06

VMFS (only Thin):
    Partition: 3
    Start Sector: 19161088 (nominally)
    End Sector: [End of disk - 1]
    File System: 0xFB

=== GPT (fresh installs) ===
Boot:
    Partition: 1
    Start Sector: 64
    End Sector: 524287
    GUID: C12A7328-F81F-11D2-BA4B-00A0C93EC93B

Bootbank 1:
    Partition: 5
    Start Sector: 524320
    End Sector: 2621439
    GUID: EBD0A0A2-B9E5-4433-87C0-68B6B72699C7

Bootbank 2:
    Partition: 6
    Start Sector: 2621472
    End Sector: 4718591
    GUID: EBD0A0A2-B9E5-4433-87C0-68B6B72699C7

Vmkcore:
    Partition: 7
    Start Sector: 4718624
    End Sector: 4943871
    GUID: 9D275380-40AD-11DB-BF97-000C2911D1B8

Locker:
    Partition: 8
    Start Sector: 4943904
    End Sector: 5529599
    GUID: EBD0A0A2-B9E5-4433-87C0-68B6B72699C7

Vmkcore (only Thin):
    Partition: 9
    Start Sector: 5529600
    End Sector: 10772479
    GUID: 9D275380-40AD-11DB-BF97-000C2911D1B8

Scratch (only Thin):
    Partition: 2
    Start Sector: 10772480
    End Sector: 19161087
    GUID: EBD0A0A2-B9E5-4433-87C0-68B6B72699C7

VMFS (only Thin):
    Partition: 3
    Start Sector: 19161088
    End Sector: [End of disk - 2 - 32]
    GUID: AA31E02A-400F-11DB-9590-000C2911D1B8
'''

from __future__ import print_function

import os
import time
import shutil
import parted
import vmkctl

from weasel import cache
from weasel import datastore
from weasel import devices
from weasel import fsset
from weasel import userchoices
from weasel import task_progress
from weasel.log import log
from weasel.consts import VMFS6
from weasel.util import (execCommand, units, linearBackoff, loadVmfsModule,
                         loadVfatModule, rescanVmfsVolumes, prompt)
from weasel.exception import HandledError


MIN_THIN_SIZE = units.valueInMebibytesFromUnit(5.2, "GiB")

# From bora/lib/vmkctl/storage/StorageInfoImpl.cpp:
# #define MIN_SCRATCH_PARTITION_SIZE  (4000000000ULL)
SIZE_KiB = (1024.0)
MIN_SCRATCH_SIZE_IN_KiB = (4000000000 / SIZE_KiB)
MIN_SCRATCH_SIZE = units.valueInMebibytesFromUnit(MIN_SCRATCH_SIZE_IN_KiB, "KiB")
# 10 MiB for fudgefactor.


MIN_EMBEDDED_SIZE = units.getValueInMebibytesFromSectors(1843200) + 10


# New minimum size for the extended layout.
# Note: 7.7 GiB just happens to be small enough to fit on 8GB memory sticks,
# which ends up working quite well in order to place the larger core dump
# partition.

# By design, the minimum VMFS6 volume metadata size is 1.5 GB and we should account
# for (VMFS6 metadata size + user required space) while choosing the VMFS partition size
# for the device to be used to format a VMFS6 volume. So we change the installer
# minimum size from 7.7 G to 8.5 G for the extended layout to created.

MIN_EXTENDED_THIN_SIZE = units.valueInMebibytesFromUnit(8.5, "GiB")

VMFS_LOCATION_EXTENDED = 15472640 # in sectors

VMFS_PART_NUM = '3'

# Got this number from `fdisk -u -l` after the binary blob is dd'ed.
#EXPECTED_END_OF_BOOTBANKS = 5529599

# SCRATCH SIZE is 4GiB - 1MiB
SCRATCH_SIZE = (1024 * 1024 * 1024 * 4) - (1024 * 1024 * 1) # in bytes
# There are 512 bytes per block
SCRATCH_SIZE /= 512 # in blocks

PARTEDUTIL_BIN = '/sbin/partedUtil'

PARTEDUTIL_GETINFO = 'getptbl'
PARTEDUTIL_SETPART = 'setptbl'
PARTEDUTIL_MKLABEL = 'mklabel'


MSDOS_MIN_PARTS = ' '.join(['msdos',
    '"4 32 8191 4 128"',
    '"1 8192 1843199 5 0"',
    '"5 8224 520191 6 0"',
    '"6 520224 1032191 6 0"',
    '"7 1032224 1257471 252 0"',
    '"8 1257504 1843199 6 0"',
])

MSDOS_SCRATCH = '"2 1843200 %d 6 0"'

MSDOS_VMFS = '"3 %d %d 251 0"'

GPT_MIN_PARTS = ' '.join(['gpt',
    '"1 64 8191 C12A7328F81F11D2BA4B00A0C93EC93B 128"',
    '"5 8224 520191 EBD0A0A2B9E5443387C068B6B72699C7 0"',
    '"6 520224 1032191 EBD0A0A2B9E5443387C068B6B72699C7 0"',
    '"7 1032224 1257471 9D27538040AD11DBBF97000C2911D1B8 0"',
    '"8 1257504 1843199 EBD0A0A2B9E5443387C068B6B72699C7 0"',
])


GPT_SCRATCH = '"2 1843200 %d EBD0A0A2B9E5443387C068B6B72699C7 0"'

GPT_VMFS = '"3 %d %d AA31E02A400F11DB9590000C2911D1B8 0"'

GPT_EXTENDED_MIN_PARTS = ' '.join(['gpt',
    '"1 64 8191 C12A7328F81F11D2BA4B00A0C93EC93B 128"',
    '"5 8224 520191 EBD0A0A2B9E5443387C068B6B72699C7 0"',
    '"6 520224 1032191 EBD0A0A2B9E5443387C068B6B72699C7 0"',
    '"7 1032224 1257471 9D27538040AD11DBBF97000C2911D1B8 0"',
    '"8 1257504 1843199 EBD0A0A2B9E5443387C068B6B72699C7 0"',
    '"9 1843200 7086079 9D27538040AD11DBBF97000C2911D1B8 0"',
])


GPT_EXTENDED_MIN_PARTS_SIZE = units.valueInMebibytesFromUnit(3.4, "GiB")

GPT_EXTENDED_SCRATCH = '"2 7086080 %d EBD0A0A2B9E5443387C068B6B72699C7 0"'

GPT_EXTENDED_VMFS = '"3 %d %d AA31E02A400F11DB9590000C2911D1B8 0"'


# PART_TYPES is used for only for upgrade/preserve.
PART_TYPES = {'msdos': [MSDOS_MIN_PARTS, MSDOS_SCRATCH, MSDOS_VMFS],
              'gpt': [GPT_MIN_PARTS, GPT_SCRATCH, GPT_VMFS],
             }

# PART_EXTENDED_LAYOUT is used only for fresh installs (with overwrite if applicable).
PART_EXTENDED_LAYOUT = [
        GPT_EXTENDED_MIN_PARTS,
        GPT_EXTENDED_SCRATCH,
        GPT_EXTENDED_VMFS,
]

VMKFSTOOLS_BIN = '/sbin/vmkfstools'

TASKNAME_PART = 'Partitioning'
TASKDESC_PART = 'Partitioning disk for ESXi'

# -----------------------------------------------------------------------------
def getDiskInfo(diskPath):
    '''diskPath should be /dev/disks/mpx...'''
    cmd = ' '.join([PARTEDUTIL_BIN, PARTEDUTIL_GETINFO, diskPath])

    rc, stdout, stderr = execCommand(cmd)

    if rc:
        raise HandledError("partedUtil failed with message: %s." % stderr)

    output = stdout.splitlines()

    partType = output[0]
    diskGeom = output[1].split(' ')
    parts = output[2:]

    return partType, diskGeom, parts

# -----------------------------------------------------------------------------
def formatVmfsFilesystems(diskPath, diskFormatType, vmfsPart, forcedName=None):
    """
    forcedName
        Nome ... vmfs partiion does not exist.
        False .. Use default volume name.
        else ... Use 'forcedName' for volume name.
    """
    takenNames = []

    @linearBackoff()
    def tryFormatDevice(path):
        fstype.formatDevice(path)
        log.info("VMFS partition formatted successfully.")

    for device in userchoices.getPhysicalPartitionRequestsDevices():
        requests = userchoices.getPhysicalPartitionRequests(device)
        for req in requests:
            if isinstance(req.fsType, fsset.vmfsFileSystem):
                takenNames.append(req.fsType.volumeName)

    @linearBackoff(tries=3)
    def tryMount(vmfsUuid):
        # Check if the path exists before trying to mount it.
        if os.path.exists(os.path.join('/vmfs/volumes', vmfsUuid)):
            log.debug("It looks like '%s' is mounted..." % vmfsUuid)
            return

        cmd = "localcli storage filesystem mount -u '%s'" % vmfsUuid
        rc, stdout, stderr = execCommand(cmd)
        if rc:
            raise HandledError("Failed to mount '%s': %s" % (vmfsUuid, stderr))
        log.info("/vmfs/volumes/%s mounted successfully." % vmfsUuid)

    # Actually format the partition if it doesn't exist or it exists and we're
    # not trying to preserve it.
    if forcedName is None or not userchoices.getPreserveVmfs():
        loadVmfsModule()
        vmfsPartPath = diskPath + ':' + VMFS_PART_NUM

        if forcedName:
            partitionName = forcedName
        else:
            partitionName = fsset.findVmfsVolumeName(takenNames)

        log.info("Disk is going to be partitioned with VMFS6")
        fstype = fsset.vmfs6FileSystem(partitionName)

        tryFormatDevice(vmfsPartPath)
    else:
       # The VMFS partitions on the disk are unmounted persistently,
       # even in case the user wants to preserveVMFS. In this case,
       # we need to mount that old VMFS partition back.
       if vmfsPart and vmfsPart.uuid:
          log.info("Mount preserved vmfs partition %s" % (vmfsPart.uuid))
          tryMount(vmfsPart.uuid)

# -----------------------------------------------------------------------------
def getEligibleDisks(disks=None):
    retval = []

    if disks == None:
       disks = devices.DiskSet().values()

    for disk in disks:

        log.debug("Checking if disk %s is eligible for vmfs." % disk)

        if disk.getSizeInMebibytes() < MIN_EMBEDDED_SIZE:
            log.debug("  %s is too small." % disk)
            continue

        retval.append(disk)

    return retval

# -----------------------------------------------------------------------------
def unmountVmfsVolume(diskPath, rescan=False, persistUnmount=False):
    '''Unmounts the VMFS volume on that disk's path if any are mounted, and
    returns the name of the VMFS volume that we umounted.
    '''
    @linearBackoff(tries=10)
    def tryUnmount(vmfsUuid):
        cmd = "localcli storage filesystem unmount -n -u '%s'" % vmfsUuid
        if persistUnmount:
           log.debug("Unnmounting volume '%s' persistently" % vmfsUuid)
           cmd = "localcli storage filesystem unmount -u '%s'" % vmfsUuid

        # Check if the path exists before trying to unmount it.
        if not os.path.exists(os.path.join('/vmfs/volumes', vmfsUuid)):
            log.debug("It doesn't look like '%s' is mounted..." % vmfsUuid)
            return

        rc, stdout, stderr = execCommand(cmd)
        if rc:
            raise HandledError("Failed to unmount '%s': %s" % (vmfsUuid, stderr))
        else:
            return

    # Check if we need to do something with the VMFS volume...
    baseName = os.path.basename(diskPath)
    datastores = datastore.DatastoreSet(rescan)
    vmfsParts = datastores.getEntriesByDriveName(baseName)

    # If so, we want to unmount it and only it.
    if vmfsParts:
        # There can only be ONE .. otherwise something's wrong.
        assert len(vmfsParts) == 1
        vmfsPart = vmfsParts[0]

        # We'll try ten times to unmount it.
        vmfsUuid = vmfsPart.uuid
        tryUnmount(vmfsUuid)

        # Return back a partition name for if we recreate it
        return vmfsPart
    else:
        return None

# -----------------------------------------------------------------------------
def unclaimFromVsanDiskGroup(diskPath):
    '''Unclaims and removes disks from a vSAN disk group.

       Note: If there is more than one magnetic disk (MD) in a vSAN disk group,
       then the removal of the disk from the group will succeed.  In the case
       where there is just one MD with the SSD, then both the SSD and the MD
       will need to be removed from the vSAN disk group.
    '''
    diskName = os.path.basename(diskPath)

    diskSet = devices.DiskSet()
    diskDev = diskSet[diskName]

    # Find disks in the vSAN disk group of the disk we want to release.
    # XXX: Can probably be moved to a vsan.py as a utility function.
    vsanUUID = diskDev.vsanClaimed
    assert vsanUUID
    vsanDiskGroup = [x for x in diskSet.values() if x.vsanClaimed == vsanUUID]

    ssdCmd = "localcli vsan storage remove -s %s"
    mdCmd = "localcli vsan storage remove -d %s"
    ssdMntCmd = "localcli vsan storage diskgroup mount -s %s"

    if len(vsanDiskGroup) > 2:
        # If >2, then we can safely remove the disk, whether it's SSD or MD
        if diskDev.isSSD:
            cmd = ssdCmd
        else:
            cmd = mdCmd

        ssdDisk = list(filter(lambda x: x.isSSD, vsanDiskGroup))[0]
        rc, stdout, stderr = execCommand(ssdMntCmd % ssdDisk.name)
        if rc:
            log.warning("Failed to mount vSAN disk group '%s': %s" %
                        (vsanDiskGroup, stderr))

        rc, stdout, stderr = execCommand(cmd % diskName)
        if rc:
            raise HandledError("Failed to unclaim vSAN disk '%s': %s" %
                    (diskName, stderr))
    else:
        # If <2, then we need to find the corresponding SSD and remove that.
        # Doing so will also remove any MDs associated with that SSD.
        # A vSAN disk group must have only *one* SSD disk.
        ssdDisk = list(filter(lambda x: x.isSSD, vsanDiskGroup))[0]
        rc, stdout, stderr = execCommand(ssdMntCmd % ssdDisk.name)
        if rc:
            log.warning("Failed to mount vSAN disk group '%s': %s" %
                        (vsanDiskGroup, stderr))

        rc, stdout, stderr = execCommand(ssdCmd % ssdDisk.name)
        if rc:
            raise HandledError("Failed to unclaim vSAN disk group '%s': %s" %
                    (vsanDiskGroup, stderr))

# -----------------------------------------------------------------------------
def prepareVisorVolumes(diskPath):
    '''diskPath should be a path like '/dev/disks/mpx.vmhba1:C0:T0:L0'
    '''
    log.info('Preparing Visor volumes on disk %s...' % diskPath)
    loadVfatModule()

    cmd = 'vmkfstools -C vfat'

    # bootbank1 (5), bootbank2 (6)
    hvVols = {'5': True,
              '6': True,
             }

    diskSet = devices.DiskSet()
    disk = diskSet[os.path.basename(diskPath)]

    # If we're doing a VUM upgrade from ESXi, don't reformat locker (8) because it
    # has our tools.  (We check for the negation instead)
    if not userchoices.getVumEnvironment() \
       or not disk.containsEsx.esxi:
        hvVols['8'] = True

    if userchoices.getUpgrade() and disk.containsEsx.esxi:
        log.info('Upgrading from ESXi: checking for previous bootbanks before reformatting')
        # If we're upgrading an ESXi system, we only want to format the bootbank
        # we're going to write to.
        device = os.path.basename(diskPath)

        rescanVmfsVolumes()
        bootbanks = cache.getBootbankParts(device)
        wipeBootbank = None

        if len(bootbanks) == 1:
            log.debug("Warning: Only one bootbank partittion found.")
        else:
            cacher = cache.Cache(device)
            wipeBootbank = cacher.bootbankPartId

        if wipeBootbank == 5:
            hvVols['6'] = False
        elif wipeBootbank == 6:
            hvVols['5'] = False

    for volNum, createVol in hvVols.items():
        if not createVol:
           continue
        hvVolPath = diskPath + ':' + volNum
        prepVolCmd = ' '.join([cmd, hvVolPath])
        rc, stdout, stderr = execCommand(prepVolCmd)
        if rc:
            raise HandledError('vmkfstools failed with message: %s.' % stderr)

        task_progress.taskProgress(TASKNAME_PART, 1)

# -----------------------------------------------------------------------------
def isScratchPartition(number, vfatPartitions):

    # Search for matching partitionId in list of vfatPartitions, warn if small
    for partition in vfatPartitions:
        if partition.partitionId == number:
            length = partition.getLength()
            if (units.getValueInMebibytesFromSectors(length) < MIN_SCRATCH_SIZE):
                log.warning("Presumed scratch partition %d has size %d MiB",
                            number, units.getValueInMebibytesFromSectors(length))
            return True

    return False

# -----------------------------------------------------------------------------
def formatScratchVolume(diskPath, partitionType, vfatPartitions):
    # In install image scratch partition is at 2, vmfs at 3 and coredump at 9
    # In dd-image coredump partition is at 2, scratch can be at 3 and never vmfs
    # In nimbus pxeboot coredump partition is at 2 and never scratch nor vmfs(?)
    # Lastly, just for fun, we can only reliably find vfat partitions on msdos
    # but as dd-image is always msdos another partition type means install image
    if partitionType != 'msdos':
        scratchVolPath = diskPath + ':2'
    elif isScratchPartition(2, vfatPartitions):
        log.debug("Found a scratch partition at 2, formatting it.")
        scratchVolPath = diskPath + ':2'
    elif isScratchPartition(3, vfatPartitions):
        log.debug("Found a scratch partition at 3, formatting it.")
        scratchVolPath = diskPath + ':3'
    else:
        log.debug("Found no scratch partition.")
        return

    if os.path.exists(scratchVolPath):
        if partitionType != 'msdos':
            log.debug("Found a scratch partition, formatting it.")
        cmd = 'vmkfstools -C vfat %s' % scratchVolPath
        rc, stdout, stderr = execCommand(cmd)
        if rc:
            raise HandledError('vmkfstools failed with message: %s.' % stderr)

# -----------------------------------------------------------------------------
def installAction(persistUnmount=False):
    '''partition the disk (via partedUtil) and format (some of) the new partitions
    Installs will make GPT tables unless specified otherwise through the boot cmdline.
    Upgrades will use the same partition table type that already exists on the disk.
    '''
    # Make sure we sync up before we try to modify those lower bits of the disk.
    rescanVmfsVolumes(automount=False)

    diskName = userchoices.getEsxPhysicalDevice()

    diskSet = devices.DiskSet()
    disk = diskSet[diskName]
    diskPath = disk.consoleDevicePath
    partSet = disk.getPartitionSet()

    vmfsParts = len(partSet.getPartitionsOfType(fsset.vmfsFileSystem))
    vfatParts = partSet.getPartitionsOfType(fsset.FAT16FileSystem)

    # We only want to repartition when we are installing
    if userchoices.getInstall():
        partType, diskGeom, parts = getDiskInfo(diskPath)
        lastSector = int(diskGeom[3])

        # If it's a fresh install, we give it GPT (unless the user specified
        # otherwise), otherwise we keep whatever scheme was used previously.
        if userchoices.getInstall() and (not userchoices.getPreserveVmfs() or
                                         partType == 'unknown'):
            log.info('Fresh install.  Using GPT')
            # If the disk is large enough to support the new, larger,
            # vmkcore partition, then we'll use the new layout.  Otherwise,
            # we'll go with the original plan.
            if lastSector > units.getValueInSectorsFromMebibytes(MIN_EXTENDED_THIN_SIZE):
                log.info("  Using the extended partition layout.")
                partTable = PART_EXTENDED_LAYOUT
                # XXX: Bad practice!
                userchoices.setLargerCoreDumpPart(True)
            # Create larger coredump partition for usb drives >= 4 GiB.
            # For usb drives we do not create scratch or VMFS partitions.
            # Hence the minimum size layout (with a 2.5 GiB coredump
            # partition) cuts down to ~3.4 GiB.

            elif not disk.supportsVmfs and \
               lastSector > units.getValueInSectorsFromMebibytes(GPT_EXTENDED_MIN_PARTS_SIZE):
                log.info("  Using the extended, minimum partition layout.")
                partTable = [PART_EXTENDED_LAYOUT[0]]
                userchoices.setLargerCoreDumpPart(True)
            else:
                log.info("  Using the standard, minimum partition layout.")
                partTable = PART_TYPES['gpt']
            # Force the partType since we're installing.
            partType = 'gpt'
        else:
            log.info('Either upgrade or preserve set.  Using previous partition '
                     'table type: %s' % partType)
            # Preserve the previous type.
            partTable = PART_TYPES[partType]

            # If the partition type is GPT, we need to make sure that we keep
            # the larger core dump partition is one was made.
            # With the new extended layout, the location of the VMFS partition
            # is pretty much locked in so we can safely rely on that to see if
            # we're preserving from the extended layout.  With this, if somehow
            # the VMFS partition started past our extended layout location and
            # we didn't have the larger coredump, we'll make one.
            if partType == 'gpt' \
               and userchoices.getPreserveVmfs() \
               and disk.vmfsLocation \
               and disk.vmfsLocation[0] >= VMFS_LOCATION_EXTENDED:
                log.debug("  Preserve VMFS set with the VMFS partition start"
                          " location fitting in our extended layout.")
                partTable = PART_EXTENDED_LAYOUT
                # XXX: Bad practice!
                userchoices.setLargerCoreDumpPart(True)

        # If it's a USB device, we don't care about the preserveVmfs flag.
        # We're going to use 'supportsVmfs' for telling us off-hand if it's a
        # USB device.
        if disk.supportsVmfs \
           and lastSector > units.getValueInSectorsFromMebibytes(MIN_THIN_SIZE) \
           and (vmfsParts or userchoices.getInstall()):
            # Looks into the defined list for the scratch partition and where it
            # starts and adds SCRATCH_SIZE.  Subtracts one for the inclusive
            # sector.
            normalEndOfScratch = int(partTable[1].split()[1]) + SCRATCH_SIZE - 1

            if userchoices.getCreateVmfsOnDisk():
                if userchoices.getPreserveVmfs() and disk.vmfsLocation:
                    startOfVmfs, endOfVmfs, ver = disk.vmfsLocation
                    log.info('Preserving VMFS %s' % str((startOfVmfs, endOfVmfs, ver)))
                else:
                    startOfVmfs = normalEndOfScratch + 1
                    if partType == 'msdos':
                        endOfVmfs = lastSector - 1
                    elif partType == 'gpt':
                        # Offset to leave room for secondary MBR
                        endOfVmfs = lastSector - 32 - 2
                    else:
                        raise HandledError("Unrecognized partition table type: %s."
                                           % partType)

                    if disk.diskFormatType == vmkctl.DiskLun.LUN_FORMAT_TYPE_4K or \
                        disk.diskFormatType == vmkctl.DiskLun.LUN_FORMAT_TYPE_4Kn_SW_EMULATED:
                       # Algorithm to ensure the value of endofVmfs is 4k aligned.
                       # (sector // 8 ) * 8 is to get the 4k aligned end sector,
                       # minus 1 is to get its sector sequence.
                       endOfVmfs = (endOfVmfs // 8) * 8 - 1

                    log.info('Creating a new VMFS: %s'
                             % str((startOfVmfs, endOfVmfs)))

                # Check if our scratch is too big
                if startOfVmfs > normalEndOfScratch:
                    endOfScratch = normalEndOfScratch
                else:
                    endOfScratch = startOfVmfs - 1


                partTable = ' '.join(partTable)
                partTable = partTable % (endOfScratch, startOfVmfs, endOfVmfs)
                makeVmfs = True
            # else, the user said to not make a vmfs partition on the disk.
            else:
                log.info("User chose to not make VMFS on this disk.")
                # This is a very special case, we don't make a VMFS partition,
                # and we don't extend the scratch partition to the end of the disk
                endOfScratch = normalEndOfScratch

                # Only get the first two, minimum partitions and the scratch.
                partTable = ' '.join(partTable[0:2])
                partTable = partTable % endOfScratch
                makeVmfs = False
        else:
            # It's a USB device, so check if the disk is large enough and set to
            # only make the required partitions.
            # Note: We don't need to check here whether we're using the larger
            # layout or not because we only select the larger layout if it fits
            # onto the device.  The check, being for 8GB works well since USB
            # sticks come in flavors that are powers of 2.  The layout wouldn't
            # fit on any smaller device anyways.
            log.info('Checking USB device...')
            if lastSector < units.getValueInSectorsFromMebibytes(MIN_EMBEDDED_SIZE):
                raise HandledError("Drive %s is not large enough." % diskPath)

            partTable = partTable[0]
            makeVmfs = False

        rescanVmfsVolumes(automount=False)

        # We have to remove any vSAN on it before we continue.
        # Note: Removing any vSAN on it clears out its partition table.
        forcedName = None
        vmfsPart = None
        if disk.vsanClaimed:
            if not userchoices.getPreserveVsan():
                unclaimFromVsanDiskGroup(diskPath)
            else:
                raise HandledError("Drive %s is claimed by vSAN and "
                                   "--overwritevsan was not set" % diskPath)
        else:
            # If we want to make a VMFS partition, we should unmount any partitions
            # already on that disk, if any already exist, so that we can partition.
            if makeVmfs:
                vmfsPart = unmountVmfsVolume(diskPath, False, persistUnmount)
                if vmfsPart and vmfsPart.name is not None:
                    # If we're going to reformat it, use default volume name.
                    forcedName = False
                else:
                    log.debug("No existing VMFS partitions found on disk -- %s", diskPath)
                    if userchoices.getPreserveVmfs():
                        log.warning(
                            "--preservevmfs was specified, but no existing "
                            "VMFS volume was found; a new volume will be formatted")

        cmd = ' '.join([PARTEDUTIL_BIN, PARTEDUTIL_SETPART, diskPath, partTable])

        rc, stdout, stderr = execCommand(cmd)
        if rc:
            raise HandledError("Command '%s' exited with status %d." % (cmd, rc),
                               stderr)

        task_progress.taskProgress(TASKNAME_PART, 5, 'Partitioned %s' % diskName)

        prepareVisorVolumes(diskPath)

        if makeVmfs:
            # We've now repartitioned and it's possible that there may be some
            # VMFS bits still in that same location (i.e., the magicblock), so
            # we need to unmount it since it's possible that it got automounted.
            unmountVmfsVolume(diskPath, True, persistUnmount)
            # Since we just accessed this disk due to rescanning, let's wait for
            # some time so that formatting the disk does not detect that the
            # disk was recently used and error out EBUSY.
            time.sleep(6)
            formatVmfsFilesystems(diskPath, disk.diskFormatType, vmfsPart,
                                  forcedName)
            task_progress.taskProgress(TASKNAME_PART, 1)

    if userchoices.getUpgrade() and disk.containsEsx.esxi:
        cacher = cache.Cache(os.path.basename(diskPath))

        # Get the partition type for upgrades to distinguish MBR from GPT
        partType, diskGeom, parts = getDiskInfo(diskPath)

        # VUM switches over to clobber the bootbank we booted from.  Check if
        # we're going through VUM and set that bootbank.
        if userchoices.getSaveBootbankUUID():
            stateBootbank = cacher.bootbankPath
        else:
            stateBootbank = cacher.altbootbankPath

        if os.path.exists('/tmp/state.tgz') \
           and not os.path.exists(os.path.join(stateBootbank, 'state.tgz')):
            shutil.copy('/tmp/state.tgz', stateBootbank)
            log.debug("Restoring state.tgz to %s." % stateBootbank)
        elif os.path.exists('/tmp/local.tgz') \
           and not os.path.exists(os.path.join(stateBootbank, 'local.tgz')):
            shutil.copy('/tmp/local.tgz', stateBootbank)
            log.debug("Restoring local.tgz to %s." % stateBootbank)
        else:
            log.warning("Didn't find a state/local to restore from /tmp")

    # Guard against some legacy code path that doesn't define partType
    try:
        partType
    except NameError:
        partType = 'unknown'

    # We always want to flush out scratch if it exists.
    formatScratchVolume(diskPath, partType, vfatParts)

    # Zero out the bits in vmkcore.
    ddCmd = 'dd if=/dev/zero of=%s conv=notrunc bs=16384 count=7039' % (diskPath + ':7')
    # dd writes the number of input and output blocks to standard error on completion.
    rc, stdout, stderr = execCommand(ddCmd)

    task_progress.taskProgress(TASKNAME_PART, 2, 'Formatted necessary Visor partitions')

# -----------------------------------------------------------------------------
if __name__ == '__main__':
    print('\nWARNING\n')
    result = prompt('This will fdisk mpx.vmhba1:C0:T0:L0. Are you sure? ')
    if result.lower() == 'y':
        userchoices.setEsxPhysicalDevice('mpx.vmhba1:C0:T0:L0')
        installAction()

