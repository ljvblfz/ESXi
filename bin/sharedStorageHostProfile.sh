#!/bin/sh
# bora/install/vmvisor/environ/bin/sharedStorageHostProfile.sh
#
# Copyright 2014 VMware, Inc.  All rights reserved.
#
# This script exports 5 commands: "local", "remote", "compare" and "configure",
# plus "automatic".  This last executes the first 4 commands in sequence.
# Local and remote extract the PSA PsaDeviceSharingProfile in text form from,
# respectively, the local and a specified remote host which must have ssh
# enabled, etc.  The compare command extracts a list of devices and sharing
# state from the two profiles and generates lists of shared and non-shared
# devices on the two hosts plus a set of esxcli commands to reset clusterwide
# sharing to match the observed sharing between the hosts.  The configure
# command sets devices to be shared clusterwide or not shared clusterwide on
# the local host and user can edit the command file before running this command.
#

export PATH=/sbin:/bin

log() {
   echo "$*"
   logger init "$*"
}

# Return values
SYNTAX_ERROR=11 # Wrong count or type of parameters, non-existent directory, etc.
USER_QUIT=10 # User terminated program rather than supplying ssh password, etc.
RUNTIME_ERROR=9 # Unable to create a working directory, etc.
FAILURE_BECUASE_RECONFIGURATION_WAS_NEEDED=8 # Failure from test-esx, etc.

