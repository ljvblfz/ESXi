#!/usr/bin/python
# **********************************************************
# Copyright 2011-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

from pluginApi import GenericProfile, Policy, ParameterMetadata, log, \
                      FixedPolicyOption, ProfileComplianceChecker, \
                      CreateLocalizedMessage, CreateLocalizedException, \
                      TASK_LIST_RES_OK, TASK_LIST_REQ_REBOOT, \
                      TASK_LIST_REQ_MAINT_MODE, CompareApplyProfile, \
                      CompareAnswerFile

from pyEngine.policy import NoDefaultOption

from pluginApi import CATEGORY_ADVANCED_CONFIG_SETTING, COMPONENT_SYSTEM_IMAGE_CONFIG
from pluginApi import ScrubHostProfile, ScrubAnswerFile, flattenUserKeys

from pluginApi.extensions import WasBootedFromStatelessCache

from pyEngine.applyConfigSpec import GetPXEBootedMac, APPLY_ANSWER_FILE, \
                                     APPLY_HOSTPROFILE_FILE

from pyVmomi import Vim, SoapAdapter
from pyVmomi.VmomiSupport import newestVersions

from vmware import runcommand

import crypt
import subprocess
import os
import sys
import tarfile
import gzip
import json
import tempfile
import time
import shutil
import string
from six import StringIO
import io
import six

import vmkctl

from vmware import runcommand

sys.path.append('/usr/lib/vmware')
from weasel import userchoices
from weasel import devices
from weasel import thin_partitions
from weasel import dd
from weasel import cache
from weasel import upgrade
from weasel.util import diskfilter

import vmware.esximage.Database
import vmware.esximage.Vib

#
# Define some constants first
#
STATELESS_TASK = 'stateless'
STATELESS_USB_TASK = 'stateless_usb'
STATEFUL_TASK = 'stateful'
STATEFUL_USB_TASK = 'stateful_usb'
HOST_PROFILE_CACHING_TASK = 'hostprofile.caching'

HOSTPROF_FILE = '/etc/vmware/hostprofile.xml.gz'
ANSFILE_FILE = '/etc/vmware/answerfile.xml.gz'

# Basic Message Keys
BASE_MSG_KEY = 'com.vmware.vim.profile.caching'
STATEFUL_INSTALL_KEY = '%s.stateful.install' % BASE_MSG_KEY
STATEFUL_INSTALL_USB_KEY = '%s.stateful.install.usb' % BASE_MSG_KEY
STATELESS_CACHING_KEY = '%s.stateless.caching' % BASE_MSG_KEY
STATELESS_CACHING_USB_KEY = '%s.stateless.caching.usb' % BASE_MSG_KEY
HOST_PROFILE_CACHING_KEY = '%s.hostprofile.caching' % BASE_MSG_KEY

FIRST_DISK_KEY  = '%s.first.disk' % BASE_MSG_KEY
OVERWRITE_VMFS_KEY = '%s.overwrite.vmfs' % BASE_MSG_KEY

STATEFUL_INSTALL_TASK_KEY = '%s.task' % STATEFUL_INSTALL_KEY
STATEFUL_INSTALL_USB_TASK_KEY = '%s.task' % STATEFUL_INSTALL_USB_KEY
STATELESS_CACHING_TASK_KEY = '%s.task' % STATELESS_CACHING_KEY
STATELESS_CACHING_USB_TASK_KEY = '%s.task' % STATELESS_CACHING_USB_KEY
HOST_PROFILE_CACHING_TASK_KEY = '%s.task' % HOST_PROFILE_CACHING_KEY
OVERWRITE_VMFS_TASK_KEY = '%s.task' % OVERWRITE_VMFS_KEY

# Compliance Error Message Keys
STATELESS_ESX_NOT_FOUND_KEY = '%s.esx.not.found' % STATELESS_CACHING_KEY
STATELESS_ESX_UNMATCHING_IMAGE_KEY = '%s.esx.unmatch.image' % STATELESS_CACHING_KEY
STATELESS_NOT_PXE_BOOTED_KEY = '%s.not.pxe.booted' % STATELESS_CACHING_KEY
STATEFUL_ESX_NOT_FOUND_KEY = '%s.esx.not.found' % STATEFUL_INSTALL_KEY

# Exception Message Keys
NO_ELIGIBLE_DISK_KEY = '%s.NoEligibleDiskEx' % BASE_MSG_KEY
CANNOT_PRESERVE_VMFS_KEY = '%s.CannotPreserveVmfsEx' % BASE_MSG_KEY
NO_HOSTPROFILE_KEY = '%s.NoHostProfileDocument' % BASE_MSG_KEY
COREDUMP_DISABLE_ERROR = '%s.CoreDumpDisableError' % BASE_MSG_KEY

DEFAULT_DISK_ORDER_STRING = "localesx,local"

STATELESS_TGZ = 'stateless.tgz'
ORIG_WAITER_TGZ_PATH = '/tardisks/waiter.tgz'

BEFORE_CACHE_LOG_TAR = 'befLogs.tgz'
AFTER_CACHE_LOG_TAR = 'aftLogs.tgz'
WAITER_TGZ = 'waiter.tgz'

# Constants for i18n key composition
UPDATEERROR_KEY = BASE_MSG_KEY + '.UpdateError.%s.label'
INVALID_FIRST_DISK_ARGS_KEY = 'InvalidFirstDiskArgs'

# Commands
CMD_SYSLOG_RELOAD = ['system', 'syslog', 'reload']
CMD_RESERVE_USB = ['system', 'settings', 'advanced', 'set', '-o',
                   '/UserVars/ReservedUsbDevice', '-s']
CMD_GET_USB = ['system', 'settings', 'advanced', 'list', '-o',
               '/UserVars/ReservedUsbDevice']
CMD_CD_PARTITION_DISABLE = ['system', 'coredump', 'partition', 'set', '-e',
                            'false']
CMD_CD_PARTITION_ENABLE = ['system', 'coredump', 'partition', 'set', '-s', '-e'
                           ,'true']
CMD_CD_FILE_DISABLE = ['system', 'coredump', 'file', 'set', '-e', 'false']
CMD_CD_FILE_ENABLE = ['system', 'coredump', 'file', 'set', '-s', '-e', 'true']

class FirstDiskNameValidator:
   """ First disk name shouldn't contain any non-ascii characters. """

   @staticmethod
   def Validate(obj, argName, arg, errors):
      if not isinstance(arg, six.string_types) or not arg.strip():
         errors.append(CreateLocalizedMessage(
                       obj, UPDATEERROR_KEY % INVALID_FIRST_DISK_ARGS_KEY))
         return False

      for c in arg:
         if ord(c) >= 128:
            errors.append(CreateLocalizedMessage(
                          obj, UPDATEERROR_KEY % INVALID_FIRST_DISK_ARGS_KEY))
            return False
      return True


