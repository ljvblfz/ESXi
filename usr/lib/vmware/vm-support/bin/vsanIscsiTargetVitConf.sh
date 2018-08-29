#!/bin/sh

vsanClusterStatus=`localcli vsan cluster get 2>/dev/null`
if [[ "${vsanClusterStatus}" == "" ]]; then
   echo "VSAN is not enabled."
   exit 0
fi

vsanSubClusterUuid=`echo "${vsanClusterStatus}" | grep 'Sub-Cluster UUID' | awk {'print $3'} | sed 's/-//g' | sed 's/./&-/16'`
cp /vmfs/volumes/vsan:"${vsanSubClusterUuid}"/.iSCSI-CONFIG/etc/vit.conf /tmp/vit.conf 2>/dev/null

sed -i 's/chap\(\s".*"\)\(\s".*"\)/chap \1/' /tmp/vit.conf 2>/dev/null
sed -i 's/chap-mutual\(\s".*"\)\(\s".*"\)\(\s".*"\)\(\s".*"\)/chap-mutual \1 \3/' /tmp/vit.conf 2>/dev/null
cat /tmp/vit.conf 2>/dev/null
