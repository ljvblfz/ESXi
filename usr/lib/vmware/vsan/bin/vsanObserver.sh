#!/bin/sh ++group=host/vim/vmvisor/vsanobserver
#
# Copyright 2015 VMware, Inc.  All rights reserved.
#
#   The VSAN observer service
#
#
VSANTRACED_CONF="/etc/vmware/vsan/vsantraced.conf"
VSANOBSERVER="vsanObserver.sh: "
VSANOBSERVER_SCRIPT="/usr/lib/vmware/vsan/bin/vsanObserver.sh"
VSANOBSERVER_NAME=vsanObserver--
VSANOBSERVER_NAMETEMPLATE=/tmp/${VSANOBSERVER_NAME}.result
VSANOBSERVER_ROTATION=10
VSANOBSERVER_TEMP="/tmp/.vsanObserver"
VSANOBSERVER_MAX_MB_SIZE=52 # Compressed size of vsanObserver traces
# Modify VSANTRACED_ROTATE_FILE_SIZE if this value is changed. Right now
# we assume 8 trace files of 45MB size after compression and 4 urgent
# trace files of 22MB for a total of 448MB. To that we add 52MB for
# observer stats for a grand total of 500MB.
# Note that if the traces are put on a VMFS volume, then du will report
# that each observer stats is consuming at least one megabyte.

# If the value of VSANOBSERVER_MAX_MB_SIZE is changed, also change the
# same value in '/bora/install/vmvisor/environ/etc/init.d/vsantraced'
# as the size of the files stored on ramdisk have to be adjusted accordingly.

PATH=/sbin:/usr/sbin:/bin:/usr/bin
export PATH

syslog() {
   echo "$@"
   logger -p daemon.info "$@"
}

if [ -e "$VSANTRACED_CONF" ]; then
   . "$VSANTRACED_CONF"
else
   syslog $VSANOBSERVER"Could not find vsantraceReader config file"
fi

# Check if vsan traces are enabled
/etc/init.d/vsantraced status
if [ $? -ne 0 ]; then
    syslog $VSANOBSERVER"vsantraced is not started - try to start it"

    /etc/init.d/vsantraced ++group=host/vim/tmp restart
    if [ $? -ne 0 ]; then
        syslog $VSANOBSERVER"vsantraced can't be started successfully"
        exit 1
    fi
    . "$VSANTRACED_CONF" # after restarting vsantraced, need to reload the conf
fi

# Check if cmmdsTimeMachine is running.
#
# Don't log on success since cmmdsTimeMachine is currently disabled
# by default (silently succeeds but no daemon started), and we don't
# want lots of log spew.
if [ -x "$/etc/init.d/cmmdsTimeMachine" ]; then
   /etc/init.d/cmmdsTimeMachine status
   if [ $? -ne 0 ]; then
       /etc/init.d/cmmdsTimeMachine ++group=host/vim/tmp restart
       if [ $? -eq 0 ]; then
          syslog $VSANOBSERVER"cmmdsTimeMachine can't be started successfully"
       fi
   fi
fi

if [ -z "$VSANTRACED_LAST_SELECTED_VOLUME" ]; then
    VSANTRACED_LAST_SELECTED_VOLUME=/var/log/vsantraces
fi

if [ ! -d "$VSANTRACED_LAST_SELECTED_VOLUME" ]; then
    syslog $VSANOBSERVER"Could not find a directory for the vsan traces"
    exit 1
fi

if [ ! -e "/bin/gzip" ]; then
    syslog $VSANOBSERVER"Gzip is not present on the box"
    exit 1
fi

# To prevent possible concurrent execution
pidCount=`sh -c "ps -uc | awk -v BIN=\\"$VSANOBSERVER_SCRIPT\\" '(\\$1 ~ /^[0-9]/ && \\$5 == BIN) { print \\$1 }' | wc -l"`
syslog "There are $pidCount $VSANOBSERVER_SCRIPT running ..."
if [ $pidCount -gt 1 ]; then
   exit 1
fi

generateNewName=0
if [ -e "$VSANOBSERVER_TEMP" ]; then
    filenameFormat=$(cat $VSANOBSERVER_TEMP | awk '{ print $1 }')
    counter=$(cat $VSANOBSERVER_TEMP | awk '{ print $2 }')
    if [ $counter -eq $VSANOBSERVER_ROTATION ]; then
        generateNewName=1
    else
        counter=$((counter+1))
    fi
else
    generateNewName=1
fi

if [ $generateNewName -eq 1 ]; then
    # Format for the file name: i.e. vsanObserver--2015-02-25T22h21m43s.gz
    filenameFormat=$(date +%FT%Hh%Mm%Ss.gz)
    filenameFormat=$VSANOBSERVER_NAME$(echo $filenameFormat | head -c26)
    counter=0
fi

touch $VSANOBSERVER_TEMP
echo $filenameFormat $counter > $VSANOBSERVER_TEMP

# Save the last observer traces
/usr/lib/vmware/vsan/bin/vsanObserver `hostname` | gzip  >> $VSANTRACED_LAST_SELECTED_VOLUME/$filenameFormat

# Only keep VSANOBSERVER_MAX_MB_SIZE of observer files
# We need to use $VSANTRACED_LAST_SELECTED_VOLUME/ with
# the final '/' to make sure we follow symlinks.

# Clean old temp files if there is any
rm ${VSANOBSERVER_NAMETEMPLATE}.* -rf

