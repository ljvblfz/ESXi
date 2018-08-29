#!/usr/bin/python -u

"""
Copyright 2015 VMware, Inc.  All rights reserved.
-- VMware Confidential
This daemon monitors VSAN device latencies, congestion and
proactively unmounts slow/faulty devices from the cluster.

Main features:
. Monitor VSAN device latencies and trigger unmount of devices which has
  sustained delays over long sampling intervals.
. Monitor congestion on all the VSAN SSDs, pick the highest congestion,
  If average high congestion sustains longer than CONGESTION_TIME_INTERVAL
  seconds and the device itself is not slow, the device is unmounted to
  prevent a cluster meltdown.
"""
__author__ = "VMware, Inc"

import re
import sys
import os
import subprocess
import time
import random
import datetime
import string
from datetime import datetime
import threading
from vmware import vsi
from pathlib import Path
sys.path.append('/usr/lib/vmware/vsan/bin')
import json
import pyCMMDS
import esx.vob as dv
import logging
import logging.handlers
import six
if six.PY3:
   import configparser
else:
   import ConfigParser as configparser
from optparse import OptionParser, make_option

uncorrectableSectorsCountIdx = 0
reallocatedSectorsCountIdx = 1
reallocatedSectorsEventCountIdx = 2
pendingReallocatedSectorsCountIdx = 3
reportedUncorrectableErrorsCountIdx = 4
commandTimeoutsCountIdx = 5

pullThePlug = 0
#
# Controls DDH unmounting of slow tier one disks.  Both pullThePlug and
# pullThePlugOnTier1 must be enabled for DDH to unmount slow tier one disks.
# Disabled by default.
#
pullThePlugOnTier1 = 0
#
# Number of IO latency monitoring intervals to consider when deriving disk
# health.  Latency must exceed threshold for this many randomly selected time
# intervals within a designated time period (latencyMonitoringTimePeriod below)
# for a disk to be considered unhealthy.  Defaults to 5 five-minute intervals.
#
latencyMonitoringIntervalCount = 0
numberOfLatencyIntervals = 0
#
# Time duration in hours for consideration of IO latency time intervals when
# deriving disk health.  Defaults to four hours.
#
latencyMonitoringTimePeriod = 0
#
# Controls DDH remounting of failed disks, both tier one and tier two disks.
# Enabled by default.
#
remountAfterFailed = 0

#
# Maximum successful remount attempts per disk.
#
MAX_REMOUNT_ATTEMPTS = 10

# Max congestion sampling interval
CONGESTION_TIME_INTERVAL = 300  # Currently at 5 mins.
# Max congestion threshold value
MAX_CONGESTION_THRESHOLD = 256
LOG_CONGESTION_THRESHOLD = 251
# Gap in between device monitoring sampling trials (in seconds).  Should match
# the IORetry moving average interval for measuring IO latency for the monitored
# devices.
VSAN_SLEEP_INTERVAL = 300
VSAN_SLEEP_INTERVAL2 = 600
# Gap in between device monitoring sampling when VSAN is disabled
VSAN_DISABLED_SLEEP_INTERVAL = 600
# Gap in between congestion sampling trials (in seconds)
VSAN_CONGESTION_COLLECTION_DELAY = 60

# DDH internal state
VSAN_DISK_UNMOUNTED = -1

# VSAN device state
VSAN_DISK_HEALTHY = 0

# VSAN CMMDS Device Health
CMMDS_HEALTH_FLAG_NONE = 0
CMMDS_HEALTH_FLAG_DISK_FAILED = 16                         # (1 << 4)
CMMDS_HEALTH_FLAG_DYING_DISK_EVACUATING = 256              # (1 << 8)
CMMDS_HEALTH_FLAG_DYING_DISK_EVACUATE_FAILED = 512         # (1 << 9)
CMMDS_HEALTH_FLAG_DYING_DISK_EVACUATE_INACCESSIBLE = 1024  # (1 << 10)
CMMDS_HEALTH_FLAG_DYING_DISK_EVACUATED = 2048              # (1 << 11)

# LSOM Disk healthy state
VSAN_DISK_OK = 1

# PLOG disk unhealthy events
PLOG_MD_UNHEALTHY_EVENT = 10
VSAN_SSD_UNHEALTHY_EVENT = 11
VSAN_DISKGROUP_LOG_CONGESTED_EVENT = 12

# PLOG Device Health
PLOG_DEVICE_CACHE_UNHEALTHY  = 0x40000 # Caching tier disk is unhealthy
PLOG_DEVICE_UNHEALTHY        = 0x80000 # Capacity tier disk is unhealthy

# Devices with high IO latency
YellowDeviceList=[]
EvacuateDeviceList=[]

# Devices with bad SMART statistics
SMARTDeviceList=[]

# Devices that have DDH IO latency attribute mis-configurations and a warning
# message has already been logged to vmkernel log.
deviceAttributeWarningList=[]

#
# List of devices which are monitored for bad congestion.
# Also to prevent multiple congestion scans on the same device.
#
CongestionMonitoredList=[]

# A list of device objects
allDevices=[]

# A list of device objects, one for each failed disk
FailedTier1DeviceList=[]
FailedTier2DeviceList=[]

#
# Setup logging to syslog.
#

VSAN_DEVICE_MONITOR_DIRECTORY="/var/run/log"
VSAN_DEVICE_MONITOR_LOGFILE="/var/run/log/vsandevicemonitord.log"

_CMD_OPTIONS_LIST = [
      make_option('--loglevel', dest='loglevel', default=None,
                  help='Log level'),
      make_option('-L', '--logfile', dest='logfile', default=None,
                  help='Log file name'),
      make_option('--logsize', dest='logsize', default=None,
                  help='Log file size in MB'),
      make_option('--logrotate', dest='logrotate', default=None,
                  help='Number of log files to keep for rotation'),
      make_option('-?', action='help'),
]
_STR_USAGE = '%prog [start|stop|restart]'

#
## Parse syslog conf arguments.
#
def ParseOptions(argv):

   # Get command line options
   cmdParser = OptionParser(option_list=_CMD_OPTIONS_LIST,
                            usage=_STR_USAGE)

   (options, args) = cmdParser.parse_args(argv)
   try:
      # optparser does not have a destroy() method in older python
      cmdParser.destroy()
   except Exception:
      pass
   del cmdParser
   return (options)

#
# Load the options from config file
#
def LoadOptionsFromConfig(options, cfgFile):

   config = configparser.RawConfigParser()

   try:
      config.read(cfgFile)
   except Exception as err:
      logging.exception("Can't load conf file")
      return

   optionVars = vars(options)
   for optName in optionVars:
      opt = getattr(options, optName)

      # options should be with either string or boolean type
      try:
         if opt is None:
            value = config.get('VSANDEVICEMONITORD', optName)
            setattr(options, optName, value)
         elif opt == False:
            value = config.getboolean('VSANDEVICEMONITORD', optName)
            setattr(options, optName, value)
      except:
         pass

#
# Setup syslog handler.
#
def SetupLogging(options):

#
# Log to /var/run/log vsandevicemonitord.log file and setup log rotation
# handler and parameters (5 1-megabyte log files by default).
#
   logSizeMB = 1
   if options.logsize:
      logSizeMB = int(options.logsize)
   numLogFiles = 5
   if options.logrotate:
      numLogFiles = int(options.logrotate)

   print("vSAN Device Monitoring logging using %d log files each of size %d MB." %(numLogFiles,logSizeMB))

   logFile = VSAN_DEVICE_MONITOR_LOGFILE
   retryNumber = 0
   numRetries = 20
   logExists = False
   while ((logExists == False) and (retryNumber < numRetries)):
      #
      # Wait for /var/run/log symlink to be created.
      #
      logExists = os.path.exists(VSAN_DEVICE_MONITOR_DIRECTORY)
      if (logExists == False):
         retryNumber = retryNumber + 1
         time.sleep(retryNumber)

   #
   # Give up on logging but return now so we don't terminate daemon.
   #
   if (logExists == False):
      print("Syslog open failed")
      return

   handler = logging.handlers.RotatingFileHandler(filename=logFile,
                                        maxBytes=logSizeMB * 1024 * 1024,
                                        backupCount=numLogFiles - 1)
#
# Setup root logger config.
#
   logLevelMap = {'fatal': logging.CRITICAL,
                  'critical': logging.CRITICAL,
                  'error': logging.ERROR,
                  'warning': logging.WARNING,
                  'info': logging.INFO,
                  "debug": logging.DEBUG}
   logLevel = options.loglevel in logLevelMap and \
       logLevelMap[options.loglevel] or logging.INFO

   rootLogger = logging.getLogger()
   rootLogger.setLevel(logLevel)
   try:
      defaultAddress = '/dev/log'
      syslogHandler = logging.handlers.SysLogHandler(defaultAddress)
      if six.PY3:
         syslogHandler.append_nul = False
      rootLogger.addHandler(syslogHandler)
   except Exception as e:
      print("Syslog configuration failed %s" %e.args)

#
# Setup log formatter.
#
   logFormat = '%(asctime)s %(levelname)s vsandevicemonitord %(message)s'
   formatter = logging.Formatter(logFormat)
   handler.setFormatter(formatter)
   rootLogger.addHandler(handler)

   Log("logSizeMB = %d, numLogFiles = %d, logLevel = %s."
       %(logSizeMB, numLogFiles, logLevel))
   if (retryNumber > 0):
      Log("Issued %d retries for log file open." %retryNumber)

# Log to syslog.
def Log(message):
   try:
      logging.info(message)
   except Exception as e:
      print("Syslog write failed %s" %e.args)

#
# Execute the given command and return the <returnCode, stdout> tuple.
#
def ExecuteCmd(cmd, silent=True):
   p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
   result = p.communicate()[0]

   if not silent:
      print("Executing %s returned %d" % (' '.join(cmd), p.returncode))
      Log("Executing %s returned %d" % (' '.join(cmd), p.returncode))

   return p.returncode, result


# Helpers

