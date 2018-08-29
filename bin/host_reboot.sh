#!/bin/sh
#
# Copyright 2008-2015 VMware, Inc.  All rights reserved.
#
# host powerops:
#    Reboot power operation for the host
#
#
POWEROP="-r"
cim_host_powerops $POWEROP
echo "Rebooting..."
