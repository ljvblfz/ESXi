#!/bin/sh

vsanClusterStatus=`localcli vsan cluster get 2>/dev/null`
if [[ "${vsanClusterStatus}" == "" ]]; then
   echo "VSAN is not enabled."
   exit 0
fi

if [ -d "/tmp/vsanIscsiTargets" ]; then
   rm -fr /tmp/vsanIscsiTargets
fi

mkdir -p /tmp/vsanIscsiTargets

vsanSubClusterUuid=`echo "${vsanClusterStatus}" | grep 'Sub-Cluster UUID' | awk {'print $3'} | sed 's/-//g' | sed 's/./&-/16'`
vsanDatastoreName="vsan:${vsanSubClusterUuid}"
for uuid in `ls /vmfs/volumes/"${vsanDatastoreName}"/.iSCSI-CONFIG/targets 2>/dev/null`; do
   mkdir /tmp/vsanIscsiTargets/$uuid
   cp /vmfs/volumes/"${vsanDatastoreName}"/$uuid/*.vmdk /tmp/vsanIscsiTargets/$uuid 2>/dev/null
   cp /vmfs/volumes/"${vsanDatastoreName}"/$uuid/*.pr /tmp/vsanIscsiTargets/$uuid 2>/dev/null
done

tar -cz -C /tmp vsanIscsiTargets 2>/dev/null