#
# Determine if this ESX instance is running within a virtual machine.  Check
# vendor name field of bios info VSI node.  If the vendor field is
# "VMware, Inc.", ESX is running within a VM.
#
def IsHostVM():
   isVm = False
   output = vsi.get('/hardware/bios/dmiInfo')
   if (output != ""):
      value = output['vendorName']
      op = re.search("VMware", value)
      if op:
         isVm = True
   return isVm

def IsTier1Disk(dev):
   try:
      isTier1Disk = False
      output = vsi.get('/vmkModules/plog/devices/%s/info' %dev)
      if (output != ""):
         isTier1Disk = output['isSSD']
         if (isTier1Disk == 1):
            isTier1Disk = True
   except Exception as e:
      Log ("Failed to get plog device info")
   return isTier1Disk

def IsCachingDisk(dev):
   try:
      isCachingDisk = False
      output = vsi.get('/vmkModules/lsom/disks/%s/info' %dev)
      if (output != ""):
         diskType = output['type']
         if (diskType == 'cache'):
            isCachingDisk = True
   except Exception as e:
      Log ("Failed to get lsom disk info")
   return isCachingDisk

def IsCapacityDisk(dev):
   try:
      isCapacityDisk = False
      output = vsi.get('/vmkModules/lsom/disks/%s/info' %dev)
      if (output != ""):
         diskType = output['type']
         if (diskType == 'data'):
            isCapacityDisk = True
   except Exception as e:
      Log ("Failed to get lsom disk info")
   return isCapacityDisk

#
# Retrieve disk health entry from CMMDS
#
def GetCMMDSDiskHealthEntry(uuid):
   foundDiskHealth = 0
   diskHealthEntry = False
   retryNumber = 1
   numRetries = 1
   while ((foundDiskHealth == 0) and (retryNumber <= numRetries)):
      if (retryNumber != 1):
         time.sleep(retryNumber + 1)
      rc, diskHealthEntry, stderr = get_status_output(
           "cmmds-tool -f python find -t HEALTH_STATUS -u %s" % uuid)
      foundDiskHealth = len(eval(diskHealthEntry))
      retryNumber = retryNumber + 1

   return len(eval(diskHealthEntry)), diskHealthEntry if diskHealthEntry else False

def DiskHealthFromExpr(vsanExpr):
   return json.loads(vsanExpr)['healthFlags']

def GetDiskHealth(dev):
   try:
      diskHealth = VSAN_DISK_UNMOUNTED
      uuid = GetDeviceUuid(dev)
      if (uuid == ""):
         return diskHealth
      foundDiskHealth, diskHealthResults = GetCMMDSDiskHealthEntry(uuid)
      if (foundDiskHealth == False):
         return diskHealth
      diskHealthResults = eval(diskHealthResults)
      diskHealth = DiskHealthFromExpr(diskHealthResults[0]['content'])
   except Exception as e:
      return diskHealth
   return diskHealth

def IsEvacuatedDisk(dev):
   isEvacuatedDisk = False
   if (GetDiskHealth(dev) == CMMDS_HEALTH_FLAG_DYING_DISK_EVACUATED):
      isEvacuatedDisk = True
   return isEvacuatedDisk

def IsFailedDisk(dev):
   isFailedDisk = False
   if (GetDiskHealth(dev) == CMMDS_HEALTH_FLAG_DISK_FAILED):
      isFailedDisk = True
   return isFailedDisk

def IsUnhealthyDisk(dev):
   isUnhealthyDisk = False
   diskHealth = GetDiskHealth(dev)
   if ((diskHealth == CMMDS_HEALTH_FLAG_DYING_DISK_EVACUATING) or
       (diskHealth == CMMDS_HEALTH_FLAG_DYING_DISK_EVACUATE_FAILED) or
       (diskHealth == CMMDS_HEALTH_FLAG_DYING_DISK_EVACUATE_INACCESSIBLE) or
       (diskHealth == CMMDS_HEALTH_FLAG_DYING_DISK_EVACUATED)):
      isUnhealthyDisk = True
   return isUnhealthyDisk

def IsUnhealthyCachingDisk(dev):
   try:
      isUnhealthyDisk = False
      output = vsi.get('/vmkModules/lsom/disks/%s/info' %dev)
      if (output != ""):
         diskState = output['state']
         if (diskState != VSAN_DISK_OK):
            isUnhealthyDisk = True
   except Exception as e:
      Log ("Failed to get lsom disk state")
   return isUnhealthyDisk

def GetDedupScope(dev):
   try:
      dedupScope = 0
      output = vsi.get('/vmkModules/plog/devices/%s/dedupStats' % dev)
      if (output != ""):
         dedupScope = output['dedupScope']
   except Exception as e:
      Log ("Failed to get plog dedup scope")
   return dedupScope

def GetDeviceCapacity(dev):
   capacity = 0
   try:
      output = vsi.get('/vmkModules/plog/devices/%s/dedupStats' % dev)
      if (output != ""):
         capacity = output['totalBytes']
   except Exception as e:
      Log ("Failed to get plog dev %s dedup capacity" % dev)
   return capacity

def GetVSANMappings():
   global tier2ToTier1

   tier2ToTier1.clear()
   try:
      mappings = vsi.list('/vmkModules/plog/mappings')
      for m in mappings:
         output = vsi.get('/vmkModules/plog/mappings/%s/info' % m)
         if (output != ""):
            tier1Disk=output['ssdDiskName']
            tier2Disks = output['mappedMDs'].split(", ")
            for tier2Disk in tier2Disks:
               tier2ToTier1[tier2Disk] = tier1Disk
   except Exception as e:
      Log ("Failed to get plog mappings")

def GetVSANDevices():
   global dedupScope
   tier1Disks=[]
   tier2Disks=[]
   disks = vsi.list('/vmkModules/plog/devices')
   dedupScope.clear()
#
# Scan first for tier 1 disks, then tier 2 disks.
#
   for d in disks:
      dedupScope[d] = GetDedupScope(d)
      if IsTier1Disk(d):
         tier1Disks.append(d)
         if IsFailedDisk(d):
            if remountAfterFailed:
               getDevice(d, True).MakeDeviceRemountable(True)

   for d in disks:
      dedupScope[d] = GetDedupScope(d)
      if not IsTier1Disk(d):
         tier2Disks.append(d)
         if IsFailedDisk(d):
            if remountAfterFailed:
               getDevice(d, False).MakeDeviceRemountable(True)

   return(tier1Disks, tier2Disks)

def GetVSANDisks():
   cachingDisks=[]
   disks = vsi.list('/vmkModules/lsom/disks')
   for d in disks:
      if IsCachingDisk(d):
         cachingDisks.append(d)

   return(cachingDisks)

def GetCapacityDisks():
   capacityDisks=[]
   disks = vsi.list('/vmkModules/lsom/disks')
   if disks == "":
      return(capacityDisks)

   for d in disks:
      if IsCapacityDisk(d):
         capacityDisks.append(d)

   return(capacityDisks)

class badness(dv.uint32):
    def _argtype(self):
       return dv.MSGFMT_ARG_STRING8

#
# Create new device object or retrieve existing device object.
#
def getDevice(name, isTier1Disk):
    global dedupScope, tier2ToTier1
    VSAN_DEDUP_SCOPE_DISKGROUP = 2

    foundDev = False
    diskName = name
    parentDiskName = ""
    isMappedTier2Disk = False

    if not isTier1Disk and diskName in dedupScope and dedupScope[diskName] == VSAN_DEDUP_SCOPE_DISKGROUP:
       if diskName in tier2ToTier1:
          parentDiskName = tier2ToTier1[diskName]
          isMappedTier2Disk = True

    for d in allDevices:
       if (d.name == diskName):
          foundDev = True
          returnDev = d

    if (foundDev == False):
      returnDev = device(diskName, isTier1Disk)

    if ((returnDev.parentDev == returnDev) and (isMappedTier2Disk == True)):
       for d in allDevices:
          if (d.name == parentDiskName):
             returnDev.SetIsMappedTier2Disk(isMappedTier2Disk, d)
#             Log("Adding child dev %s to parent dev %s." %(returnDev.name,d.name))
             d.childDevs.append(returnDev)

#    Log ("getDevice object with name %s and parent %s" %(returnDev.name,returnDev.parentDev.name))

    return returnDev

# Wrapper function for python3 compatibility
# This function replaces the command.getoutput and commands.getstatusoutput calls.
# NOTE: limited tests with python3 due to lack of expertise
#       resources in this area at the time of this change
def get_status_output(cmd):
   cmd = cmd.split()
   p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
   stdout, stderr = p.communicate()
   return p.returncode, stdout, stderr

#
# Device class to retain recent history of IO latency intervals and previous
# disk re-mount attempts.
#
class device:

    def __init__(self, name, isTier1Disk):
       self.name = name
       self.parentDev = self
       self.childDevs = []
       self.isRemountable = True
       self.isFailedDisk = False
       self.isTier1Disk = isTier1Disk
       self.isMappedTier2Disk = False
       self.remountAttempts = 0
       self.successfulRemountAttempts = 0
       self.failStartTime = datetime.now()
       self.latencyIntervalCount = 0
       self.latencyThresholdExceededCount = 0
       self.mostRecentLatencyIntervalThresholdExceeded = 0
       self.sampleLatencyIntervals = []
       self.logCongestionIntervals = 0
       self.startPlogSegnoValid = False
       self.startPlogSegno = 0
       self.startLlogSegnoValid = False
       self.startLlogSegno = 0
       self.logPrepareAverageLatencyIntervals = 0
       allDevices.append(self)
#       Log ("Created device object with name %s" % name)

#
# Useful for debugging only.
#
#    def __del__(self):
#       Log ("Deleted device object.")

#
# Indicate that device represents a mapping from tier 2 disk to tier 1 disk.
#
    def SetIsMappedTier2Disk(self, isMapped, device):
       self.isMappedTier2Disk = isMapped
       self.parentDev = device

