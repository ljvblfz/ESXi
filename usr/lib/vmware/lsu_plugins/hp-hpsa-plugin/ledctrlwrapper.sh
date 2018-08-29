#!/bin/sh

path=/usr/lib/vmware/lsu_plugins/hp-hpsa-plugin
vmkorproc=$1
naa=$2

vmhba=$1
if [ -e /proc/driver/hpsa ]; then
    hpsaNodes=`ls /proc/driver/hpsa`
fi

for i in $hpsaNodes; do
    cat /proc/driver/hpsa/$i | grep "$vmhba" > /dev/null
    if [ $? -eq 0 ]; then
        vmkorproc="$i"
    fi
done

mpx=$( echo "$naa" |cut -b 0-3 )
if [ "$mpx" == "mpx" ]; then
    naa=$( esxcfg-scsidevs -d $naa -l |grep vml |cut -b 21-36 )
    naa="naa.$naa"
fi

shift 2

# The ledctrl may fail due to controller busy, try at most 5 time if it fails.
retry=5

for i in `seq $retry`
do
    $path/ledctrl $vmkorproc $naa $@ 2> /dev/null
    if [ $? -eq 0 ]; then
       exit 0
    fi
    sleep 1
done

exit 1
