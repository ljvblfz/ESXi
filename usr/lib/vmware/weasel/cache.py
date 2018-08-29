import datetime
import os
import re
import shutil
import subprocess
import tarfile
from . import util
import vmkctl
import tempfile


from weasel import devices
from weasel import userchoices
from weasel import task_progress
from weasel.exception import HandledError
from weasel.log import log

import vmware.esximage.Database
import vmware.esximage.Transaction
import vmware.esximage.Utils.XmlUtils
import vmware.esximage.Vib
import vmware.esximage.VibCollection

BOOT_MODULES_PATH = '/var/db/payloads/boot'
TAR_PATH = '/tardisks'
ESXIMG_PAYLOADTAR_NAME = "imgpayld.tgz"
ESXIMG_DBTAR_NAME = "imgdb.tgz"
ESXIMG_LOCKER_PACKAGES_DIR = 'packages'
ESXIMG_LOCKER_DB_DIR = 'var/db/locker'
USE_XZ_CFG_FILE = '/var/lib/initenvs/installer/EnableXZip'
SIG_FILE_DIR = '/usr/share/weasel'
BOOTMODULES_RAMDISK_PATH = '/bootmodules'

BOOTCFG_TEXT = '''bootstate=%(bootstate)d
title=%(title)s
timeout=%(timeout)d
prefix=%(prefix)s
kernel=%(boot)s
kernelopt=%(kernelopt)s
modules=%(modules)s
build=%(version)s-%(build)s
updated=%(updated)d
'''

BOOTBANK1_PART = 5
BOOTBANK2_PART = 6
LOCKER_PART = 8

TASKNAME = "Cache"
TASKDESC = "Caching the required files for ESXi"

