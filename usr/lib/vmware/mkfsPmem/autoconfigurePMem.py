#! /bin/python
"""
Copyright 2016-2018 VMware, Inc.  All rights reserved. -- VMware Confidential
"""

# A good documentation for this API can be found at:
# https://www.linuxvoice.com/issues/005/pyparted.pdf

import parted
import os
import sys
import struct
import fcntl
import uuid
import subprocess
import zlib
import ctypes
import atexit

from argparse import ArgumentParser
from pyVim import connect, host, path, task, vm, vmconfig
from vmware import vsi

PMEM_VOLUME_MAGIC = 0x566D654D50574D56
IOCTLCMD_PMEM_ADD_VOLUME_EXTENT = 3090
IOCTLCMD_PMEM_GET_HEALTH_STATS = 3103
IOCTLCMD_VMFS_BLKRRPART = 3010

PMEM_VOL_MAX_EXTENTS = 256

PMEM_BLK_SIZE = 4096

mkfsPmem = os.path.join(os.path.sep, 'usr', 'lib', 'vmware', 'mkfsPmem',
                        'mkfsPmem')


class PMem_UUID(ctypes.Array):
   _length_ = 16
   _type_ = ctypes.c_ubyte

   def __eq__(self, other):
      return self[:] == other[:]

class PMem_ExtentNV(ctypes.Structure):
   _fields_ = [("extentSize", ctypes.c_ulonglong),
               ("extentUuid", PMem_UUID)]

   def __eq__(self, other):
      return self.extentSize == other.extentSize and \
            self.extentUuid == other.extentUuid

class PMem_VolumeExtentStateNV(ctypes.Structure):
   _fields_ = [("volGen", ctypes.c_ulonglong),
               ("numExtents", ctypes.c_ulonglong),
               ("extents", PMem_ExtentNV * PMEM_VOL_MAX_EXTENTS),
               ("pad", ctypes.c_uint),
               ("crc32", ctypes.c_uint)]

   def __eq__(self, other):
      """
      Check that the 2 extent state have the same extents.
      """
      if self.numExtents != other.numExtents:
         return False

      for i in range(self.numExtents):
         if self.extents[i] != other.extents[i]:
            return False

      return True


class PMem_VolumeExtentNV(ctypes.Structure):
   __padding = 4096 - 3 * ctypes.sizeof(ctypes.c_ulonglong) - \
         3 * ctypes.sizeof(PMem_UUID)

   _fields_ = [("magic", ctypes.c_ulonglong),
               ("extentUuid", PMem_UUID),
               ("volumeUuid", PMem_UUID),
               ("namespaceUuid", PMem_UUID),
               ("volumeExtentStateNVSize", ctypes.c_ulonglong),
               ("dataLossCounter", ctypes.c_ulonglong),
               ("pad", ctypes.c_byte * __padding),
               ("state", PMem_VolumeExtentStateNV * 2)]

   def __eq__(self, other):
      """
      Perform a deep comparison of the volume extent.
      """

      if self.volumeUuid != other.volumeUuid:
         return False

      return self.state[self.activeState] == other.state[other.activeState]

   def findExtent(self, extentUuid):
      for i in range(self.state[self.activeState].numExtents):
         if extentUuid == self.state[self.activeState].extents[i].extentUuid:
            return i

      raise ValueError("UUID: %s is not in the volume",
                       uuid.UUID(bytes=bytes(extentUuid)))

def dirHasEntries(d):
   """Test whether a directory has files.
   """
   return os.listdir(d) != []

def getDir(d):
   """Iterator over all the files in a directory.
   """
   for f in os.listdir(d):
      yield os.path.join(d, f)

def hasNS():
   """Test whether the system has some namespaces.
   """
   d = os.path.join(os.path.sep, 'vmfs', 'devices', 'PMemNamespaces')
   return dirHasEntries(d)

def getNS():
   """Iterator that returns the path to the namespace found on the system.
   """
   d = os.path.join(os.path.sep, 'vmfs', 'devices', 'PMemNamespaces')
   for ns in getDir(d):
      yield ns

