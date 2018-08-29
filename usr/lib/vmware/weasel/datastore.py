import vmkctl
from . util import loadVmfsModule, rescanVmfsVolumes
from . util.singleton import Singleton

from weasel.log import log

class Datastore:
    def __init__(self, name, uuid=None, consolePath=None, driveName="",
                 majorVersion=0, minorVersion=0, totalBlocks=0,
                 blockSize=0, blocksUsed=0, unscannable=False):
        self.name = name
        self.uuid = uuid
        self.consolePath = consolePath
        self.driveName = driveName
        self.majorVersion = majorVersion
        self.minorVersion = minorVersion
        self.totalBlocks = totalBlocks
        self.blockSize = blockSize
        self.blocksUsed = blocksUsed
        self.unscannable = unscannable

    def getFreeBlocks(self):
        return self.totalBlocks - self.blocksUsed

    def getFreeSize(self):
        return self.getFreeBlocks() * self.blockSize

    def getSize(self):
        return self.totalBlocks * self.blockSize


class DatastoreSet(Singleton):
    '''A class to store vmfs volumes'''
    def _singleton_init(self, scan=False):
        self.entries = []
        self.scanned = False

    def __init__(self, scan=False):
        if scan or not self.scanned:
            self.entries = []

            self.scanVmfsVolumes()
            self.scanned = True

    def scanVmfsVolumes(self):
        loadVmfsModule()
        rescanVmfsVolumes()

        storage = vmkctl.StorageInfoImpl()
        volumes = [ptr.get() for ptr in storage.GetVmfsFileSystems()]

        for vol in volumes:
            # XXX - need to deal with vmfs extents properly
            extents = [extPtr.get() for extPtr in vol.GetExtents()]
            assert len(extents) > 0

            # device name = 'vml.XXXXX'
            driveName = extents[0].GetDeviceName()

            allDriveNames = [ ext.GetDeviceName for ext in extents ]

            try:
                self.append(Datastore(
                    name=vol.GetVolumeName(),
                    uuid=vol.GetUuid(),
                    consolePath=vol.GetConsolePath(),
                    driveName=driveName,
                    majorVersion=vol.GetMajorVersion(),
                    minorVersion=vol.GetMinorVersion(),
                    totalBlocks=vol.GetTotalBlocks(), blockSize=vol.GetBlockSize(),
                    blocksUsed=vol.GetBlocksUsed()))
            except vmkctl.HostCtlException as ex:
                log.exception("Got a potentially corrupt volume on  disk: %s."
                              " Marking it as such" % driveName)
                self.append(Datastore(
                    name=vol.GetVolumeName(),
                    uuid=vol.GetUuid(),
                    consolePath=vol.GetConsolePath(),
                    driveName=driveName,
                    unscannable=True))

    def getEntryByName(self, name):
        for entry in self.entries:
            if entry.name == name or entry.uuid == name:
                return entry
        return None

    def getEntriesByDriveName(self, driveName):
        foundEntries = []
        for entry in self.entries:
            if entry.driveName == driveName:
                foundEntries.append(entry)
        return foundEntries

    def append(self, entry):
        self.entries.append(entry)

    def remove(self, entry):
        self.entries.remove(entry)

    def __getitem__(self, key):
        return self.entries[key]

    def __len__(self):
        return len(self.entries)

    def __bool__(self):
        return len(self.entries) > 0

def checkForClearedVolume(driveList, datastoreSet, volumeName):
    '''Check to see if a given datastore has been cleared'''

    vol = datastoreSet.getEntryByName(volumeName)
    if vol and vol.driveName in driveList:
        return True
    return False

