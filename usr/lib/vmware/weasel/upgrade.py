# Doctests for this file are in 'tests/upgrade.doctest'

import os
import parted
import vmkctl
from weasel import devices, \
                   fsset, \
                   cache, \
                   util

from weasel.exception import HandledError
from weasel.log import log
from weasel.util import isNOVA, isBootbankRecent, setAutomounted

DISK_DEV_PREFIX = '/vmfs/devices/disks/'
TMP_DIR = '/tmp/esx_upgrade/'
MINIMUM_VMFS_START_SECTOR = 1843200 # See functional spec.
VALID_VMFS_VERSIONS = ['vmfs3', 'vmfs5', 'vmfs6']

ESX_CONF_PATH = 'etc/vmware/esx.conf'

class UpgradeError(HandledError): pass

def execute_once(f):
    def wrapper(*args, **kwargs):
      if not wrapper.has_done:
         wrapper.has_done = True
         return f(*args, **kwargs)
    wrapper.has_done = False
    return wrapper


@execute_once
def LoadRescanMount():
    log.info("Load vfat, rescanVmfs and automount all at once.")
    util.loadVfatModule()
    # Force to automount storage filesystem for only once.
    setAutomounted(False)
    util.rescanVmfsVolumes()


def findVisorPartitions(diskDevName):
    """
    Find partitions 5 and 6, check if they are vfat, and check what sizes they
    are while we're at it .. so we can figure out the version of ESXi.  Requires
    that ESXi with a valid state (bootstate=0) exist in one of the bootbanks.
    """
    LoadRescanMount()

    bootbankParts = cache.getBootbankParts(diskDevName)

    esxVar = devices.ESXVariant()

    # XXX: It's likely this can change incase we would need to get rid of the
    # second bootbank to make more room for the first one... so just be careful.
    if len(bootbankParts) != 2:
        return esxVar

    # Now that we've made it here, lets make sure they have a boot.cfg for
    # whichever is the active bootbank, and for its size.
    bootbankInfo = []
    for part in bootbankParts:
        # According to spec, there should be a boot.cfg in both bootbanks ..
        # otherwise it's not ESXi.
        bootCfgPath = os.path.join(part.GetConsolePath(), 'boot.cfg')
        if not os.path.exists(bootCfgPath):
            return esxVar
        else:
            bootbankInfo.append((part, cache.parseBootConfig(bootCfgPath)))

    # Now that we've gotten this far, we at least know that we have ESXi.
    esxVar.esxi = True

    # Lets find the one with the largest updated value.
    updated = -1
    usedBootbank = None
    for info in bootbankInfo:
        if info[1].get('bootstate') != 0:
            continue

        curUpdated = info[1].get('updated', -1)
        if curUpdated > updated:
            usedBootbank = info
            updated = curUpdated

    if not usedBootbank:
        log.warn("Neither of the bootbanks found on %s have a valid state: %s."
                 " Not attempting version detection." % (diskDevName, bootbankInfo))
        return esxVar

    esxVar.pathToActiveBootbank = usedBootbank[0].GetConsolePath()
    if isNOVA():
        esxVar.bootbankIsRecent = isBootbankRecent(esxVar.pathToActiveBootbank)
        if not esxVar.bootbankIsRecent:
            log.warn("The active bootbank found on %s does not have a "
                     "valid state: %s." % (diskDevName,
                                           esxVar.pathToActiveBootbank))

    # Now that we're here .. we'll first use the bootbank size as the source of
    # info, then we'll look into the boot.cfg for the version.
    volSize = usedBootbank[0].GetHeadPartition().get().GetSize()
    esxVar.version = tuple(map(int,usedBootbank[1]['version'].split('.')))

    return esxVar


def findVmfsPartition(diskDevName):
    """
    Checks the given disk for a VMFS partition and returns a tuple of the
    start sector, end sector, and vmfs version.  Returns None if we can't find it.
    """

    diskSet = devices.DiskSet()
    disk = diskSet[diskDevName]
    partSet = disk.getPartitionSet()


    vmfsParts = partSet.getPartitionsOfType(fsset.vmfsFileSystem)

    if not vmfsParts:
        return None

    if len(vmfsParts) > 1:
        raise HandledError("Found more than one VMFS partition on disk '%s'."
                           % diskDevName)

    vmfsPart = vmfsParts[0]

    return (vmfsPart.startSector, vmfsPart.endSector, vmfsPart.fsType.name)


def cleanupFileDevices(diskDev):
    """
    Removes all partition filedevices.  We don't need to worry about the device
    filedevice since we mount the partition directly (it's exposed to us).
    """
    partSet = diskDev.getPartitionSet()
    for part in partSet:
        try:
            part.removeDeviceLinkedFile()
        except HandledError:
            pass


def checkForPreserveVmfs(diskDev):
    """
    Modifies the diskDev argument (of type devices.DiskDev).
    diskDev.vmfsLocation is set to:
     a triplet if we found one and we can save it,
     remains None if we didn't find one.
    """
    diskDev.vmfsLocation = findVmfsPartition(diskDev.name)
    if diskDev.vmfsLocation is not None:
        if diskDev.vmfsLocation[0] < MINIMUM_VMFS_START_SECTOR:
            log.debug("  Found vmfs, but cannot save it: "
                      "VMFS starts at sector: %s" % diskDev.vmfsLocation[0])
            diskDev.canSaveVmfs = False
        else:
            diskDev.canSaveVmfs = True


def checkForPreviousInstalls(diskDev, forceRecheck=False):
    """
    Scans the given weasel disk device for any installs of any ESX.
    """
    if not diskDev.containsEsx.scanned or forceRecheck:
        log.info("Scanning %s for any installs ..." % diskDev.name)
        visorType = findVisorPartitions(diskDev.name)
        if visorType:
            log.info("  Found ESXi on %s: %s." % (diskDev.name, visorType))
            diskDev.containsEsx = visorType

            # Also find out if the ESXi partition layout is the new one
            # from 6.6 and later, this will help to determine if install
            # can preserveVmfs. By default we assume it is the old one.
            partSet = diskDev.getPartitionSet()
            for part in partSet.partitions:
                # We use start sector of bootbank (partition 5) to tell
                # if the layout is new. New one is at 524320
                if part.getId() == 5:
                    if part.getStartSector() == 524320:
                        diskDev.containsEsx.newPartLayout = True
                    break
        else:
            log.info("  Found nothing on %s." % diskDev.name)

        diskDev.containsEsx.scanned = True
        cleanupFileDevices(diskDev)
        checkForPreserveVmfs(diskDev)