# Since the parameters for stateful and stateless are the same, we'll just
# define that here
PARAM_DATA = [
   ParameterMetadata('firstDisk', 'string', False, DEFAULT_DISK_ORDER_STRING,
                     paramChecker = FirstDiskNameValidator),
   ParameterMetadata('overwriteVmfs', 'bool', False, False),
   ParameterMetadata('ignoreSsd', 'bool', False, False),
]

PARAM_USB_DATA = [
]

def serializeGzToTarFile(data, tarFile, filename):
   ''' Serialize and gzip compress an object into a specified file in a tar.
   '''
   dstBits = io.BytesIO(gzip.compress(SoapAdapter.Serialize(data,
               version=newestVersions.Get('vim'))))
   info = tarfile.TarInfo(filename)
   info.size = len(dstBits.getvalue())
   tarFile.addfile(info, dstBits)

def writeProfilePassword(userKeys, tarFile):
   ''' Add the profilePasswords.json to the tar file.
       This file contains a mapping from the user to the
       encrypted password.
   '''
   profPasswordsData = {}

   for user, password in userKeys.items():
      pwd = crypt.crypt(password,
                        crypt.mksalt(crypt.METHOD_SHA512))
      profPasswordsData[user] = pwd
      log.debug('Caching password for user: %s' % user)

   if profPasswordsData:
      log.info('Adding profilePasswords.json to tar...')
      s = json.dumps(profPasswordsData, separators=(',',':'))
      info = tarfile.TarInfo('etc/vmware/autodeploy/profilePasswords.json')
      import io
      content = io.BytesIO(str.encode(s))
      info.size = len(content.getvalue())
      tarFile.addfile(info, content)



def appendToKernelOpts(bootCfgPath, kernOpts):
   fp = open(bootCfgPath)
   lines = fp.readlines()
   fp.close()

   with open(bootCfgPath, 'wb') as fp:
      for line in lines:
         if line.startswith('kernelopt='):
            line = line.strip()
            line += ' %s\n' % kernOpts

         try:
            fp.write(line)
         except TypeError:
            fp.write(line.encode())


def addModuleToBootCfg(bootCfgPath, moduleName):
   fp = open(bootCfgPath)
   lines = fp.readlines()
   fp.close()

   with open(bootCfgPath, 'wb') as fp:
      for line in lines:
         if line.startswith('modules='):
            line = line.strip()
            line += ' --- %s\n' % moduleName

         try:
            fp.write(line)
         except TypeError:
            fp.write(line.encode())


def extractVMKBootOptions(hostServices):
   # Get the vmkernel.bootoptions from the host profile...
   vmkernelBootOpts = []

   configInfo = hostServices.hostConfigInfo.host.config
   optionDefDict = dict([ (x.key, x) for x in configInfo.optionDef ])

   for opt in configInfo.option:
      if opt.key.startswith('VMkernel.Boot.'):
         if not optionDefDict[opt.key].optionType.valueIsReadonly:
            if opt.value != optionDefDict[opt.key].optionType.defaultValue:
               vmkernelBootOpts += [ opt ]

   kernelOpts = []
   for opt in vmkernelBootOpts:
      optKey = opt.key.split('.', 2)[-1]
      kernelOpts += [ "%s=%s" % (optKey, opt.value) ]

   return kernelOpts


def getFirstDisksOrder(weaselDisks, firstDiskStr, ignoreSsd=False):

   filterList = diskfilter.getDiskFilters(firstDiskStr)
   notSsd = lambda disk: not disk.isSSD

   diskOrder = []
   cache = {}
   for diskFilter in filterList:
      filteredDisks = diskFilter(weaselDisks, cache)

      if ignoreSsd:
          filteredDisks = [disk for disk in filteredDisks if notSsd(disk)]

      for disk in filteredDisks:
         if disk not in diskOrder:
            diskOrder.append(disk)

   # XXX: There should be a way to return something like
   # TASK_LIST_RES_ERROR incase there aren't any disks for us.
   log.info("=== DISK ORDER ===")
   for disk in diskOrder:
      log.info("%s" % str(disk))
   log.info("=== DISK ORDER END ===")

   return diskOrder


def addHostDataToTar(hostTar):
   # Add the new hostprofile.xml and answerfile to the provided tar.
   tmpHostProfFile = os.environ.get(APPLY_HOSTPROFILE_FILE) or ""
   tmpAnsFile = os.environ.get(APPLY_ANSWER_FILE) or ""
   log.debug('Tmp host profile and answer file: %s, %s' % (tmpHostProfFile, tmpAnsFile))

   if os.path.exists(tmpHostProfFile):
      hostTar.add(tmpHostProfFile, HOSTPROF_FILE)
   elif os.path.exists(HOSTPROF_FILE):
      # There should not be a case where the hostprofile.tmp.gz is not present
      # but the hostprofile.xml.gz is. There is potential to clean this up
      # later.
      log.warn('Did not find temporary host profile at location: %s' % tmpHostProfFile)
      hostTar.add(HOSTPROF_FILE)
   else:
      # raise an exception
      log.error('Did not find original or temporary host profile document ' \
                'to cache')
      raise CreateLocalizedException(None, NO_HOSTPROFILE_KEY)
   if os.path.exists(tmpAnsFile):
      hostTar.add(tmpAnsFile, ANSFILE_FILE)
   elif os.path.exists(ANSFILE_FILE):
      log.info('Did not find temporary answerfile at location: %s' % tmpAnsFile)
      hostTar.add(ANSFILE_FILE)


