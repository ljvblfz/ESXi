# Copyright 2008-2015 VMware, Inc.
# All rights reserved. -- VMware Confidential
#! /usr/bin/env python
'''
script.py
A module for dealing with %pre, %post, and %firstboot scripts.
'''

import os
import sys
import gzip
import stat
import shutil
from weasel.featureSwitch import ReturnFeatureSwitchString
import json
import vmkctl
from . import task_progress
from weasel import userchoices # always import via weasel.

from weasel import devices
from weasel import util
from weasel import cache
from weasel.log import log, LOGLEVEL_HUMAN, LOGLEVEL_UI_ALERT, ESX_LOG_PATH
from .exception import HandledError

TASKNAME = 'Scripts'
TASKDESC = 'Writing first-boot configuration'

TASKDESC_PRE = 'Executing pre scripts'
TASKDESC_POST = 'Executing post scripts'

STAGE_DIR = '/tmp/onetime'
RC_FIRSTBOOT_CFG = '/var/lib/vmware/firstboot/firstboot.json'
FIRSTBOOT_DIR = '/var/lib/vmware/firstboot'
TARFILE_PATH = '/tmp/onetime.tar'
GZFILE_NAME = 'onetime.tgz' # Note: this filename must conform to 8.3 format

GZFILE_PATH = None
BOOT_CFG_PATH = None


def addFirstBootCfg(name, value):
   try:
      configPath = RC_FIRSTBOOT_CFG
      data = {}
      if os.path.exists(configPath):
         with open(configPath, mode='r') as f:
            data = json.load(f)
      data[name] = value
      with open(configPath, mode='w') as f:
         json.dump(data, f, indent=4, sort_keys=True)
   except Exception as e:
      message = "Failed to load firstboot configuration: %s" % e
      raise RuntimeError(message)


def addFirstBootConfigFiles(paths):
   try:
      configPath = FIRSTBOOT_DIR
      data = {}
      for path in paths:
         dstPath = "%s/%s" % (configPath, os.path.basename(path))
         shutil.copyfile(path, dstPath)
         copyFileToStage(dstPath)
         data[dstPath] = path
      addFirstBootCfg("copyFiles", data)
   except Exception as e:
      message = "Failed to add first boot config files: %s" % e
      raise RuntimeError(message)


class Script:
    def __init__(self, script, interp, inChroot, timeoutInSecs, ignoreFailure,
                 group = None):
        self.script = script
        self.interp = interp
        self.inChroot = inChroot
        self.timeoutInSecs = timeoutInSecs
        self.ignoreFailure = ignoreFailure

        self.relativePath = "tmp/ks-script"
        self.realPath = None # don't know the value until we know the chroot
        self.group = group # pre or post script

    def __str__(self):
        return '<Script %s %s>' % (self.interp, self.script[:9])

    def stage(self, chroot):
        self.realPath = os.path.join(chroot, self.relativePath)

        f = open(self.realPath, "w")
        f.write(self.script)
        f.close()
        os.chmod(self.realPath, 0o700)

    def unstage(self):
        os.unlink(self.realPath)

    def run(self, chroot="/"):
        self.stage(chroot)

        if self.inChroot:
            execPath = os.path.join('/', self.relativePath)
        else:
            execPath = self.realPath

        cmd = self.interp.split() + [execPath]

        if self.inChroot:
            execRoot = chroot
        else:
            execRoot = '/'

        rc = util.execWithLog(cmd[0], cmd,
                              level=LOGLEVEL_HUMAN,
                              root=execRoot,
                              timeoutInSecs=self.timeoutInSecs,
                              raiseException=False)
        if rc != 0:
            group='script'
            if self.group:
                group = '%%%s script' % self.group
            msg = 'User-supplied %s failed. (Error code %s)' % (group, str(rc))
            if self.ignoreFailure:
                log.warn(msg)
                log.log(LOGLEVEL_UI_ALERT, msg)
            else:
                raise HandledError(msg)

        self.unstage()
        return rc

    def __eq__(self, rhs):
        return (self.script == rhs.script and
                self.interp == rhs.interp and
                self.inChroot == rhs.inChroot and
                self.timeoutInSecs == rhs.timeoutInSecs and
                self.ignoreFailure == rhs.ignoreFailure)

    def __repr__(self):
        return repr(self.__dict__)