def getVol():
   """Iterator that returns the path to the volumes.
   """
   d = os.path.join(os.path.sep, 'vmfs', 'devices', 'PMemVolumes')
   for vol in getDir(d):
      yield vol

def getDevUUID(device):
   """Get the device UUID.

   As namespaces names contain the UUID, we can get the device UUID from
   the filename of the namespace.
   """
   devBasename = os.path.basename(device.path)
   devUuid = uuid.UUID(devBasename.split('-', maxsplit=1)[1])

   return devUuid

def new_disk_exn(exn_type, exn_opt, message):
   """When an error is found on the gpt, attempt to fix it.
   """
   return parted.EXCEPTION_RESOLVE_FIX

def getDisk(ns):
   """Read or create a GPT from this namespace.
   """

   dev = parted.getDevice(ns)

   geom = parted.Geometry(dev, start=0, length=dev.getLength())

   try:
      fs = parted.probeFileSystem(geom)
      # libparted did find that a filesystem was present on this
      # namespace. Re-formatting it would erase the data in this
      # filesystem, thus let's bail out.
      return None
   except:
      pass

   try:
      parted.register_exn_handler(new_disk_exn)
      disk = parted.newDisk(dev)
   except parted.DiskException as e:
      # XXX: Only do this if no volume were found.
      disk = parted.freshDisk(dev, 'gpt')

   parted.clear_exn_handler()

   return disk

def readDiskAndDeleteGPT(ns):
   """Read and delete GPT from this namespace.
   """
   # Unmount volume to allow deletion of GPT on this namespace
   volumeUnmounted = False
   try:
      for vol in getVol():
         subprocess.run([mkfsPmem, '--unmount', vol],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, check=True)
         volumeUnmounted = True
   except subprocess.CalledProcessError as e:
      if b"No such file or directory\n" not in e.stderr:
         raise Exception("Cannot unmount PMem volume")

   try:
      # Delete existing GPT (if any) by creating a fresh GPT partition on it
      dev = parted.getDevice(ns)
      disk = parted.freshDisk(dev, 'gpt')
   except parted.DiskException as e:
      # If creating new disk fails, do nothing
      pass

   disk.commit()
   return volumeUnmounted


def computeVolumeExtentStateCrc32(volExtent, extentState):
   """
   Compute the checksum of this extent state.
   """
   volBuf = bytes(volExtent)
   crc32 = zlib.crc32(volBuf[:PMem_VolumeExtentNV.state.offset])

   extentStateBuf = bytes(extentState)
   return zlib.crc32(extentStateBuf[:PMem_VolumeExtentStateNV.crc32.offset],
                     crc32)

def isVolumeExtentStateValid(volExtent, extentState):
   """
   Compute the checksum of the extentState and compare it to the stored
   one.
   """
   crc32 = computeVolumeExtentStateCrc32(volExtent, extentState)

   return crc32 == extentState.crc32

def getValidPMemVolumeExtentState(dev, volExtent):
   """
   Examine the state of the volume and determine the volume state to
   use. None will be returned if the volume isn't valid, or the index of
   the active volume state.
   """

   if volExtent.magic != PMEM_VOLUME_MAGIC:
      return None

   storedNsUuid = uuid.UUID(bytes_le=bytes(volExtent.namespaceUuid))
   if storedNsUuid != getDevUUID(dev):
      return None

   states = [False, False]
   states[0] = isVolumeExtentStateValid(volExtent, volExtent.state[0])
   states[1] = isVolumeExtentStateValid(volExtent, volExtent.state[1])

   if states[0] and states[1]:
      if volExtent.state[0].volGen > volExtent.state[1].volGen:
         return 0
      else:
         return 1
   elif states[0]:
      return 0
   elif states[1]:
      return 1
   else:
      return None