def cacheWaiterTgz(diskName, hostServices, task=None):
   #
   # Now, we need to crack open waiter.tgz and stateless.tgz and repackage them
   # with the latest hostprofile and answerfile files.
   #
   c = cache.Cache(diskName)
   bbPath = c.altbootbankPath
   origWaiterTar = tarfile.open(ORIG_WAITER_TGZ_PATH, 'r')
   newWaiterTarPath = os.path.join(bbPath, WAITER_TGZ)
   newWaiterTar = tarfile.open(newWaiterTarPath, 'w')

   # Copy everything other than stateless.tgz directly into the new waiter tgz
   for member in origWaiterTar.getmembers():
      if member.name != STATELESS_TGZ:
         memberFile = origWaiterTar.extractfile(member)
         newWaiterTar.addfile(member, memberFile)

   # Now create a new version of stateless.tgz
   origStatelessFile = origWaiterTar.extractfile(STATELESS_TGZ)
   origStatelessTar = tarfile.open(fileobj=origStatelessFile)
   tmpStatelessTgzPath = os.path.join('/tmp', STATELESS_TGZ)
   newStatelessTar = tarfile.open(tmpStatelessTgzPath, 'w:gz')
   hostprofPath = HOSTPROF_FILE[1:]
   ansfilePath = ANSFILE_FILE[1:]

   # Cache the passwords in the host profile and answerfile
   # to etc/vmware/autodeploy/profilePasswords.json in waiter.tgz
   # during stateful remediation only.
   # TODO: During gtl we should determine if the passwords have changed
   # and execute the following only then as opposed to doing this for any
   # change in the host profile.
   hpObject = None
   afObject = None
   if not hostServices.postBoot and not hostServices.earlyBoot:
      log.info('Caching host profile passwords.')
      tmpHostProfFile = os.environ.get(APPLY_HOSTPROFILE_FILE)
      with gzip.open(tmpHostProfFile, 'rb') as f:
         hpObject = SoapAdapter.Deserialize(f.read())

      tmpAnsFile = os.environ.get(APPLY_ANSWER_FILE)
      if tmpAnsFile:
         with gzip.open(tmpAnsFile, 'rb') as f:
            afObject = SoapAdapter.Deserialize(f.read())

      userKeys = ScrubHostProfile(hpObject.applyProfile)
      ScrubAnswerFile(userKeys, afObject)
      userKeys = flattenUserKeys(userKeys, hpObject)
      writeProfilePassword(userKeys, newWaiterTar)

   for member in origStatelessTar.getmembers():
      if member.name not in [ hostprofPath, ansfilePath ]:
         if member.isfile():
            memberFile = origStatelessTar.extractfile(member)
            newStatelessTar.addfile(member, memberFile)
         else:
            newStatelessTar.addfile(member)

   if hpObject:
      serializeGzToTarFile(hpObject, newStatelessTar,
                     'etc/vmware/hostprofile.xml.gz')
      if afObject:
         serializeGzToTarFile(afObject, newStatelessTar,
                        'etc/vmware/answerfile.xml.gz')

   else:
      addHostDataToTar(newStatelessTar)
   # Next: add the hostprofile and answerfile to the new stateless.tgz

   # We're done with the rest of the tar's, except for the new waiter.tgz
   newStatelessTar.close()
   origStatelessTar.close()
   origWaiterTar.close()

   # Simply add the new stateless tar to the new waiter tar, and we're done-ish
   newWaiterTar.add(tmpStatelessTgzPath, os.path.join('/', STATELESS_TGZ))
   newWaiterTar.close()
   return bbPath


def performGenericCacheTask(hostServices, task, diskName, overwriteVmfs):
   userchoices.setEsxPhysicalDevice(diskName)
   userchoices.setPreserveVmfs(not overwriteVmfs)

   diskSet = devices.DiskSet()
   disk = diskSet[diskName]
   upgrade.checkForPreviousInstalls(disk)

   userchoices.setInstall(True)
   userchoices.setUpgrade(False)

   runcommand.runcommand('/bin/lsof > /tmp/openfile-before-unmount.txt')
   thin_partitions.installAction(persistUnmount=True)
   dd.installActionDDSyslinux()
   dd.installActionDDBootPart()
   dd.installActionWriteGUID()
   cache.installAction()

   # Now cache waiter.tgz, which will bundle in the latest copy of the
   # hostprofile and answerfile
   bbPath = cacheWaiterTgz(userchoices.getEsxPhysicalDevice(), hostServices,
                           task)

   # Should be done with waiter.tgz. Let's add it to boot.cfg
   bootCfgPath = os.path.join(bbPath, 'boot.cfg')
   addModuleToBootCfg(bootCfgPath, WAITER_TGZ)

   # The caching operation can take a long time. Let's reset the hostservices
   # to account for possible disconnects with VIM/hostd and CIM/SFCB.
   hostServices.Reset()


   # TODO: These sorts of calls should probably be moved off to the installer (cache.py).

   if task in [STATELESS_TASK, STATELESS_USB_TASK]:
      appendToKernelOpts(bootCfgPath, 'statelessCacheBoot')
   else:
      appendToKernelOpts(bootCfgPath, 'statefulInstallBoot')

   bootMac = GetPXEBootedMac()

   appendToKernelOpts(bootCfgPath, 'statelessBOOTIF=01-%s' % bootMac.replace(':', '-'))

   hpKernelOpts = extractVMKBootOptions(hostServices)
   appendToKernelOpts(bootCfgPath, ' '.join(hpKernelOpts))

   try:
      from . import appendBootCfg
      kernelOpts = appendBootCfg.GetKernelOpts()
      if kernelOpts:
         appendToKernelOpts(bootCfgPath, ' '.join(kernelOpts))
   except ImportError:
      # Logs are present in the imported module, so we can silent it here.
      pass

def UpdateScratchLocation(hostServices):
   """ Update the scratch location in hostd by invoking the hostd API
   """
   if hostServices.earlyBoot:
      return

   # Since scratch could get rearranged (mainly volume UIDs change) after a
   # caching/install task, the scratch value in hostd cache is not going to be
   # up to date
   # XXX: This is a workaround since there is no other way to tell hostd to
   # invalidate its cache.
   with open('/etc/vmware/locker.conf', 'r') as fileHandle:
      readData = fileHandle.read()

   if readData:
      # This code is called after the jumpstart plugin for scratch is run. So,
      # it cannot not be of format "<scratch path> <swap state>"
      scratchLocation = readData.split()[0]
      scratchOption = Vim.option.OptionValue()
      scratchOption.key = 'ScratchConfig.ConfiguredScratchLocation'
      scratchOption.value = scratchLocation

      configMgr = hostServices.hostSystemService.configManager
      configMgr.advancedOption.UpdateValues([scratchOption])


def BootedImageMatchesDisk(disk=None, cacheObj=None):
   if cacheObj is None:
      assert disk is not None, \
             'Neither cacheObj or disk parameters given for ' \
             'BootedImageMatchesDisk() method'
      cacheObj = cache.Cache(disk.name)
   activeBB = cacheObj.altbootbankPath
   lockerDbPath = os.path.join(cacheObj.lockerPath,
                               cache.ESXIMG_LOCKER_PACKAGES_DIR,
                               cache.ESXIMG_LOCKER_DB_DIR)

   # Read in the imgdb, see if it matches the one we booted.
   bbImgdb = cache.getDB(os.path.join(activeBB, cache.ESXIMG_DBTAR_NAME), isTar=True)
   lockerDb = cache.getDB(lockerDbPath, isTar=False)

   bootedImgdb = cache.getDB("/var/db/esximg")
   bootedLockerVibs = []

   # Taken from weasel's cache.py:rebuildDb
   # We need to extract the locker VIBs from our booted db.
   profile = bootedImgdb.profile
   vibs = bootedImgdb.vibs
   for vib in (vibs[vibid] for vibid in profile.vibIDs):
      if vib.vibtype == vib.TYPE_LOCKER:
         # Add it to our locker vib list, remove the vib from the
         # base image; also, don't save so we don't modify the
         # booted profile.
         log.info("Found a locker VIB in booted image: %s" % vib.id)
         bootedLockerVibs.append(vib)
         profile.RemoveVib(vib.id)
         vibs.RemoveVib(vib.id)

   if bbImgdb is not None \
      and bbImgdb.profile == bootedImgdb.profile:
         if bootedLockerVibs:
            if lockerDb:
               log.info("bootedLockerVibs: '%s'; lockerDb: '%s'"
                        % (bootedLockerVibs, list(lockerDb.vibs.values())))
               if bootedLockerVibs == list(lockerDb.vibs.values()):
                  log.info("Booted locker VIBs equal those in locker partition.")
                  # If we booted an image that has locker VIBs, make
                  # sure that the cached locker has the same VIBs
                  return True
            else:
               log.info("Booted image contained locker VIBs, but"
                        " there was no db in the locker partition.")
         else:
            # If we didn't boot with an image that has locker
            # VIBs, we don't particularly care if the cache has a
            # populated locker or not (we'll just leave it as
            # is); as long as our base image matches, we're fine.
            return True
   return False