class Cache(object):
    skipTarList = ['upgrade.tgz']
    saveTarList = []

    @classmethod
    def mountBootBanks(cls):
        '''Load the vfat driver and mount any vfat partitions'''
        util.loadVfatModule()
        util.rescanVmfsVolumes()


    def __init__(self, device,
                 bootbank=-1,
                 upgrade=False,
                 mount=True,
                 skipTarList=None,
                 saveTarList=None,
                 saveBootbank=None):
        self.device = device
        self.upgrade = upgrade
        self.bootSerial = 0

        self.bootbankPath = ''
        self.altbootbankPath = ''
        self.lockerPath = ''

        self.kernelArgs = ''

        self.saveBootbank = saveBootbank

        self.compresslevel = userchoices.getCompresslevel()
        log.debug("Compress level is %s" % self.compresslevel)

        if mount:
            self.mountBootBanks()

        if bootbank == -1:
            log.debug("Search for active bootbank")
            self.findBootBank()
        else:
            self.bootbankPartId = bootbank

        if skipTarList:
            self.skipTarList = skipTarList
        if saveTarList:
            self.saveTarList = saveTarList

        # Once we make sure that all of our bootbank info is populated, we'll
        # make sure we mark the right one.
        if saveBootbank:
            if saveBootbank == os.path.basename(self.altbootbankPath):
                log.debug("We're upgrading through VUM, we need to make sure that we"
                          " save and cache into that bootbank")
                # swap bootbanks
                if self.bootbankPartId == BOOTBANK1_PART:
                    self.setBootbank(BOOTBANK2_PART)
                else:
                    self.setBootbank(BOOTBANK1_PART)


    def getBootbank(self):
        return self._bootbankPartId

    def setBootbank(self, bootbank):
        '''Sets the bootbank to the partition id specified.'''
        if bootbank not in [BOOTBANK1_PART, BOOTBANK2_PART]:
            raise HandledError("Cannot set bootbank to partition %s" % bootbank)

        self._bootbankPartId = bootbank
        self._setESXiPaths()

    bootbankPartId = property(getBootbank, setBootbank)

    def _setESXiPaths(self):
        '''Find the path to the bootbanks'''

        bootbankParts, lockerPart = getESXiParts(self.device)

        if len(bootbankParts) == 0:
            log.debug('No bootbank partitions were found on the system')
        elif len(bootbankParts) == 1:
            self.bootbankPath = bootbankParts[0].GetConsolePath()
        elif len(bootbankParts) == 2:
            part1, part2 = bootbankParts
            if part1.GetHeadPartition().get().GetPartition() == self.bootbankPartId:
                self.bootbankPath = part1.GetConsolePath()
                self.altbootbankPath = part2.GetConsolePath()
            elif part2.GetHeadPartition().get().GetPartition() == self.bootbankPartId:
                self.bootbankPath = part2.GetConsolePath()
                self.altbootbankPath = part1.GetConsolePath()
            else:
                log.error('Bootbank was set to an invalid partition')
        else:
            # invalid parts
            log.error('More than two bootbank partitions found')

        log.debug("bootbank is %s" % self.bootbankPath)
        log.debug("altbootbank is %s" % self.altbootbankPath)

        if lockerPart is None:
            log.error('No locker partition was found on the system')
        else:
            self.lockerPath = lockerPart.GetConsolePath()
        log.debug('locker is %s' % (self.lockerPath))

    def findBootBank(self):
        '''Search through existing partitions and set the active bootbank'''

        bootbankParts = getBootbankParts(self.device)

        found = False

        if len(bootbankParts) != 2:
            raise HandledError("Expecting 2 bootbanks, found %s." % len(bootbankParts))

        # search through the partitions for the boot.cfg file
        # and check the updated and bootstate flags.

        for vol in bootbankParts:
            partId = vol.GetHeadPartition().get().GetPartition()
            bootCfgPath = os.path.join(vol.GetConsolePath(), 'boot.cfg')

            if os.path.exists(bootCfgPath):
                bootArgs = parseBootConfig(bootCfgPath)
                bootSerial = bootArgs.get('updated', -1)
                bootStateFlag = bootArgs.get('bootstate', -1)
                log.debug("boot serial - current: %d found: %d with bootstate: %d" %
                          (self.bootSerial, bootSerial, bootStateFlag))

                if bootStateFlag not in [0, 1]:
                    # If it's not a 0, 1, then it's probably bad.
                    # We're going to be safe and assume that a 2 meant it didn't work.
                    # 0: Successful boot.
                    # 1: Updated in last boot.
                    # 2: Boot attempted after upgrade.
                    # 3: Voluntarily marked as bad/invalid.
                    # -1: Invalid boot.cfg
                    log.debug("Skipping bootbank: %s... has invalid state." %
                              vol.GetConsolePath())
                    continue

                found = True
                self.kernelArgs = bootArgs.get('kernelopt', '')
                log.debug("Setting kernel args: %s" % self.kernelArgs)

                # compare the two bootSerial numbers and choose the
                # bootbank with the lowest bootSerial number as
                # the bootbank we'll operate on

                if bootSerial > self.bootSerial:
                    self.bootSerial = bootSerial

                    # swap bootbanks
                    if partId == BOOTBANK1_PART:
                        self.bootbankPartId = BOOTBANK2_PART
                    else:
                        self.bootbankPartId = BOOTBANK1_PART

                    log.debug("bootbank partid = %d" % self.bootbankPartId)

        if not found:
            self.bootbankPartId = BOOTBANK1_PART

    def migrateState(self):
        '''
        local.tgz and state.tgz are special files.  local.tgz only exists on
        embedded systems and the name is guaranteed to be local.tgz.  This
        file contains the state of the system.  On ThinESX, system state is
        maintained in state.tgz (and again, the file name is fixed).  This file
        contains only a single file: local.tgz.

        As of ESXi 5.0, we always create state.tgz.  For the case of ThinESX,
        this simply means copying over the file.  In the case of Embedded,
        this means converting the state to the new format (read: wrap into
        state.tgz) and then placing it in the boot bank.
        '''

        state_tgz = 'state.tgz'
        local_tgz = 'local.tgz'

        savedState = os.path.join(self.bootbankPath, state_tgz)

        if self.saveBootbank:
            currentState = os.path.join(self.bootbankPath, local_tgz)
        else:
            currentState = os.path.join(self.altbootbankPath, local_tgz)

        if os.path.exists(currentState):
            log.debug('Migrating %s to %s' % (currentState, savedState))
            # Wrap local.tgz to state.tgz
            with tarfile.open(savedState, 'w:gz') as tgz:
                tgz.add(currentState, arcname=local_tgz)
        else:
            if self.saveBootbank:
                currentState = os.path.join(self.bootbankPath, state_tgz)

                if os.path.exists(currentState):
                    log.debug("Found a 'state.tgz' in VUM saved bootbank ...")
                else:
                    log.debug("No saved state found ...")
                    savedState = None
            else:
                currentState = os.path.join(self.altbootbankPath, state_tgz)

                if os.path.exists(currentState):
                    log.debug('Copying %s to %s' % (currentState, savedState))
                    shutil.copy2(currentState, savedState)
                else:
                    log.debug("No saved state found ...")
                    savedState = None

        if savedState:
            return os.path.basename(savedState)
        else:
            return None

    def cache(self):
        if not self.bootbankPath or not self.lockerPath:
            raise HandledError("Either bootbank or locker aren't set.  Cannot cache.")

        stateFiles = ['state.tgz', 'local.tgz']

        # clean-up any files in the bootbank
        # XXX - this isn't directory safe right now
        for filename in os.listdir(self.bootbankPath):
            # In the VUM case, don't remove the state files.
            if filename in stateFiles and self.saveBootbank:
                continue

            os.remove(os.path.join(self.bootbankPath, filename))

        # find the files to cache and filter out unwanted files
        modules, lockermodules = findModulesOrder(self.skipTarList,
                                                  self.upgrade,
                                                  self.altbootbankPath,
                                                  self.bootbankPath,
                                                  self.lockerPath)

        # '3' to compensate for esximg_db, state and bootcfg.
        task_progress.reviseEstimate(TASKNAME,
                len(modules) + len(lockermodules) + 3)

        # compress each of the vmtar files onto the bootbank
        for filename, directory, oldname in modules:
            #No directory signifies that the file has already been copied
            #over - e.g. imgdb.tgz
            if directory == None:
                continue
            if oldname:
                src = open(os.path.join(directory, oldname), "rb")
            else:
                src = open(os.path.join(directory, filename), "rb")
            dstPath = os.path.join(self.bootbankPath, filename)
            if directory == BOOT_MODULES_PATH or directory == self.altbootbankPath:
                dst = open(dstPath, "wb")
            elif directory == TAR_PATH:
                # if the sys and sys boot tardisks need to be xz compressed
                # before being written out, the file is xzipped and then the
                # respective signature is appended to it.
                if filename in ["sb.v00", "s.v00", "vmx.v00", "vim.v00"] \
                    and os.path.isfile(USE_XZ_CFG_FILE):
                    xzFile = os.path.join(BOOTMODULES_RAMDISK_PATH, filename)
                    if os.path.isfile(xzFile):
                        log.debug("Found '%s' in %s cache" % (filename, BOOTMODULES_RAMDISK_PATH))
                        src.close()
                        src = open(xzFile, "rb")
                    else:
                        tmpfd, tmpfile = tempfile.mkstemp()
                        tmp = os.fdopen(tmpfd, "r+b")
                        try:
                            xz = subprocess.Popen("xz --compress --stdout \
                                                  --lzma2=dict=2048KiB \
                                                  --check=crc32 --threads=8",
                                                  shell=True,
                                                  stdin=src,
                                                  stdout=tmp,
                                                  stderr=subprocess.PIPE)
                            log.debug("Caching '%s' to xzipped '%s'" % (src, tmp))
                            _, err = xz.communicate()
                            if xz.returncode != 0:
                                raise Exception("xzipping failed (status:%u): %s"
                                                % (xz.returncode, err))
                            src.close()
                            tmp.flush()
                        except Exception as e:
                            msg = "Could not xzip boot module: %s. Error: %s" \
                                  % (filename, str(e))
                            log.exception(msg)
                            raise HandledError(msg)

                        sigfile = os.path.join(SIG_FILE_DIR,
                                               os.path.splitext(filename)[0]) + \
                                               '.sigblob'
                        # check if the signature file exists
                        if not os.path.isfile(sigfile):
                            raise HandledError("Signature file missing for module: %s"
                                               % filename)
                        with open(sigfile, "rb") as sigfd:
                            tmp.write(sigfd.read())

                        # delete temporary files created
                        tmp.flush()
                        tmp.seek(0)
                        src = tmp
                        os.unlink(tmpfile)

                # Limit the number of compress threads to 120.
                # (60*2 for processors with hyper threading)
                # The soft limit for the maximum number of allowed child threads
                # is 128.
                dst = subprocess.Popen('pigz -%d -p 60 -n -T > %s' %
                                       (self.compresslevel, dstPath),
                                       shell=True,
                                       stdin=subprocess.PIPE).stdin

            log.debug("Caching '%s' to '%s'" % (src, dst))
            try:
                shutil.copyfileobj(src, dst)
                dst.flush()
            except shutil.Error as e:
                msg = "Caching file %s to %s failed during the installation process "\
                      "with error message: %s." % (src, dst, str(e))
                log.exception(msg)
                raise HandledError(msg)

            finally:
                src.close()
                dst.close()

            task_progress.taskProgress(TASKNAME)

        # untar locker payload to locker packages directory
        # remove userworld core dump first
        #However, is this is an upgrade ad there are no lockermodules
        #to be copied over, leave the partition alone.
        if self.upgrade and not lockermodules:
            pass
        else:
            lockerVarDir = os.path.join(self.lockerPath, 'var')
            vsantracesDir = os.path.join(self.lockerPath, 'vsantraces')
            lockerPkgDir = os.path.join(self.lockerPath,
                  ESXIMG_LOCKER_PACKAGES_DIR)
            for path in (lockerVarDir, lockerPkgDir, vsantracesDir):
                if os.path.exists(path):
                    shutil.rmtree(path)
            os.makedirs(lockerPkgDir)
            for filename, directory in lockermodules:
                src = os.path.join(directory, filename)
                log.debug("Extracting '%s' to '%s'..." % (src, lockerPkgDir))
                if not os.path.exists(src):
                    # Likely a VUM upgrade (so tools is already extracted) and
                    # even if not, absence of tools shouldn't cause failure
                    log.warn('Could not find %s. Skipping' % src)
                    continue
                tar = tarfile.TarFile(src, mode='r')
                tar.extractall(lockerPkgDir)
                tar.close()
                task_progress.taskProgress(TASKNAME)

            # rebuild database
            bootbankDb = os.path.join(self.bootbankPath, ESXIMG_DBTAR_NAME)
            rebuildDb(bootbankDb, lockerPkgDir)
            task_progress.taskProgress(TASKNAME)

        # save any state files which need to be preserved
        # XXX - this will choke if the user has specified a directory as
        #       one of the vmtar files.
        if self.upgrade and self.altbootbankPath:
            for tarFile in self.saveTarList:
                log.debug("Checking if %s exists in %s." % (tarFile, self.altbootbankPath))
                filename = os.path.join(self.altbootbankPath, tarFile)
                if os.path.exists(filename):
                    log.debug("Copying %s to %s" % (filename, self.bootbankPath))
                    shutil.copy2(filename, self.bootbankPath)
                    if tarFile not in [mod[0] for mod in modules]:
                        modules.append((tarFile, None, None))
            task_progress.taskProgress(TASKNAME)

            state = self.migrateState()
            if state:
                modules.append((state, None, None))
            else:
                log.debug('Did not find existing state, potentially upgrading'
                          ' from a Classic system?')

        version, build = findVersionAndBuild()

        disk = devices.DiskSet()[self.device]

        # bootstate is to be 0 if it's a fresh install or an upgarde from VUM
        # (in which case, we clobber the original bootbank), and 1 if we can rollback.
        bootstate = 0
        if self.upgrade and not self.saveBootbank:
            # We need to be sure to set bootstate to 1 if we want to rollback.
            if disk.containsEsx.esxi:
                bootstate = 1

        bootArgs = {
            'boot'      : modules[0][0],
            'kernelopt' : '',
            'modules'   : ' --- '.join(i[0] for i in modules[1:]),
            'title'     : "Loading VMware ESXi",
            'timeout'   : 5,
            'prefix'    : '',
            'version'   : version,
            'build'     : build,
            'updated'   : self.bootSerial + 1,
            'bootstate' : bootstate
        }

        # If we're fresh installing, with GPT, and the disk is large enough,
        # then it's safe to assume that the larger coredump partition is made.
        if userchoices.getLargerCoreDumpPart():
            log.debug("Adding additional kernel argument to support larger core dump")
            bootArgs['kernelopt'] = bootArgs['kernelopt'] + ' installerDiskDumpSlotSize=2560'

        self.writeBootConfig(bootArgs)

        # Only if the altbootbank doesn't have a boot.cfg, do we place a
        # boot.cfg there.
        if not os.path.exists(os.path.join(self.altbootbankPath, 'boot.cfg')):
            altbootArgs = bootArgs
            altbootArgs['updated'] = bootArgs['updated'] + 1
            altbootArgs['bootstate'] = 3

            self.writeBootConfig(altbootArgs, True)

        task_progress.taskProgress(TASKNAME)


    def writeBootConfig(self, args=None, alt=False):
        if not args:
            args = {}
            # XXX - raise an error here

        if alt:
            bootbankPath = self.altbootbankPath
        else:
            bootbankPath = self.bootbankPath

        f = open(os.path.join(bootbankPath, 'boot.cfg'), 'w')
        f.write(BOOTCFG_TEXT % args)
        f.close()