def getPMemVolumeExtentBlockSize(dev):
   """
   Compute and return the number of blocks required to store the volume extent.
   """
   return -(-ctypes.sizeof(PMem_VolumeExtentNV) // dev.sectorSize)

def probePMemVolumeExtent(dev, part):
   """
   XXX: libparted is supposed to probe the partition with all
   the known filesystem, but on a 4K native block device no
   probing is actually done on those until libparted 3.2. Until
   cayman_esx_parted is updated, let's do the probing by hand.
   """
   dev.open()
   buf = part.geometry.read(0, getPMemVolumeExtentBlockSize(dev))
   dev.close()

   vol = PMem_VolumeExtentNV.from_buffer_copy(buf)
   volExtentStateIdx = getValidPMemVolumeExtentState(dev, vol)

   if volExtentStateIdx is None:
      return None

   if vol.dataLossCounter != dev.dataLossCounter:
     vsi.set("/system/sysAlert", "PMem health counters are not matching")

   setattr(vol, 'activeState', volExtentStateIdx)
   setattr(part, 'vol', vol)

   return parted.FileSystem('vmwpmemvolume', part.geometry)

def probePMemPartitions(disk):
   """Iterator over all the PMem partitions.
   """
   dev = disk.device
   
   with open(dev.path) as f:
      try:
         buf = struct.pack("QQ", 1, 0)  # the version/feature is 1
         retBuf = fcntl.ioctl(f, IOCTLCMD_PMEM_GET_HEALTH_STATS, buf)
         version, counter = struct.unpack("QQ", retBuf)
         setattr(dev, 'dataLossCounter', counter)
      except IOError as e:
         raise Exception("Couldn't read PMem health counters: error %s" %
                          e.stderr)

   for part in disk.partitions:
      fs = part.fileSystem
      if fs is None:
         fs = probePMemVolumeExtent(dev, part)

      if fs is None or fs.type != 'vmwpmemvolume':
         continue

      part.fileSystem = fs

      yield part

def createPMemPartitions(disk, volUuid):
   """Iterator that goes over all the free space and tries to create a
   partition on it. Yields all the partition that were successfully added.
   """
   dev = disk.device

   startAlign = parted.Alignment(offset=0,
         grainSize=parted.sizeToSectors(1, 'MiB',
                                        dev.sectorSize))
   endAlign = parted.Alignment(offset=0,
         grainSize=parted.sizeToSectors(2, 'MiB',
                                        dev.sectorSize))

   minSize = parted.sizeToSectors(64, 'MiB', dev.sectorSize)

   for extent in disk.getFreeSpaceRegions():
      fs = parted.FileSystem('vmwpmemvolume', extent)
      part = parted.Partition(disk, parted.PARTITION_NORMAL, fs, extent)

      constraint = parted.Constraint(startAlign=startAlign,
                                     endAlign=endAlign,
                                     startRange=extent,
                                     endRange=extent,
                                     minSize=minSize, maxSize=dev.length)

      try:
         added = disk.addPartition(part, constraint)
      except parted.PartitionException as e:
         if 'Unable to satisfy all constraints on the partition.' not in str(e):
            raise
         else:
            continue
      else:
         if not added:
            continue

      vol = PMem_VolumeExtentNV()

      vol.magic = PMEM_VOLUME_MAGIC
      vol.extentUuid = PMem_UUID(*uuid.uuid4().bytes)
      vol.volumeUuid = volUuid
      vol.namespaceUuid = PMem_UUID(*getDevUUID(dev).bytes_le)
      vol.volumeExtentStateNVSize = ctypes.sizeof(PMem_VolumeExtentStateNV)
      vol.dataLossCounter = dev.dataLossCounter;

      setattr(vol, 'activeState', 0)
      setattr(part, 'vol', vol)

      yield part

def writePartitionHeader(part, allParts):
   """Write the partition header to the namespace.
   """
   disk = part.disk
   dev = disk.device

   # In order for this partition to be recognised as a vmwpmemvolume
   # one, we have to write the magic number to the partition, so that
   # probing this partition will match the vmwpmemvolume correctly.

   dev.open()

   vol = part.vol
   bufSize = getPMemVolumeExtentBlockSize(dev) * dev.sectorSize
   ctypes.resize(vol, bufSize)

   nextIdx = (vol.activeState + 1) % 2

   vol.state[nextIdx].volGen = vol.state[vol.activeState].volGen + 1
   vol.state[nextIdx].numExtents = len(allParts)
   vol.state[nextIdx].pad = 0
   vol.state[nextIdx].crc32 = 0

   for i, p in enumerate(allParts):
      extentSize = p.geometry.length // (PMEM_BLK_SIZE // dev.sectorSize)
      vol.state[nextIdx].extents[i].extentSize = extentSize
      vol.state[nextIdx].extents[i].extentUuid = p.vol.extentUuid

   # Let's first write the whole volume extent header with an invalid
   # crc.  Later on, once the header is known to be fully persistent, we
   # can write the crc. This guarantees that unless the crc is fully
   # written, the volume will not be recognized.

   part.geometry.write(bytearray(vol), 0, bufSize // dev.sectorSize)

   vol.state[nextIdx].crc32 = computeVolumeExtentStateCrc32(vol,
                                                            vol.state[nextIdx])
   part.geometry.write(bytearray(vol), 0, bufSize // dev.sectorSize)

   dev.close()

def exposeToVMKernel(part):
   """Advertise all the extent to the VMKernel.
   """
   disk = part.disk
   dev = disk.device
   ns = dev.path

   with open(ns) as f:
      start = part.geometry.start // (PMEM_BLK_SIZE // dev.sectorSize)
      length = part.geometry.length // (PMEM_BLK_SIZE // dev.sectorSize)
      buf = struct.pack("QQ", start, length)
      fcntl.ioctl(f, IOCTLCMD_PMEM_ADD_VOLUME_EXTENT, buf)

def refreshStorageSystem():
   """
   Refresh storage system to remove PMem datastore from
   hostd/vmodl

   XXX: This can be long running task, as it involves reading
   all storage devices on the host. Change this to less intrusive
   task when available.
   """
   userName = os.getenv('VI_USERNAME', '')
   try:
      si = connect.Connect(host='localhost', user=userName)

      content = si.RetrieveContent()
      rootFolder = content.GetRootFolder()
      dataCenter = rootFolder.GetChildEntity()[0]
      hostFolder = dataCenter.hostFolder
      host = hostFolder.childEntity[0].host[0]
      configManager = host.GetConfigManager()
      storageSystem = configManager.GetStorageSystem()
      storageSystem.Refresh()
   finally:
      connect.Disconnect(si)

def getAllDisks():
   """Probe all the namespaces for GPT partitions.
   """
   allDisks = []

   for ns in getNS():
      disk = getDisk(ns)
      if disk is not None:
         allDisks.append(disk)

   if allDisks == []:
      raise Exception("No suitable namespaces found.")

   return allDisks

def maintenanceModeCheck():
   """Check if system is in maintenance mode.
   """
   from esxutils import runCli

   if runCli(["system", "maintenanceMode", "get"], True) != "Enabled":
      raise Exception("The volume can only be destroyed under maintenance "
                      "mode")

def removeVMWGPT(args):
   """Remove all VMware's partitions from all the namespaces.
   """
   maintenanceModeCheck()

   volumeUnmounted = False
   for vol in getVol():
      subprocess.run([mkfsPmem, '--unmount', vol],
                     stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, check=True)
      volumeUnmounted = True

   allDisks = getAllDisks()

   for d in allDisks:
      for p in probePMemPartitions(d):
         d.removePartition(p)

   for d in allDisks:
      d.commit()

   if volumeUnmounted:
      refreshStorageSystem()

def removeGPT(args):
   """
   Delete GPT partition from from the namespaces.
   """
   maintenanceModeCheck()

   nsFound = False
   for ns in getNS():
      if ns.split("PMemNS-", 1)[1] == args.uuid:
         nsFound = True
         break

   if not nsFound:
      raise Exception("Namespace %s not found"% args.uuid)

   volumeUnmounted = readDiskAndDeleteGPT(ns)
   if volumeUnmounted:
      refreshStorageSystem()

def formatPMem(allDisks, allParts):
   """
   Format the PMem volume with given partitions.
   All the partitions are assumed to be newly created and not committed
   """

   # We are creating new partitions, lets first format the volume
   # then write the partition header to deal with failures. If a failure
   # happens during partition header writing, it will shows up as
   # missing volume extent. At least easier to recognize the error.
   for part in allParts:
      writePartitionHeader(part, allParts)
      exposeToVMKernel(part)

   # Create the volume device, by exposing partition table.
   for d in allDisks:
      dev = d.device
      with open(dev.path) as f:
         try:
            fcntl.ioctl(f, IOCTLCMD_VMFS_BLKRRPART)
         except IOError as e:
            raise Exception("Couldn't expose partitions: %s" % e.stderr)

   for vol in getVol():
      try:
         subprocess.run([mkfsPmem, '--format', vol], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, check=True)
      except subprocess.CalledProcessError as e:
         raise Exception("The PMem Volume couldn't be formatted: " + e.stderr)

def create(args):
   allDisks = getAllDisks()

   existingPmemPartitions = []
   for d in allDisks:
      for p in probePMemPartitions(d):
         existingPmemPartitions.append(p)

   if existingPmemPartitions != []:
      vol = None
      for p in existingPmemPartitions:
         if vol is None:
            vol = p.vol
         else:
            if vol != p.vol:
               raise Exception("Multiple volumes are not supported.")

      s = lambda p: vol.findExtent(p.vol.extentUuid)
      existingPmemPartitions = sorted(existingPmemPartitions, key=s)

      numExtents = vol.state[vol.activeState].numExtents
      if numExtents != len(existingPmemPartitions):
         raise Exception("A volume extent is missing.")

      for e, p in zip(vol.state[vol.activeState].extents,
                      existingPmemPartitions):
         if e.extentUuid != p.vol.extentUuid:
            raise Exception("A volume extent is missing.")

      volumeUuid = vol.volumeUuid
   else:
      volumeUuid = PMem_UUID(*uuid.uuid4().bytes)

   newPmemPartitions = []
   for d in allDisks:
      for p in createPMemPartitions(d, volumeUuid):
         newPmemPartitions.append(p)

   if existingPmemPartitions == [] and newPmemPartitions == []:
      raise Exception("Couldn't find or create a partition on the "
                      "namespaces.")

   if newPmemPartitions != [] and existingPmemPartitions != []:
      vsi.set("/system/sysAlert", "Found free PMem space. "
              "Automatic volume extension is not supported.")

   if existingPmemPartitions == [] and newPmemPartitions != []:
      formatPMem(allDisks, newPmemPartitions)
      # Finally, commit all the partitions to the namespaces. This will
      # also create the volume since it will internally issue the
      # FDS_IOCTL_REREAD_PARTITIONS ioctl, if it is not already created.
      for d in allDisks:
         d.commit()
   else:
      for part in existingPmemPartitions:
         exposeToVMKernel(part)

      # Create the volume device, by exposing partition table.
      for d in allDisks:
         dev = d.device
         with open(dev.path) as f:
            try:
               fcntl.ioctl(f, IOCTLCMD_VMFS_BLKRRPART)
            except IOError as e:
               raise Exception("Couldn't expose partitions: %s" % e.stderr)

   for vol in getVol():
      # Since there could be only one volume, having valid partitions
      # means that the volume is already formatted with the RegionStore
      # and we can try to mount it directly.
      try:
         subprocess.run([mkfsPmem, '--mount', vol], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, check=True)
      except subprocess.CalledProcessError as e:
         raise Exception("The region-store couldn't be mounted. Error: " +
                            e.stderr)

if __name__ == '__main__':
   if hasNS():
      parser = ArgumentParser(description='PMem configurations.')
      subparsers = parser.add_subparsers()

      # parser for command "create"
      parser_create = subparsers.add_parser('create',
                                            help='Format PMem namespaces with VMware RegionStore')
      parser_create.set_defaults(func=create)

      # parser for command "destroy"
      parser_destroy = subparsers.add_parser('destroy',
                                             help='Remove VMware partition from namespaces')
      parser_destroy.set_defaults(func=removeVMWGPT)

      # parser for command "deleteGpt"
      parser_deleteGpt = subparsers.add_parser('deleteGpt',
                                               help='Remove GPT from namespaces')
      parser_deleteGpt.add_argument('--uuid', required=True,
                                    help="UUID of namespace")
      parser_deleteGpt.set_defaults(func=removeGPT)

      args = parser.parse_args()
      try:
         args.func(args)
      except Exception as e:
         print("ERROR:", str(e))
         sys.exit(1)

   print("<output><bool>true</bool></output>")