class CachingProfileComplianceChecker(ProfileComplianceChecker):
   firstDisksOrder = None
   # In order to optimize the scanning for diskOrder, the SetFirstDisksOrder is
   # a method to pass in this ordering into the compliance checker. At a later
   # point, we should make this optimization through GatherData()
   @classmethod
   def SetFirstDisksOrder(cls, diskOrderVal):
      cls.firstDisksOrder = diskOrderVal

   @classmethod
   def CheckProfileCompliance(cls, profileInstances, hostServices, profileData, parent):
      log.info("Running a compliance check for stateful/stateless system cache.")
      cachingOption = profileInstances[0].CachingPolicy.policyOption
      if isinstance(cachingOption, (StatelessOption, StatelessUSBOption,
                                    StatefulOption, StatefulUSBOption)):
         machinePxe, weaselDisks, bootDisk = profileData

      complianceFailures = []

      if isinstance(cachingOption, (StatelessOption, StatelessUSBOption)):
         # We also need to have PXE'd to do stateless caching.
         if machinePxe:
            # Since we're stateless and there's actually no good way to find out
            # which disk is bootable or which disk the EFI/BIOS will boot to, we'll
            # have to search for the disk with ESXi.  We'll abuse the
            # getFirstDisksOrder function for that.
            log.info("The compliance check is checking for installs of ESXi.")

            diskOrder = cls.firstDisksOrder
            if not diskOrder:
               # Filter for only disks that they ask for.
               if isinstance(cachingOption, StatelessUSBOption):
                   # We need to force firstDiskStr to 'usb' since the USB policy
                   # options don't provide any place for a user to input a
                   # string, and we want to filter out just the USB disks for
                   # this policy option.
                   firstDiskStr = 'usb'
                   ignoreSsd = False
               else:
                   firstDiskStr = cachingOption.firstDisk
                   ignoreSsd = cachingOption.ignoreSsd

               log.info("Checking for disks of '%s' and ignorSsd:%s" % \
                        (firstDiskStr, ignoreSsd))

               filteredDisks = getFirstDisksOrder(weaselDisks, firstDiskStr, ignoreSsd)

               # Try to scan the disks
               diskOrder = getFirstDisksOrder(filteredDisks, 'esx')

               # Filter for disks with ESXi, leave out those with Classic.
               diskOrder = [x for x in diskOrder if x.containsEsx.esxi]

            if not diskOrder:
               failMsg = CreateLocalizedMessage(None, STATELESS_ESX_NOT_FOUND_KEY)
               complianceFailures.append(failMsg)
            else:
               compliantImage = False

               # Now, we see if we have the right version.
               # XXX: Do we want to check all of the disks?
               for disk in diskOrder:
                  if isinstance(cachingOption, StatelessUSBOption):
                     if not disk.isUSB:
                        log.info("Found an install of ESXi that isn't on USB.  Skipping.")
                        # If the user set the stateless usb cache and the disk
                        # we found with ESX isn't a USB disk, keep going.
                        continue

                  if BootedImageMatchesDisk(disk=disk):
                     compliantImage = True
                     break

               if not compliantImage:
                  failMsg = CreateLocalizedMessage(None, STATELESS_ESX_UNMATCHING_IMAGE_KEY)
                  complianceFailures.append(failMsg)

         else:
            # Check if the host booted from the stateless cache.
            # If not booted from cache, generate a compliance error.
            if not WasBootedFromStatelessCache():
               failMsg = CreateLocalizedMessage(None,
                                                STATELESS_NOT_PXE_BOOTED_KEY)
               complianceFailures.append(failMsg)
            else:
               log.info('This host has booted from a stateless cache.')

      elif isinstance(cachingOption, (StatefulOption, StatefulUSBOption)):
         if machinePxe or not bootDisk.containsEsx.esxi:
            failMsg = CreateLocalizedMessage(None, STATEFUL_ESX_NOT_FOUND_KEY)
            complianceFailures.append(failMsg)

      log.info('System image caching compliance check result: %s.' % complianceFailures)
      return (len(complianceFailures) == 0, complianceFailures)


