#! /usr/bin/env python

import os
from . import util
from . import script
import tarfile
from weasel import userchoices # always import via weasel.
from weasel import cache
from weasel import consts
from weasel import devices
from weasel.log import log
from .exception import HandledError

TASKDESC = 'Writing the serial number'
TASKNAME = 'Serial'

LICENSE_CHECK_RESULT = {
    # Taken from bora/support/check_serial/checkserial.c
    2: "The serial number is incompatible.",
    3: "The serial number is invalid.",
    4: "The serial number has expired.",
    5: "No matching licenses for serial number.",
    }

EVAL_KEY = "00000-00000-00000-00000-00000"

_serialNum = None

_licenseCfgFile = None
# Note, that this EPOC value is for PRODUCT_LICENSING_VERSION=6.0 ("86400#6.0") and should be changed on next major version of the product.
licenseCfgFile = "<ConfigRoot><epoc>AQD+yggAAACZjD8aJmfEjDQAAABVz3b2HP04RGHLvzTqVlxWP50GxxaqjnWRkpx8V0+okACP89M3g922WK+lDtHFHuLK1ymy</epoc><mode>eval</mode><owner/></ConfigRoot>"


class LicenseException(HandledError): pass

class EvalLicException(HandledError): pass

def checkSerialNumber(value):
    args = ["/sbin/check_serial", "-c", value]

    if value.strip() == EVAL_KEY:
        raise EvalLicException("License is an evaluation license.")

    rc = util.execWithLog(args[0], args)
    if rc != 0:
        if os.WIFEXITED(rc):
            code = os.WEXITSTATUS(rc)
        else:
            code = None
        msg = LICENSE_CHECK_RESULT.get(
            code, "Internal error while validating serial number.")
        raise LicenseException(msg)


def hostAction():
    applyUserchoices()

def installAction():
    applyUserchoices()

def upgradeAction():
    applyUserchoices()

def applyUserchoices():
    global _serialNum
    choice = userchoices.getSerialNumber()

    # Only if we're upgrading, do we need to extract prior epoc value
    # and reset licensing state to evaluation mode.
    upgrade = userchoices.getUpgrade()
    if upgrade and not choice:
        resetLic = False

        upDisk = userchoices.getEsxPhysicalDevice()
        c = cache.Cache(upDisk)
        d = devices.DiskSet()[upDisk]

        stateTgzPath = os.path.join(c.altbootbankPath, 'state.tgz')
        if os.path.exists(stateTgzPath):
            stateTgz = tarfile.open(stateTgzPath)
            localTgzFile = stateTgz.extractfile('local.tgz')
            localTgz = tarfile.open(fileobj=localTgzFile)
            try:
                vmwareLic = localTgz.extractfile('etc/vmware/vmware.lic')
                serialNum = vmwareLic.read().strip()
                checkSerialNumber(serialNum)
            except (KeyError, EvalLicException) as ex:
                # vmware.lic doesn't exist so it's still in eval mode, or it's
                # actually in eval mode... but we should reset it if they're
                # changing major version numbers.
                log.info("Still in eval mode...")
                if d.containsEsx.version \
                   and d.containsEsx.version[0] != int(consts.PRODUCT_VERSION_NUMBER[0]):
                    log.info("  ... major versions changed, resetting.")
                    resetLic = True
            except LicenseException as ex:
                # Anything wrong with the license number we have, we'll reset it.
                log.info("Resetting the license to evaluation.  Existing license is"
                         " invalid with this release.")
                resetLic = True
            stateTgz.close()
            localTgz.close()
        else:
            log.warn("Could not find state.tgz")
            log.info("Resetting the license to evaluation.")
            resetLic = True

        if resetLic:
            _licenseCfgFile = licenseCfgFile
            _serialNum = EVAL_KEY
        else:
            log.info("Upgrading with a valid license; not resetting license.")
    else:
        if not choice:
            log.info("no license key entered, defaulting to evaluation mode")
            return

        serialNum = choice['esx']
        checkSerialNumber(serialNum)

        log.info('Creating license script with serialnum %s' % serialNum)
        _serialNum = serialNum


def getFirstBootVals():
   global _serialNum
   keyVals = {} 
   if _serialNum is not None:
      keyVals["licenseFile"] = _serialNum
   if _licenseCfgFile is not None:
      keyVals["licenseCfgFile"] = _licenseCfgFile
   return keyVals


if __name__ == '__main__':
    import sys
    # Never hard-code a valid serial number in this file.
    serial = sys.argv[1]
    userchoices.setSerialNumber(esx=serial)
    checkSerialNumber(serial)
    applyUserchoices()
