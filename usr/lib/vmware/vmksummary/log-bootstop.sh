#!/bin/sh
#
# Copyright 2011,2017 VMware, Inc.  All rights reserved.
#
# Sends log messages and vobs for boot and shutdown/reboot.

log() {
   /bin/logger -t bootstop "$@"
}

logvob() {
   local msg=$1 uvob=$2
   shift 2
   log "$msg"
   /usr/lib/vmware/vob/bin/addvob "vob.user.$uvob" "$@"
}

boot() {
   if [ $(vsish -e get /system/loadESX/isBootLoadESX) -eq 1 ]
   then
      logvob "Host has booted via loadESX" host.boot
   else
      logvob "Host has booted" host.boot
   fi
}

stop() {
    case "$SHUTDOWN_TYPE" in
      (reboot)
          logvob "Host is rebooting" host.stop.reboot
          ;;
      (poweroff)
          logvob "Host is powering off" host.stop.shutdown
          ;;
      (*)
          logvob "Host is halting" host.stop.shutdown
          ;;
    esac
}

case "$1" in
    (boot)
      boot
      ;;
    (stop)
      stop
      ;;
    (*)
      echo "Usage: $0 {boot|stop}" 1>&2
      exit 1
esac
