#!/bin/sh

###############################################################################
# Copyright 2007 - 2015 VMware, Inc.  All rights reserved.      -- VMware Confidential
###############################################################################
#
# fixup the GPT tables
#

LOGGER=$(which logger)
PARTEDUTIL=$(which partedUtil)
ESXCFGINFO=$(which esxcfg-info)
VMKFSTOOLS=$(which vmkfstools)
AWK=$(which awk)

BOOTUUID=$("${ESXCFGINFO}" -b)

if [ "${BOOTUUID}" = "" ] ; then
   ${LOGGER} "Unable to find Bootdisk UUID"
   exit 1
fi

BOOTPART=$("${VMKFSTOOLS}" -P "/vmfs/volumes/${BOOTUUID}")
BOOTDISK=$(echo "${BOOTPART}" | ${AWK} '/Partitions spanned/ {getline; gsub(/\:[0-9]+$/,"",$1); print $1}')

"${PARTEDUTIL}" fix /dev/disks/"${BOOTDISK}"

if [ $? != 0 ] ; then
   ${LOGGER} "Unable to fix GPT Partition Table"
   exit 1
fi

${LOGGER} "Secondary GPT Partition Table written"

exit 0