def getESXiParts(deviceName):
    '''Returns a list of bootbank partitions and locker partition on a device'''
    bootbankParts = []
    lockerPart = None
    vfatVols = [ptr.get() for ptr in vmkctl.StorageInfoImpl().GetVFATFileSystems()]

    for vol in vfatVols:
        if vol.GetHeadPartition().get().GetDeviceName() != deviceName:
            continue

        part = vol.GetHeadPartition().get().GetPartition()
        if part in [BOOTBANK1_PART, BOOTBANK2_PART]:
            log.debug("Found bootbank partition %d" % part)
            bootbankParts.append(vol)
        elif part == LOCKER_PART:
            log.debug("Found locker partition %d" % part)
            lockerPart = vol

    if not bootbankParts:
        log.debug("Didn't find any bootbank partitions")
    if lockerPart is None:
        log.debug("Didn't find locker partition")

    return (bootbankParts, lockerPart)

def getBootbankParts(deviceName):
    bootbankParts, _lockerPart = getESXiParts(deviceName)
    return bootbankParts

def parseBootConfig(path=''):
    '''Parse the boot.cfg file and create a dictionary of boot args

    '''
    if not os.path.exists(path):
        log.warn("Couldn't find %s" % path)
        return []

    log.debug("Parsing bootconfig file:  %s" % path)
    f = open(path)
    bootText = f.readlines()
    f.close()

    bootArgs = {}

    for count, line in enumerate(bootText):
        line = line.rstrip()

        if '=' not in line:
            log.debug("Skipping line %d:  %s" % (count, line))
            continue

        arg, val = line.split('=', 1)

        if arg == 'build':
            version, build = val.split('-', 1)
            bootArgs['version'] = version
            bootArgs['build'] = build
        elif arg in ['updated', 'bootstate']:
            try:
                bootArgs[arg] = int(val)
            except ValueError as e:
                log.debug("Couldn't convert line %d:  %s" % (count, line))
                raise
        else:
            bootArgs[arg] = val

    return bootArgs


