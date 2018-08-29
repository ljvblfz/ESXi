#! /bin/sh

#
# Copyright 2016 VMware, Inc.  All rights reserved. -- VMware Confidential
#

# Is there a vm-support incident key in the ESXi key cache?
vmSupportKeyKid=$(/bin/crypto-util keys getkidbyname VmSupportKey 2> /dev/null)

# No VmSupportKey key? Nothing to include
if [ $? -ne 0 ]; then
   /bin/crypto-util keys vm-support epilog
   exit 0
fi

# If there a vm-support incident key file, include it.
keyFile=/tmp/vm-support-incident-key

if [ -e ${keyFile} ]; then
   cat ${keyFile}
else
   /bin/crypto-util keys vm-support epilog
fi

exit 0