#
# Determine the devices on the local host that are shared and those that are
# not shared with the remote host.  Shared devices are assumed to be shared
# clusterwide so care may need to be taken in choosing the remote host.
# Further determine which devices need to be reconfigured due to default
# clusterwide sharing state not matching actual sharing.  Avoid reconfiguring
# local devices which compare as false positives for sharing clusterwide due
# to identical identifiers for local devices on both hosts.
#
compare() {
   localFile=$1
   remoteFile=$2
   outFile=$3
   tmpDir=`dirname $outFile`/$$
   if [ $# -gt 3 ]; then
      failIfAnyWorkToDo=$4
   else
      failIfAnyWorkToDo=0
   fi

   mkdir $tmpDir
   if [ ! -d $tmpDir ]; then
      log "unable to create $tmpDir subdirectory for intermediate files; $outFile not created"
      return ${RUNTIME_ERROR}
   fi

   #
   # ESXi busybox lacks comm (although busybox does have it), so roll our own.
   # Note also that we need to detect shared devices with different sharing
   # settings on the two hosts as shared so adding comm to busybox will _not_
   # make this a one-liner.  Given that comm is rarely used we chose not to
   # bloat ESXi by requesting for it to be added.  For each of local and remote
   # generate 2 files, 1 with lines of form "mpx.vmhba0:C0:T0:L0" and 1 with
   # "\tisSharedClusterwide = True" (or False) appended.  All sorted by device.
   #
   for file in $localFile $remoteFile
   do
      if [ ! -s $file ]; then
         command=`basename $file | cut -d- -f1`
         if [ -f $file ]; then
            log "$file is empty; rerun \"${command}\" command"
         else
            log "$file not found; rerun \"${command}\" command"
         fi

         rm -rf $tmpDir
         return 3
      fi

      tmpFile=`basename $file`
      cat $file | awk '{if ($1 == "deviceName") printf "%s\t",$3; else if ($1 == "isSharedClusterwide") {gsub(/^[ ]+/, "", $0); print};}' | sort -k 1,1 > ${tmpDir}/${tmpFile}.sharing
      cat  ${tmpDir}/${tmpFile}.sharing | cut -f1 >  ${tmpDir}/${tmpFile}.devices
   done

   #
   # Diff .devices files for a list of local devices not shared with other host.
   # Diff local devices files (shared and not) to get a list of shared devices.
   #
   localTmpFile=${tmpDir}/`basename $localFile`
   remoteTmpFile=${tmpDir}/`basename $remoteFile`
   outTmpFile=${tmpDir}/`basename $outFile`

   diff -U 0 ${localTmpFile}.devices ${remoteTmpFile}.devices | grep '^[-][^-]' | cut -c2- > ${localTmpFile}.notShared.devices
   diff -U 0 ${localTmpFile}.devices ${localTmpFile}.notShared.devices | grep '^[-][^-]' | cut -c2- > ${localTmpFile}.shared.devices


   #
   # Intersection of ${localTmpFile}.{notShared,shared}.devices is empty set.
   # Construct a file with "\tisSharedClusterwide = True" (or False) appended.
   #
   cat ${localTmpFile}.shared.devices | awk '{printf "%s\tisSharedClusterwide = True\n",$0}' > ${localTmpFile}.sharing.raw
   cat ${localTmpFile}.notShared.devices | awk '{printf "%s\tisSharedClusterwide = False\n",$0}' >> ${localTmpFile}.sharing.raw
   sort -k 1,1 ${localTmpFile}.sharing.raw > ${localTmpFile}.sharing.clusterwide

   #
   # Store local host devices that are misconfigured in $outTmpFile.raw
   # Local devices cannot be shared, so strip any corrections that set a local
   # devices to shared as these indicate identical local devices on both hosts.
   #
   diff -U 0 ${localTmpFile}.sharing.clusterwide ${localTmpFile}.sharing | grep '^[-][^-]' | cut -c2- > ${outTmpFile}.raw
   touch ${outTmpFile}.final ${outTmpFile}.skipped-local-devices
   for line in `cat ${outTmpFile}.raw | awk '{printf "%s+%s\n",$1,$4}'`
   do
      device=`echo $line | cut -d+ -f1`
      sharedClusterwide=`echo $line | cut -d+ -f2`
      if [ "x"`esxcli --formatter=keyvalue storage core device list -d $device | grep ScsiDevice.IsLocal.boolean | cut -d= -f2` == "xtrue" -a $sharedClusterwide == "True" ]; then
         echo $line | cut -d+ -f1 >> ${outTmpFile}.skipped-local-devices
      else
         echo $line | awk -F+ '{printf "%s\t%s\n",$1,$2;}' >> ${outTmpFile}.final
      fi
   done

   #
   # Finally, build up a set of esxcli commands to effect the needful changes
   #
   rm -rf $outFile
   touch $outFile
   cat ${outTmpFile}.final | awk '{if ($2 == "False") VAL = "false"; else VAL = "true"; printf "esxcli storage core device setconfig -d %s --shared-clusterwide=%s\n",$1,VAL}' > $outFile

   if [ -f $outFile ]; then
      # XXX Don't clean up empty file as empty means no reconfiguration needed
      compResult=0
      log "Commands to reconfigure device sharing on localhost written to $outFile"
   else
      log "Commands to reconfigure device sharing on localhost could not be determined."
      compResult=4
   fi
   if [ $failIfAnyWorkToDo -ne 0 -a -s $outFile ]; then
      echo "$outFile is not empty; PSA device sharing on local host is NOT properly configured; failing command."
      return ${FAILURE_BECUASE_RECONFIGURATION_WAS_NEEDED}
   fi

   rm -rf $tmpDir
   return $compResult
}

#
# Configure sharing appropriately on the local host
#
configure() {
   cmdFile=$1
   if [ $# -gt 1 ]; then
      failIfAnyWorkToDo=$2
   else
      failIfAnyWorkToDo=0
   fi

   if [ ! -s $cmdFile ]; then
      if [ -f $cmdFile ]; then
         echo "$cmdFile is empty; PSA device sharing on local host is properly configured."
         return 0
      else
         echo "$cmdFile not found; rerun \"compare\" command"
         return 5
      fi
   fi
   if [ $failIfAnyWorkToDo -ne 0 ]; then
      echo "$cmdFile is not empty; PSA device sharing on local host is NOT properly configured; failing command."
      return ${FAILURE_BECUASE_RECONFIGURATION_WAS_NEEDED}
   fi


   echo "Preparing to reconfigure PSA device sharing on the local host;"
   echo `cat $cmdFile | wc -l`" PSA devices are incorrectly configured:"
   echo ""
   for device in `cat $cmdFile | awk '{for (i=1; i<=NF; ++i) if ($i == "-d") {print $(i+1); break;}}'`
   do
      echo "   $device"
   done

   echo ""
   echo "Continue to automatically reconfigure all of the above devices."
   echo "Alternatively you may stop and enter some or all of the commands in"
   echo "$cmdFile manually."
   echo ""
   echo -n "To continue press y and to quit press n: "

   read answer
   if [ "x$answer" != "xy" -a "x$answer" != "xY" ]; then
      return ${USER_QUIT}
   fi

   . $cmdFile
   return 0
}

#
# Get the PsaDeviceSharingProfile for the local host
#
local() {
   outFile=$1
   errorFile=$2

   rm -f $outFile $errorFile
   /usr/lib/vmware/vm-support/bin/storageHostProfiles.sh storage.psa_psaProfile_PluggableStorageArchitectureProfile.psa_psaProfile_PsaDeviceSharingProfile > $outFile 2> $errorFile

   if [ -s $outFile ]; then
      log "localhost's PsaDeviceSharingProfile written to $outFile"
   else
      # XXX Clean up any empty file
      rm -f $outFile
      log "localhost's PsaDeviceSharingProfile could not be extracted; details in $errorFile"
      return 2
   fi

   return 0
}

#
# Get the PsaDeviceSharingProfile for the specified remote host
#
remote() {
   rHost=$2
   ping -c 2 $rHost 2>&1 > /dev/null

   if [ $? -ne 0 ]; then
      echo "Usage: `basename "$0"` remote output-directory hostname-that-is-up-and-reachable"
      return ${SYNTAX_ERROR}
   fi

   echo "Attempting to execute via ssh the command to extract the PsaDeviceSharingProfile"
   echo "from remote host $rHost.  This requires that ssh be"
   echo "enabled and that you have access to an account on the host.  Alternatively"
   echo "you may execute \"$0 local\" command on the remote"
   echo "host and manually transfer the $rHost:/tmp/local-shared-profile.txt"
   echo "output file to this host as "`dirname $1`"/remote-shared-profile.txt."
   echo ""
   echo -n "To continue press y and to quit press n: "

   read answer
   if [ "x$answer" != "xy" -a "x$answer" != "xY" ]; then
      return ${USER_QUIT}
   fi

   # Cannot use error errorFile because ssh can require a password
   outFile=$1
   user=`who | head -1 | cut -d' ' -f1`

   rm -f $outFile
   ssh $user@$rHost "/usr/lib/vmware/vm-support/bin/storageHostProfiles.sh storage.psa_psaProfile_PluggableStorageArchitectureProfile.psa_psaProfile_PsaDeviceSharingProfile" > $outFile

   echo ""
   if [ -s $outFile ]; then
      log "remote host ($rHost) PsaDeviceSharingProfile written to $outFile"
   else
      # XXX Clean up any empty file left behind by a timed out ssh session
      rm -f $outFile
      log "remote host ($rHost) PsaDeviceSharingProfile could not be extracted"
      return 1
   fi

   return 0
}

#
# Marshall and dispatch the command
#
dispatch()
{
   localFile=$1/local-shared-profile.txt
   localErrorFile=$1/local-shared-profile.err
   remoteFile=$1/remote-shared-profile.txt
   configFile=$1/esxcli-sharing-reconfiguration-commands.txt
   dispResult=0

   case "$2" in
      compare)
         compare $localFile $remoteFile $configFile $3
         dispResult=$?
         ;;
      configure)
         configure $configFile $3
         dispResult=$?
         ;;
      local)
         local $localFile $localErrorFile
         dispResult=$?
         ;;
      remote)
         if [ $# -eq 3 ]; then
            remote $remoteFile $3
            dispResult=$?
         else
            dispResult=${SYNTAX_ERROR}
         fi
         ;;
      *)
         dispResult=${SYNTAX_ERROR}
   esac

   return $dispResult
}