def findVersionAndBuild():
    '''Find the version and build of an ESX system'''

    # matches version and build
    regex = '(\d+\.\d+\.\d+)\s+build-(\d+)'

    cmd = '/bin/vmware -v'
    rc, stdout, stderr = util.execCommand(cmd)

    if rc:
        log.error("Couldn't find version and build")
        #raise CacheError, "Couldn't find version and build"

    matchObj = re.search(regex, stdout)
    if matchObj:
        return matchObj.groups()

    return ('', '')


def getDB(path=None, isTar=False):
    ''' Load up the database at the location provided by the user.
        Parameters:
            --- path : Path to the db.
            --- isTar : Whether it is a compressed db or not.
    '''
    assert path

    imgdb = None
    try:
        if os.path.exists(path):
            if isTar:
                imgdb = vmware.esximage.Database.TarDatabase(dbpath = path, dbcreate = False)
            else:
                imgdb = vmware.esximage.Database.Database(dbpath = path, dbcreate = False)
            imgdb.Load()
            # Locker db doesn't have profile info
            if imgdb.profile:
                for vibid in imgdb.profile.vibIDs:
                    imgdb.profile.vibs[vibid] = imgdb.vibs[vibid]
        else:
            log.debug("The path %s does not exist." % (str(path)))
    except:
        log.exception("Error reading database : %s" % (str(path)))
        imgdb = None

    return imgdb



