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

# Have an encrypted core dump file?
fileState=$(/bin/crypto-util envelope describe ${1} 2>/dev/null | fgrep keyID)

if [ $? -ne 0 ]; then
   cat ${1}
   exit 0
fi

# Is the core dump encrypted with a key in the ESXi key cache?
fileKid=$(echo ${fileState} | cut -d \' -f 2)

isPresent=$(/bin/crypto-util keys iskeyincache "${fileKid}" 2> /dev/null)

if [ "${isPresent}" != "YES" ]; then
   cat ${1}
   exit 0
fi

# Recrypt accordingly
/bin/crypto-util envelope recrypt \
   --from --id "${fileKid}" \
   --to --id "${vmSupportKeyKid}" --wrappedkey \
   ${1} - 2> /dev/null

exit 0
