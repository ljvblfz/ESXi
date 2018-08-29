from util import execWithLog
import glob
import os
from weasel import userchoices # always import via weasel.
from exception import HandledError

import vmkctl

from weasel.log import log

VMFS_CDROMDEV_PATH = '/vmfs/devices/cdrom'
CDROM_PATH = '/vmfs/volumes/%s'
# DDIMAGE_PATH = 'IMAGEDD.BZ2'

class CdromMountError(HandledError): pass

ISOMODULE_LOADED = False

def _loadModule():
    global ISOMODULE_LOADED

    si = vmkctl.SystemInfoImpl()

    if ISOMODULE_LOADED or \
       'iso9660' in [module.get().GetName() for module in si.GetLoadedModules()]:
        log.warn('Attempted to load iso9660 module twice')
        return

    try:
        module = vmkctl.ModuleImpl('iso9660')
        module.Load()
    except vmkctl.HostCtlException:
        log.error('Couldn''t load iso9660 module')
        raise
    else:
        log.info('Loaded iso9660 module')
        ISOMODULE_LOADED = True

def mount(dev):
    _loadModule()

    # XXX - this should be replaced by something more permanent

    args = [ '/sbin/vsish', '-e', 'set', '/vmkModules/iso9660/mount',
             os.path.basename(dev) ]

    try:
        execWithLog(args[0], args, raiseException=True)
    except Exception as e:
        log.info("Didn't find a CD-ROM on %s" % dev)
        return None

    return CDROM_PATH % os.path.basename(dev)

def umount(dev):
    # XXX - this should be replaced by something more permanent

    args = [ '/sbin/vsish', '-e', 'set', '/vmkModules/iso9660/umount',
             os.path.basename(dev) ]

    try:
        execWithLog(args[0], args, raiseException=True)
    except Exception as e:
        log.info("Didn't find a CD-ROM on %s" % dev)
        return None

    return CDROM_PATH % os.path.basename(dev)

# def mount_media():
#
#     cdromDevices = cdromDevicePaths()
#
#     if len(cdromDevices) < 1:
#         raise CdromMountError("No CD-ROM device found")
#
#     cdromDevices.sort()
#
#     foundImage = False
#
#     for dev in cdromDevices:
#         mountedPath = mount(dev)
#         if mountedPath == None:
#             continue
#
#         imagePath = os.path.join(mountedPath, DDIMAGE_PATH)
#
#         if os.path.exists(imagePath):
#             foundImage = True
#             break
#
#     if not foundImage:
#         raise CdromMountError("Could not find the install image on CD-ROM devices")
#
#     mediaLocation = 'file://%s' % imagePath
#
#     return mediaLocation

def cdromDevicePaths():
    cdromPaths = []

    entries = os.listdir(VMFS_CDROMDEV_PATH)
    for entry in entries:
        cdromPath = os.path.join(VMFS_CDROMDEV_PATH, entry)
        if os.path.isfile(cdromPath) and not os.path.islink(cdromPath):
            cdromPaths.append(cdromPath)
    return cdromPaths

def ejectCdroms():
    paths = cdromDevicePaths()
    if not paths:
        log.warn('Eject attempted, but no CD-ROM devices found')
        return

    for cdromPath in paths:
        cmd = ['/bin/eject', cdromPath]
        execWithLog(cmd[0], cmd, timeoutInSecs=10)

