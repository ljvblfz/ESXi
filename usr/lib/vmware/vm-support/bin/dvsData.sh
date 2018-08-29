#!/bin/sh

# This script will find out all DVSwitches that are present
# on this host and create tar file of corresponding dvPort files
# from each datastore into a temporary directory. The script will
# then generate a tarball from this temporary directory.

# Get the list of all dvSwitches present on this host
IFS=$'\n'
dvsList=`net-dvs -l | awk '/^switch/ {$1=""; $17=""; print $0}' | sed 's/^ //;s/ $//'`

if [ -n "$dvsList" ] ; then
   # Create a temporary directory to save dvPort files
   dvsDataDir=`mktemp -d`

   # Fetch all dvsData directories accessible on this host
   dvsDataList=`ls -d /vmfs/volumes/*/.dvsData/*`

   # Filter dvsData directories based on dvSwitches that are present on this host
   hasDvsData=false
   i=0
   for dvsData in $dvsDataList ; do
      for dvsUuid in $dvsList ; do
         # Create tar only if dvsUuid is the name of dvsData directory
         if [ "$dvsUuid" = "${dvsData##*/}" ] ; then
            tarFile="$dvsDataDir/dvsData.$i.tar"
            tar -f $tarFile -c "$dvsData" 2>/dev/null
            let i=i+1
            hasDvsData=true
         fi
      done
   done

   if [ $hasDvsData ] ; then
      tar -C $dvsDataDir -c . 2>/dev/null
   fi

   # Delete the temporary dvsData directory
   rm -rf $dvsDataDir 2>/dev/null
fi
