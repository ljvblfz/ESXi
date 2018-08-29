#! /bin/sh

#
# Copyright 2016 VMware, Inc.  All rights reserved. -- VMware Confidential
#

# No vm-support incident key? No crypto to do...
vmSupportKeyKid=$(/bin/crypto-util keys getkidbyname VmSupportKey 2> /dev/null)

if [ $? -ne 0 ]; then
   cat ${1}
   exit 0
fi

# Is the zdump encrypted?
fileState=$(/bin/crypto-util envelope describe --offset 4096 ${1} 2>/dev/null | fgrep keyID)

if [ $? -ne 0 ]; then
   cat ${1}
   exit 0
fi

# Is the zdump encrypted with a key in the ESXi key cache?
fileKid=$(echo ${fileState} | cut -d \' -f 2)

isPresent=$(/bin/crypto-util keys iskeyincache "${fileKid}" 2> /dev/null)

if [ "${isPresent}" != "YES" ]; then
   cat ${1}
   exit 0
fi

# Recrypt accordingly
zdumpOffset=4096

dd if=${1} bs=${zdumpOffset} count=1 2> /dev/null

/bin/crypto-util envelope recrypt --offset ${zdumpOffset} \
   --from --id "${fileKid}" \
   --to --id "${vmSupportKeyKid}" --wrappedkey \
    ${1} - 2> /dev/null

exit 0