class FirstBootScript(Script):
    count = 0
    def __init__(self, script, interp, suffix = None,
                 order = None):
        FirstBootScript.count += 1

        self.script = script
        self.interp = interp

        if order != None:
            self.order = order
        else:
            self.order = FirstBootScript.count

        if suffix != None:
            self.suffix = suffix
        else:
            # we need to give them unique names, otherwise they'll
            # overwrite each other
            self.suffix = '%03d' % FirstBootScript.count

    def makeFirstBootScriptFiles(self):
        name = '%03d.firstboot_%s' % (self.order, self.suffix)
        dirname = FIRSTBOOT_DIR
        path = os.path.join(dirname, name)
        content = '\n'.join(('#!%s' % self.interp, self.script))

        return { path : content }

    def stage(self):
        files = self.makeFirstBootScriptFiles()
        its = files.items()

        for fpath, contents in its:
            fpath = os.path.join(STAGE_DIR, fpath.lstrip('/'))
            log.info('Writing %d chars to %s' % (len(contents), fpath))
            fp = open(fpath, 'w')
            fp.write(contents)
            fp.close()
            os.chmod(fpath, 0o777)

            try:
                util.verifyFileWrite(fpath, contents)
            except IOError as ex:
                raise HandledError('File write failed', str(ex))

def copyFileToStage(srcPath, stageDir=STAGE_DIR, makeSticky=False):
    '''copy the files to the stage ('/tmp/onetime/') so that we can
    later tar/gzip them into onetime.tgz
    The makeSticky argument will set their sticky bit and put them into a
    sub-tar file that gets extracted (and hence branched) by an initscript
    during the reboot. Only when they are marked sticky and branched will
    they be preserved in subsequent reboots.
    '''
    if not os.path.exists(srcPath):
       return
    destPath = os.path.join(stageDir, srcPath.lstrip('/'))

    # make sure the destination directory exists
    dirname = os.path.dirname(destPath)
    if not os.path.isdir(dirname):
        os.makedirs(dirname)

    # copy
    destPath = os.path.join(stageDir, srcPath.lstrip('/'))
    log.info('Copying %s to %s' % (srcPath, destPath))
    src = open(srcPath)
    dest = open(destPath, 'w')
    contents = ''
    chunk = src.read(1024)
    while chunk:
        dest.write(chunk)
        contents += contents
        chunk = src.read(1024)
    src.close()
    dest.close()

    if makeSticky:
        os.chmod(destPath, os.stat(destPath).st_mode | stat.S_ISVTX)

def postScriptAction():
    util.restoreFirewallState()
    postScriptDicts = userchoices.getPostScripts()
    for psDict in postScriptDicts:
        script = psDict['script']
        script.run()

def hostAction():
    util.restoreFirewallState()
    mountHostRoot()
    task_progress.taskProgress(TASKNAME, 1)

    updateBootCfg()
    task_progress.taskProgress(TASKNAME, 1)

    stageFirstBootScripts()
    task_progress.taskProgress(TASKNAME, 1)

    packageScripts()
    task_progress.taskProgress(TASKNAME, 1)


def mountHostRoot():
    '''magic invokation to be able to see the Hypervisors'''
    util.loadVfatModule()
    cmd = '/sbin/vmkfstools -V'.split()
    util.execWithLog(cmd[0], cmd)

    # We're going to set these before they get used...
    global GZFILE_PATH, BOOT_CFG_PATH

    # Use the Cache object to figure out which Hypervisor we need to put the
    # onetime.tgz
    disk = userchoices.getEsxPhysicalDevice()
    c = cache.Cache(disk)
    # By now, we've already cached, so the altbootbank is the one we're looking
    # for.
    bootbankPath = c.altbootbankPath

    GZFILE_PATH = os.path.join(bootbankPath, GZFILE_NAME)
    BOOT_CFG_PATH = os.path.join(bootbankPath, 'boot.cfg')


