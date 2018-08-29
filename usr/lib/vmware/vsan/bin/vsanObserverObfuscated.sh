#!/bin/sh
#
# Copyright 2017 VMware, Inc.  All rights reserved.
#
#   scrub private data from light weight observer traces
#

CURRENT_HOSTNAME=`hostname`
OBFUSCATED_HOSTNAME=`echo $CURRENT_HOSTNAME | sha1sum | awk '{ print $1 }'`

for f in "/var/log/vsantraces/vsanObserver--*.gz"
do
  zcat $f | sed -e "s/$CURRENT_HOSTNAME/$OBFUSCATED_HOSTNAME/g"
done