#
# Make disk eligible for remount.
#
    def MakeDeviceRemountable(self, isFailedDisk):
       global dedupScope, tier2ToTier1
       VSAN_DEDUP_SCOPE_DISKGROUP = 2
       if not self.isTier1Disk and self.name in dedupScope and dedupScope[self.name] == VSAN_DEDUP_SCOPE_DISKGROUP:
          dev = self.parentDev
       else:
          dev = self
#       Log ("MakeDeviceRemountable %s,%s" %(dev.name,dev.parentDev.name))

       if (dev.isRemountable and isFailedDisk):
          dev.isFailedDisk = isFailedDisk
          if dev.isTier1Disk:
             if dev not in FailedTier1DeviceList:
                FailedTier1DeviceList.append(dev)
                dev.failStartTime = datetime.now()
                dev.remountAttempts = 0
          else:
             if dev not in FailedTier2DeviceList:
                FailedTier2DeviceList.append(dev)
                dev.failStartTime = datetime.now()
                dev.remountAttempts = 0


    def IsDeviceUnmounted(self):
       unmounted = False
       if not IsDeviceMounted(self.name):
          unmounted = True
          if self.isTier1Disk:
             numDevices = len(self.childDevs)
             while numDevices > 0:
                dev = self.childDevs[numDevices - 1]
                if IsDeviceMounted(dev.name):
#                   Log("Tier2 disk %s is __NOT__ unmounted." %dev.name)
                   unmounted = False
                numDevices = numDevices - 1
       return unmounted


#
# Check if the disk represented by the object is no longer in a state where
# it needs to be re-mounted. That is for disks previously failed by LSOM,
# the disk has already been (manually) unmounted and re-mounted and is
# no longer in a failed state.  If so, remove the disk's object from the
# failed disk list.
#
    def IsDeviceRemounted(self):
       if IsDeviceMounted(self.name) and not IsFailedDisk(self.name):
#
# If tier1 disk, make sure all of the tier2 disks are also properly mounted
# since sometimes this is not the case if IO error writing to one of the tier2
# disks during unmount.
#
          remounted = True
          if self.isTier1Disk:
             numDevices = len(self.childDevs)
             while numDevices > 0:
                dev = self.childDevs[numDevices - 1]
                if not IsDeviceMounted(dev.name) or IsFailedDisk(dev.name):
#                   Log("Tier2 disk %s is __NOT__ mounted or failed." %dev.name)
                   remounted = False
                numDevices = numDevices - 1
             if (remounted == True):
                if self in FailedTier1DeviceList:
#                   Log("Removing device %s from Failed List." %self.name)
                   FailedTier1DeviceList.remove(self)
          else:
             if (remounted == True):
                if self in FailedTier2DeviceList:
#                   Log("Removing device %s from Failed List." %self.name)
                   FailedTier2DeviceList.remove(self)
          return (remounted == True)

       return False


#
# Re-mount fail'ed device if config variable, 'lsomSlowDeviceRemount' is set
#
    def RemountFailedDevice(self, lastAttempt):
       unMounted = self.UnmountDevice(lastAttempt)
       if unMounted:
#          Log("Device %s unmounted successfully." %self.name)
          mounted = MountDevice(self.name, self.isTier1Disk, self.remountAttempts, lastAttempt)
          return mounted
       else:
          return False


#
# Try to remount the  disk.
#
    def RemountDevice(self):

       global dedupScope, tier2ToTier1
       VSAN_DEDUP_SCOPE_DISKGROUP = 2
       if not self.isTier1Disk and self.name in dedupScope and dedupScope[self.name] == VSAN_DEDUP_SCOPE_DISKGROUP:
#
# Use the caching tier disk for dedup enabled disk groups since the remount
# state/context information will be kept in one place.
#
          dev = self.parentDev
       else:
          dev = self

#
# Check if the disk represented by the object is no longer in a state where
# it needs to be re-mounted (e.g., the disk was manually re-mounted). If so,
# reset the state that throttles future re-mount attempts.
#
       if (dev.IsDeviceRemounted() == True):
          dev.isRemountable = True
          dev.remountAttempts = 0
          dev.successfulRemountAttempts = 0
          dev.failStartTime = 0
          return False

#
# Otherwise, try to re-mount the disk if not throttled by either unsuccessful
# or successful remount limits.
#
       if dev.isRemountable:
          dev.remountAttempts += 1

          if (dev.successfulRemountAttempts < MAX_REMOUNT_ATTEMPTS):
#
# DDH will attempt to remount a failed disk for remountAfterFailedTimePeriod
# seconds after the failure is first detected.  No further attempts will be
# made to remount the failed disk after that point in order to avoid
# thrashing with fail/unmount/remount sequence.
# Remount attempts are done at the same rate as the disk monitor polling rate.
#
             secs = (datetime.now() - dev.failStartTime).seconds
             if (secs < remountAfterFailedTimePeriod):

#
# Failed disks need to be unmounted before they are re-mounted. Pass on
# indication if this will be the last remount attempt for this disk/diskgroup.
#
                sleepInterval = GetSleepInterval()
                if ((secs + (2 * sleepInterval)) >= remountAfterFailedTimePeriod):
                   lastAttempt = True
                else:
                   lastAttempt = False
                remounted = dev.RemountFailedDevice(lastAttempt)
                if remounted:
                   #
                   # Track the # of successful remount attempts.
                   #
                   dev.successfulRemountAttempts += 1
                   return True
                else:
                   return False
             else:
                #
                # Give up on re-mount attempts due to excessive time.
                #
                Log("Not re-mounting failed disk %s due to throttling after %d unsuccessful re-mount attempts." %(dev.name, (dev.remountAttempts - 1)))
                dev.isRemountable = False
          else:
             #
             # Must throttle even the successful attempts at re-mounting
             # a failed disk so DDH does not thrash continually remounting
             # a disk after repeatedly incurring the same (e.g., media error)
             # error.
             #
             Log("Not re-mounting failed disk %s due to throttling after %d successful re-mount attempts." %(dev.name, dev.successfulRemountAttempts))
             dev.isRemountable = False

       return False

#
# Record history of excessive IO latency for the  disk.
#

    def MarkSlowDevice(self, isSlow, isRead, logStr):
#
# Do not track excessive read IO latency.
#
       if not isRead:
          if self.latencyIntervalCount == 0:
             self.mostRecentLatencyIntervalThresholdExceeded = 0

#
# List of integers representing the ordinal value of a particular time interval
# within a time period of duration latencyMonitoringTimePeriod minutes.  Each
# time interval is a sleepInterval seconds in length.  These are the intervals
# that will actually be sampled.  Currently, 60% of the intervals are sampled.
#
             self.sampleLatencyIntervals = random.sample(list(range(numberOfLatencyIntervals)), 3 * latencyMonitoringIntervalCount)
             self.sampleLatencyIntervals.sort()
             Log ("Sample latency intervals for %s are %s." %(self.name, self.sampleLatencyIntervals))

          if isSlow:
             Log(logStr)
             Log("Latency monitoring interval # is %d for device %s." %(self.latencyIntervalCount, self.name))
             dv.DynamicEvent(logStr, badness(0xDEADBEEF)).send()
#
# Check for next randomly selected interval.  Carefully avoid consecutive
# intervals.  Interval ordinal values range from 0 to numberOfLatencyIntervals
# minus one.
#
             if self.latencyIntervalCount in self.sampleLatencyIntervals and ((self.latencyIntervalCount > (self.mostRecentLatencyIntervalThresholdExceeded + 1)) or (self.latencyThresholdExceededCount == 0)):
                self.latencyThresholdExceededCount += 1
                Log("Number of monitored intervals with excessive latency is %d for device %s." %(self.latencyThresholdExceededCount, self.name))
                self.mostRecentLatencyIntervalThresholdExceeded = self.latencyIntervalCount

#
# Consider disk unhealthy if latencyMonitoringIntervalCount number of
# randomly selected intervals spread over some number of hours show excessive
# disk IO latency.
#
             if (self.latencyThresholdExceededCount >= \
                latencyMonitoringIntervalCount):
                if self.name in YellowDeviceList:
                   YellowDeviceList.remove(self.name)
                if pullThePlug and (not self.isTier1Disk or \
                                    self.isMappedTier2Disk or \
                                    pullThePlugOnTier1):
                   if self not in EvacuateDeviceList:
                      EvacuateDeviceList.append(self)

             self.latencyIntervalCount += 1
             if self.latencyIntervalCount == (numberOfLatencyIntervals - 1):
                self.latencyIntervalCount = 0
                self.latencyThresholdExceededCount = 0

          else:
             self.latencyIntervalCount += 1
             if self.latencyIntervalCount == (numberOfLatencyIntervals - 1):
                self.latencyIntervalCount = 0
                self.latencyThresholdExceededCount = 0

#
# Mark log congestion as acceptableand record plog/llog start points.
#
    def MarkLogDeviceAcceptable(self, startPlogSegno, startLlogSegno):
       self.logCongestionIntervals = 0
       self.startPlogSegno = startPlogSegno
       self.startPlogSegnoValid = True
       self.startLlogSegno = startLlogSegno
       self.startLlogSegnoValid = True

#
# Record history of excessive log congestion for the caching tier disk.
# Diagnose disk as unhealthy if the log congestion endures for a specified
# threshold number of monitoring intervals while the start point for either
# the llog or plog does not budge.
#
    def MarkLogCongestedDevice(self, startPlogSegno, startLlogSegno):

       #
       # Check if congestion is accompanied with either plog or llog start
       # log position not moving over time.
       #
       if ((self.startPlogSegnoValid and (self.startPlogSegno == \
           startPlogSegno)) or (self.startLlogSegnoValid and
           (self.startLlogSegno == startLlogSegno))):

          self.logCongestionIntervals = self.logCongestionIntervals + 1

          logStr = "WARNING - Maximum log congestion on VSAN device %s " \
                   "%d/%d times." %(self.name, self.logCongestionIntervals, \
                   logCongestionMonitoringIntervalCount)
          Log(logStr)
          dv.DynamicEvent(logStr, badness(0xDEADBEEF)).send()

          #
          # If the log congestion persists across a specified # of monitoring
          # intervals we diagnose the disk as unhealthy.
          #
          if (self.logCongestionIntervals >=
              logCongestionMonitoringIntervalCount):
             Log("Found congestion: Evacuating disk %s.." % (self.name))
             if self not in EvacuateDeviceList:
                EvacuateDeviceList.append(self)
       else:
          #
          # Reset things if at maximum congestion but active portion of log is
          # moving.
          #
          self.MarkLogDeviceAcceptable(startPlogSegno, startLlogSegno)

