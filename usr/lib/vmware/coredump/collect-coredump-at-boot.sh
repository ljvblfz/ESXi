#!/bin/sh
#
# Copyright 2017 VMware, Inc.  All rights reserved.
#
# Collects coredumps from the dump partition or file during boot.

MAX_CORES=10
MIN_SPACE_MB=600 # Includes space for new core dump (100MB)

log() {
   /bin/logger -t bootstop "$@"
}

logvob() {
   local msg=$1 uvob=$2
   shift 2
   log "$msg"
   /usr/lib/vmware/vob/bin/addvob "vob.user.$uvob" "$@"
}

netDumpEnabled() {
   /sbin/localcli --formatter=json system coredump network get \
      | grep -q '\"Enabled\"\: true\,$'
}

listCores() {
   ls -t /var/core/vmkernel-zdump.* 2> /dev/null 
}

listVmfsDumps() {
   ls -t /var/core/*vmfsdump.gz 2> /dev/null
}

volumeFreeSpaceMB() {
   stat -fc '%s %f' $1 | (read bsize nfree; echo $((bsize * nfree / 1000000)))
}

rotateCores() {
   #
   # Limit the number of core files
   #
   numCores=$(listCores | wc -l)
   if [ $numCores -ge $MAX_CORES ]; then
      removeCount=$((numCores - MAX_CORES + 1))
      listCores | tail -$removeCount | xargs rm -f
   fi

   #
   # Try to leave some space available. We strive to keep at least
   # one old core around, but remove extra cores if we don't have
   # enough space.
   #
   case "$(readlink -f /var/core)"  in
      (/vmfs/volumes/*)
         # This is a datastore; we can dump if there's enough space.
         while [ "$(volumeFreeSpaceMB /var/core)" -lt $MIN_SPACE_MB ]; do
            # Keeping vmfs dumps around is lower priority than zdumps
            lastVmfsDump=$(listVmfsDumps | tail -1)
            if [ -n "$lastVmfsDump" ] ; then
               log "Removing vmfsdump $lastVmfsDump to make space."
               rm -f "$lastVmfsDump"
            else
               lastCore=$(listCores | tail -1)
               numCores=$(listCores | wc -l)
               if [ -z "$lastCore" -o "$numCores" -eq 1 ]; then
                  logvob "Unable to free up ${MIN_SPACE_MB}MB in /var/core." \
                           coredump.copyspace $MIN_SPACE_MB
                  return 1
               fi
               log "Removing $lastCore to make space."
               rm -f "$lastCore"
            fi
         done
         return 0
         ;;
      (*)
         # This is visorfs; do not dump
         log "/var/core is on visorfs."
         return 1
         ;;
   esac
}

checkVmfsDump() {
   firstCore=$(listCores | head -1)

   /sbin/vmkdump_extract -l -L /tmp/vmk.log "$firstCore"
   device=`grep 'and upload the dump by \`dd if=\/vmfs\/devices\/disks' \
           /tmp/vmk.log | \
           sed 's/^.*dd if=\/vmfs\/devices\/disks\/\(.*\) of=.*$/\1/'`
   vsandevice=false
   module=vmfs
   vmfs6=false
   if [ -z "$device" ] ; then
      device=`grep 'and upload the dump by \`voma -m vmfs' \
              /tmp/vmk.log | \
              sed 's/^.* dump -d \/vmfs\/devices\/disks\/\(.*\) -D.*$/\1/'`
      module=`grep 'and upload the dump by \`voma -m vmfs' \
              /tmp/vmk.log | \
              sed 's/^.*voma -m \(.*\) -f.*$/\1/'`
      vmfs6=true
   fi
   if [ -z "$device" ] ; then
      device=`grep -E 'and upload the dump by \`objtool open -u .*; dd ' \
              /tmp/vmk.log | \
              sed 's/^.*dd if=\/dev\/vsan\/\(.*\) of=.*$/\1/'`
      vmfs6=false
      vsandevice=true
      module=vmfsd
   fi
   if [ -z "$device" ] ; then
      device=`grep -E 'and upload the dump by \`objtool open -u .*; voma ' \
              /tmp/vmk.log | \
              sed 's/^.*-f dump -d \/dev\/vsan\/\(.*\) -D.*$/\1/'`
      vmfs6=true
   fi
   if [ -n "$device" ] ; then
      log "core dumped due to fs corruption on $device."
      case "$(readlink -f /var/core)"  in
         (/vmfs/volumes/*)
            # Remove any previously existing vmfs dumps, regardless of how
            # much free space is left ($MIN_SPACE_MB)
            vmfsDumps=$(listVmfsDumps)
            if [ -n "$vmfsDumps" ] ; then
               log "Removing existing VMFS dumps to make room for new one."
               rm -f $vmfsDumps
            fi
            log "dumping $device metadata."
            devicename=`basename $device`
            if [ "$vsandevice" = "true" ] ; then
               # We need to make sure vsan object is open first
               lscmd=`echo "/usr/lib/vmware/osfs/bin/objtool open -u $devicename"`
               module=vmfsd
               path=/dev/vsan/$device
            else
               lscmd=`echo "true"`
               path=/vmfs/devices/disks/$device
            fi

	    if [ "$vmfs6" = "true" ] ; then
               $lscmd &> /dev/null &&
                  /bin/voma -m $module -f dump -d $path -D \
                  /var/core/$devicename.vmfsdump
	    else
               $lscmd &> /dev/null && 
                  /bin/dd if=$path bs=1M count=2000 conv=notrunc | /bin/gzip > \
                  /var/core/$devicename.vmfsdump.gz
	    fi
            log "dumping of $device metadata completed."
            ;;
         (*)
            # visorfs - don't waste the space
            log "/var/core is on visorfs, not dumping $device metadata."
            ;;
      esac
   fi
   rm -f /tmp/vmk.log
}

checkDumpFile() {
   case "$(/sbin/esxcfg-dumppart -F -T -D active -n)" in
      (YES)
         logvob "file core dump found" host.coredump
         rotateCores && /sbin/esxcfg-dumppart -F -C -D active -n \
            && checkVmfsDump
         ;;
      (NO)
         ;;
      (*)
         log "Error encountered when checking for file core dump"
         ;;
   esac
}

checkDumpPartition() {
   local partition=$1

   # We first check to see if we can extract a coredump with the -Z option
   # which indicates the slot size. In cases when we dump core even before
   # coredump partition is setup, this option is required for extracting the
   # coredump from the partition. If this does not work, we fall back to
   # extraction without -Z. Note that for the larger coredump partition,
   # we will never need to use the -Z option.
   case "$(/sbin/esxcfg-dumppart -T -C -D $partition -Z 100 -n)" in
      (YES)
         logvob "partition core dump found" host.coredump
         rotateCores && /sbin/esxcfg-dumppart -C -D $partition -Z 100 -n \
            && checkVmfsDump
         ;;

      (NO | *)
         case "$(/sbin/esxcfg-dumppart -T -C -D $partition -n)" in
            (YES)
               logvob "partition core dump found" host.coredump
               rotateCores && /sbin/esxcfg-dumppart -C -D $partition -n \
               && checkVmfsDump
               ;;
            (NO)
               ;;
            (*)
               log "Error encountered when checking for partition core dump"
               ;;
         esac
   esac
}

diskpart="$(/sbin/esxcfg-dumppart -t)"
filepart="$(/sbin/esxcfg-dumppart -Ft)"

if [ "$diskpart" = "none" -a "$filepart" = "none" ] && ! netDumpEnabled; then
   logvob "No disk, file or network coredump enabled" coredump.unconfigured
   return
fi

if [ "$diskpart" != "none" ]; then

   # Complete partition paths are in the second column, ignore the first 2 lines
   # since they contain column names and a line separator.
   partList="$(/sbin/localcli system coredump partition list | awk '{print $2}' | tail -n+3)"

   for partition in $partList; do
      checkDumpPartition $partition
   done
fi

if [ "$filepart" != "none" ]; then
   checkDumpFile
fi