def DoesProfileDiffer(profileInstances, firstDisksOrder, profileData):
   """  Check whether the hostprofile and the answer file on
        the cache match what is being applied (what's on the ramdisk).
   """
   log.info("Running a difference check for the updated hostprofile.")

   cachingOption = profileInstances[0].CachingPolicy.policyOption
   machinePxe, weaselDisks, bootDisk = profileData

   diskOrder = firstDisksOrder

   for disk in diskOrder:
      cacheObj = cache.Cache(disk.name)
      activeBB = cacheObj.altbootbankPath

      if BootedImageMatchesDisk(cacheObj=cacheObj):
         tarPath = os.path.join(activeBB, WAITER_TGZ)
         if os.path.exists(tarPath):
            #
            # Compare the host profile document
            #
            # First, crack open the outer tarball from the cache bootbank
            tarHandle = tarfile.open(tarPath, 'r')

            # Next, get the inner tarball
            statelessTar = tarHandle.extractfile(STATELESS_TGZ)
            statelessTarHandle = tarfile.open(fileobj=statelessTar)
            statelessTarMemberNames = statelessTarHandle.getnames()

            # Now get the hostprofile file out of the inner tarball
            tarHPFilePath = HOSTPROF_FILE[1:]   # drop the preceding '/' for extractfile
            if tarHPFilePath not in statelessTarMemberNames:
               log.info('Host profile not present in cache')
               statelessTarHandle.close()
               tarHandle.close()
               return (True, disk)

            tarHPFile = statelessTarHandle.extractfile(tarHPFilePath)
            gzipHandle = gzip.GzipFile(fileobj = tarHPFile, mode = 'rb')
            tarHPContents = gzipHandle.read()
            gzipHandle.close()

            tmpHostProfFile = os.environ.get(APPLY_HOSTPROFILE_FILE) or ""
            tmpAnsFile = os.environ.get(APPLY_ANSWER_FILE) or ""
            log.debug('DoesProfileDiffer found temp host profile and answerfile paths: %s, %s' % \
                     (tmpHostProfFile, tmpAnsFile))

            # Will tmp hostprofile.xml always exist?
            hpFile = HOSTPROF_FILE
            if os.path.exists(tmpHostProfFile):
               hpFile = tmpHostProfFile

            gzipHandle = gzip.open(hpFile, 'rb')
            gzHPContents = gzipHandle.read()
            gzipHandle.close()
            if not CompareApplyProfile(tarHPContents, gzHPContents, True):
               log.info('Host profile documents differ.')
               statelessTarHandle.close()
               tarHandle.close()
               return (True, disk)

            # Compare the answer file now
            ansFileInCache = False
            tarAnsFilePath = ANSFILE_FILE[1:] # drop the preceding '/' for extractfile
            if tarAnsFilePath in statelessTarMemberNames:
               statelessTarHandle.getmember(tarAnsFilePath)
               ansFileInCache = True
            else:
               log.info('Answer file is not present in the cache')
               ansFileInCache = False

            # Will tmp answerfile.xml always exist?
            ansFile = ''
            if os.path.exists(tmpAnsFile):
               ansFile = tmpAnsFile
            elif os.path.exists(ANSFILE_FILE):
               ansFile = ANSFILE_FILE

            if not ansFileInCache and not bool(ansFile):
               log.info('Answer file not present in the cache and the filesystem')
               statelessTarHandle.close()
               tarHandle.close()
               return (False, None)

            if (ansFileInCache and not bool(ansFile)) or \
               (not ansFileInCache and bool(ansFile)) :
               log.info('Answer file in cache: %s.  Answer file in filesystem: %s' \
                         % (ansFileInCache, bool(ansFile)))
               statelessTarHandle.close()
               tarHandle.close()
               return (True, disk)

            # If we have come here, it means answer file is present in both
            # cache and the file system
            tarAnsFile = statelessTarHandle.extractfile(tarAnsFilePath)
            gzipHandle = gzip.GzipFile(fileobj = tarAnsFile, mode = 'rb')
            tarAnsFileContents = gzipHandle.read()
            gzipHandle.close()

            gzipHandle = gzip.open(ansFile, 'rb')
            gzAnsFileContents = gzipHandle.read()
            gzipHandle.close()

            if not CompareAnswerFile(tarAnsFileContents, gzAnsFileContents, True):
               log.info('Answer files differ.')
               statelessTarHandle.close()
               tarHandle.close()
               return (True, disk)

            statelessTarHandle.close()
            tarHandle.close()

         # There is no need to look at other disks, since we found the one
         # where the cache is
         break

   return (False, None)


class StatelessOption(FixedPolicyOption):
   paramMeta = PARAM_DATA


class StatefulOption(FixedPolicyOption):
   paramMeta = PARAM_DATA


class StatelessUSBOption(FixedPolicyOption):
   paramMeta = PARAM_USB_DATA


class StatefulUSBOption(FixedPolicyOption):
   paramMeta = PARAM_USB_DATA


class CachingPolicy(Policy):
   possibleOptions = [ NoDefaultOption,
                       StatelessOption,
                       StatefulOption,
                       StatelessUSBOption,
                       StatefulUSBOption,
                     ]