def findModulesOrder(skipTarList=(), upgrade=False, altbootbankPath=None,
      bootbankPath=None, lockerPath=None):
    '''Determine the ordering of the loaded bootbank/locker modules
            Parameters:
            - skipTarList     : List of modules that should be skipped.
            - upgrade         : Whether this is an upgrade or an install.
            - altbootbankPath : The bootbank that the system last successfully
                                booted from.
            - bootbankPath    : The bootbank to which the new image will be
                                installed on.
    '''

    modules = list()
    lockermodules = list()
    srcimgdb = None
    if upgrade and altbootbankPath:
        path = os.path.join(altbootbankPath, ESXIMG_DBTAR_NAME)
        srcimgdb = getDB(path=path, isTar=True)

        # If bootbank DB is not loaded, no need to check locker DB
        if srcimgdb and lockerPath:
            lockerDBPath = os.path.join(lockerPath, ESXIMG_LOCKER_PACKAGES_DIR, ESXIMG_LOCKER_DB_DIR)
            srclockerdb = getDB(path=lockerDBPath, isTar=False)
            if srclockerdb:
               log.debug("Merging locker VIBs: %s"
                         % (list(srclockerdb.vibs.keys())))
               srcimgdb.profile.AddVibs(srclockerdb.vibs)

    try:
        #Need to get the DB from the actual DB instead of the running image,
        #since the running image does not reflect the actual acceptance level.
        isodb = getDB(path="/var/db/esximg")
        isoprofile = isodb.profile
        isoprofile.vibs = isodb.vibs
        vibcollection = vmware.esximage.VibCollection.VibCollection()

        if srcimgdb:
            vibcollection += srcimgdb.profile.vibs

        if vibcollection:
            log.debug("The customizations will be retained.")
        else:
            log.debug("The customizations will not be retained")

        (updates, downgrades, new, existing) = isoprofile.ScanVibs(vibcollection)

        newdbpath = os.path.join(bootbankPath, ESXIMG_DBTAR_NAME)
        newimgdb = vmware.esximage.Database.TarDatabase(dbpath=newdbpath, dbcreate=False)
        newimgdb.vibs = isoprofile.vibs
        newimgdb.profiles.AddProfile(isoprofile.Copy())

        if upgrade and srcimgdb:
            trust_order = vmware.esximage.ImageProfile.AcceptanceChecker.TRUST_ORDER

            if trust_order[newimgdb.profile.acceptancelevel] > trust_order[srcimgdb.profile.acceptancelevel]:
                log.debug("Lowering the imageprofile acceptance level.")
                newimgdb.profile.acceptancelevel = srcimgdb.profile.acceptancelevel

            if new or updates:
                log.debug("Retaining the following vibs : %s" % str(new | updates))

                # Update image profile information for upgrade case
                vibstr = '\n'.join('  %s\t%s' % (vibcollection[vibid].name,
                         vibcollection[vibid].versionstr)
                         for vibid in (new | updates))
                changelog = "Host is upgraded with following VIBs from " \
                            "original image profile %s:\n%s" % \
                            (srcimgdb.profile.name, vibstr)
                vmware.esximage.Transaction.Transaction._updateProfileInfo(
                                                 newimgdb.profile, changelog)

            for vibid in (new | updates):
                newimgdb.profile.AddVib(srcimgdb.profile.vibs[vibid], True)

        newimgdb.vibs = newimgdb.profile.vibs
        newimgdb.profile.GenerateVFATNames(strictVFatName=True)

        problems = newimgdb.profile.Validate()

        if problems:
            msg = "The installation profile could not be validated due to the following errors:\n%s" %\
                  "\n".join("  %s" % p for p in problems)
            log.error(msg)
            raise HandledError(msg)

        payload_types = (vmware.esximage.Vib.Payload.TYPE_TGZ,
                         vmware.esximage.Vib.Payload.TYPE_VGZ,
                         vmware.esximage.Vib.Payload.TYPE_BOOT)
        for vibid, payload in newimgdb.profile.GetBootOrder(payload_types):
            # Locker VIBs go to locker partition
            if vibid in (new | updates):
                # If tools VIB on the host is new, don't need to do anything for
                # locker, just drop it from the new database
                if vibid in  newimgdb.profile.vibIDs and \
                      newimgdb.profile.vibs[vibid].vibtype == newimgdb.profile.vibs[vibid].TYPE_LOCKER:
                    log.debug("Keeping locker VIB %s" % (vibid))
                    newimgdb.profile.RemoveVib(vibid)
                    continue

                if payload.localname not in skipTarList:
                   oldpayloadname = srcimgdb.profile.vibstates[vibid].payloads[payload.name]
                   modules.append((payload.localname, altbootbankPath, oldpayloadname))
            else:
                # If the vibid isn't in new or updates, then it's live on the
                # system (i.e., from the ISO or from PXE boot)
                isopayldname = isodb.profile.vibstates[vibid].payloads[payload.name]
                if isoprofile.vibs[vibid].vibtype == isoprofile.vibs[vibid].TYPE_LOCKER:
                    if payload.payloadtype == payload.TYPE_TGZ:
                        lockermodules.append((isopayldname, TAR_PATH))
                    continue
                if (payload.payloadtype == payload.TYPE_BOOT
                    and payload.localname not in skipTarList):
                    modules.append((payload.localname, BOOT_MODULES_PATH, isopayldname))
                elif payload.payloadtype in (payload.TYPE_VGZ, payload.TYPE_TGZ):
                    modules.append((payload.localname, TAR_PATH, isopayldname))

            utctz = vmware.esximage.Utils.XmlUtils._utctzinfo
            newimgdb.profile.vibs[vibid].installdate = datetime.datetime.now(utctz)

        newimgdb.Save(dbpath=newdbpath, savesig=True)
        modules.append((ESXIMG_DBTAR_NAME, None, None))

    except Exception as e:
        # log the original exception for later troubleshooting.
        msg = "Could not obtain module order from esximage db : %s" % str(e)
        log.exception(msg)
        raise HandledError(msg)

    if len(modules) < 2:
        raise HandledError("One or more boot modules missing")
    return (modules, lockermodules)