def updateBootCfg():
    log.info('Reading the boot.cfg file')
    fp = open(BOOT_CFG_PATH)
    lines = fp.readlines()
    fp.close()

    log.info('Writing to the boot.cfg file')
    fp = open(BOOT_CFG_PATH, 'w')
    newlines = []
    for line in lines:
        if line.startswith('kernelopt='):
# TODO      if not userchoices.getPartitionEmbed():
                line = line.strip()
                if not line.endswith('kernelopt='):
                    line += ' '
                line += 'no-auto-partition%s\n' % ReturnFeatureSwitchString()
        if line.startswith('modules='):
            line = line[:-1] + (' --- %s\n' % GZFILE_NAME)
        fp.write(line)
        newlines.append(line)
    fp.close()

    try:
        util.verifyFileWrite(BOOT_CFG_PATH, ''.join(newlines))
    except IOError as ex:
        raise HandledError(str(ex))


def stageFirstBootScripts():
    log.info('Staging the first-boot scripts in %s' % STAGE_DIR)

    dst = FIRSTBOOT_DIR
    scriptDir = os.path.join(STAGE_DIR, dst.lstrip('/'))
    if os.path.exists(scriptDir):
       shutil.rmtree(scriptDir)
    os.makedirs(scriptDir)

    firstBootScripts = userchoices.getFirstBootScripts()
    for scriptChoice in firstBootScripts:
        script = scriptChoice['script']
        script.stage()

    # users has the script that sets the root password
    from . import users

    # keyboard has the script that sets the keymap
    from . import keyboard

    # esxlicense has the script that sets the .lic file
    from . import esxlicense

    # workarounds.scripts has scripts to fix host acceptance level and
    # Active Directory
    from .workarounds.scripts import AcceptanceLevelMigration, AdMigration

    configmodules = [users,keyboard,esxlicense,AcceptanceLevelMigration,AdMigration]

    for mod in configmodules:
       keyVals = mod.getFirstBootVals()
       for key in keyVals:
          addFirstBootCfg(key, keyVals[key])

    addFirstBootCfg("bootCfgPath", BOOT_CFG_PATH)

    copyFiles = []
    if userchoices.getInstall():
        # Clear out the PXEBootEnabled option from esx.conf before it gets
        # copied.
        log.debug("Clearing out the PXEBootEnabled flag whether it exists or not.")
        cmd = "esxcfg-advcfg -L PXEBootEnabled"
        rc, stdout, stderr = util.execCommand(cmd)

        from . import networking
        copyFiles = networking.getFirstBootConfigFiles()

    copyFiles.append(ESX_LOG_PATH)
    addFirstBootConfigFiles(copyFiles)

    copyFileToStage(RC_FIRSTBOOT_CFG, makeSticky=False)

def packageScripts():
    '''The scripts should be staged in directories /tmp/onetime/etc and
    /tmp/onetime/var.
    Package these dirs into the tgz file, /vmfs/volumes/(primary bootbank)/ontime.tgz
    '''
    log.info('packaging first-boot scripts to %s' % GZFILE_PATH)

    # Create the tarfile
    roots = os.listdir(STAGE_DIR)
    # roots += ' lib' # for vmkctl
    cmd = ['/bin/tar', '-C', STAGE_DIR, '-f', TARFILE_PATH, '-cv']
    cmd.extend(roots)

    util.execWithLog(cmd[0], cmd)

    # Now create the tgz
    fp = open(TARFILE_PATH)
    tarBytes = fp.read()
    fp.close()

    gzfp = gzip.GzipFile(GZFILE_PATH, 'w')
    if sys.version_info[0] >= 3:
       tarBytes = tarBytes.encode()
    gzfp.write(tarBytes)
    gzfp.close()

    try:
        util.verifyGzWrite(GZFILE_PATH, tarBytes)
    except IOError as ex:
        raise HandledError(str(ex))


if __name__ == '__main__':
    from . import sys
    # Never hard-code a valid serial number in this file.
    serial = sys.argv[1]
    from . import esxlicense
    userchoices.setSerialNumber(esx=serial)
    esxlicense.installAction()
    from . import users
    crypted = users.cryptPassword('asdfasdf')
    userchoices.setRootPassword(crypted, userchoices.ROOTPASSWORD_TYPE_CRYPT)
    users.applyUserchoices()
    hostAction()
