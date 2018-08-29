#!/bin/sh
#
# Copyright 2008-2015 VMware, Inc.  All rights reserved.
#
# host powerops:
#    Shutdown power operation for the host
#
#

# Default power operation
POWEROP="-s"
cim_host_powerops $POWEROP
echo "Shutting Down..."