def rebuildDb(bootbankDb, lockerPkgDir):
    '''Rebuild bootbankDb and create DB in locker
       Remove locker VIBs from bootbank database and create database in locker
       partition with locker VIBs
       Parameters:
          * bootbankDb - file path to bootbank database tar file
          * lockerPkgDir - packages directory in locker partion
    '''
    lockervibs = list()
    try:
        db = vmware.esximage.Database.TarDatabase(bootbankDb, dbcreate=False)
        db.Load()
        utctz = vmware.esximage.Utils.XmlUtils._utctzinfo
        profile = db.profile
        vibs = db.vibs
        assert profile
        for vib in (vibs[vibid] for vibid in profile.vibIDs):
            vib.installdate = datetime.datetime.now(utctz)
            if vib.vibtype == vib.TYPE_LOCKER:
                lockervibs.append(vib)
        # locker VIBs are in a separate DB
        for vib in lockervibs:
            profile.RemoveVib(vib.id)
            vibs.RemoveVib(vib.id)
        db.Save(savesig=True)
    except Exception as e:
        msg = "Could not rebuild bootbank database"
        log.exception(msg)
        raise HandledError("Could not rebuild bootbank database")

    # create locker DB
    dbdir = os.path.join(lockerPkgDir, 'var/db/locker')
    try:
        if os.path.exists(dbdir):
            shutil.rmtree(dbdir)
        db = vmware.esximage.Database.Database(dbdir, addprofile=False)
        for vib in lockervibs:
            db.vibs.AddVib(vib)
        db.Save()
    except Exception as e:
        msg = 'Could not create locker database'
        log.exception(msg)
        raise HandledError(msg)

def installAction():
    deviceName = userchoices.getEsxPhysicalDevice()

    cacher = Cache(deviceName)

    cacher.cache()

def upgradeAction():
    deviceName = userchoices.getEsxPhysicalDevice()
    saveBootbank = userchoices.getSaveBootbankUUID()

    cacher = Cache(deviceName, upgrade=True,
                   saveBootbank=saveBootbank,
                   saveTarList=['jumpstrt.gz'])

    cacher.cache()

