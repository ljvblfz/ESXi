#!/bin/sh

###############################################################################
# Copyright 2007 - 2015 VMware, Inc.  All rights reserved.      -- VMware Confidential
###############################################################################
#
# remove frstbt.tgz from boot.cfg
#

SED=$(which sed)
LOGGER=$(which logger)
BOOTCFG="/bootbank/boot.cfg"

if [ ! -e ${BOOTCFG} ] ; then
   ${LOGGER} "boot.cfg doesn't exist. Can't remove firstboot references"
   exit 1
fi

"${SED}" -i -e "s/--- frstbt.tgz//g" /bootbank/boot.cfg

${LOGGER} "frstbt.tgz removed from boot configuration"

exit 0
