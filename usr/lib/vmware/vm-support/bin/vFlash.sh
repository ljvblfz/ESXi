#!/bin/sh

LOCALCLI=/usr/sbin/localcli

echo -e "vFlash module and cache statistics information\n"

# XXX tr isn't included in ESX busybox so we have to use awk
MODULES=`$LOCALCLI storage vflash module list | awk -F ',' '{for (i=1; i<=NF; ++i) printf "%s ", $i; printf "\n"}'`

for module in $MODULES
do
   echo "Module:  $module"

   echo -e "$($LOCALCLI storage vflash module get -m $module)\n"

   # Get the list of caches supported by this module
   CACHES=`$LOCALCLI storage vflash cache list -m $module | awk -F ',' '{for (i=1; i<=NF; ++i) printf "%s ", $i; printf "\n"}'`

   for cache in $CACHES
   do
      echo "Cache:  $cache"
      echo -e "$($LOCALCLI storage vflash cache get -m $module -c $cache)\n"
      echo -e "$($LOCALCLI storage vflash cache stats get -m $module -c $cache)\n"
   done

done