#
# Mark log prepare latency as acceptable.
#
    def MarkPrepareLatencyAcceptable(self):
       self.logPrepareAverageLatencyIntervals = 0

#
# Record history of excessive log prepare latency for the caching tier disk.
# Diagnose disk as unhealthy if the log prepare latency lasts for a specified
# threshold number of consecutive monitoring intervals.
#
    def MarkExcessivePrepareLatency(self, prepareAverageLatency,
                                    prepareAverageLatencyThreshold):

       self.logPrepareAverageLatencyIntervals = \
          self.logPrepareAverageLatencyIntervals + 1

       logStr = "WARNING - Excessive log prepare average latency %d has " \
                "exceeded threshold %d on VSAN device %s %d/%d times." \
                %(prepareAverageLatency, prepareAverageLatencyThreshold, \
                  self.name, self.logPrepareAverageLatencyIntervals, \
                  logPrepareAverageLatencyMonitoringIntervalCount)
       Log(logStr)
       dv.DynamicEvent(logStr, badness(0xDEADBEEF)).send()

       if (self.logPrepareAverageLatencyIntervals >=
           logPrepareAverageLatencyMonitoringIntervalCount):
          if self not in EvacuateDeviceList:
             EvacuateDeviceList.append(self)

#
# Try to unmount the  disk.
#
    def UnmountDevice(self, lastAttempt):
      unmounted = UnmountDevice(self.name, self.isTier1Disk,
                                self.isMappedTier2Disk, self.remountAttempts,
                                lastAttempt)
#
# Ignore error from UnmountDevice since it may return error if the
# disk/diskgroup is already unmounted.
#
      if self.IsDeviceUnmounted():
         return True
      else:
         return False

    def GetAggregateCapacity(self):
      global dedupScope
      VSAN_DEDUP_SCOPE_DISKGROUP = 2
      capacity = 0

      if self.isTier1Disk:
         if not self.name in dedupScope:
            dedupScope[self.name] = GetDedupScope(self.name)

         if dedupScope[self.name] == VSAN_DEDUP_SCOPE_DISKGROUP:
            capacity = GetDeviceCapacity(self.name)
         else:
            for d in self.childDevs:
               capacity += GetDeviceCapacity(d)
      else:
         capacity = GetDeviceCapacity(self.name)
      return capacity

def GetSleepInterval():
   return vsi.get('/config/LSOM/intOpts/lsomDeviceMonitorInterval')['cur']

def GetLogCongestionPersonality():
   return vsi.get('/config/LSOM/intOpts/lsomDeviceMonitorLogCongestion')['cur']

def GetLogCongestedIntervalCount():
   return vsi.get('/config/LSOM/intOpts/lsomDeviceMonitorLogCongestedIntervals')['cur']

def GetLogPrepareAverageLatencyPersonality():
   return vsi.get('/config/LSOM/intOpts/lsomDeviceMonitorLogPrepareLatency')['cur']

def GetLogPrepareAverageLatencyIntervalCount():
   return vsi.get('/config/LSOM/intOpts/lsomDeviceMonitorLogPrepareLatencyIntervals')['cur']

def GetRemountFailedDeviceTimePeriod():
   return vsi.get('/config/LSOM/intOpts/lsomFailedDeviceRemountPeriod')['cur']

def GetUnmountPersonality():
   return vsi.get('/config/LSOM/intOpts/lsomSlowDeviceUnmount')['cur']

def GetTier1UnmountPersonality():
   return vsi.get('/config/LSOM/intOpts/lsomSlowTier1DeviceUnmount')['cur']

def GetSlowDeviceRemountPersonality():
   return vsi.get('/config/LSOM/intOpts/lsomSlowDeviceRemount')['cur']

def GetFailedDeviceRemountPersonality():
    return vsi.get('/config/LSOM/intOpts/lsomFailedDeviceRemount')['cur']

def DeviceMonitoringDisabled():
   return vsi.get('/config/LSOM/intOpts/VSANDeviceMonitoring')['cur']

def DeviceMonitoringIfVM():
   return vsi.get('/config/LSOM/intOpts/VSANDeviceMonitoringIfVM')['cur']

def GetSlowDeviceMonitoringIntervalCount():
   return vsi.get('/config/LSOM/intOpts/lsomSlowDeviceLatencyIntervals')['cur']

def GetSlowDeviceMonitoringTimePeriod():
   return vsi.get('/config/LSOM/intOpts/lsomSlowDeviceLatencyTimePeriod')['cur']

def GetReadLatencyThreshold(dev):
   return vsi.get('/vmkModules/plog/devices/%s/health/movingAverageReadLatencyThreshold' %dev)

def GetWriteLatencyThreshold(dev):
   return vsi.get('/vmkModules/plog/devices/%s/health/movingAverageWriteLatencyThreshold' %dev)

def GetReadPrepareAverageLatencyThreshold(disk):
   return vsi.get('/vmkModules/lsom/disks/%s/health/readPrepareAverageLatencyThreshold' %disk)

def GetWritePrepareAverageLatencyThreshold(disk):
   return vsi.get('/vmkModules/lsom/disks/%s/health/writePrepareAverageLatencyThreshold' %disk)

def GetUnmapPrepareAverageLatencyThreshold(disk):
   return vsi.get('/vmkModules/lsom/disks/%s/health/unmapPrepareAverageLatencyThreshold' %disk)

def GetLatencyInterval(dev):
   return vsi.get('/vmkModules/plog/devices/%s/health/movingAverageLatencyInterval' %dev)

def GetVSANNodeHealth():
   cmd = "esxcli --formatter=keyvalue vsan cluster get | \
          grep LocalNodeHealthState.string"
   res, outStr, stderr = get_status_output(cmd)
   health=outStr.split('=')
   return health[1]

def IsDeviceMounted(dev):
   if (GetDiskHealth(dev) == VSAN_DISK_UNMOUNTED):
#      Log("Device %s is unmounted (%s)." %(dev,GetDiskHealth(dev)))
      return False
   else:
#      Log("Device %s is __NOT__ unmounted (%s)." %(dev,GetDiskHealth(dev)))
      return True

def IsNodeInCluster():
   cmd = "esxcli vsan cluster get"
   res, outStr, stderr = get_status_output(cmd)
   return res

def GetReadCurrAveLatency(dev, stats):
   readStats = stats['read']
   readStatsCurr = readStats['current']
   return readStatsCurr['averageLatency']/1000

def GetReadMaxIOs(dev, stats):
   readStats = stats['read']
   readStatsMax = readStats['maximum']
   return readStatsMax['nrIOs']

def GetReadMaxAveLatency(dev, stats):
   readStats = stats['read']
   readStatsMax = readStats['maximum']
   return readStatsMax['averageLatency']/1000

def GetReadThresholdExceededCount(dev, stats):
   readStats = stats['read']
   return readStats['thresholdExceededCount']

def GetMinimumReadIOsExceededCount(dev, stats):
   readStats = stats['read']
   return readStats['minimumIOsExceededCount']

def GetWriteCurrAveLatency(dev, stats):
   writeStats = stats['write']
   writeStatsCurr = writeStats['current']
   return writeStatsCurr['averageLatency']

def GetWriteMaxIOs(dev, stats):
   writeStats = stats['write']
   writeStatsMax = writeStats['maximum']
   return writeStatsMax['nrIOs']

def GetWriteMaxAveLatency(dev, stats):
   writeStats = stats['write']
   writeStatsMax = writeStats['maximum']
   return writeStatsMax['averageLatency']/1000

def GetWriteThresholdExceededCount(dev, stats):
   writeStats = stats['write']
   return writeStats['thresholdExceededCount']

def GetMinimumWriteIOsExceededCount(dev, stats):
   writeStats = stats['write']
   return writeStats['minimumIOsExceededCount']

def GetDeviceName(uuid):
   deviceInfo = vsi.get('/vmkModules/plog/devices_by_uuid/%s/info' %uuid)
   if (deviceInfo != ""):
      return deviceInfo['diskName']
   else:
      return ""

def GetDeviceUuid(name):
   try:
      deviceInfo = vsi.get('/vmkModules/plog/devices/%s/info' %name)
      if (deviceInfo != ""):
         return deviceInfo['deviceUUID']
      else:
         return ""
   except Exception as e:
      return ""

def GetDeviceCongestion(dev):
   info = vsi.get('/vmkModules/lsom/disks/%s/info' %dev)
   if (info != ""):
      return max(info['memCongestion'], info['slabCongestion'], \
                 info['ssdCongestion'], info['iopsCongestion'], \
                 info['logCongestion'])
   else:
      return 0

def GetDiskLogCongestion(disk, stats):
   if (stats != ""):
      return stats['logCongestion']
   else:
      return 0

def GetDiskStartPlogSegno(disk, stats):
   if (stats != ""):
      return stats['plogStartSegNo']
   else:
      return 0

def GetDiskStartLlogSegno(disk, stats):
   if (stats != ""):
      return stats['llogStartSegNo']
   else:
      return 0

def GetDiskReadPrepareAverageLatency(disk, stats):
   if (stats != ""):
      return stats['avgReadLatency']
   else:
      return 0

def GetDiskWritePrepareAverageLatency(disk, stats):
   if (stats != ""):
      return stats['avgWriteLatency']
   else:
      return 0

def GetDiskUnmapPrepareAverageLatency(disk, stats):
   if (stats != ""):
      return stats['avgUnmapLatency']
   else:
      return 0

