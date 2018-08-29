#!/bin/sh

export VMSUPPORT_MODE=1
export files_to_skip=`awk '$1 == "prune" {print $3}' /etc/vmware/vm-support/config-system.mfx | cut -d'/' -f2-` 
tar -C / -zc $(/sbin/backup.sh 0 2>/dev/null) 
unset VMSUPPORT_MODE
unset files_to_skip
