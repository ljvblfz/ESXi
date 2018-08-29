#!/bin/sh

#
# Copyright 2016 VMware, Inc.  All rights reserved. -- VMware Confidential
#

#
# Send, to the standard output, an ESXi dump if one is found in the dump
# partition. Deal with core dump encryption while we're at it.

# Transformative functions
cryptography () {
   dumpKid=$1
   vmSupportKeyKid=$2

   # Pass on, unmodified, the dump header
   dd count=4096 bs=1 2> /dev/null

   # Recrypt the remainder of the data
   /bin/crypto-util envelope recrypt \
      --from --id "${dumpKid}" \
      --to --id "${vmSupportKeyKid}" --wrappedkey \
      - - 2> /dev/null
}

passthrough () {
   # arguments ignored; pass the data through unmodified
   cat 2> /dev/null
}

# Extraction variables
extrOpts="-C -D"
isThereACoreDump=""

# Is there an ESXi kernel core dump?
isThereACoreDump=$(/bin/esxcfg-dumppart -T -D active -n 2>/dev/null)

if [ "$isThereACoreDump" != "YES" ]; then
   isThereACoreDump=$(/bin/esxcfg-dumppart -F -T -D active -n 2>/dev/null)

   if [ "$isThereACoreDump" = "YES" ]; then
      extrOpts="-F -C -D"
   fi
fi

# No core dump? Nothing to do.
if [ "$isThereACoreDump" != "YES" ]; then
   exit 0
fi

# Cryptographic variables
dumpKid=""
vmSupportKeyKid=""
transformFunction=passthrough

# Is the core dump encrypted?
dumpState=$(/bin/esxcfg-dumppart ${extrOpts} active --stdout 2> /dev/null | \
            /bin/crypto-util envelope describe --offset 4096 - 2> /dev/null | \
            fgrep keyID)

if [ $? -eq 0 ]; then
   # Is the key used for the core dump encryption in the ESXi key cache?
   dumpKid=$(echo ${dumpState} | cut -d \' -f 2)

   isPresent=$(/bin/crypto-util keys iskeyincache "${dumpKid}" 2> /dev/null)

   if [ "$isPresent" = "YES" ]; then
      # Is the vm-support incident key in the ESXi key cache?
      vmSupportKeyKid=$(/bin/crypto-util keys getkidbyname VmSupportKey 2> /dev/null)

      if [ $? -eq 0 ]; then
         transformFunction=cryptography
      fi
   fi
fi

/bin/esxcfg-dumppart ${extrOpts} active --stdout 2> /dev/null | \
   ${transformFunction} "${dumpKid}" "${vmSupportKeyKid}"

exit 0