def GetDiskReadPrepareAverageIOps(disk, stats):
   if (stats != ""):
      return stats['avgReadIOPS']
   else:
      return 0

def GetDiskWritePrepareAverageIOps(disk, stats):
   if (stats != ""):
      return stats['avgWriteIOPS']
   else:
      return 0

def GetDiskUnmapPrepareAverageIOps(disk, stats):
   if (stats != ""):
      return stats['avgUnmapIOPS']
   else:
      return 0

#
# Is the device under low latency? Used in congestion monitoring to
# disambiguate whether congestion is due to device latency in the
# first place.
#
def HighDeviceLatency(devName):
   if devName in YellowDeviceList or \
      devName in SMARTDeviceList:
     return True
   else:
     return False

#
# Unmount device if config variable, 'lsomSlowDeviceUnmount' is set
#
def UnmountDevice(dev, isTier1Disk, isMappedTier2Disk, remountAttempts,
                  lastAttempt):
   global dedupScope, tier2ToTier1
   VSAN_DEDUP_SCOPE_DISKGROUP = 2

   if not isTier1Disk and dev in dedupScope and dedupScope[dev] == VSAN_DEDUP_SCOPE_DISKGROUP:
      if dev in tier2ToTier1:
         return UnmountDevice(tier2ToTier1[dev], True, True, remountAttempts,
                              lastAttempt)
      else:
         Log("Tier 1 disk unknown for %s" % dev)
         return False

   if remountAfterFailed:
      if isTier1Disk:
         devStr = "-s"
      else:
         devStr = "-d"
      cmd = "/sbin/localcli vsan storage diskgroup unmount " + devStr + " %s" %dev
      res, outStr, stderr = get_status_output(cmd)
      if (res != 0):
         Log("stderr %s, stdout %s from command %s." %(stderr, outStr, cmd))
      if ((res != 0) or IsFailedDisk(dev)):
         if isTier1Disk:
            if (lastAttempt == True):
               Log("Unmount is tried on diskgroup %s, attempt %d: Giving up" %(dev, remountAttempts))
            else:
               Log("Unmount is tried on diskgroup %s, attempt %d: failed" %(dev, remountAttempts))
            return False
         else:
            if (lastAttempt == True):
               Log("Unmount is tried on disk %s, attempt %d: Giving up" %(dev, remountAttempts))
            else:
               Log("Unmount is tried on disk %s, attempt %d: failed" %(dev, remountAttempts))
            return False
      else:
         if isTier1Disk:
            logStr = "Unmounting failed VSAN diskgroup %s." %dev
            Log("Unmount is tried on diskgroup %s, attempt %d: success" %(dev, remountAttempts))
         else:
            logStr = "Unmounting failed VSAN disk %s." %dev
            Log("Unmount is tried on disk %s, attempt %d: success" %(dev, remountAttempts))

         dv.DynamicEvent(logStr, badness(0xDEADBEEF)).send()

         if dev in YellowDeviceList:
            YellowDeviceList.remove(dev)
         if dev in SMARTDeviceList:
            SMARTDeviceList.remove(dev)
         return True
   else:
      return False

#
# Mount device.
#
def MountDevice(dev, isTier1Disk, remountAttempts, lastAttempt):

   if remountAfterFailed:
      if isTier1Disk:
         devStr = "-s"
      else:
         devStr = "-d"
      cmd = "/sbin/localcli vsan storage diskgroup mount " + devStr + " %s" %dev
      res, outStr, stderr = get_status_output(cmd)
      if (res != 0):
         Log("stderr %s, stdout %s from command %s." %(stderr, outStr, cmd))
      #
      # Check if device is actually mounted in CMMDS.
      #
      if ((res != 0) or IsFailedDisk(dev) or (IsDeviceMounted(dev) == False)):
         if isTier1Disk:
            if (lastAttempt == True):
               Log("Re-mount is tried on diskgroup %s, attempt %d: Giving up" %(dev, remountAttempts))
            else:
               Log("Re-mount is tried on diskgroup %s, attempt %d: failed" %(dev, remountAttempts))
            return False
         else:
            if (lastAttempt == True):
               Log("Re-mount is tried on disk %s, attempt %d: Giving up" %(dev, remountAttempts))
            else:
               Log("Re-mount is tried on disk %s, attempt %d: failed" %(dev, remountAttempts))
            return False
      else:
         if isTier1Disk:
            logStr = "Re-mounting failed VSAN diskgroup %s." %dev
            Log("Re-mount is tried on diskgroup %s, attempt %d: success" %(dev, remountAttempts))
         else:
            devStr = "-d"
            logStr = "Re-mounting failed VSAN disk %s." %dev
            Log("Re-mount is tried on disk %s, attempt %d: success" %(dev, remountAttempts))

         dv.DynamicEvent(logStr, badness(0xDEADBEEF)).send()

         return True
   else:
      return False



#
# Reset DDH latency stats in ioretry so that in the case that we don't unmount
# the slow disk, we don't keep generating event and log messages for the same
# "old" latency conditions.
#
def ResetLatencyStats(dev):
   cmd = "vsish -e set /vmkModules/plog/devices/%s/health/latencyStats" %dev
   res, outStr, stderr = get_status_output(cmd)

#
# Helper routine to track READ latency stats. Users are only notified when
# device latency reaches half of the maximum latency permitted. If device
# latency goes higher than maximum threshold value, the device is unmounted.
#
def CheckReadStats(dev, stats, isTier1Disk):
   #
   # Warning latency threshold is at half the MAX tolerance threshold
   # when the device is unmounted.
   #
   MaxAveLatency = GetReadLatencyThreshold(dev)
   HalfLifeLatency = MaxAveLatency/2
   ReadMaxAveLatency = GetReadMaxAveLatency(dev, stats)

   if ReadMaxAveLatency > HalfLifeLatency and ReadMaxAveLatency < MaxAveLatency:
      if dev not in YellowDeviceList:
         logStr = "WARNING - Half-life READ Average Latency on VSAN device %s is %d us " \
                  "and is higher than threshold value %u ms." \
                   %(dev, HalfLifeLatency, ReadMaxAveLatency)
         dv.DynamicEvent(logStr, badness(0xDEADBEEF)).send()
         Log ("WARNING - Half-life READ Average Latency on VSAN device %s is %d us "
              "and is higher than threshold value %d us." \
              %(dev, HalfLifeLatency, ReadMaxAveLatency))
         YellowDeviceList.append(dev)

   ReadThresholdExceededCount = GetReadThresholdExceededCount(dev, stats)
   if ReadThresholdExceededCount > 0:
      logStr = "WARNING - READ Average Latency on VSAN device %s " \
               "has exceeded threshold value %d us %d times." \
               %(dev, MaxAveLatency, ReadThresholdExceededCount)
      getDevice(dev, isTier1Disk).MarkSlowDevice(True, True, logStr)
      ResetLatencyStats(dev)
   else:
      #
      # Only track latency for this interval if there were sufficient IOs.
      #
      minimumReadIOsExceededCount = GetMinimumReadIOsExceededCount(dev, stats)
      if minimumReadIOsExceededCount > 0:
         getDevice(dev, isTier1Disk).MarkSlowDevice(False, True, "")
   return False

#
# Helper routine to track WRITE latency stats. Users are only notified when
# device latency reaches half of the maximum latency permitted. If device
# latency goes higher than the maximum threshold, the device is unmounted.
#
def CheckWriteStats(dev, stats, isTier1Disk):
   #
   # Warning latency threshold is at half the tolerance threshold
   # when the device is unmounted.
   #
   MaxAveLatency = GetWriteLatencyThreshold(dev)
   HalfLifeLatency = MaxAveLatency/2
   WriteMaxAveLatency = GetWriteMaxAveLatency(dev, stats)

   if WriteMaxAveLatency > HalfLifeLatency and \
      WriteMaxAveLatency < MaxAveLatency:
      if dev not in YellowDeviceList:
         logStr = "WARNING - Half-life WRITE Average Latency on VSAN device %s is %d us " \
                  "and is higher than threshold value %d us." \
                   %(dev, HalfLifeLatency, WriteMaxAveLatency)
         dv.DynamicEvent(logStr, badness(0xDEADBEEF)).send()
         Log ("WARNING - Half-life WRITE Average Latency on VSAN device %s is %d us "
              "and is higher than threshold value %d us." \
               %(dev, HalfLifeLatency, WriteMaxAveLatency))
         YellowDeviceList.append(dev)

   WriteThresholdExceededCount = GetWriteThresholdExceededCount(dev, stats)
   if WriteThresholdExceededCount > 0:
      logStr = "WARNING - WRITE Average Latency on VSAN device %s " \
               "has exceeded threshold value %d us %d times." \
                %(dev, MaxAveLatency, WriteThresholdExceededCount)
      getDevice(dev, isTier1Disk).MarkSlowDevice(True, False, logStr)
      ResetLatencyStats(dev)
   else:
      #
      # Only track latency for this interval if there were sufficient IOs.
      #
      minimumWriteIOsExceededCount = GetMinimumWriteIOsExceededCount(dev, stats)
      if minimumWriteIOsExceededCount > 0:
         getDevice(dev, isTier1Disk).MarkSlowDevice(False, False, "")
   return False

