#!/bin/python
#
# Preserve a VMFS partition on a disk before it is re-imaged with ESXi
# Copyright 2009 VMware, Inc.  All rights reserved. 
#

import getopt
import sys
import os
import re

# Commands for passing to fdisk to restore the partition.
#   - assumes vmfs will be partition #3
FDISK_SCRIPT = """n
p
3
%d
%d
t
3
fb
w"""

VISOR_VMFS_PART_ID = 3

VMFS_SCRIPT_NAME = '/vmfs-part.fdisk'
EXTENDED_PART_SIZE = 8192 + 1835008

ERR_PART_EXISTS = "Partition #%d already exists\n" 
ERR_NO_VMFS_SCRIPT = "No vmfs partition script found\n"
ERR_VMFS_SCRIPT = "Vmfs partition script '%s' already exists\n"
ERR_SPECIFY_ARG = "Must specify -s or -r\n"
ERR_NO_DISK_NAME = "Must include disk name to save or restore\n"
ERR_NO_DISK = "Couldn't find disk %s\n"
ERR_NO_GEOM = "Must specify start and end locations\n"
ERR_START_BEFORE_END = "Start sector is before the end sector\n"
ERR_NO_COMMAND = "No command specified\n"
ERR_UNSAVEABLE = "Found vmfs partition but it must be after LBA %d " + \
                 "to save it\n"
ERR_BAD_GEOM = "The start location must be after LBA %d\n"
ERR_NO_VMFS = "No vmfs partition found\n"

TEXT_FOUND_VMFS = """Found vmfs partition:
  Start Sector: %d
  End Sector: %d

  Save these values in case ESXi re-imaging fails.
"""

def write_script(start, end):
    f = open (VMFS_SCRIPT_NAME, 'w')
    f.write(FDISK_SCRIPT % (start, end))
    f.close()

def scan_partitions(disk):
    import parted

    pedDevice = parted.PedDevice.get(disk)
    pedDisk = parted.PedDisk.new(pedDevice)

    part = pedDisk.next_partition()

    found = False

    while part:
        if part.type in [parted.PARTITION_PRIMARY, parted.PARTITION_LOGICAL]:
            if part.fs_type and part.fs_type.name == 'vmfs3':
                if part.geom.start < EXTENDED_PART_SIZE:
                    sys.stderr.write("error: " + 
                                     ERR_UNSAVEABLE % EXTENDED_PART_SIZE)
                    sys.exit(1)
                else:
                    print TEXT_FOUND_VMFS % (part.geom.start, part.geom.end)
                    write_script(part.geom.start, part.geom.end)
                    found = True
                    break
        part = pedDisk.next_partition(part)

    if not found:
        sys.stderr.write(ERR_NO_VMFS)

def find_partition_number(disk, num):
    import parted

    pedDevice = parted.PedDevice.get(disk)
    pedDisk = parted.PedDisk.new(pedDevice)

    part = pedDisk.next_partition()
    found = False

    while part:
        if part.num == num:
            return True
        part = pedDisk.next_partition(part)

    return False

def restore_partition(disk):
    if find_partition_number(disk, VISOR_VMFS_PART_ID):
        sys.stderr.write("error: " + ERR_PART_EXISTS % VISOR_VMFS_PART_ID)
        sys.exit(1)

    if os.path.exists(VMFS_SCRIPT_NAME):
        os.system('fdisk -u %s < %s' % (disk, VMFS_SCRIPT_NAME))
    else:
        sys.stderr.write("error: " + ERR_NO_VMFS_SCRIPT)
        sys.exit(1)

def restore_partition_with_geometry(disk, start, stop):
    if os.path.exists(VMFS_SCRIPT_NAME):
        sys.stderr.write("error: " + ERR_VMFS_SCRIPT % VMFS_SCRIPT_NAME)
        sys.exit(1)

    write_script(start, stop)
    restore_partition(disk)

def usage():
    buf = '''Usage: save_vmfs [-sr] [-g <start>,<end>] <DISK>

Save a current VMFS datastore before re-imaging ESXi onto a disk.

Options:
        -s            Scan and save any VMFS partition before imaging
        -r            Restore the VMFS partition after imaging
        -g start,end  Restore with starting and ending positions
'''

    print buf

def main(argv):
    try:
        opts, args = getopt.getopt(argv[1:], 'rsh?g:', ['help'])
    except getopt.error, e:
        sys.stderr.write("error: %s\n" % str(e))
        return 1

    if opts and opts[0] in [('-h', ''), ('-?', ''), ('--help', '')]:
        usage()
        return 0

    if len(opts) < 1:
        sys.stderr.write("error: " + ERR_SPECIFY_ARG)
        return 1
    elif len(args) != 1:
        sys.stderr.write("error: " + ERR_NO_DISK_NAME)
        return 1

    if os.path.exists(args[0]):
        disk = args[0]
    elif os.path.exists(os.path.join('/vmfs/devices/disks', args[0])):
        disk = os.path.join('/vmfs/devices/disks', args[0])
    else:
        sys.stderr.write("error: " + ERR_NO_DISK % os.path.basename(args[0]))
        return 1

    start = 0
    end = 0
    restore = False
    scan = False

    for opt, arg in opts:
        if opt == '-s':
            scan = True
        elif opt == '-r':
            restore = True
        elif opt == '-g':
            if not re.match(r'^\d+,\d+$', arg):
                sys.stderr.write("error: " + ERR_NO_GEOM)
                return 1

            start, end = arg.split(',')
            if int(start) >= int(end):
                sys.stderr.write("error: " + ERR_START_BEFORE_END)
                return 1
            elif int(start) < EXTENDED_PART_SIZE:
                sys.stderr.write("error: " + ERR_BAD_GEOM % EXTENDED_PART_SIZE)
                return 1

    if scan:
        scan_partitions(disk)
    elif restore:
        if int(end) > 0:
            restore_partition_with_geometry(disk, int(start), int(end))
        else:
            restore_partition(disk)
    else:
        sys.stderr.write("error: " + ERR_NO_COMMAND)
        return 1

    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