class CachingProfile(GenericProfile):
   """A Host Profile that manages the stateful/stateless/no-op confuguration on ESXi hosts.
   """

   @staticmethod
   def MachinePXEBooted(hostServices):
      cmd = ['system', 'settings', 'advanced', 'list', '-o', '/UserVars/PXEBootEnabled']
      status, output = hostServices.ExecuteEsxcli(cmd)

      if not status:
         if len(output) == 1:
            if output[0]["Int Value"]:
               return True

      return False

   policies = [ CachingPolicy ]
   singleton = True

   category = CATEGORY_ADVANCED_CONFIG_SETTING
   component = COMPONENT_SYSTEM_IMAGE_CONFIG

   complianceChecker = CachingProfileComplianceChecker

   @classmethod
   def GatherData(cls, hostServices):
      """Retrieves the current settings for the host.
      """
      # Determine whether this host is PXE-booted.
      machinePxe = cls.MachinePXEBooted(hostServices)

      # Get all of the disks.
      weaselDiskSet = devices.DiskSet()

      # Figure out if we've booted to a certain disk.
      bootDisk = vmkctl.SystemInfoImpl().GetBootDevice()
      if bootDisk:
         bootDev = weaselDiskSet[bootDisk]
         upgrade.checkForPreviousInstalls(bootDev)
         bootDisk = bootDev
      else:
         bootDisk = None

      return (machinePxe, list(weaselDiskSet.values()), bootDisk)

   @classmethod
   def GenerateProfileFromConfig(cls, hostServices, profileData, parent):
      policyOpt = NoDefaultOption([])
      policy = CachingPolicy(True, policyOpt)
      return cls([policy])

   @classmethod
   def GenerateTaskList(cls, profileInstances, taskList, hostServices, profileData, parent):
      cachingOption = profileInstances[0].CachingPolicy.policyOption

      if isinstance(cachingOption, NoDefaultOption):
         log.info("User did not choose any caching option.")
         return TASK_LIST_RES_OK
      elif isinstance(cachingOption, (StatefulOption, StatelessOption)):
         if hostServices.earlyBoot:
            # If it's earlyBoot, don't generate a taskList...
            return TASK_LIST_RES_OK

         machinePxe, weaselDisks, bootDisk = profileData
         firstDiskStr = cachingOption.firstDisk
         overwriteVmfs = cachingOption.overwriteVmfs
         ignoreSsd = cachingOption.ignoreSsd

         log.info("System image cache profile settings: firstDiskStr: '%s' " \
                  "with overwriteVmfs: '%s' and ignoreSsd: '%s'."
                  % (firstDiskStr, overwriteVmfs, ignoreSsd))

         diskOrder = getFirstDisksOrder(weaselDisks,
                                        firstDiskStr,
                                        ignoreSsd=ignoreSsd)

         esxDiskOrder = getFirstDisksOrder(diskOrder, 'esx')
         CachingProfileComplianceChecker.SetFirstDisksOrder(esxDiskOrder)
         imgPassed, imgFailures = CachingProfileComplianceChecker.CheckProfileCompliance(
                              profileInstances, hostServices, profileData, parent)

         log.info("Image compliance passed: %s; Failures: %s" % (imgPassed, imgFailures))

         if isinstance(cachingOption, StatefulOption):
            log.info("User chose to make the host stateful.")

            # We need to check if the host is actually stateful or not before we
            # say "DO IT".
            if not imgPassed:
               TASK_MSG_KEY = STATEFUL_INSTALL_TASK_KEY
               taskList.addTask(None, STATEFUL_TASK)
            else:
               return TASK_LIST_RES_OK

         else:
            log.info("User chose to add a stateless cache to the host.")

            profDiff, chosenDisk = DoesProfileDiffer(profileInstances,
                                                esxDiskOrder, profileData)

            if not imgPassed and machinePxe:
               log.info("Complete stateless caching needs to be performed")
               TASK_MSG_KEY = STATELESS_CACHING_TASK_KEY
               taskList.addTask(None, STATELESS_TASK)
            elif profDiff:
               # Image is compliant with cache with PXE boot, but host profile
               # is not, cache the hostprofile only
               if chosenDisk is None:
                  log.error('Could not find the disk to cache to')
                  return TASK_LIST_RES_OK
               log.info("Host profile caching needs to be performed")
               taskMsg = CreateLocalizedMessage(None, HOST_PROFILE_CACHING_TASK_KEY)
               taskList.addTask(None, HOST_PROFILE_CACHING_TASK)
               taskList.addTask(taskMsg, chosenDisk.name)
               taskList.addTask(None, None)
               return TASK_LIST_RES_OK
            else:
               # Host profile is compliant, either the image is compliant
               # or not, but machine has not PXE booted. Do nothing.
               log.info("Not going to try caching. PXE boot: %s" % machinePxe)
               return TASK_LIST_RES_OK


         if not diskOrder:
            # Raise an exception that we found no eligible disks.
            exDict = { 'diskargs' : firstDiskStr }
            raise CreateLocalizedException(None, NO_ELIGIBLE_DISK_KEY, exDict)

         firstDisk = None
         for disk in diskOrder:
            upgrade.checkForPreserveVmfs(disk)
            if overwriteVmfs or not disk.vmfsLocation or disk.canSaveVmfs:
               firstDisk = disk
               break
            else:
               log.info("No overwriteVmfs option. Skipping %s" % disk.name)

         # If we found VMFS without an overwrite and we can't save it...
         if not firstDisk:
            diskstr = diskOrder[0].name
            if len(diskOrder) == 2:
               diskstr = diskstr + ',' + diskOrder[-1].name
            elif len(diskOrder) > 2:
               diskstr = diskstr + ',...,' + diskOrder[-1].name
            exDict = {'disk': diskstr}
            raise CreateLocalizedException(None, CANNOT_PRESERVE_VMFS_KEY, exDict)

         taskDict = {'disk' : firstDisk.name}
         taskMsg = CreateLocalizedMessage(None, TASK_MSG_KEY, taskDict)

         taskList.addTask(taskMsg, firstDisk.name)

         if overwriteVmfs:
            taskMsg = CreateLocalizedMessage(None, OVERWRITE_VMFS_TASK_KEY, taskDict)
         else:
            taskMsg = None

         taskList.addTask(taskMsg, overwriteVmfs)

         if isinstance(cachingOption, StatefulOption):
            return TASK_LIST_REQ_REBOOT
         else:
            return TASK_LIST_REQ_MAINT_MODE
      elif isinstance(cachingOption, (StatefulUSBOption, StatelessUSBOption)):
         machinePxe, weaselDisks, bootDisk = profileData

         if isinstance(cachingOption, StatefulUSBOption):
            log.info("User chose for a stateful install to a USB disk.")
            TASK_MSG_KEY = STATEFUL_INSTALL_USB_TASK_KEY
            taskList.addTask(None, STATEFUL_USB_TASK)
         else:
            log.info("User chose for stateless caching to a USB disk.")
            TASK_MSG_KEY = STATELESS_CACHING_USB_TASK_KEY
            taskList.addTask(None, STATELESS_USB_TASK)

         # Find the first USB disk ...
         usbDiskOrder = getFirstDisksOrder(weaselDisks, 'usb')

         if hostServices.earlyBoot:
            if not machinePxe:
               # Machine isn't pxe booted; don't do anything...
               taskList.clearTasks()
               return TASK_LIST_RES_OK

            if not usbDiskOrder:
               exDict = { 'diskargs' : 'usb' }
               raise CreateLocalizedException(None, NO_ELIGIBLE_DISK_KEY, exDict)

            firstDisk = usbDiskOrder[0]

            taskDict = { 'disk' : firstDisk.name }
            taskMsg = CreateLocalizedMessage(None, TASK_MSG_KEY, taskDict)
            taskList.addTask(taskMsg, firstDisk.name)

            # Set overwrite to False; it's the third item in the taskList
            taskList.addTask(None, False)
            log.info("Earlyboot: USB setup complete for use in remediate stage")
            return TASK_LIST_RES_OK
         elif hostServices.postBoot:
            # Again, we're going to abuse the compliancechecker for our own
            # selfish purposes.
            passed, failures = CachingProfileComplianceChecker.CheckProfileCompliance(
                                  profileInstances, hostServices, profileData, parent)

            if not usbDiskOrder:
               exDict = { 'diskargs' : 'usb' }
               raise CreateLocalizedException(None, NO_ELIGIBLE_DISK_KEY, exDict)

            if passed:
               # We've passed compliance check, but the host profile may differ.
               log.info("Postboot: USB already has correct stateful install or stateless caching on it")
               taskList.clearTasks()

               if isinstance(cachingOption, StatelessUSBOption):
                  profDiff, chosenDisk = DoesProfileDiffer(profileInstances,
                        usbDiskOrder, profileData)

                  if profDiff and machinePxe and chosenDisk:
                     # Clear the tasks, add the host profiles differ task.
                     taskMsg = CreateLocalizedMessage(None, HOST_PROFILE_CACHING_TASK_KEY)
                     taskList.addTask(None, HOST_PROFILE_CACHING_TASK)
                     taskList.addTask(taskMsg, chosenDisk.name)
                     taskList.addTask(None, None)
                     log.info("PostBoot: HostProfile cached on USB is stale, adding task %s" % HOST_PROFILE_CACHING_TASK)

               return TASK_LIST_RES_OK
            else:
               log.info("Postboot: USB does not have correct stateful install or stateless caching on it")
               # Otherwise, we should cache to the disk.
               return TASK_LIST_RES_OK
         else:
            # We're not in earlyBoot nor postBoot, so it's an apply from VC.
            # If we have a matching image, also check the host profile, if that
            # fails, fix the profile, otherwise reboot to fix the image.
            if usbDiskOrder:
               # If we got some USB disks in a VC apply state and we can find a
               # compliant image, we should check if the profiles match.
               # Note: we shouldn't do anything if we find a non-compliant image
               # because we can't be sure that the non-mounted USB stick is
               # actually for what we want it to be... we'll let the user reboot
               # and do its thing if that's what they want.
               passed, failures = CachingProfileComplianceChecker.CheckProfileCompliance(
                                    profileInstances, hostServices, profileData, parent)

               if passed:
                  taskList.clearTasks()
                  if isinstance(cachingOption, StatelessUSBOption):
                     profDiff, chosenDisk = DoesProfileDiffer(profileInstances,
                           usbDiskOrder, profileData)

                     if profDiff and machinePxe and chosenDisk:
                        # Clear the tasks, add the host profiles differ task.
                        taskMsg = CreateLocalizedMessage(None, HOST_PROFILE_CACHING_TASK_KEY)
                        taskList.addTask(None, HOST_PROFILE_CACHING_TASK)
                        taskList.addTask(taskMsg, chosenDisk.name)
                        taskList.addTask(None, None)

                  return TASK_LIST_RES_OK

            return TASK_LIST_REQ_REBOOT

   @classmethod
   def retryCoredumpFileEnable(cls, hostServices):
      # This function is called when smart enable of coredump file fails.
      # We need to first add a new vmkdump file and then enable it.
      cmd = ['system', 'coredump', 'file', 'add']
      status, output = hostServices.ExecuteEsxcli(cmd)
      if status != 0:
         log.error("Adding coredump file failed: %s" % output)
      else:
         cmd = ['system', 'coredump', 'file', 'set', '-s', '-e', 'true']
         status, output = hostServices.ExecuteEsxcli(cmd)
         if status != 0:
            log.error("Reactivating coredump file failed: "
                      "%s. Giving up" % output)
         else:
            log.info("Coredump file reactivated")


   @classmethod
   def disableCoredumpPartition(cls, hostServices):
      # Turn off coredump partition (if setup), it uses the vmkcore partition on disk.
      status, output = hostServices.ExecuteEsxcli('system coredump partition get')
      if status != 0:
         # TODO: Handle error case
         log.error('command to fetch coredump partition state failed: %s' % output)
         coredumpPartEnabled = False
      else:
         coredumpPartEnabled = output['Active']

      if coredumpPartEnabled:
         log.warn('Core dump partition is enabled. Disabling it')
         status, output = hostServices.ExecuteEsxcli(CMD_CD_PARTITION_DISABLE)
         log.warn("Shutting off coredump partition: %s:%s" % (status, output))
         if (status != 0):
            # It is safer not to proceed if coredump could not be stopped
            raise CreateLocalizedException(None, COREDUMP_DISABLE_ERROR)
      return coredumpPartEnabled

   @classmethod
   def disableCoredumpFile(cls, hostServices):
      # Turn off coredump file (if setup), it uses a vmfs volume on disk.
      status, output = hostServices.ExecuteEsxcli('system coredump file get')
      if status != 0:
         # TODO: Handle error case
         log.error('command to fetch coredump file state failed: %s' % output)
         coredumpFileEnabled = False
      else:
         coredumpFileEnabled = output['Active']
      if coredumpFileEnabled:
         log.warn('Core dump file is enabled. Disabling it')
         status, output = hostServices.ExecuteEsxcli(CMD_CD_FILE_DISABLE)
         log.warn("Shutting off coredump file: %s:%s" % (status, output))
         if (status != 0):
            # It is safer not to proceed if coredump could not be stopped
            raise CreateLocalizedException(None, COREDUMP_DISABLE_ERROR)
      return coredumpFileEnabled

   @classmethod
   def enableCoredumpPartition(cls, coredumpPartEnabled, hostServices):
      if not coredumpPartEnabled:
         return
      status, output = hostServices.ExecuteEsxcli(CMD_CD_PARTITION_ENABLE)
      if status != 0:
         log.error("Reactivating coredump partition failed :%s" % output)
      else:
         log.info("Coredump partition reactivated")

   @classmethod
   def enableCoredumpFile(cls, coredumpFileEnabled, hostServices):
     if not coredumpFileEnabled:
        return
     status, output = hostServices.ExecuteEsxcli(CMD_CD_FILE_ENABLE)
     if status != 0:
         log.warn("Reactivating coredump file failed: %s. Retrying" % output)
         cls.retryCoredumpFileEnable(hostServices)
     else:
         log.info("Coredump file reactivated")


   @classmethod
   def restoreScratchConfig(cls, hostservices):
      # Remove these two symlinks so that the jumpstart plugin will do its thing.
      os.remove('/locker')
      os.remove('/scratch')
      status, output = runcommand.runcommand(["/bin/jumpstart",
         "--plugin=libconfigure-locker.so"])
      log.info("Running libconfigure-locker.so: %s:%s" % (status, output))
      # Reload syslog
      status, output = hostservices.ExecuteEsxcli(CMD_SYSLOG_RELOAD)

      # PR1969213: See comment below.
      runcommand.runcommand(['/etc/init.d/rhttpproxy', 'pcap_reset'])

   @classmethod
   def backupScratchConfig(cls, hostservices):
      # We need to move symlinks so that we free up the FDs opened in scratch
      # XXX: We should also probably check to see if it's set to some
      # remote syslog.  If it is, there shouldn't be a need to reload syslog.
      curScratch = os.readlink('/scratch')
      log.info("Before caching, scratch points to: '%s'." % curScratch)
      scratchIsTmp = curScratch != '/tmp/scratch'
      tmpLogTarName = os.path.join('/tmp', BEFORE_CACHE_LOG_TAR)

      if scratchIsTmp:
         log.info("Resymlinking /scratch to /tmp/scratch")
         os.remove('/scratch')
         if not os.path.exists('/tmp/scratch'):
            os.mkdir('/tmp/scratch')
         os.symlink('/tmp/scratch', '/scratch')

         # Reload the syslog so that it uses the new symlink for scratch...
         status, output = hostservices.ExecuteEsxcli(CMD_SYSLOG_RELOAD)

         # PR1969213: rhttpproxy opens a packet capture file
         # at /var/run/log, which points to /scratch/log/ which
         # can potentially be on the device we are trying to install to.
         # These open files, hold the device and cause the installation to
         # fail. Therefore we need to close/reopen these files at the new
         # location for /scratch/log. This must happen after syslog
         # reloads as the syslog reload creates the /scratch/log dir.
         runcommand.runcommand(['/etc/init.d/rhttpproxy', 'pcap_reset'])

         # Make our tar of the logs after we move the log location.
         logsTar = tarfile.open(tmpLogTarName, 'w:gz')

         # PR1969213: As part of the rhttpproxy pcap_reset, the pcap files
         # are compressed to gz files. This can cause a race condition where
         # where we try to add a .pcap file to the tar, but that file has been
         # compressed to .pcap.gz and we get a file not found error for the
         # .pcap path. Therefore we filter out rhttpproxy pcap files.
         exPcapFiles = lambda x: all(s in x for s in ['rhttpproxy', 'pcap'])

         logsTar.add(os.path.join(curScratch, 'log'), 'caching/logs/before',
                     exclude=exPcapFiles)
         logsTar.close()
      return (scratchIsTmp, tmpLogTarName)

   @classmethod
   def backupVARLOG(cls, diskName):
      # We have to create a tarball with all the files in /var/log, and
      # symlinks need to be copied as actual files. So, iterate through all
      # files in /var/log and add each one to the tarball. If symlink, verify
      # that it is not broken and then add the actual file.
      tmpLogTarName = os.path.join('/tmp', AFTER_CACHE_LOG_TAR)
      try:
         logDir = '/var/log'
         files = cls.getFilePaths(logDir)
         logsTar = tarfile.open(tmpLogTarName, 'w:gz')
         for f in files:
            filename = f
            nameInTar = 'caching/logs/after/' + os.path.relpath(f, logDir)
            if os.path.islink(f):
               filename = os.path.realpath(f)
               if not os.path.isfile(filename):
                  continue
            logsTar.add(filename, nameInTar)
         logsTar.close()
      except Exception as err:
         log.error('Error while creating aftLogs.tgz: %s' % str(err))

      c = cache.Cache(diskName)
      shutil.copyfile(tmpLogTarName, os.path.join(c.altbootbankPath,
                                                  AFTER_CACHE_LOG_TAR))

   @classmethod
   def getFilePaths(cls, directory):
      """ Method to obtain all filepaths under a given directory.
      """
      filePathList = []
      for root, directories, files in os.walk(directory):
         for filename in files:
            filePath = os.path.join(root, filename)
            filePathList.append(filePath)
      return filePathList

   @classmethod
   def storeUSBDevice(cls, hostservices, diskName):
      # All we have to do here is reserve it for the postBoot part.
      CMD_RESERVE_USB.append(diskName)
      status, output = hostservices.ExecuteEsxcli(CMD_RESERVE_USB)
      log.info("Setting /UserVars/ReservedUsbDevice to '%s'; got back '%s:%s'."
               % (diskName, status, output))

   @classmethod
   def getUSBDevice(cls, hostservices):
      # If it's a postBoot, we have to get the USB disk from the UserVars
      diskName = None
      status, output = hostservices.ExecuteEsxcli(CMD_GET_USB)
      if not status:
          diskName = output[0]["String Value"]
          log.info("Got disk: '%s'" % diskName)
      else:
          log.error("esxcli call failed: '%s:%s'" % (status, output))
      return diskName

   @classmethod
   def RemediateConfig(cls, taskList, hostServices, profileData):
      # The first item in the task list should *always* be set.
      task = taskList[0]

      if task in [STATEFUL_USB_TASK, STATELESS_USB_TASK]:
         if hostServices.earlyBoot:
            try:
               diskName = taskList[1]
               overwriteVmfs = taskList[2]
            except IndexError as ex:
               log.warn("System image caching profile missing expected task"
                        " data; probably didn't PXE, exiting remediation for"
                        " USB caching/install.")
               return
            log.info("Early boot: %s to USB disk %s." % (task, diskName))
            cls.storeUSBDevice(hostServices, diskName)

         if hostServices.postBoot:
            diskName = cls.getUSBDevice(hostServices)
            if diskName:
               log.info("Caching to USB disk: '%s'." % diskName)
               # A USB which has been already partitioned will have
               # diagnostic partition which will get enabled during boot.
               # Disabling that partition prior to install.
               coredumpPartEnabled = cls.disableCoredumpPartition(hostServices)
               time.sleep(5)
               performGenericCacheTask(hostServices, task, diskName, False)

      if task in [STATEFUL_TASK, STATELESS_TASK]:
         diskName = taskList[1]
         overwriteVmfs = taskList[2]
         log.info("Post boot: %s to disk %s.  With overwriteVmfs:%s."
                   % (task, diskName, overwriteVmfs))

         # PR 969063, 1023805 - VSAN and VMFS traced hold open file handles on
         # the local partitions, so the relevant services are turned off before
         # caching operations begin.
         StopVsanServices()
         StopVmfsTraceService()
         StopCiscoNexusServices()
         scratchIsTmp, tmpLogTarName = cls.backupScratchConfig(hostServices)
         coredumpPartEnabled = cls.disableCoredumpPartition(hostServices)
         coredumpFileEnabled = cls.disableCoredumpFile(hostServices)
         time.sleep(5)
         log.info("Now caching to disk: %s" % diskName)
         performGenericCacheTask(hostServices, task, diskName, overwriteVmfs)

         # Copy over the tar to the bootbank, no need to add it to the boot.cfg
         if scratchIsTmp:
            c = cache.Cache(diskName)
            shutil.copyfile(tmpLogTarName, os.path.join(c.altbootbankPath,
                                                        BEFORE_CACHE_LOG_TAR))

      if hostServices.postBoot and task in [STATEFUL_TASK, STATEFUL_USB_TASK]:
         cls.backupVARLOG(diskName)
         runcommand.runcommand(["/bin/reboot"])
      elif hostServices.postBoot and task == STATELESS_USB_TASK:
         cls.enableCoredumpPartition(coredumpPartEnabled, hostServices)
      elif task == STATELESS_TASK:
         cls.enableCoredumpPartition(coredumpPartEnabled, hostServices)
         cls.enableCoredumpFile(coredumpFileEnabled, hostServices)
         cls.restoreScratchConfig(hostServices)
         # PR 969063 - VSAN holds open file handles on the scratch partition, so
         # the relevant services were turned off before caching operations began.
         # This op turns those vsan services back on again.
         StartVsanServices()
         StartVmfsTraceService()
         StartCiscoNexusServices()
         UpdateScratchLocation(hostServices)

      if task == HOST_PROFILE_CACHING_TASK:
         # Invoking the method to cache the waiter.tgz file will take care of
         # replacing the hostprofile and answerfile in the cache
         cacheWaiterTgz(taskList[1], hostServices, task)