result=0

if [ $# -lt 2 -o $# -gt 3 ]; then
   result=${SYNTAX_ERROR}
elif [ $1 == "automatic" ]; then
   tempDir=/tmp/$$/$$/

   mkdir -p $tempDir
   if [ ! -d $tempDir ]; then
      log "unable to create $tempDir directory for intermediate files; aborting automatic operation"
      result=${RUNTIME_ERROR}
   else
      for command in remote local compare configure
      do
         if [ $command == "compare" -o $command == "configure" ]; then
            dispatch $tempDir $command $3
         else
            dispatch $tempDir $command $2
         fi
         result=$?
         if [ $command == "remote" -a $result -eq ${USER_QUIT} ]; then
            echo "Ssh to remote host aborted; do you wish to continue after manually transferring the file?"
            echo ""
            echo -n "To continue, first manually transfer the file as directed above and then press y; to quit press n: "

            read answer
            if [ "x$answer" != "xy" -a "x$answer" != "xY" ]; then
               result=${USER_QUIT}
               break
            fi
         elif [ $result -ne 0 ]; then
            log "Command $command failed; aborting automatic operation"
            break
         else
            echo ""
         fi
      done

      if [ $result -eq 0 ]; then
         rm -rf $tempDir
      else
         log "Command \"automatic\" failed; intermediate files left in $tempDir"
      fi
   fi
elif [ ! -d $2 ]; then
   result=${SYNTAX_ERROR}
else
   dispatch $2 $1 $3
   result=$?
fi

if [ $result -ge $SYNTAX_ERROR ]; then
   # We expose a "fail-if-any-change-needed" option for automated tests.
   # The option is needed to prevent the "configure" command from hanging
   # waiting on user input but it is desireable to early fail in the "compare"
   # command so that intermediate files from latter are preserved for analysis.
   log "Usage: "`basename $0`" { compare | configure } input-output-directory [ fail-if-any-change-needed ]"
   log "Usage: "`basename $0`" local output-directory"
   log "Usage: "`basename $0`" remote output-directory name-or-ip-of-remote-host"
   log "Usage: "`basename $0`" automatic name-or-ip-of-remote-host [ fail-if-any-change-needed ]"
elif [ $result -eq $USER_QUIT ]; then
   log "Command \"$1\" did not succeed due to user termination."
elif [ $result -eq $FAILURE_BECUASE_RECONFIGURATION_WAS_NEEDED ]; then
   log "Command \"$1\" did not succeed because reconfiguration was needed."
elif [ $result -ne 0 ]; then
   log "Command \"$1\" did not succeed.  Error code $result"
elif [ $1 == "automatic" -o $1 == "configure" ]; then
   log "Command \"$1\" succeeded.  You can now extract the host profile."
else
   log "Command \"$1\" succeeded."
fi

exit $result

