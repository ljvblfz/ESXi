#!/usr/bin/python
# **********************************************************
# Copyright 2010-2015 VMware, Inc.  All rights reserved. -- VMware Confidential
# **********************************************************

__author__ = "VMware, Inc."

import os

from pluginApi import ParameterMetadata, \
                      CreateLocalizedException, \
                      log

from pluginApi import CATEGORY_GENERAL_SYSTEM_SETTING, \
                      COMPONENT_HOST_CACHE_CONFIG, \
                      TASK_LIST_REQ_MAINT_MODE

from pluginApi.extensions import SimpleConfigProfile

from pyEngine import storageprofile

from operator import itemgetter


# Localization message catalog keys used by this profile
BASE_MSG_KEY = 'com.vmware.profile.hostCacheConfig'
INVALID_SYS_CONFIG_MSG_KEY = BASE_MSG_KEY + '.InvalidSystemConfig'
ESXCLI_ERROR_MSG_KEY = BASE_MSG_KEY + '.EsxcliError'


class HostCacheConfigProfile(SimpleConfigProfile):
   """A Host Profile that manages host cache config settings on ESX hosts."""

   # Required class attributes

   parameters = [ParameterMetadata('Model', 'string', False),
                 ParameterMetadata('SizeMB', 'int', False)]

   singleton = False

   setConfigReq = TASK_LIST_REQ_MAINT_MODE

   dependencies = [storageprofile.StorageProfile]

   category = CATEGORY_GENERAL_SYSTEM_SETTING
   component = COMPONENT_HOST_CACHE_CONFIG


   # Functions that read data from ESXCLI

   @classmethod
   def executeEsxcli(c, h, command):
      """Execute an esxcli command and handle potential errors"""

      status, ret = h.ExecuteEsxcli(command)
      if status != 0:
         msgData = {'cmd': str(command), 'errMsg': str(ret)}
         raise CreateLocalizedException(None, ESXCLI_ERROR_MSG_KEY, msgData)
      if ret == None:
         ret = []
      return ret

   @classmethod
   def getHostCaches(c, h):
      """Get all host caches"""
      return c.executeEsxcli(h, 'sched hostcache list')

   @classmethod
   def removeVFlashVolume(c, volumesList):
      """Remove the VFlash volume from the list and returns it"""
      return list(filter(lambda v: v['Type'] != 'VFFS', volumesList))

   @classmethod
   def getVolumes(c, h):
      """Get all volumes"""
      volumes = c.executeEsxcli(h, 'storage filesystem list -i')
      return c.removeVFlashVolume(volumes)

   @classmethod
   def getVMFSExtents(c, h):
      """Get all VMFS extents"""
      return c.executeEsxcli(h, 'storage vmfs extent list -i')

   @classmethod
   def getDevices(c, h):
      """Get all devices"""
      return c.executeEsxcli(h, 'storage core device list')

   @classmethod
   def getVMFSPartitions(c, h):
      """Get VMFS partitions"""

      # Select only VMFS partitions
      allPartitions = c.executeEsxcli(h, 'storage core device partition list')
      partitions = [p for p in allPartitions if p['Type'] == 0xfb]
      return partitions


   #
   # Data model used by this profile
   #
   # hostCache         volume            VMFS extent         partition      device
   # ---------         -----------       -----------         ---------      --------
   # SizeMB            Mount Point       Partition ===0/1:1= Partition      Is SSD
   # Volume ====0/1:1= Volume Name       Device Name =0/1:1= Device ===*:1= Device
   #         or=0/1:1= UUID ========1:+= VMFS UUID           Type           Is Local
   #                   Free
   #

   # Functions that traverse from one object to another

   @classmethod
   def vmfsVolume2Partitions(c, volume, vmfsExtentsList, vmfsPartitionsList):
      """Return partitons a VMFS volume is on"""

      partitions = []
      for partition in vmfsPartitionsList :
         for extent in vmfsExtentsList :
            if partition['Device'] == extent['Device Name'] \
               and partition['Partition'] == extent['Partition'] \
               and extent['VMFS UUID'] == volume['UUID']:
                  partitions.append(partition)
      return partitions

   @classmethod
   def partition2Device(c, partition, deviceList):
      """Return the device a partitons is on"""

      for dev in deviceList:
         if partition['Device'] == dev['Device']:
            return dev
      return None

   @classmethod
   def volumeName2Volume(c, volumeName, volumesList):
      """Find the volume with a certain name or UUID"""

      for volume in volumesList:
         if volume['Volume Name'] == volumeName \
            or volume['UUID'] == volumeName:
            return volume
      return None

   # Traverse to and object and return a single field
   @classmethod
   def volume2HostCacheSize(c, volume, volumesList, hostCacheList):
      """Return the device a partitons in on."""

      for hc in hostCacheList:
         if c.volumeName2Volume(hc['Volume'], volumesList)['UUID'] == \
            volume['UUID']:
            return hc['SizeMB']
      return 0

   @classmethod
   def partition2Model(c, partition, deviceList):
      """Return the model of the device a partitons in on."""
      return c.partition2Device(partition, deviceList)['Model']

   # Functions to check for properties of a object
   @classmethod
   def __buildIsDebug(c):
      """For testing purposes, allow any volume.
      """
      return 'DEBUG' in os.uname().version

   @classmethod
   def isVolumeOnSingleSSD(c, volume, vmfsExtentsList, vmfsPartitionsList, \
                           deviceList):
      """Return the device a partitons in on."""

      partitions = c.vmfsVolume2Partitions(volume, vmfsExtentsList, \
                                           vmfsPartitionsList)

      return len(partitions) == 1 \
             and (c.partition2Device(partitions[0], deviceList)['Is SSD'] or \
                   c.__buildIsDebug())


   # Policy
   @classmethod
   def findBestVolume(c, h, model, size, volumesList):
      """Find the best suitable volume for a (model, size) tuple"""

      # We cathegorize the volumes after their charachteristic and later select
      # the best volume.

      possibleVolumes = []
      bigEnoughVolumes = []
      rightModelVolumes = []

      vmfsExtentsList =  c.getVMFSExtents(h)
      vmfsPartitionsList = c.getVMFSPartitions(h)
      deviceList = c.getDevices(h)
      hostCacheList = c.getHostCaches(h)

      for volume in volumesList:
         if c.volume2HostCacheSize(volume, volumesList, hostCacheList) == 0 \
            and c.isVolumeOnSingleSSD(volume, vmfsExtentsList, \
                                      vmfsPartitionsList, deviceList):
            possibleVolumes.append(volume)

            if volume['Free'] / (1024 * 1024) >= size:
               bigEnoughVolumes.append(volume)

               if c.partition2Model(c.vmfsVolume2Partitions(volume, \
                                                            vmfsExtentsList, \
                                                            vmfsPartitionsList)[0], \
                                                            deviceList) \
                  == model:
                  rightModelVolumes.append(volume)

      # Sort volume lists with preferred volume being lower
      possibleVolumes = sorted(possibleVolumes, \
                               key=itemgetter('Free'), reverse=True)
      bigEnoughVolumes = sorted(bigEnoughVolumes, \
                                key=itemgetter('Free'))
      rightModelVolumes = sorted(rightModelVolumes, \
                                 key=itemgetter('Free'))

      # We prefer volumes in the following order
      #
      # 1. Right model
      # 2. Big enough to fit the host cache
      # 3. Best fit

      if len(rightModelVolumes) > 0:
         return rightModelVolumes[0]
      elif len(bigEnoughVolumes) > 0:
         return bigEnoughVolumes[0]
      elif len(possibleVolumes) > 0:
         return possibleVolumes[0]
      else:
         return None


   # Actions
   @classmethod
   def setHostCacheSize(c, h, volume, sizeReq):
      """Set size of host cache on a certain volume"""

      # Compute final size of the host cache
      free = volume['Free'] / (1024 * 1024)
      size = min(sizeReq, free)
      size = size - size % 1024

      if size != sizeReq:
         log.error('host cache on volume ' + volume['UUID'] + ' will be ' \
                   + str(size) + ' MB instead of the requested ' \
                   + str(sizeReq) + ' MB.')
      c.executeEsxcli(h, 'sched hostcache set -v ' + volume['UUID'] + ' -s ' \
                      + str(size))


   @classmethod
   def removeAllHostCaches(c, h, volumesList):
      """remove all currently configured host caches"""

      for hc in c.getHostCaches(h):
         vol = c.volumeName2Volume(hc['Volume'], volumesList)
         if vol is not None:
            volume = c.volumeName2Volume(hc['Volume'], volumesList)
            c.setHostCacheSize(h, volume, 0)


   # External interface

   @classmethod
   def ExtractConfig(c, h):
      """Gets the host cache config on the ESX system"""

      configs = []
      hostCaches = c.getHostCaches(h)
      if len(hostCaches) == 0:
         return configs

      volumesList = c.getVolumes(h)
      vmfsExtentsList =  c.getVMFSExtents(h)
      vmfsPartitionsList = c.getVMFSPartitions(h)
      deviceList = c.getDevices(h)

      for hc in hostCaches:
         # Find the partitions belonging to the volume.
         volume = c.volumeName2Volume(hc['Volume'], volumesList)
         if volume is not None:
            partitions = c.vmfsVolume2Partitions(volume, vmfsExtentsList, \
                                                 vmfsPartitionsList)
            # Having a host cache span over multiple partitions should be very
            # uncommon. Hence we ignore those caches.
            if len(partitions) == 1:
               model = c.partition2Model(partitions[0], deviceList)
               configs.append({'Model': model, 'SizeMB': hc['SizeMB']})
      return configs


   @classmethod
   def SetConfig(c, configs, h):
      """Sets the host cache configuration settings."""

      isSuccessful = True
      volumesList = c.getVolumes(h)

      # first remove all current hostCaches
      c.removeAllHostCaches(h, volumesList)

      # then create new ones
      sortedConfigs = sorted(configs, key=itemgetter('SizeMB'), reverse=True)

      # Refresh the volumesList because we removed the existing hostCache
      volumesList = c.getVolumes(h)

      for config in sortedConfigs:
          model = config['Model']
          size = config['SizeMB']
          bestVolume = c.findBestVolume(h, model, size, volumesList)
          if bestVolume == None:
             log.error('Could not find any suitable volume to create host' \
                       + 'cache for the following constraints: model: ' \
                       + model + ', size: ' + str(size))
             isSuccessful = False
             continue
          c.setHostCacheSize(h, bestVolume, size)
      return isSuccessful
