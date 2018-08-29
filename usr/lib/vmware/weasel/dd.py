#! /usr/bin/env python
'''
write directly (dd) to a storage device
'''
from __future__ import print_function

# Get rid of any calls to visor_cdrom.mount_media() since we don't need the DD image from it anymore.
import os
import sys
import gzip
import hashlib
import struct
import vmkctl

from binascii import hexlify
from weasel import devices
from weasel import userchoices # always import via weasel.
from weasel.thin_partitions import getDiskInfo
from . import task_progress
from . import cache

from weasel.log import log
from weasel.util import rescanVmfsVolumes, linearBackoff, prompt
from .exception import HandledError

from time import time

TASKNAME_WRITELDR = 'WRITE_LOADER'
TASKDESC_WRITELDR = 'Writing syslinux bootloader.'

TASKNAME_WRITEBP = 'WRITE_BOOTPART'
TASKDESC_WRITEBP = 'Writing binary to boot partition.'

TASKNAME_WRITEGUID = 'WRITE_GUID'
TASKDESC_WRITEGUID = 'Writing GUIDs to the bootbanks.'

_bootPartDD = "/bootpart.gz"
_bootPartDD4kn = "/bootpart4kn.gz"

_msdosSyslinuxDD = "/usr/share/syslinux/mbr.bin"
_gptSyslinuxDD = "/usr/share/syslinux/gptmbr.bin"

_syslinuxDD = {'msdos': _msdosSyslinuxDD,
               'gpt': _gptSyslinuxDD,
              }

BOOTPART_NUM = {'msdos': 4,
                'gpt': 1,
               }

MAX_BOOTLOADER_SIZE = 446

class DDError(HandledError): pass

def getLunByName(name):
    '''get a vmkctl disk lun given the mpx style name
    >>> getLunByName('mpx.vmhba1:C0:T0:L0')
    Traceback (most recent call last):
    ...
    DDError: Error (see log for more info):
    Disk mpx.vmhba1:C0:T0:L0 was not found after rescan
    <BLANKLINE>
    >>> getLunByName('vml.0001')
    {'lunType': 0, 'scsiPaths': ...}

    '''
    # call this each time so that we can see any changes made.
    rescanVmfsVolumes()
    # XXX - re-mount the cdrom since Rescanning will unmount it
    # mediaLocation = userchoices.getMediaLocation().get('mediaLocation')
    # if mediaLocation and mediaLocation.startswith('file:'):
    #     visor_cdrom.mount_media()

    luns = [ptr.get() for ptr in vmkctl.StorageInfoImpl().GetDiskLuns()]
    matches = [lun for lun in luns
               if lun.GetConsoleDevice().endswith(name)]
    if not matches:
        raise DDError('Disk %s was not found after rescan' % name)
    return matches[0]


def installActionDDSyslinux():
    diskName = userchoices.getEsxPhysicalDevice()
    installDisk = getLunByName(diskName)
    diskPath = installDisk.GetConsoleDevice()

    partType, diskGeom, parts = getDiskInfo(diskPath)

    syslinuxDD = _syslinuxDD[partType]

    log.debug('Writing %s to disk %s.' % (syslinuxDD, diskPath))

    sourceSize = os.path.getsize(syslinuxDD)

    if sourceSize == 0:
        raise DDError('File %s is empty.  Cannot write to disk' % syslinuxDD)
    elif sourceSize > MAX_BOOTLOADER_SIZE:
        raise DDError('File %s is too large.  Cannot write to disk.' % syslinuxDD)

    task_progress.reviseEstimate(TASKNAME_WRITELDR, sourceSize)
    task_progress.taskProgress(TASKNAME_WRITELDR, 0, 'Writing image')

    # Syslinux needs to fit on the first sector of the disk.
    src = os.open(syslinuxDD, os.O_RDONLY)
    buf = os.read(src, MAX_BOOTLOADER_SIZE)

    written = retryWrites(diskPath, buf)

    log.debug('Wrote %d bytes to disk.' % written)
    task_progress.taskProgress(TASKNAME_WRITELDR, written)

    os.close(src)


