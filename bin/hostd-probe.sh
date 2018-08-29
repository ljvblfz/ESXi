#!/bin/sh
#
# Copyright 2016-2017 VMware, Inc.  All rights reserved.
#

STATSGRP="++group=host/vim/vmvisor/hostd-probe/stats"

pid=$(pgrep $STATSGRP/pgrep hostd-probe)
if [ -z "$pid" ]; then
  /bin/hostd-probe $STATSGRP/probe
  exit $?
fi

logger $STATSGRP/logger -t 'hostd-probe.sh' 'found hostd-probe from previous iteration: ' $pid

#
# In a case hostd-probe is stuck then generate live cores of hostd/hostd-probe
# only on DEBUG builds.
#

buildType=$(vmware $STATSGRP/vmware -l | awk $STATSGRP/awk '{print $4}')
if [ "$buildType" != "DEBUG" ]; then
   exit 1
fi

#
# Generate live core dumps only once in 24 hours.
#
latest_core=$(ls $STATSGRP/ls -c /var/core/live-hostd-zdump.* | head $STATSGRP/head -n1)
if [ -n "$latest_core" ]; then
   time_since_latest_core=$(date +%s -r $latest_core)
   time_now=$(date +%s)
   time_diff_hours=$(( ($time_now - $time_since_latest_core) / 3600 ))
   if [ $time_diff_hours -lt 24 ]; then
      exit 1
   fi
fi

logger $STATSGRP/logger -t 'hostd-probe.sh' 'forcing livecore dump for hostd/hostd-probe'

#
# Request live core dumps of hostd/hostd-probe without waiting for result.
# This will also generate two backtrace files in /var/log directory with
# -latest suffix.
#
/bin/vmkbacktrace $STATSGRP/vmkbacktrace -c -n hostd -f -o hostd-probed-latest -d /var/log/ -l live-hostd
/bin/vmkbacktrace $STATSGRP/vmkbacktrace -c -n hostd-probe -f -o probe-latest -d /var/log/ -l live-hostd-probe
exit 1

