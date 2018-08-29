
import os
import glob

from util import execWithLog

import devices
import vmkctl
import subprocess

from weasel.log import log
from weasel import userchoices

KS_PATH = '/tmp/ks.cfg'

def copyFileFromUSBMedia(source, dest):
    '''Copy file from a usb device'''

    diskSet = devices.DiskSet(forceReprobe=True)

    usbDisks = [disk for disk in diskSet.values()
                if disk.driverName in devices.DiskDev.DRIVER_USB_STORAGE]

    if not usbDisks:
        log.info("") # XXX just for spacing
        log.warn("Attempted to find file on USB but no USB devices found.")
        return ''

    for disk in usbDisks:
        try:
            partSet = disk.getPartitionSet()
        except Exception as ex:
            log.error(str(ex))
            continue
        for part in partSet.getPartitions():
            if not part.fsType:
               log.debug('No fsType found on partition %s' %str(part))
               continue
            if part.fsType.partedFileSystemName in ['fat16', 'fat32']:

                # XXX - normally this would be used with execWithLog,
                #       however if it isn't executed on the shell it
                #       doesn't work

                args = ['/sbin/mcopy', '-i', part.consoleDevicePath,
                        '\\::%s' % source, dest]

                cmd = ' '.join(args)
                log.debug("Executing: %s" % cmd)

                pid = subprocess.Popen(cmd, shell=True)

                _pid, rc = os.waitpid(pid.pid, 0)

                if not rc:
                    # If we've found the file we want to save, we want to not
                    # wipe this USB disk (in case clearpart was used).
                    userchoices.addDriveUse(disk.name, 'file')
                    return dest

    log.debug("Couldn't find file %s on a usb device" % source)

    return ''

