
import vmkctl
import util
import os.path

PART_TYPE_NTFS = 7

TEMP_DIR = '/'

def copyFileFromNtfsPartition(filename='ks.cfg'):
    '''Searches through all partitions to find an ntfs partition containing
       a particular file.  Copies the file and returns true if found,
       or returns false if not found.
    '''

    si = vmkctl.StorageInfoImpl()
    diskLuns = [ptr.get() for ptr in si.GetDiskLuns()]

    fileContents = ''
    foundFile = False

    # mtab needs to be there for ntfscat to work.
    if not os.path.exists('/etc/mtab'):
        mtab = open('/etc/mtab', 'w')
        mtab.close()

    for lun in diskLuns:
        for part in [partPtr.get() for partPtr in lun.GetPartitions()]:
            if part.GetPartitionType() == PART_TYPE_NTFS:
                args = ['/sbin/ntfscat', part.GetDevfsPath(), filename]

                try:
                    fileContents = util.execWithCapture(args[0], args,
                                                        raiseException=True)
                except Exception as e:
                    continue

                f = open(os.path.join(TEMP_DIR, filename), 'w')
                f.write(fileContents)
                f.close()

                return True

    return False