def StartVsanServices():
   """Method to start services related to VSAN.
   """
   log.info('System image caching plugin starting vsan services')
   runcommand.runcommand('/etc/init.d/vsantraced start')


def StopVsanServices():
   """Method to start services related to VSAN.
   """
   log.info('System image caching plugin stopping vsan services')
   runcommand.runcommand('/etc/init.d/vsantraced stop')

def StartVmfsTraceService():
   """Method to start services related to VMFS.
   """
   log.info('System image caching plugin starting VMFS trace services')
   errCode, output = runcommand.runcommand('/etc/init.d/vmfstraced start')
   if errCode != 0:
      log.error("Failed to start VMFS trace services")

def StopVmfsTraceService():
   """Method to start services related to VMFS.
   """
   log.info('System image caching plugin stopping vmfs services')
   errCode, output = runcommand.runcommand('/etc/init.d/vmfstraced stop')
   if errCode != 0:
      log.error("Failed to stop VMFS trace services")

n1kVemServ = '/etc/init.d/n1k-vem'
def StartCiscoNexusServices():
   """Method to start the n1k-vem service from the cisco nexus vib
      PR1823400: The n1k-vem service creates files and a socket on
      the scratch partition. This was causing the install to fail when
      formatting the scratch partition. We therefore stop the service
      before the installation and start it after.
   """
   try:
      if os.path.exists(n1kVemServ):
         log.info('Starting n1k-vem service.')
         runcommand.runcommand('%s start' % n1kVemServ)
   except:
      log.exception('Failed to start n1k-vem service.')


def StopCiscoNexusServices():
   """Method to stop the n1k-vem service from the cisco nexus vib
   """
   try:
      if os.path.exists(n1kVemServ):
         log.info('Stopping n1k-vem service.')
         runcommand.runcommand('%s stop' % n1kVemServ)
   except:
      log.exception('Failed to stop n1k-vem service.')