#
# Check device SMART stats and issue a user warning if any of
# uncorrectableSectorsCount, reallocatedSectorsCount, reallocatedSectorsEventCount,
# pendingReallocatedSectorsCount, or commandTimeoutsCount is non-zero. Devices
# will continue to serve IOs inspite of such errors; high latency is the only
# indicator used to unmount the device. SMART is advisory only.
#
def CheckSMARTStats(dev, logStatsUnconditionally):
   try:
      info = vsi.get('/vmkModules/plog/devices/%s/health/SMART/info' %dev)
      uncorrectableSectorsCount = info['uncorrectableSectorsCount']
      reportedUncorrectableErrorsCount = info['reportedUncorrectableErrorsCount']
      reallocatedSectorsCount = info['reallocatedSectorsCount']
      reallocatedSectorsEventCount = info['reallocatedSectorsEventCount']
      pendingReallocatedSectorsCount = info['pendingReallocatedSectorsCount']
      commandTimeoutsCount = info['commandTimeoutsCount']

      if (logStatsUnconditionally == True):
         Log ("Critical SMART health attributes for VSAN device %s are shown below." %dev)
         Log ("Uncorrectable sectors: %s." %uncorrectableSectorsCount)
         Log ("Reported uncorrectable sectors: %s." %reportedUncorrectableErrorsCount)
         Log ("Sector reallocation events: %s." %reallocatedSectorsEventCount)
         Log ("Sectors successfully reallocated: %s." %reallocatedSectorsCount)
         Log ("Pending sector reallocations: %s." %pendingReallocatedSectorsCount)
         Log ("Disk command timeouts: %s." %commandTimeoutsCount)
      else:
         if ((uncorrectableSectorsCount > 0 or reallocatedSectorsCount > 0 or \
            reallocatedSectorsEventCount > 0 or pendingReallocatedSectorsCount > 0 or \
            reportedUncorrectableErrorsCount > 0 or commandTimeoutsCount > 0) and \
            dev not in SMARTDeviceList):
            logStr = "WARNING - VSAN device %s is degrading. Consider replacing it." %dev
            dv.DynamicEvent(logStr, badness(0xDEADBEEF)).send()
            Log ("WARNING - VSAN device %s is degrading. Consider replacing it." %dev)
            SMARTDeviceList.append(dev)
      return
   except Exception as e:
      return

#
# Check if LSOM disk has maximum LLOG/PLOG log congestion and remember if so.
#
def CheckDiskLogCongestion(disk, stats):

   # xlate uuid to disk name
   dev = GetDeviceName(disk)
   if (dev != ""):
      #
      # Get log congestion and start positions for llog and plog.
      #
      logCongestion = GetDiskLogCongestion(disk, stats)
      startPlogSegno = GetDiskStartPlogSegno(disk, stats)
      startLlogSegno = GetDiskStartLlogSegno(disk, stats)

#      Log("Log congestion for %s,%s is %d (%d,%d)." \
#          %(dev, disk, logCongestion, startPlogSegno, startLlogSegno))

      if (logCongestion >= LOG_CONGESTION_THRESHOLD):
         # mark device object as congested
         devObj = getDevice(dev, True).MarkLogCongestedDevice(startPlogSegno,
                                                              startLlogSegno)
      else:
         # mark device object as NOT congested
         devObj = getDevice(dev, True).MarkLogDeviceAcceptable(startPlogSegno,
                                                               startLlogSegno)

#
# Check if LSOM disk has excessive LLOG read/write/unmap prepare average
# latency and remember if so.
#
def CheckDiskPrepareAverageLatency(disk, stats):

   dev = GetDeviceName(disk)
   if (dev != ""):
      #
      # Get average latencies.
      #
      readPrepareAverageLatency = GetDiskReadPrepareAverageLatency(disk, stats)
      writePrepareAverageLatency = GetDiskWritePrepareAverageLatency(disk,
                                                                     stats)
      unmapPrepareAverageLatency = GetDiskUnmapPrepareAverageLatency(disk,
                                                                     stats)
      #
      # Get average IOps.
      #
      readPrepareAverageIOps = GetDiskReadPrepareAverageIOps(disk, stats)
      writePrepareAverageIOps = GetDiskWritePrepareAverageIOps(disk, stats)
      unmapPrepareAverageIOps = GetDiskUnmapPrepareAverageIOps(disk, stats)

      #
      # Get average latency thresholds.
      #
      readPrepareAverageLatencyThreshold = \
         GetReadPrepareAverageLatencyThreshold(disk)
      writePrepareAverageLatencyThreshold = \
         GetWritePrepareAverageLatencyThreshold(disk)
      unmapPrepareAverageLatencyThreshold = \
         GetUnmapPrepareAverageLatencyThreshold(disk)

#      Log("Avg read/write/unmap prepare average latencies for " \
#          "%s,%s are %d/%d/%d usecs." \
#          %(dev, disk, readPrepareAverageLatency, \
#            writePrepareAverageLatency, unmapPrepareAverageLatency))

#      Log("Avg read/write/unmap prepare average IOps for " \
#          "%s,%s are %d/%d/%d." \
#          %(dev, disk, readPrepareAverageIOps, \
#            writePrepareAverageIOps, unmapPrepareAverageIOps))

#      Log("Avg read/write/unmap prepare average latency thresholds for disk " \
#          "%s,%s are %d/%d/%d usecs."\
#          %(dev, disk, readPrepareAverageLatencyThreshold, \
#            writePrepareAverageLatencyThreshold, \
#            unmapPrepareAverageLatencyThreshold))

      #
      # Mark unacceptable latency if any of the read/write/unmap latencies
      # are over threshold as long as there is > 1 IOps.
      #
      if (((readPrepareAverageLatency > readPrepareAverageLatencyThreshold) and
           (readPrepareAverageIOps > 1)) or
          ((writePrepareAverageLatency >
              writePrepareAverageLatencyThreshold) and
           (writePrepareAverageIOps > 1)) or
          ((unmapPrepareAverageLatency >
              unmapPrepareAverageLatencyThreshold) and
           (unmapPrepareAverageIOps > 1))):

         # only need one of these to be over threshold
         if (readPrepareAverageLatency > readPrepareAverageLatencyThreshold):
            prepareAverageLatency = readPrepareAverageLatency
            prepareAverageLatencyThreshold = \
               readPrepareAverageLatencyThreshold
         if (writePrepareAverageLatency >
             writePrepareAverageLatencyThreshold):
            prepareAverageLatency = writePrepareAverageLatency
            prepareAverageLatencyThreshold = \
               writePrepareAverageLatencyThreshold
         if (unmapPrepareAverageLatency >
             unmapPrepareAverageLatencyThreshold):
            prepareAverageLatency = unmapPrepareAverageLatency
            prepareAverageLatencyThreshold = \
               unmapPrepareAverageLatencyThreshold

         # mark device object as having excessive log prepare average latency
         devObj = getDevice(dev, True).MarkExcessivePrepareLatency(
                                   prepareAverageLatency,
                                   prepareAverageLatencyThreshold)

      #
      # Mark acceptable latency IFF all latencies are under threshold and there
      # are > 1 IOps.
      #
      if (((readPrepareAverageLatency < readPrepareAverageLatencyThreshold) and
           (readPrepareAverageIOps > 1)) and
          ((writePrepareAverageLatency <
              writePrepareAverageLatencyThreshold) and
           (writePrepareAverageIOps > 1)) and
          ((unmapPrepareAverageLatency <
              unmapPrepareAverageLatencyThreshold) and
           (unmapPrepareAverageIOps > 1))):
         # mark device object having acceptable log prepare average latency
         devObj = getDevice(dev, True).MarkPrepareLatencyAcceptable()


def CongestionMonitorThread(devUUID, dummy):
   startTime = datetime.now()
   aveCongestion = 0
   numTrials = 0
   sumCongestion = 0
   devName = GetDeviceName(devUUID)
   if devName == "":
      return
   while (datetime.now() - startTime).seconds < CONGESTION_TIME_INTERVAL:
      sumCongestion += GetDeviceCongestion(devUUID)
      numTrials += 1
      aveCongestion = sumCongestion/numTrials
      time.sleep(VSAN_CONGESTION_COLLECTION_DELAY)
   CongestionMonitoredList.remove(devUUID)
   if aveCongestion > MAX_CONGESTION_THRESHOLD:
      if not HighDeviceLatency(devName):
         logStr = "WARNING - VSAN device %s is under congestion. Unmounting it to " \
                  "bring congestion under control." %devName
         dv.DynamicEvent(logStr, badness(0xDEADBEEF)).send()
         Log ("WARNING - VSAN device %s is under congestion. Unmounting it to "
              "bring congestion under control." %devName)
#         UnmountDevice(devName, True, False, False)
   return

def GetDeviceStats(dev):
   try:
      stats = vsi.get('/vmkModules/plog/devices/%s/health/latencyStats' %dev)
      return stats
   except Exception as e:
      return ""

def GetDiskStats(disk):
   try:
      stats = vsi.get('/vmkModules/lsom/disks/%s/info' %disk)
      return stats
   except Exception as e:
      return ""

def CheckDeviceAttributes(sleepInterval, dev):
   try:
      latencyInterval = GetLatencyInterval(dev)
      if (latencyInterval > sleepInterval):
         if dev not in deviceAttributeWarningList:
            deviceAttributeWarningList.append(dev)
            Log("VSAN device %s has movingAverageLatencyInterval of %d seconds." %(dev,latencyInterval))
            Log("This value should not be set greater than the lsomDeviceMonitorInterval ESX")
            Log("advanced config option which is currently set at %d seconds.  Please correct." %sleepInterval)
      else:
         if dev in deviceAttributeWarningList:
            deviceAttributeWarningList.remove(dev)
   except Exception as e:
      return

#
# Scan all tier 1 devices' congestion and unmount diskgroup if
# higher than allowed threshold value.
#
def ScanDeviceCongestion():
   diskList=vsi.list('/vmkModules/lsom/disks')
   if diskList == "":
      return
   for dev in diskList:
      info=vsi.get('/vmkModules/lsom/disks/%s/info' %dev)
      if (info != ""):
         if info['type'] == 'cache':
            if dev not in CongestionMonitoredList:
               # Spawn a thread to monitor latency for a pre-determined
               # interval. The device is unmounted if sustained congestion
               # is noticed on a device.
               CongestionMonitoredList.append(dev)
               t = threading.Thread(target=CongestionMonitorThread, \
                                    args=(dev, dev))
               t.start()
   return

