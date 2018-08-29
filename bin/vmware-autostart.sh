#!/bin/sh
# Copyright 2008 VMware Inc.

export PATH=/bin:/sbin

VIMSH=/bin/vim-cmd
subsys=vmware-autostart

ROOT_USER="root"
VPX_USER="vpxuser"

NO_PERMISSION_EXPR="vim.fault.NoPermission|vim.fault.InvalidLogin"

AUTOSTART_CMD="hostsvc/autostartmanager/autostart"
AUTOSTOP_CMD="hostsvc/autostartmanager/autostop"
CONFIG_FILE="/etc/vmware/hostd/config.xml"

# AutoStart vms if any ( Execute the subshell in the background )
vmware_autostart_vms() {
   (
      logger -t 'VMware[startup]' " Starting VMs"

      # Wait until hostd is up and trigger poweron
      # for autostart configured VMs
      waitToStart=1

      while [ $waitToStart -gt 0 ]; do
         # Try first with the root user
         val=$("$VIMSH" -U $ROOT_USER -c $CONFIG_FILE $AUTOSTART_CMD 2>&1 > /dev/null)
         waitToStart=$?

         if [ $waitToStart -gt 0 ]; then
            noPermission=$(echo $val | grep -Ec "($NO_PERMISSION_EXPR)")

            # When the host is in lock down mode or the root has
            # no permissions try with the vpxuser
            if [ $noPermission -gt 0 ]; then
               val=$("$VIMSH" -U $VPX_USER -c $CONFIG_FILE $AUTOSTART_CMD 2>&1 > /dev/null)
               waitToStart=$?

               if [ $waitToStart -gt 0 ]; then
                  noPermission=$(echo $val | grep -Ec "($NO_PERMISSION_EXPR)")

                  if [ $noPermission -gt 0 ]; then
                     logger -t 'VMware[startup]' "Auto power on VMs failed: Cannot log in"

		     # There is no valid user to log in so stop trying.
                     waitToStart=0
                  fi
               fi
            fi
         fi

         if [ $waitToStart -gt 0 ]; then
            sleep 3
         fi
      done # wait to start
   ) &
}

# AutoStop vms if any
vmware_autostop_vms() {
   logger -t 'VMware[shutdown]' " Stopping VMs"

   val=$("$VIMSH" -U $ROOT_USER -c $CONFIG_FILE $AUTOSTOP_CMD 2>&1 > /dev/null)

   if [ $? -gt 0 ]; then
      noPermission=$(echo $val | grep -Ec "($NO_PERMISSION_EXPR)")

      # When the host is in lock down mode or the root has
      # no permissions try with the vpxuser
      if [ $noPermission -gt 0 ]; then
         val=$("$VIMSH" -U $VPX_USER -c $CONFIG_FILE $AUTOSTOP_CMD 2>&1 > /dev/null)

         if [ $? -gt 0 ]; then
            noPermission=$(echo $val | grep -Ec "($NO_PERMISSION_EXPR)")

            if [ $noPermission -gt 0 ]; then
               logger -t 'VMware[shutdown]' "Auto power off VMs failed: Cannot log in"
            fi
         fi
      fi
   fi
}

usage() {
   echo "Usage: `basename "$0"` {start|stop|restart}"
}

case $1 in
   "start")
      vmware_autostart_vms
      ;;
   "stop")
      vmware_autostop_vms
      ;;
   "restart")
      vmware_autostop_vms
      vmware_autostart_vms
      ;;
   *)
      usage
      exit 1
esac