sizeKB=0
freeMB=0
tmpFile=$(mktemp ${VSANOBSERVER_NAMETEMPLATE}.XXXXXX)

CalcFreeSpace() {
   # Below we execute a bunch of commands for calculating logs size and free
   # space. We don't use much longer pipeline operation since that will cause
   # multiple processes created at the same time, which may cause hitting the
   # memory limitation of vsanObserver. We try to avoid that by limiting the
   # pipeline operations.

   find $VSANTRACED_LAST_SELECTED_VOLUME/ -name "$VSANOBSERVER_NAME*" | xargs ls -s -k > $tmpFile
   if [ $? -ne 0 ]; then
      syslog "Error: failed to find vsanObserver logs"
      return 1
   fi
   sizeKB=$(cat $tmpFile | awk 'BEGIN {sum=0} {sum+=$1} END {print sum}')

   IFS=$'\n'

   # Try to find vsantraces volume in ramdisk list
   fsList=$(localcli system visorfs ramdisk list | tail -n+3)
   if [ $? -ne 0 ]; then
      syslog "Error: failed to get ramdisk list"
      return 1
   fi
   traceDir=$(readlink -f $VSANTRACED_LAST_SELECTED_VOLUME)
   for line in $fsList; do
      mp=$(echo $line | awk '{ print $19 }')
      if [ "x$mp" == "x"]; then
         # syslog "Skip invalid ramdisk mount point: $line"
         continue
      fi
      mp=$(readlink -f $mp)
      if [[ $traceDir == $mp* ]]; then
         syslog "Found ramdisk entry for vsantraces: $line"
         freeMB=$(echo $line | awk '{ print $6-$8 }')
         if [ $? -ne 0 -o "x$freeMB" == "x" ]; then
            syslog "Unable to get ramdisk free space: $line"
            freeMB=0
            return 1
         else
            freeMB=$(expr $freeMB / 1024)
            return 0
         fi
      fi
   done

   # If we don't find it from ramdisk list, we try the persistent volumes

   # Get vsantrace volume device ID
   devId=$(stat -c %d -L $VSANTRACED_LAST_SELECTED_VOLUME)
   if [ $? -ne 0 ]; then
      syslog "Error: failed to get devive ID of $VSANTRACED_LAST_SELECTED_VOLUME"
      return 1
   fi
   syslog "vsantraces is on device $devId"

   # Get the full filesystem list through localcli
   fsList=$(localcli storage filesystem list | tail -n+3)
   if [ $? -ne 0 ]; then
      syslog "Error: failed to get filesystem list"
      return 1
   fi

   for line in $fsList; do
      startCh=${line:0:1}
      if [ "x$startCh" == "x" -o "x$startCh" == "x " ]; then
         # Unexpected output, skip it
         # syslog "Skip due to invalid mount point: $line"
         continue
      fi

      # Get the mount point
      mp=$(echo $line | awk '{ print $1 }')

      # Get devId of the mount point, skip if there is error
      fsDevId=$(stat -c %d -L $mp)
      if [ $? -ne 0 ]; then
         # syslog "Skip due to fail to get devId: $line"
         continue
      fi

      if [ "x$devId" == "x$fsDevId" ]; then
         syslog "Found file system entry for vsantraces: $line"
         freeMB=$(echo "$line" | awk '{if (NF == 6) { print $6 } else { print $7 }}')
         if [ $? -ne 0 -o "x$freeMB" == "x" ]; then
            syslog "Unable to get volume free space: $line"
            freeMB=0
            return 1
         else
            freeMB=$(expr $freeMB / 1024 / 1024)
            return 0
         fi
      fi
   done

   return 1
}

CalcFreeSpace

syslog "CalcFreeSpace sizeKB: $sizeKB, freeMB: $freeMB"

# If for some reason the free space is falling below the amount of observer
# stats we keep around, clear more of the observer files.
if [ $? -eq 0 -a freeMB -lt "$VSANOBSERVER_MAX_MB_SIZE" ]; then
   VSANOBSERVER_MAX_MB_SIZE=$freeMB
   syslog $VSANOBSERVER"Only keeping $VSANOBSERVER_MAX_MB_SIZE MB of observer traces"
fi

VSANOBSERVER_MAX_KB_SIZE=$(expr $VSANOBSERVER_MAX_MB_SIZE \* 1024)

while [ $sizeKB -gt "$VSANOBSERVER_MAX_KB_SIZE" ];
do
   # Find the oldest log and delete for release some more space
   find $VSANTRACED_LAST_SELECTED_VOLUME/ -name "$VSANOBSERVER_NAME*" | xargs stat  -c "%Y %n" -L > $tmpFile
   if [ $? -ne 0 ]; then
      syslog "Error: failed to find vsanObserver logs for deleting last"
      exit 1
   fi

   last=$(sort -n -k1 -r $tmpFile | tail -1)
   last=$(echo $last | awk '{ print $2 }')
   syslog "Remove oldest log file: $last"

   if [ -e "$last" ]; then
      rm $last
   fi

   find $VSANTRACED_LAST_SELECTED_VOLUME/ -name "$VSANOBSERVER_NAME*" | xargs ls -s -k > $tmpFile
   if [ $? -ne 0 ]; then
      syslog "Error: failed to find vsanObserver logs for recalc size"
      exit 1
   fi
   sizeKB=$(cat $tmpFile | awk 'BEGIN {sum=0} {sum+=$1} END {print sum}')

   syslog "Log size is $sizeKB after removing $last"

done

exit 0