#
# Scan device latencies, SMART counters and unmount if latencies are higher than
# allowed threshold values.
#
def ScanDevices(devList, isTier1Disk):
   sleepInterval = GetSleepInterval()
   numDevices = len(devList)
   while numDevices > 0:
      dev = devList[numDevices - 1]
      #
      # Monitor this disk IFF (1) the disk is mounted in CMMDS and
      # (2) the disk's CMMDS health entry indicates a healthy disk.
      #
      if (IsDeviceMounted(dev) and (not IsUnhealthyDisk(dev))):
         stats = GetDeviceStats(dev)
         if (stats != ""):
            CheckReadStats(dev, stats, isTier1Disk)
            CheckWriteStats(dev, stats, isTier1Disk)
            CheckSMARTStats(dev, False)
            CheckDeviceAttributes(sleepInterval, dev)
            numDevices = numDevices - 1
         else:
            numDevices = numDevices - 1
            continue
      else:
         numDevices = numDevices - 1
   return

#
# Scan LSOM caching tier log congestion and LSOM read/write/umnmap prepare
# latencies.
#
def ScanDisks(diskList):
   numDisks = len(diskList)
   while numDisks > 0:
      disk = diskList[numDisks - 1]
      if (not IsUnhealthyCachingDisk(disk)):
         stats = GetDiskStats(disk)
         if (stats != ""):
            if diagnoseExcessiveLogCongestion:
               CheckDiskLogCongestion(disk, stats)
            if diagnoseExcessiveLogPrepareAverageLatency:
               CheckDiskPrepareAverageLatency(disk, stats)
            numDisks = numDisks - 1
         else:
            numDisks = numDisks - 1
            continue
      else:
         numDisks = numDisks - 1
   return

#
# Initialize the latency monitoring data structures.
#
def SetUpLatencyMonitoring():
   global numberOfLatencyIntervals
#
# The device polling rate (sleepInterval) is specified in seconds and
# the latencyMonitoringTimePeriod is specified in minutes.  Normalize the
# latter to seconds and compute the # of time intervals within the specified
# device monitoring time period.
#

   numberOfLatencyIntervals = int((latencyMonitoringTimePeriod * 60) / sleepInterval)
   if (numberOfLatencyIntervals == 0):
      numberOfLatencyIntervals = 1

#
# We want the time period to accomodate half of an order of magnitude more time
# intervals than the number of time intervals that are actually sampled in
# order to derive an effective random distribution of selected time intervals
# within the time period.  Adjust the total number of intervals and therefore
# the latencyMonitoringTimePeriod accordingly.
#
   if (numberOfLatencyIntervals < (latencyMonitoringIntervalCount * 5)):
      numberOfLatencyIntervals = latencyMonitoringIntervalCount * 5

#
# Attempt to re-mount (unmount followed by mount) of any failed devices.
#
def RemountDevices(devList):
   try:
      if remountAfterFailed:
         numDevices = len(devList)
         while numDevices > 0:
            dev = devList[numDevices - 1]
            devRemounted = dev.RemountDevice()
            if (devRemounted == True):
#               Log("Removing device %s from Failed List." %dev.name)
               devList.remove(dev)
            numDevices = numDevices - 1
   except Exception as e:
      Log ("RemountDevices failed")
   return

def RemountAllFailedDevices():
   try:
      RemountDevices(FailedTier1DeviceList)
      RemountDevices(FailedTier2DeviceList)
   except Exception as e:
      Log ("RemountAllFailedDevices failed")
   return

def EvacuateDevice(dev):
   global dedupScope, tier2ToTier1
   VSAN_DEDUP_SCOPE_DISKGROUP = 2

   if not IsTier1Disk(dev.name) and \
      dev in dedupScope and \
      dedupScope[dev.name] == VSAN_DEDUP_SCOPE_DISKGROUP:
      if dev.name in tier2ToTier1:
         return EvacuateDevice(tier2ToTier1[dev.name])
      else:
         Log("Tier 1 disk unknown for %s" % dev.name)
         return False
   if IsTier1Disk(dev.name):
      #
      # Generate different events for excessive log congestion and excessive
      # IO latency since in the  former case the diskgroup disks may be re-used
      # so the recovery instructions for user are different.
      #
      if (dev.logCongestionIntervals >=
          logCongestionMonitoringIntervalCount):
         Log("Tier 1 (%s) failure due to log congestion." % (dev.name))
         cmd = "vsish -e set /vmkModules/plog/devices/%s/diskEvent %d" \
            %(dev.name, VSAN_DISKGROUP_LOG_CONGESTED_EVENT)
      else:
         Log("Tier 1 (%s) unhealthy" % (dev.name))
         cmd = "vsish -e set /vmkModules/plog/devices/%s/diskEvent %d" \
            %(dev.name, VSAN_SSD_UNHEALTHY_EVENT)
   else:
      Log("Tier 2 (%s) as unhealthy" % (dev.name))
      cmd = "vsish -e set /vmkModules/plog/devices/%s/diskEvent %d" \
         %(dev.name, PLOG_MD_UNHEALTHY_EVENT)
   res, outStr, stderr = get_status_output(cmd)
   if (res == 0):
      return True;
   else:
      return False;

def EvacuateAllUnhealthyDevices(devList):
   try:
      numDevices = len(devList)
      while numDevices > 0:
         dev = devList[numDevices - 1]
         dev.latencyIntervalCount = 0
         dev.latencyThresholdExceededCount = 0
         dev.startPlogSegnoValid = False
         dev.startLlogSegnoValid = False
         dev.startPlogSegno = 0
         dev.startLlogSegno = 0
         dev.logPrepareAverageLatencyIntervals = 0
         CheckSMARTStats(dev.name, True)
         deviceEvacuated = EvacuateDevice(dev)
         if (deviceEvacuated == True):
            EvacuateDeviceList.remove(dev)
         # Device log congestion interval should be
         # reset after evacuation, as it is used
         # to determine cause of disk failure
         dev.logCongestionIntervals = 0
         numDevices = numDevices - 1
   except Exception as e:
      Log ("EvacuateAllUnhealthyDevices failed: %s" % (e))
      return
   return

# Dedup Space Reclaim Stuff

# Dedup Space Reclaim state
DEDUP_SPACE_RECLAIM_DISABLE = 0
DEDUP_SPACE_RECLAIM_ENABLE = 1
DEDUP_SPACE_RECLAIM_COMPLETE = 2

DEDUP_SPACE_RECLAIM_USED_CAPACITY_PERCENT = 30
# Change this to 0 percent for testing
#DEDUP_SPACE_RECLAIM_USED_CAPACITY_PERCENT = 0

#Dedup ref count does not happen if the disk capacity is
#is less than 16TB (logical) or 1.6TB physical
DEV_PHYS_CAPACITY_1MB = 1024 * 1024
DEV_PHYS_CAPACITY_1GB = 1024 * DEV_PHYS_CAPACITY_1MB
DEDUP_SPACE_RECLAIM_DISK_CAPACITY = 1.6 * 1024 * DEV_PHYS_CAPACITY_1GB
# Change this to 0 percent for testing
#DEDUP_SPACE_RECLAIM_DISK_CAPACITY = DEV_PHYS_CAPACITY_1GB


#  Dedup is first released with disk format version 4 and it
#  has the space leak code. Fix for leak is in version 5 already.
#  But include format versions 5 and 6 for this fix just for
#  safety so we don't miss any upgrade scenarios
DEDUP_SPACE_RECLAIM_MIN_DISKFORMAT_VERS = 4
DEDUP_SPACE_RECLAIM_MAX_DISKFORMAT_VERS = 6

# Devices that completed scan
DedupSpaceReclaimCompletedDeviceList=[]

# Devices with scanner in progress
DedupSpaceReclaimInProgressDeviceList=[]

# Check disk type for Data
def IsDataDisk(type):
   return True if type == 'data' else False

#
# Check if space reclaim is complete on a data device
#
def IsDeviceDedupSpaceReclaimComplete(dev, silent=True):
   isComplete=True

   stats = vsi.get('/vmkModules/lsom/disks/%s/virstoSpaceReclaimStats' % dev)
   if (stats != ""):
      if stats['reclaimComplete'] == 0:
         isComplete=False

   if isComplete:
      if dev not in DedupSpaceReclaimCompletedDeviceList:
         Log("Dedup space reclaim complete for disk with uuid(%s) name(%s)" \
                              %(dev, GetDeviceName(dev)))
         DedupSpaceReclaimCompletedDeviceList.append(dev)
         if dev in DedupSpaceReclaimInProgressDeviceList:
            DedupSpaceReclaimInProgressDeviceList.remove(dev)
   else:
      if dev not in DedupSpaceReclaimInProgressDeviceList:
         Log("Dedup space reclaim in progress for disk with uuid(%s) name(%s)" \
               %(dev, GetDeviceName(dev)))
         DedupSpaceReclaimInProgressDeviceList.append(dev)

   return isComplete

#
# Scan all data  devices' space reclaim and return true if reclaim is
# complete on all devices
#
def IsDedupSpaceReclaimComplete(silent=True):
   tier2Disks = GetCapacityDisks()
   if tier2Disks == []:
      Log("Dedup space reclaim empty data disk List")
      return False

   for dev in tier2Disks:
      if not IsDeviceDedupSpaceReclaimComplete(dev, silent):
         return False

   Log("Dedup space reclaim complete for all (%s) disks" % len(tier2Disks))
   return True

def EnableDedupSpaceReclaim():
   cmd = 'esxcfg-advcfg -s %u /Virsto/DedupSpaceReclaim' % DEDUP_SPACE_RECLAIM_ENABLE
   ret, output = ExecuteCmd(cmd.split())
   if (ret != 0):
      print("DedupSpaceReclaim enable failed, output: %s" % output)
      Log("DedupSpaceReclaim enable failed, output: %s" % output)
      return
   Log("DedupSpaceReclaim enabled")

