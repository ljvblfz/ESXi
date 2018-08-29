import os
import shutil
import tarfile

import vmkctl

from weasel import cache
from weasel import devices
from weasel import userchoices
from weasel.log import log

TASKNAME_MIGRATE = "Migrating..."
TASKDESC_MIGRATE = "Parsing and migrating settings."

LOCAL_TGZ = "local.tgz"
STATE_TGZ = "state.tgz"


def deleteFilesFromStateTgz():
    """
    This deals with files that were once marked sticky, but we don't
    want to preserve changes on upgrade.
    """
    log.debug('attempting to delete files from state.tgz')

    deviceName = userchoices.getEsxPhysicalDevice()
    c = cache.Cache(deviceName)
    bootbankPath = c.altbootbankPath

    if not bootbankPath:
        log.debug('boot bank path is none')
        return

    STATE_TEMP_DIR = '/tmp/stateunzip'
    STATE_FILE = os.path.join(bootbankPath, STATE_TGZ)
    LOCAL_TGZ_FILE = os.path.join(STATE_TEMP_DIR, LOCAL_TGZ)
    LOCAL_TGZ_UNZIP = os.path.join(STATE_TEMP_DIR, 'local')

    # for details ...
    # - PR#614697  : /etc/init.d/*
    # - PR#887592  : /etc/profile
    # - PR#884073  : /etc/rc.local
    # - PR#1021752 : /etc/vmware/usb.ids
    PURGE_DIRS = ['etc/init.d',]
    PURGE_FILES = ['etc/gshadow', 'etc/profile', 'etc/rc.local',
                   'etc/vmware/service/service.xml',
                   'etc/vmware/usb.ids']

    if not os.path.exists(STATE_FILE):
        log.debug('state.tgz does not exist')
        return

    log.debug('state.tgz exists')
    # untar state.tgz
    tar = tarfile.open(STATE_FILE)
    tar.extractall(STATE_TEMP_DIR)
    tar.close()

    # state.tgz contains local.tgz
    if not os.path.exists(LOCAL_TGZ_FILE):
        log.debug('state.tgz does not exist')
        return

    log.debug('local.tgz exists')
    # untar local.tgz
    tar = tarfile.open(LOCAL_TGZ_FILE)
    tar.extractall(LOCAL_TGZ_UNZIP)
    tar.close()
    os.remove(LOCAL_TGZ_FILE)

    # Delete those directories...
    for purgeDir in PURGE_DIRS:
        delDir = os.path.join(LOCAL_TGZ_UNZIP, purgeDir)
        if os.path.exists(delDir):
            log.debug("Found dir '%s', deleting it from state ..." % delDir)
            shutil.rmtree(delDir)

    # Delete those files...
    for purgeFile in PURGE_FILES:
        delFile = os.path.join(LOCAL_TGZ_UNZIP, purgeFile)
        if os.path.isfile(delFile):
            log.debug("Found file '%s', deleting it from state ..." % delFile)
            os.remove(delFile)

    currDir = os.getcwd()
    localGzip = tarfile.open(LOCAL_TGZ_FILE, 'w:gz')
    os.chdir(LOCAL_TGZ_UNZIP)
    localGzip.add('.')
    localGzip.close()

    # Gzip local.tgz into state.tgz
    os.chdir(STATE_TEMP_DIR)
    stateGzip = tarfile.open('state.tgz', 'w:gz')
    stateGzip.add('local.tgz')
    stateGzip.close()

    # copy newly created state.tgz to bootbank again
    log.debug('copying state.tgz')
    shutil.copyfile(STATE_TGZ, STATE_FILE)

    os.chdir(currDir)

def migrateAction():

    deviceName = userchoices.getEsxPhysicalDevice()
    disk = devices.DiskSet()[deviceName]
    if disk.containsEsx.esxi:
        deleteFilesFromStateTgz()