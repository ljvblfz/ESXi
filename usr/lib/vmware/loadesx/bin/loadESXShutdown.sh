#!/bin/ash
#
# Copyright 2017 VMware, Inc.  All rights reserved.
#
# Shutdown script to prepare a fast reboot

prepare() {
    case "$SHUTDOWN_TYPE" in
      (reboot)
          #If loadESX is enabled, we will prepare a fast reboot
          /usr/lib/vmware/loadesx/bin/loadESX.py
          ;;
    esac
}

case "$1" in
    (prepare)
      prepare
      ;;
    (*)
      echo "Usage: $0 prepare" 1>&2
      exit 1
esac