def MarkDedupSpaceReclaimComplete():
   cmd = 'esxcfg-advcfg -s %u /Virsto/DedupSpaceReclaim' % DEDUP_SPACE_RECLAIM_COMPLETE
   ret, output = ExecuteCmd(cmd.split())
   if (ret != 0):
      print("DedupSpaceReclaim disable failed, output: %s" % output)
      Log("DedupSpaceReclaim disable failed, output: %s" % output)
      return
   DedupSpaceReclaimCompletedDeviceList.clear()
   DedupSpaceReclaimInProgressDeviceList.clear()
   Log("DedupSpaceReclaim disabled")

def IsDedupSpaceReclaimEnabled():
   return vsi.get('/config/Virsto/intOpts/DedupSpaceReclaim')['cur']

def IsDedupSpaceReclaimAlreadyCompleted():
   isComplete = False
   state = vsi.get('/config/Virsto/intOpts/DedupSpaceReclaim')['cur']
   if (state == DEDUP_SPACE_RECLAIM_COMPLETE):
      isComplete = True
   return isComplete

# Check diskFormats for any possible leak.
def checkDiskFormatVersionForSpaceLeak(dev, diskFormatVersion):
   if diskFormatVersion < DEDUP_SPACE_RECLAIM_MIN_DISKFORMAT_VERS or \
         diskFormatVersion > DEDUP_SPACE_RECLAIM_MAX_DISKFORMAT_VERS:
      Log("dev with uuid(%s) has version %s that may not need space reclaim" \
            % (dev, diskFormatVersion))
      return False
   return True

# check if a given data disk has space consumed greater than
# DEDUP_SPACE_RECLAIM_USED_CAPACITY_PERCENT
def IsDeviceSpaceConsumedAboveThreshold(dev, deviceInfo):
   if (deviceInfo == "") or not IsDataDisk(deviceInfo['type']):
      return False
   diskCapacity = deviceInfo['physDiskCapacity']
   diskCapacityUsed = deviceInfo['physDiskCapacityUsed']
   if diskCapacity:
      percentCapacityUsed = (diskCapacityUsed * 100) / diskCapacity
      Log("dev with uuid(%s) has consumed %.2f percent of phys capacity" \
            %(dev, round(percentCapacityUsed, 2)))
      if (percentCapacityUsed >= DEDUP_SPACE_RECLAIM_USED_CAPACITY_PERCENT):
         return True
   return False


# Only disk groups that are greater than 16TB in logical capacity can
# overflow dedup reference count
def CheckDedupCapacity():
   GetVSANMappings()
   tier1Disks, tier2Disks = GetVSANDevices()
   if tier1Disks == [] or tier2Disks == []:
      return False

   for d in tier2Disks:
      getDevice(d, False)

   isMinLeakCapacity = False
   for d in tier1Disks:
      capacity = getDevice(d, True).GetAggregateCapacity()
      Log("Disk Group %s has capacity: %.2fGB" \
            %(d, capacity/DEV_PHYS_CAPACITY_1GB))
      if capacity > DEDUP_SPACE_RECLAIM_DISK_CAPACITY:
         isMinLeakCapacity = True
   return isMinLeakCapacity

def CheckCachingDisks(tier1Disks):
   isAllFlash = True
   isDedup = True
   for dev in tier1Disks:
      info = vsi.get('/vmkModules/lsom/disks/%s/info' % dev)
      if (info != ""):
            devName = GetDeviceName(dev)
            if not info['isAllFlash']:
               Log("Skipping reclaim, dev with uuid(%s) name(%s) is not " \
                     "all flash device" %(dev, devName))
               isAllFlash = False
            if GetDedupScope(devName) == 0:
               Log("Skipping reclaim, dev with uuid(%s) name(%s) is not " \
                     "dedup enabled" %(dev, devName))
               isDedup = False
   if not isAllFlash or not isDedup:
      return False
   else:
      return True


def CheckCapacityDisks(tier2Disks):
   usedDisks = 0
   for dev in tier2Disks:
      info = vsi.get('/vmkModules/lsom/disks/%s/info' % dev)
      if (info != ""):
         # skip disk format version check for now.
         #diskFormat = info['formatVersion']
         # if IsDeviceSpaceConsumedAboveThreshold(dev, info) and \
         #      checkDiskFormatVersionForSpaceLeak(dev, diskFormat):
         if IsDeviceSpaceConsumedAboveThreshold(dev, info):
            usedDisks += 1

   if usedDisks == 0:
      return False
   Log("%s disks out of %s data disks have space consumed > %s percent" \
         %(usedDisks, len(tier2Disks), \
         DEDUP_SPACE_RECLAIM_USED_CAPACITY_PERCENT))
   return True

# No need to run space reclaim on new host or new DiskGroup or
# sparsely used systems. Given reclaim is a host-level setting,
# check all disks and if the usage is less than
# 30% turn off space reclaim permanently
def IsSpaceReclaimNeeded():
   try:
      tier1Disks=[]
      tier2Disks=[]

      tier1Disks = GetVSANDisks()
      tier2Disks = GetCapacityDisks()
      # In Dedup all disks in Disk group come online. If there is no cache disk
      # it is either Hybrid or Non-Dedup all flash group. No need to enable
      # reclaim scanner in both these cases regardless of disk usage
      if tier1Disks == [] or tier2Disks == []:
         return (tier1Disks, tier2Disks, False)

      if not CheckCachingDisks(tier1Disks):
         return (tier1Disks, tier2Disks, False)

      if not CheckDedupCapacity():
         Log("Skipping reclaim, all disk groups are smaller than 1.6TB")
         return (tier1Disks, tier2Disks, False)

      if not CheckCapacityDisks(tier2Disks):
         Log("Skipping reclaim, all (%s) data disks have low space consumed" \
               % len(tier2Disks))
         return (tier1Disks, tier2Disks, False)

      return (tier1Disks, tier2Disks, True)
   except Exception as e:
      return (0, 0, False)


def DedupSpaceReclaim():
   try:
      # If space reclaim is already completed (== 2), nothing to do
      if IsDedupSpaceReclaimAlreadyCompleted():
         return
      # If space reclaim is currently disabled (== 0) and has not run at least once
      # auto enable it here.
      if not IsDedupSpaceReclaimEnabled():
         tier1Disks, tier2Disks, isReclaimNeeded = IsSpaceReclaimNeeded()
         # If there are no DATA disks yet, don't make any decision. Let some of
         # them join. Simply return here.
         if tier1Disks == [] and tier2Disks == []:
            Log("Dedup space reclaim empty disk List")
            return
         # If all known DATA disks have low space usage turn OFF space reclaim
         if not isReclaimNeeded:
            Log("Auto disable DedupSpaceReclaim")
            MarkDedupSpaceReclaimComplete()
            return
         # Even if a single DATA disk has used more than
         # DEDUP_SPACE_RECLAIM_USED_CAPACITY_PERCENT, auto turn ON space reclaim
         Log("Auto enable DedupSpaceReclaim")
         EnableDedupSpaceReclaim()
         return

      # If space reclaim is enabled (==1), scan all disks and check the state.
      # If reclaim is complete on all devices go ahead and disable
      # space reclaim and persist the config
      if IsDedupSpaceReclaimComplete():
         Log("Auto disable DedupSpaceReclaim")
         MarkDedupSpaceReclaimComplete()

   except Exception as e:
      Log ("Reclaim scan failed: %s" % (e))

   return

if __name__ == '__main__':
   try:
      dedupScope = dict()
      tier2ToTier1 = dict()
      random.seed()
      options = ParseOptions([])
      LoadOptionsFromConfig(options, '/etc/vmware/vsan/vsandevicemonitord.conf')
      SetupLogging(options)
      Log("Checking VSAN device latencies and congestion.")
      if (IsHostVM() and not DeviceMonitoringIfVM()):
         Log("Host is a VM.  VSAN Device Monitor is disabled.")
      while True:
         sleepInterval = GetSleepInterval()
         diagnoseExcessiveLogCongestion = GetLogCongestionPersonality()
         diagnoseExcessiveLogPrepareAverageLatency = \
            GetLogPrepareAverageLatencyPersonality()
         pullThePlug = GetUnmountPersonality()
         pullThePlugOnTier1 = GetTier1UnmountPersonality()
         remountAfterFailed = GetFailedDeviceRemountPersonality()
         remountAfterFailedTimePeriod = GetRemountFailedDeviceTimePeriod()
         #
         # Piggyback Dedup Space Reclaim on this monitor daemon
         #
         DedupSpaceReclaim()
         #
         # Disable monitoring if configured to disable monitoring or if ESX
         # is running in a VM and configured to disabled monitoring if ESX is
         # running in a VM.
         #
         if ((DeviceMonitoringDisabled() == 0) or (IsHostVM() and \
             not DeviceMonitoringIfVM())):
            time.sleep(VSAN_DISABLED_SLEEP_INTERVAL)
            continue
         latencyMonitoringIntervalCount = GetSlowDeviceMonitoringIntervalCount()
         latencyMonitoringTimePeriod = GetSlowDeviceMonitoringTimePeriod()
         logCongestionMonitoringIntervalCount = GetLogCongestedIntervalCount()
         logPrepareAverageLatencyMonitoringIntervalCount = \
            GetLogPrepareAverageLatencyIntervalCount()
         SetUpLatencyMonitoring()
         GetVSANMappings()
         tier1Disks, tier2Disks = GetVSANDevices()
         if tier1Disks == [] or tier2Disks == []:
            RemountAllFailedDevices()
            time.sleep(sleepInterval * 2)
            continue
         cachingDisks = GetVSANDisks()
         ScanDevices(tier1Disks, True)
         ScanDevices(tier2Disks, False)
         ScanDisks(cachingDisks)
         time.sleep(sleepInterval)
         RemountAllFailedDevices()
         tier1Disks, tier2Disks = GetVSANDevices()
         if tier1Disks == [] or tier2Disks == []:
            RemountAllFailedDevices()
            time.sleep(sleepInterval)
            continue
         time.sleep(sleepInterval)
         RemountAllFailedDevices()
         EvacuateAllUnhealthyDevices(EvacuateDeviceList)
   except Exception as e:
      Log ("Scan failed: %s" % (e))