def installActionDDBootPart():
    diskName = userchoices.getEsxPhysicalDevice()
    installDisk = getLunByName(diskName)
    diskPath = installDisk.GetConsoleDevice()

    partType, diskGeom, parts = getDiskInfo(diskPath)
    bootPartNum = BOOTPART_NUM[partType]
    bootPartPath = diskPath + ':' + str(bootPartNum)

    diskFormatType = installDisk.GetFormatType()
    bootPartDD = _bootPartDD
    if diskFormatType == vmkctl.DiskLun.LUN_FORMAT_TYPE_4K or \
       diskFormatType == vmkctl.DiskLun.LUN_FORMAT_TYPE_4Kn_SW_EMULATED:
        log.debug("The disk format type is 4K/sector, using bootpart4kn.gz file.")
        bootPartDD = _bootPartDD4kn
    else:
        log.debug("The disk format type is 512/sector, using bootpart.gz file.")

    log.debug('Writing %s to disk %s.' % (bootPartDD, bootPartPath))

    bootSrc = gzip.GzipFile(bootPartDD)
    buf = bootSrc.read()

    written = retryWrites(bootPartPath, buf)

    log.debug('Wrote %d bytes to disk.' % written)
    task_progress.taskProgress(TASKNAME_WRITEBP, 10)


def installActionWriteGUID():
    diskName = userchoices.getEsxPhysicalDevice()

    diskSet = devices.DiskSet()
    weaselDisk = diskSet[diskName]
    thin = not weaselDisk.isUSB

    # If this is set, we're upgrading from VUM; don't nuke the UUIDs
    if userchoices.getSaveBootbankUUID() or \
       (userchoices.getUpgrade() and \
        weaselDisk.containsEsx.esxi):
        log.info("Not writing new UUIDs ...")
        return

    installDisk = getLunByName(diskName)

    parts = [partPtr.get() for partPtr in installDisk.GetPartitions()]

    def partId(part):
        return int(part.GetConsoleDevice().split(':')[-1])

    # 5 and 6 are the identifiers for the first and second bootbanks.
    bootBanks = [part for part in parts if partId(part) in [5, 6]]

    if not bootBanks:
        raise DDError('No boot banks after image was written to disk')
    for part in bootBanks:
        # in order for ESXi to boot up properly, the UUID of the partition
        # must be written to a magic location on each boot bank
        log.info('found bootbank partition %s' % partId(part))
        uuid = generateUUID(partId(part), thin)
        f = os.open(part.GetConsoleDevice(), os.O_RDWR)
        os.lseek(f, 512, os.SEEK_SET)
        log.info('Writing uuid (%s) to partition %s.' % (
            getReadableUUID(uuid), partId(part)))
        os.write(f, uuid)
        os.close(f)
        task_progress.taskProgress(TASKNAME_WRITEGUID)


@linearBackoff()
def retryWrites(destPath, buf):
    try:
        dest = os.open(destPath, os.O_RDWR)
        written = os.write(dest, buf)
    except OSError as msg:
        try:
            # We should try closing just in case.
            os.close(dest)
        except:
            pass
        raise
    else:
        # Success!
        os.close(dest)
        return written

# XXX: Move this elsewhere.
#    remote_files.tidyAction()

# If it's an embedded device, thin should be passed in as False
# Note: We determine if it's an embedded device by whether the device supports
# VMFS or not, which is set by determing if the interface is SCSI_IFACE_TYPE_USB
# (see devices.py:237)
def generateUUID(partition, thin=True):
    UUID_FMT = b'VMWARE FAT16    '

    digester = hashlib.md5()
    digester.update((str(time()) + str(partition)).encode())

    digest = digester.digest()
    # The first nibble of a ThinESX FS UUID should be 7
    if thin:
        firstNibble = 0x7
    else:
        firstNibble = 0xe

    if sys.version_info[0] <=2:
        uuid = "%c%s" % (chr(firstNibble << 4 | ord(digest[0]) & 0xF), digest[1:])
    else:
        uuid = bytes([firstNibble << 4 | digest[0] & 0xF]) + digest[1:]

    return UUID_FMT + uuid


def getReadableUUID(uuid):
    _, uuid1, uuid2, uuid3, uuid4 = struct.unpack("<16sIIH6s", uuid)
    uuidStr = hexlify(uuid4)
    if sys.version_info[0] >= 3:
        uuidStr = uuidStr.decode()
    return "%08x-%08x-%04x-%s" % (uuid1, uuid2, uuid3, uuidStr)


if __name__ == '__main__':
    print('\nWARNING\n')
    result = prompt('This will dd the image to mpx.vmhba1:C0:T0:L0'
                    ' Are you sure? ')
    if result.lower() == 'y':
        userchoices.setInstall(True)
        #url = 'http://172.16.221.2/foo.bz2'
        #url = visor_cdrom.mount_media()
        #userchoices.setMediaLocation(url)
        userchoices.setEsxPhysicalDevice('mpx.vmhba1:C0:T0:L0')
        #installActionGetBinary()
        installActionDDSyslinux()
        installActionDDBootPart()
        installActionWriteGUID()


